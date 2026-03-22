# REFINER FLOW

End-to-end flow for the refinement pipeline, based on REFINER_PLAN,
REFINER_TECHNICAL, REFINER_PRD, and METRICS_JSON specifications.

## 1. Artifacts and Their Roles

| Artifact | Purpose |
| -------- | ------- |
| `train.csv` | Canonical dataset used for retraining; only updated when metrics improve |
| `misclassified.csv` | Identify specific mistakes to analyze (local debugging) |
| `metrics.json` | Measure global model quality; evaluation signal (global evaluation) |

`metrics.json` answers: **"Did the dataset changes improve the classifier?"**
`misclassified.csv` answers: **"What mistakes did the model make?"**

## 2. High-Level Flow (Updated: Two-Phase Refine)

```ascii
                    train.csv (host)
                           |
                           v
                    +-------------+
                    |   trainer   |
                    +-------------+
                           |
         +-----------------+-----------------+
         |                 |                 |
         v                 v                 v
   model.joblib      metrics.json    misclassified.csv
         |                 |                 |
         |                 +--------+--------+
         |                          |
         v                          v
   ai_router (runtime)        training-api (offline jobs)
                                  |
                                  +--> relabel phase (Redis Streams tasks)
                                  |       |
                                  |       v
                                  |   ollama pool (multi-instance)
                                  |       |
                                  |       v
                                  |   refine_runs/<run_id>/relabel/
                                  |     proposed_relabels.csv
                                  |     train_relabel_candidate.csv
                                  |     metrics_relabel_candidate.json
                                  |
                                  +--> augment phase (Redis Streams tasks)
                                          |
                                          v
                                      ollama pool (multi-instance)
                                          |
                                          v
                                      refine_runs/<run_id>/augment/
                                        proposed_examples.csv
                                        train_augment_candidate.csv
                                        metrics_augment_candidate.json
                                  |
                                  v
                             promote (optional)
                                  |
                    +-------------+-------------+
                    |                           |
        accuracy improved or within      below threshold
        tolerance (see below)              (discard)
                    |                           |
                    v                           v
             train.csv updated            discard candidate
             model.joblib promoted        train.csv unchanged
                    |
                    v
            restart ai_router
```

## 3. Detailed Step-by-Step Flow

### Phase 1: Train

1. **Input**: `train.csv` (mounted from host at `services/trainer/train.csv`)
2. **Action**: `docker compose --profile train run --rm trainer`
3. **Output** (to `model_artifacts` volume):
   - `model.joblib` - classifier for ai_router
   - `metrics.json` - accuracy, classification_report, confusion_matrix
   - `misclassified.csv` - rows where pred_label != true_label

### Phase 2: Refine (Relabel + Augment)

1. **Input**:
   - `train.csv` (read-only)
   - `misclassified.csv` (from volume)
   - `metrics.json` (from volume)

2. **Action**: Use the UI or call the training-api endpoints:

   - `POST /refine/relabel` (plus SSE at `GET /refine/relabel/events/{job_id}`)
   - `POST /refine/augment` (plus SSE at `GET /refine/augment/events/{job_id}`)

3. **Refine sub-steps**:
   - Ingest inputs (`train.csv`, `misclassified.csv`, `metrics.json`)
   - Use Redis Streams to enqueue work units:
     - Relabel: tasks are batches of misclassified rows
     - Augment: tasks are one label per task
   - Process tasks in parallel with an Ollama pool (multi-instance)
   - Write conflict-free per-task outputs under `refine_runs/<run_id>/...`
   - Merge deterministically into a candidate dataset CSV per phase
   - Retrain on the candidate and write phase-specific metrics JSON for a
     before/after comparison

4. **Output** (to `model_artifacts` volume):
   - `refine_runs/<run_id>/metrics_before.json`
   - Relabel:
     - `refine_runs/<run_id>/relabel/proposed_relabels.csv`
     - `refine_runs/<run_id>/relabel/train_relabel_candidate.csv`
     - `refine_runs/<run_id>/relabel/metrics_relabel_candidate.json`
   - Augment:
     - `refine_runs/<run_id>/augment/proposed_examples.csv`
     - `refine_runs/<run_id>/augment/train_augment_candidate.csv`
     - `refine_runs/<run_id>/augment/metrics_augment_candidate.json`
     - Per-label outputs under `refine_runs/<run_id>/augment/labels/` (raw LLM
       output, prompts, validation JSON, optional rejected rows)

