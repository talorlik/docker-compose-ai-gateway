# REFINER SERVICE - TECHNICAL SPECIFICATION

Technical specification for the refiner service: architecture, artifacts,
Docker Compose integration, and data flow. See
[REFINER_PLAN.md](REFINER_PLAN.md) for the conceptual overview and workflow.

> [!NOTE]
> **Agent cross-reference**: Sections include `<!-- REFINER-TECH:BATCH-N -->`
> markers linking to [REFINER_TASKS.md](REFINER_TASKS.md) batches. When
> implementing a task, search for the matching BATCH-N marker to find the
> relevant spec. Section 11 has the full mapping table.

## 1. Purpose and Scope

The refiner service improves the training dataset by analyzing
`misclassified.csv` (validation rows the model predicted incorrectly
during the holdout test) and producing proposals for relabeling and
augmentation. It runs **offline** and **on demand**, after the trainer
service. Invocation and promotion: see
[TRAIN_AND_REFINE_GUI_PAGES_TECH.md](docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md).

## 2. Two-Model Architecture

| Role | Model | Runtime | Purpose |
| ---- | ----- | ------- | ------- |
| Router | TF-IDF + LogisticRegression | ai-router, every request | Classify route |
| Data assistant | phi3:mini (Ollama) | refiner, offline only | Improve dataset |

The LLM **never participates in request routing**. It only improves the
dataset during the refinement pipeline.

## 3. Inputs and Outputs

<!-- REFINER-TECH:BATCH-3 -->

### 3.1 Inputs

| File | Source | Purpose |
| ---- | ------ | ------- |
| `train.csv` | host mount | Canonical dataset used for retraining |
| `misclassified.csv` | trainer output | Identify specific mistakes to analyze |
| `metrics.json` | trainer output | Measure global model quality; evaluation signal |

`metrics.json` is **not** used to change labels directly. It is used to decide
whether a newly trained model is better than the previous one, and to
identify weak labels (low recall) and confusion patterns for augmentation.
See [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) for details.

Columns in `misclassified.csv`:

- `text`, `true_label`, `pred_label`, `pred_confidence`, `probs_json`

### 3.2 Output Artifacts

<!-- REFINER-TECH:BATCH-5,BATCH-7,BATCH-8 -->

| File | Schema | Description |
| ---- | ------ | ----------- |
| `proposed_relabels.csv` | `text,current_label,suggested_label,reason,confidence` | Relabel suggestions |
| `proposed_examples.csv` | `text,label,source_pattern,generator_model` | Augmentation candidates |
| `refinement_report.json` | Summary counts and quality stats | Audit report |

### 3.3 Output Contract and Persistence

Only data that **actually improves** the model is written to `train.csv`.
The refiner writes a candidate; promotion is conditional on metrics.

1. Refiner produces `proposed_relabels.csv` and `proposed_examples.csv` (audit)
2. Refiner merges into `train_candidate.csv` (not train.csv)
3. Run `scripts/promote.sh` to retrain with the candidate and compare metrics
4. If metrics improve: promote candidate to `train.csv` and `model.joblib`
5. If metrics do not improve: discard candidate, keep current `train.csv`

`train.csv` is mounted read-only; the refiner never writes to it directly.

## 4. Automated Refinement Pipeline (Six Stages)

<!-- REFINER-TECH:BATCH-3,BATCH-5,BATCH-6,BATCH-7 -->

1. **Ingest**: Read `train.csv` and `misclassified.csv`.
2. **Detect patterns**: Identify frequent confusions (e.g. `ops -> image`),
   low-margin decisions, vague rows that should become `unknown`.
3. **Relabel**: Use secondary validator (LLM) to propose corrected labels.
4. **Augment**: Generate examples for underperforming classes.
5. **Filter**: Deduplicate, quality-filter banned patterns, minimum length,
   class-balance controls.
6. **Retrain and promote**: Retrain only if metrics improve; promote
   `model.joblib` only when `unknown` recall and confusion pairs improve.

## 5. LLM Integration

<!-- REFINER-TECH:BATCH-4,BATCH-5 -->

### 5.1 Model Choice

- **Model**: phi3:mini
- **Runtime**: Ollama (containerized)
- **Rationale**: Fast CPU inference, small memory footprint (~2-3 GB),
  adequate structured output and instruction adherence for dataset
  refinement tasks. Switched from Qwen2.5 7B-Instruct to reduce
  CPU-only inference time from minutes to seconds per call.

### 5.2 Prompt Design

For each misclassified row, the refiner sends a prompt with:

- Labels: `search`, `image`, `ops`, `unknown`
- Input row: `text`, `true_label`, `pred_label`
- Output constraints: JSON only, schema:
  `{suggested_label, reason, examples: [...]}`

### 5.3 Safeguards

<!-- REFINER-TECH:BATCH-6 -->

- Output must pass deterministic filters before merge: exact-duplicate
  removal, minimum length, banned-pattern checks.
- Merge applies relabels (update) and examples (append) to
  `train_candidate.csv`; promotion to `train.csv` is conditional.

## 6. Docker Compose Configuration

<!-- REFINER-TECH:BATCH-1 -->

### 6.1 Services

| Service | Purpose |
| ------- | ------- |
| gateway | Routing + threshold policy |
| ai_router | ML classifier |
| search_service | Backend demo |
| image_service | Backend demo |
| ops_service | Backend demo |
| trainer | Trains classifier |
| refiner | Dataset improvement |
| ollama | Local LLM server |

### 6.2 Ollama Service

The model is pulled automatically when Compose brings up the ollama service.
No manual pull command is required.

