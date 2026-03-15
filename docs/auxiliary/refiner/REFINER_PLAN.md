# REFINER SERVICE

Conceptual overview and workflow for the refiner service. For technical
specification see [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md); for requirements
see [REFINER_PRD.md](REFINER_PRD.md).

## 1. Manual Workflow: Using misclassified.csv

**Query:** How do I use `misclassified.csv` to relabel rows and enter them
correctly back into `train.csv`?

**Response:** Use `misclassified.csv` as a review queue, not as a file you
blindly merge back.

### What misclassified.csv is

A subset of validation rows from `train.csv` that the model predicted
incorrectly during the holdout test. Those rows already came from
`train.csv`, so you usually do **not** copy them back. Instead: inspect,
decide, then edit `train.csv` accordingly.

### Correct workflow

1. Open `train.csv` and `misclassified.csv`.
2. For each misclassified row, find the same `text` in `train.csv` and
   decide which case applies:

| Case | Example | Action |
| ---- | ------- | ------ |
| A - Original label wrong | `detect text in an image` true: search, pred: image | Change label in train.csv to `image` |
| B - Text ambiguous | `analyze image data` true: image, pred: search | Add clearer examples, rewrite, or move to `unknown` |
| C - Coverage weak | `pod cannot pull container image` true: ops, pred: image | Keep row, add more ops examples with similar wording |
| D - Should be unknown | `help` true: search, pred: unknown | Change label to `unknown` |

1. Edit `train.csv` only; `misclassified.csv` is diagnostic output.
2. Optionally add new rows when a misclassification reveals a missing pattern.
3. Retrain, inspect metrics and misclassified, repeat until stable.

### Best review order

1. High-confidence wrong predictions (dataset problems or missing counterexamples)
2. Rows near decision boundaries (tune thresholds and `unknown`)
3. Obviously vague rows (move many to `unknown`)

### What not to do

- Do not blindly replace `true_label` with `pred_label`
- Do not paste all `misclassified.csv` rows back into `train.csv`
- Do not duplicate rows unless intentionally adding variants

### Improvement: add id column

Add `id` to `train.csv` and carry it into `misclassified.csv` for exact
row lookup without searching by text.

## 2. Automated Refinement and Local LLM

**Query:** How do I automate this and use a local AI model with Docker Compose?

**Response:** A separate refiner pipeline sits beside the trainer and
ai-router. It processes misclassified rows, produces proposals, applies
filters, and writes `train_candidate.csv`. Run refine and promote via
**training-api** (UI or CLI) or `scripts/promote.sh`. **Promote to
`train.csv` only if metrics improve**. See
[TRAIN_AND_REFINE_GUI_PAGES_TECH.md](docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md)
for UI/CLI and event-driven flow.

### Six-stage pipeline

1. Ingest `train.csv`, `misclassified.csv`, and `metrics.json` (evaluation
   signal; see [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md))
2. Detect error patterns (frequent confusions, low-margin decisions, vague rows)
3. Relabel candidate rows using a secondary validator (LLM)
4. Generate augmentation candidates for underperforming classes
5. Deduplicate and quality-filter
6. Retrain, compare metrics, promote only on improvement

### Local LLM role

Keep TF-IDF + LogisticRegression for ai-router. Use a local instruct
model (phi3:mini via Ollama) only in the refiner service. The LLM:

- Proposes corrected labels
- Generates synthetic examples
- Explains ambiguity

The refiner container sends prompts to Ollama over the internal Compose
network, validates JSON output, filters duplicates, and writes
`train_candidate.csv`. The promote script retrains and promotes to
`train.csv` only when metrics improve. No internet or external API required.

### Safeguards

- Proposals pass deterministic filters before merge
- Only data that improves metrics is promoted to `train.csv`
- Proposal files (`proposed_relabels.csv`, `proposed_examples.csv`) are
  kept for audit

## 3. Two Models: Router vs Data Assistant

**Query:** What is the difference between the models and when do I use each?

**Response:** Two different types of models, each for a different job.

| Model | Type | Where | When | Purpose |
| ----- | ---- | ----- | ---- | ------- |
| **Router** | TF-IDF + LogReg | ai-router | Every request | Decide route |
| **Data assistant** | phi3:mini (Ollama) | refiner | Offline only | Improve dataset |

The router is fast and deterministic. The LLM generates examples,
rewrites text, and explains mistakes. Do not use the LLM for routing:
it is slower, unpredictable, and inconsistent.

**Mental model:** Router = traffic cop. LLM = teacher training the cop.

## 4. Model Choice: phi3:mini

**Query:** Which model is used for local dataset refinement?

**Response:** phi3:mini is the current model for this project.

| Factor | phi3:mini |
| ------ | --------- |
| Structured output | Good |
| Memory | ~2-3 GB |
| CPU inference speed | Fast (seconds per call) |
| Instruction adherence | Adequate for refinement |

Switched from Qwen2.5 7B-Instruct to phi3:mini to reduce CPU-only
inference time from minutes to seconds per call. On-demand model
selection is a planned future enhancement (see PRD.md and
PROJECT_PLAN.md).

## 5. Containerized Setup

**Query:** How do I install Ollama with phi3:mini and integrate it into
Docker Compose?

**Response:** Run Ollama as a container in the same Compose stack. Do not
install Ollama on the host.

### Flow

```text
train.csv + misclassified.csv
        |
        v
     refiner
        |
        v
     ollama (phi3:mini)
        |
        v
proposed_relabels.csv + proposed_examples.csv (audit)
        |
        v
     train_candidate.csv
        |
        v
     scripts/promote.sh (retrain, compare metrics, promote if improved)
```

### Trigger pattern

Use the `refine` profile so the refiner runs only when requested:

```bash
docker compose --profile refine run --rm refiner
```

See [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) for Compose config,
Dockerfile, and API details.

## 6. Final Architecture

**Query:** I will stick with the containerized version.

**Response:** Correct choice for this project. Containerization guarantees
reproducibility across macOS, Linux, and Windows + WSL2.

### Stack

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

### Recommended first-run sequence

1. `docker compose --profile train run --rm trainer`
2. `docker compose --profile refine run --rm refiner`

Ollama pulls `phi3:mini` automatically when the refine profile
starts; no manual pull is required. First run may take a minute
to download the model; later runs reuse the cached model.

The model container is not part of request routing; it is only used
during the refinement pipeline.

## 7. Cross-References

- [REFINER_FLOW.md](REFINER_FLOW.md) - End-to-end flow
- [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) - metrics.json purpose
and usage
- [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) - Technical specification
- [REFINER_PRD.md](REFINER_PRD.md) - Requirements