### Phase 3: Promote

1. **Input**: A run_id candidate dataset (augment preferred, else relabel) plus
   its `metrics_before.json`.

2. **Action**: Use the UI Promote button (sends the most recent `run_id`) or
   call `POST /refine/promote` with body `{ "run_id": "..." }`.

3. **Promote sub-steps**:
   - Retrain with train_candidate.csv (produces model_candidate.joblib,
     metrics_candidate.json)
   - Compare accuracy: metrics_candidate vs metrics_before using
     `REFINER_PROMOTE_ACCURACY_TOLERANCE` (promote when
     `acc_after >= acc_before - tolerance`, or when `acc_before` is zero)
   - **If promoted**: copy train_candidate.csv to train.csv (host), copy
     model_candidate.joblib to model.joblib, update metrics.json. The JSON
     response includes per-label recall deltas for debugging.
   - **If not promoted**: discard candidate; train.csv and model.joblib
     unchanged

4. **Post-promote**: Restart ai_router to load new model (if promoted)

## 4. Commands Summary

```bash
# 1. Train
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer

# 2. Refine (via training-api endpoints; uses multi Ollama instances)
# Use the UI at /refine or call:
# - POST /refine/relabel
# - POST /refine/augment

# 3. Promote when accuracy improves or stays within tolerance
./scripts/promote.sh

# 4. If promoted, restart ai_router
docker compose -f compose/docker-compose.yaml restart ai_router
```

Before running refine-related commands in a new environment, generate the env
file from the centralized configuration:

```bash
python scripts/generate_env.py dev
```

This reads `config/PROJECT_CONFIG.yaml` (default and dev sections) and writes
`env/.env.dev`, which is then consumed by Docker Compose via `env_file` so
training-api and the refine pipeline receive consistent settings
(`REDIS_URL`, `MODEL_ARTIFACTS_PATH`, `PROMOTE_TARGET_PATH`, `OLLAMA_URLS`,
`OLLAMA_MODEL`, and `REFINER_*` values).

Or via demo.sh:

```bash
./scripts/demo.sh train
./scripts/demo.sh refine
./scripts/demo.sh promote
```

## 5. Decision Points

| Decision | Condition | Action |
| -------- | --------- | ------ |
| Labels to augment | Weak labels from metrics (recall < 0.75 or all labels if metrics missing) | Per-label N: base `REFINER_AUGMENT_N_PER_LABEL`, scaled up for rarer classes (capped at 3x base) |
| Promote candidate | `acc_after >= acc_before - REFINER_PROMOTE_ACCURACY_TOLERANCE` (or `acc_before == 0`) | Copy to train.csv, promote model |
| Discard candidate | candidate accuracy below threshold | Keep train.csv and model.joblib |

Augmentation uses seed examples from `train.csv`, optional verification
(`REFINER_AUGMENT_VERIFY_LABELS`), length limits, and fuzzy dedupe at merge.
See [AUGMENTATION_QUALITY_IMPROVEMENTS.md](../planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md).

## 6. Final train.csv Contents (When Promoted)

1. **Post-refined original content**: Relabels applied to misclassified rows
2. **Additional synthetic examples**: Generated per weak label with quality
   gates (seeded prompts, verification, dedupe). The legacy standalone refiner
   used a 150-row skip threshold; **training-api** augment does not apply that
   rule and instead uses class-weighted counts and filters above.

## 7. Cross-References

- [REFINER_PLAN.md](REFINER_PLAN.md) - Conceptual overview
- [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) - Technical specification
- [REFINER_PRD.md](REFINER_PRD.md) - Requirements
- [AUGMENTATION_QUALITY_IMPROVEMENTS.md](../planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md)
Training-api augment and promote tuning
- [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) - metrics.json
purpose and usage
