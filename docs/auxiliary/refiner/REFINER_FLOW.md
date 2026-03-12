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

## 2. High-Level Flow

```text
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
   ai_router (runtime)         +----------+
         |                     | refiner  |
         |                     +----------+
         |                          |
         |                          v
         |                     ollama (LLM)
         |                          |
         |                          v
         |              proposed_relabels.csv
         |              proposed_examples.csv
         |              train_candidate.csv
         |              metrics_before.json
         |                          |
         |                          v
         |                   promote.sh
         |                          |
         |              +-----------+-----------+
         |              |                       |
         |         metrics improved        metrics worse
         |              |                       |
         |              v                       v
         |     train.csv updated          discard candidate
         |     model.joblib promoted      train.csv unchanged
         |              |
         |              v
         |     restart ai_router
         |
         v
   (live routing uses model.joblib)
```

## 3. Detailed Step-by-Step Flow

### Phase 1: Train

1. **Input**: `train.csv` (mounted from host at `services/trainer/train.csv`)
2. **Action**: `docker compose --profile train run --rm trainer`
3. **Output** (to `model_artifacts` volume):
   - `model.joblib` - classifier for ai_router
   - `metrics.json` - accuracy, classification_report, confusion_matrix
   - `misclassified.csv` - rows where pred_label != true_label

### Phase 2: Refine

1. **Input**:
   - `train.csv` (read-only)
   - `misclassified.csv` (from volume)
   - `metrics.json` (from volume)

2. **Action**: `docker compose --profile refine run --rm refiner`

3. **Refiner sub-steps**:
   - Ingest train.csv and misclassified.csv
   - Verify Ollama connectivity
   - **Relabel**: For each misclassified row, call LLM; propose corrected label
   - **Augment**: For each label needing improvement (from misclassified +
     weak recall from metrics + confusion patterns), generate min 25 examples
   - Filter: dedupe, min length
   - Merge relabels and examples into train_candidate.csv
   - Save metrics_before.json for promote comparison

4. **Output** (to `model_artifacts` volume):
   - `proposed_relabels.csv` (audit)
   - `proposed_examples.csv` (audit)
   - `train_candidate.csv` (candidate dataset)
   - `metrics_before.json` (snapshot for comparison)

### Phase 3: Promote

1. **Input**: `train_candidate.csv`, `metrics_before.json`

2. **Action**: `./scripts/promote.sh`

3. **Promote sub-steps**:
   - Retrain with train_candidate.csv (produces model_candidate.joblib,
     metrics_candidate.json)
   - Compare accuracy: metrics_candidate vs metrics_before
   - **If improved**: copy train_candidate.csv to train.csv (host), copy
     model_candidate.joblib to model.joblib, update metrics.json
   - **If not improved**: discard candidate; train.csv and model.joblib
     unchanged

4. **Post-promote**: Restart ai_router to load new model (if promoted)

## 4. Commands Summary

```bash
# 1. Train
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer

# 2. Refine (requires Ollama; first run pulls qwen2.5:7b-instruct)
docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner

# 3. Promote only if metrics improve
./scripts/promote.sh

# 4. If promoted, restart ai_router
docker compose -f compose/docker-compose.yaml restart ai_router
```

Or via demo.sh:

```bash
./scripts/demo.sh train
./scripts/demo.sh refine
./scripts/demo.sh promote
```

## 5. Decision Points

| Decision | Condition | Action |
| -------- | --------- | ------ |
| Labels to augment | Labels in misclassified OR recall < 0.75 OR confusion count >= 10 | Generate min 25 examples per label |
| Promote candidate | candidate_accuracy > previous_accuracy | Copy to train.csv, promote model |
| Discard candidate | candidate_accuracy <= previous_accuracy | Keep train.csv and model.joblib |

## 6. Final train.csv Contents (When Promoted)

1. **Post-refined original content**: Relabels applied to misclassified rows
2. **Additional synthetic examples per label**: Min 25 per label that needed
   improvement (from misclassified, weak recall, or confusion patterns)

## 7. Cross-References

- [REFINER_PLAN.md](REFINER_PLAN.md) - Conceptual overview
- [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) - Technical specification
- [REFINER_PRD.md](REFINER_PRD.md) - Requirements
- [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) - metrics.json
purpose and usage
