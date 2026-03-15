# REFINER SERVICE - TASKS

Actionable, incremental tasks to build the refiner service stack. Tasks are
grouped into batches for pace control. Run batches in order: "do batch 1,"
then "do batch 2," and so forth.

> [!NOTE]
> **Agent cross-reference**: Each batch has `<!-- REFINER-TECH:BATCH-N §X.Y -->`.
> § = section refs in REFINER_TECHNICAL.md. Full mapping: Section 11.

Reference: [REFINER_PLAN.md](REFINER_PLAN.md), [REFINER_PRD.md](REFINER_PRD.md),
[REFINER_TECHNICAL.md](REFINER_TECHNICAL.md).

## Batch 1: Infrastructure

<!-- REFINER-TECH:BATCH-1 §6.1-6.4 -->

Foundation: Compose services, volumes, profiles.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 1.1 | Add or verify `ollama` service in `compose/docker-compose.yaml`: image `ollama/ollama:latest`, profile `refine`, port 11434, volume `ollama_data`, entrypoint that runs `ollama serve` and `ollama pull phi3:mini`. | `docker compose --profile refine up ollama -d` starts Ollama. | x |
| 1.2 | Add or verify `ollama` healthcheck: `ollama list \| grep -q phi3:mini`, interval 30s, start_period 600s. | Refiner can depend on `condition: service_healthy`. | x |
| 1.3 | Add or verify `refiner` service: profile `refine`, depends_on ollama with `condition: service_healthy`, env `OLLAMA_HOST`, `OLLAMA_MODEL`, volume `model_artifacts:/data`. | `docker compose --profile refine run --rm refiner` can run after ollama is healthy. | x |
| 1.4 | Ensure `model_artifacts` volume exists and trainer writes `misclassified.csv` to it. | After `trainer` run, `/model/misclassified.csv` (or equivalent) exists in the volume. | x |

## Batch 2: Refiner Service Shell

<!-- REFINER-TECH:BATCH-2 §7.1-7.3 -->

Minimal refiner container that ingests and exits gracefully.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 2.1 | Create `services/refiner/Dockerfile`: `python:3.12-slim`, WORKDIR /app, copy requirements and app, CMD `python app.py`. | `docker build services/refiner` succeeds. | x |
| 2.2 | Create `services/refiner/requirements.txt`: `requests>=2.32.0`, `pandas>=2.2.0`. | `pip install -r requirements.txt` works. | x |
| 2.3 | Create minimal `services/refiner/app.py`: read `/data/misclassified.csv`; if missing or empty, print clear message and exit 0. | Refiner exits with message when misclassified.csv is missing or empty. | x |
| 2.4 | Verify `docker compose --profile refine run --rm refiner` runs and exits gracefully when `misclassified.csv` is absent. | REF-AC-003 satisfied. | x |

## Batch 3: train.csv Availability

<!-- REFINER-TECH:BATCH-3 §3.1,3.2,4 -->

Ensure refiner can read `train.csv` per REF-FR-005.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 3.1 | Add `train.csv` to refiner inputs: refiner mounts `../services/trainer/train.csv` read-write for merge. | Refiner can read and write `train.csv` at `/data/train.csv`. | x |
| 3.2 | Implement ingest in app.py: read `train.csv` and `misclassified.csv`, validate required columns (`text`, `label` for train; `text`, `true_label`, `pred_label` for misclassified). | Ingest loads both files and validates schema. | x |

## Batch 4: Ollama Integration

<!-- REFINER-TECH:BATCH-4 §5.1,5.2,7.4,7.5 -->

Connect refiner to Ollama and handle errors.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 4.1 | Implement `ask_ollama(prompt)` in app.py: POST to `{OLLAMA_HOST}/api/generate` with `model`, `prompt`, `stream: false`; return `response` field. | Refiner can call Ollama API. | x |
| 4.2 | Add timeout (e.g. 300s) and handle `requests.RequestException`; log or skip failed rows. | REF-NFR-004: timeouts and parse errors handled gracefully. | x |
| 4.3 | Verify refiner reaches Ollama over Compose network (`http://ollama:11434`). | REF-AC-004 satisfied. | x |

## Batch 5: Relabel Pipeline

<!-- REFINER-TECH:BATCH-5 §3.2,5.2 -->