```yaml
services:
  ollama:
    image: ollama/ollama:latest
    container_name: ollama
    profiles:
      - refine
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    entrypoint: ["/bin/sh", "-c"]
    command: >
      "ollama serve &
       sleep 5 &&
       ollama pull phi3:mini &&
       wait"
    healthcheck:
      test: ["CMD", "sh", "-c", "ollama list | grep -q phi3:mini"]
      interval: 30s
      timeout: 10s
      retries: 10
      start_period: 600s
    restart: unless-stopped

volumes:
  ollama_data:
```

First startup downloads the model (may take several minutes); subsequent
runs reuse the cached model in the persistent volume.

### 6.3 Refiner Service

```yaml
  refiner:
    build:
      context: ../services/refiner
      dockerfile: Dockerfile
    profiles:
      - refine
    depends_on:
      ollama:
        condition: service_healthy
    environment:
      OLLAMA_HOST: http://ollama:11434
      OLLAMA_MODEL: phi3:mini
    volumes:
      - model_artifacts:/data
```

### 6.4 Volume Sharing

- `model_artifacts`: trainer writes `model.joblib`, `metrics.json`,
  `misclassified.csv`; refiner reads `misclassified.csv` and writes
  `proposed_relabels.csv`, `proposed_examples.csv`,
  `refinement_report.json`; ai-router reads `model.joblib`.
- `train.csv`: host-mounted read-only; refiner writes `train_candidate.csv`
  to the volume; promote script conditionally copies to train.csv.

## 7. Refiner Service Implementation

<!-- REFINER-TECH:BATCH-2,BATCH-4 -->

### 7.1 Directory Structure

```text
services/refiner/
  Dockerfile
  requirements.txt
  app.py
  prompts.py
```

> [!NOTE]
> The legacy `services/refiner/` container runs a single-phase
> refinement. The two-phase relabel/augment pipeline now lives
> in `services/training-api/app/refine/` with a shared JSON
> parser (`parser.py`) used by both `relabel.py` and
> `augment.py`. See [REFINER_FLOW.md](REFINER_FLOW.md) for
> the current end-to-end flow.

### 7.2 Dependencies

```text
requests>=2.32.0
pandas>=2.2.0
```

### 7.3 Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

CMD ["python", "app.py"]
```

### 7.4 Ollama API

- Endpoint: `POST {OLLAMA_HOST}/api/generate`
- Payload: `{model, prompt, stream: false}`
- Response: `response` field contains generated text

### 7.5 Environment Variables

| Variable | Default | Description |
| -------- | ------- | ----------- |
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama API base URL |
| `OLLAMA_MODEL` | `phi3:mini` | Model tag |
| `AUGMENT_MIN_PER_LABEL` | `5` | Minimum synthetic examples to generate per weak label |
| `AUGMENT_MAX_ATTEMPTS` | `2` | Max LLM calls per label during augmentation |
| `AUGMENT_SKIP_THRESHOLD` | `150` | Labels with >= this many training rows skip augmentation |

## 8. Trigger Flow

<!-- REFINER-TECH:BATCH-8 -->

### 8.1 On-Demand (Recommended)

```bash
# 1. Train
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer

# 2. Refine (produces train_candidate.csv)
docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner

# 3. Promote only if metrics improve
./scripts/promote.sh

# 4. Restart ai_router if promoted
docker compose -f compose/docker-compose.yaml restart ai_router
```

### 8.2 Profile Usage

- `refine` profile: refiner and ollama start only when explicitly requested.
- `ollama` must be started before refiner (or use `depends_on` with
  `condition: service_healthy` when running refiner).

## 9. Promotion Rule

- **Training-api:** Promote when candidate accuracy is at least
  `previous_accuracy - REFINER_PROMOTE_ACCURACY_TOLERANCE`, or when baseline
  accuracy is zero. See [AUGMENTATION_QUALITY_IMPROVEMENTS.md](../planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md).
- Do not replace `model.joblib` blindly outside that contract.
- Threshold logic (`T_ROUTE`, `T_MARGIN`) remains in gateway; refinement
  improves the model, thresholds control routing policy.

## 10. GPU Support (Optional)

- **Linux / WSL2 + NVIDIA**: Add GPU reservation to ollama service.
- **macOS**: CPU-only; Ollama does not support GPU passthrough in Docker
  Desktop on macOS.

## 11. Cross-References

- [REFINER_FLOW.md](REFINER_FLOW.md) - End-to-end flow
- [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) - metrics.json purpose,
structure, and usage
- [REFINER_PLAN.md](REFINER_PLAN.md)
- [REFINER_PRD.md](REFINER_PRD.md)
- [TECHNICAL.md](docs/auxiliary/architecture/TECHNICAL.md) (trainer, ai-router,
gateway)

### Task-to-Technical Mapping

§ = section numbers. TASKS uses `<!-- REFINER-TECH:BATCH-N §X.Y -->`.

| Batch | Tasks | Technical Sections |
| ----- | ----- | ------------------ |
| 1 | 1.1-1.4 | 6.1, 6.2, 6.3, 6.4 |
| 2 | 2.1-2.4 | 7.1, 7.2, 7.3 |
| 3 | 3.1-3.2 | 3.1, 3.2, 4 |
| 4 | 4.1-4.3 | 5.1, 5.2, 7.4, 7.5 |
| 5 | 5.1-5.5 | 3.2, 5.2 |
| 6 | 6.1-6.3 | 5.3 |
| 7 | 7.1-7.4 | 3.2, 4 |
| 8 | 8.1-8.4 | 3.2, 8.1, 8.2 |