Produce `proposed_relabels.csv` from misclassified rows.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 5.1 | Design relabel prompt: labels `search`, `image`, `ops`, `unknown`; input row `text`, `true_label`, `pred_label`; output JSON schema `{suggested_label, reason, confidence}`. | Prompt produces structured JSON. | x |
| 5.2 | Parse LLM response: handle raw JSON and markdown-wrapped JSON (strip code fences if present). | Robust parsing for common LLM output formats. | x |
| 5.3 | Validate parsed JSON against schema; skip row on validation failure. | Invalid output does not crash; row is skipped. | x |
| 5.4 | Write `proposed_relabels.csv` with columns: `text`, `current_label`, `suggested_label`, `reason`, `confidence`. | REF-FR-008 satisfied. | x |
| 5.5 | Process misclassified rows (limit to first N for initial runs, e.g. 20); add progress logging. | Refiner processes rows and logs progress. | x |

## Batch 6: Deterministic Filters

<!-- REFINER-TECH:BATCH-6 §5.3 -->

Apply filters before writing proposals.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 6.1 | Exact-duplicate removal: drop relabel proposals where `(text, suggested_label)` already exists in proposals or in `train.csv`. | No duplicate proposals. | x |
| 6.2 | Minimum length filter: drop proposals where `text` or suggested `text` is below threshold (e.g. 3 chars). | REF-FR-015 (minimum length). | x |
| 6.3 | Banned-pattern check (optional): reject proposals containing configurable banned substrings. | Optional safeguard against low-quality patterns. | x |

## Batch 7: Augmentation Pipeline

<!-- REFINER-TECH:BATCH-7 §3.2,4 -->

Produce `proposed_examples.csv` for underperforming classes.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 7.1 | Detect underperforming classes from `metrics.json` or confusion matrix; or use misclassified `true_label` distribution. | Identify classes needing more examples. | x |
| 7.2 | Design augmentation prompt: generate N examples for a given label; output JSON array of `{text, label}`. | LLM produces synthetic examples. | x |
| 7.3 | Write `proposed_examples.csv` with columns: `text`, `label`, `source_pattern`, `generator_model`. | REF-FR-009 satisfied. | x |
| 7.4 | Apply filters to augmentation output: deduplicate, min length, exclude if already in `train.csv`. | Augmentation candidates pass same filters as relabels. | x |

## Batch 8: Report and Polish

<!-- REFINER-TECH:BATCH-8 §3.2,8.1,8.2 -->

Final outputs, logging, and acceptance verification.

| ID | Task | Acceptance | Done |
| -- | ---- | ---------- | ---- |
| 8.1 | Write `refinement_report.json` with summary: `rows_processed`, `relabels_proposed`, `examples_proposed`, `rows_skipped`, `errors`. | REF-FR-010 satisfied. | x |
| 8.2 | Add structured logging: rows processed, files written, any errors. | REF-NFR-003 satisfied. | x |
| 8.3 | End-to-end test: run trainer, then refiner; verify `train.csv` contains merged results and proposal files exist for audit. | REF-AC-001, REF-AC-002 satisfied. | x |
| 8.4 | Document trigger flow in README or DEMO: `train` profile first, then `refine` profile. | User can follow documented workflow. | x |

## Task Summary

| Batch | Focus | Task Count |
| ----- | ----- | ---------- |
| 1 | Infrastructure | 4 |
| 2 | Refiner shell | 4 |
| 3 | train.csv | 2 |
| 4 | Ollama integration | 3 |
| 5 | Relabel pipeline | 5 |
| 6 | Filters | 3 |
| 7 | Augmentation | 4 |
| 8 | Report and polish | 4 |

## Suggested Commands

```bash
# Batch 1: Start Ollama (optional, for manual testing)
docker compose -f compose/docker-compose.yaml --profile refine up ollama -d

# Batch 2-5: Run refiner (after trainer)
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer
docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner

# Initial runs: limit to first 20 rows (REFINER_LIMIT=20)
docker compose -f compose/docker-compose.yaml --profile refine run --rm \
  -e REFINER_LIMIT=20 refiner
```

## Cross-References

- [REFINER_PLAN.md](REFINER_PLAN.md) - Conceptual overview
- [REFINER_PRD.md](REFINER_PRD.md) - Requirements
- [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) - Technical specification
