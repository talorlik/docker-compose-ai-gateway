# REFINER SERVICE - PRODUCT REQUIREMENTS DOCUMENT

Requirements for the refiner service: an on-demand, containerized
dataset refinement pipeline using a local LLM. See
[REFINER_PLAN.md](REFINER_PLAN.md) for the conceptual overview and
[REFINER_TECHNICAL.md](REFINER_TECHNICAL.md) for the technical specification.

## 1. Document Control

| Attribute | Value |
| --- | --- |
| Document type | Product Requirements Document (PRD) |
| Format | Requirements specification |
| Source | REFINER_PLAN.md, REFINER_TECHNICAL.md |
| Scope | Refiner service and Ollama integration |

## 2. Business Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-BR-001 | The refiner SHALL improve the training dataset by analyzing misclassified validation rows. | Must |
| REF-BR-002 | The refiner SHALL run on demand after the trainer service, not as part of every request. | Must |
| REF-BR-003 | The refiner SHALL run fully locally with no external API calls. | Must |
| REF-BR-004 | The refiner SHALL be containerized and part of the same Docker Compose stack. | Must |

## 3. Model Architecture Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-001 | The router model (TF-IDF + LogisticRegression) SHALL remain in ai-router for live routing. | Must |
| REF-FR-002 | A local LLM (Qwen2.5 7B-Instruct) SHALL run in a containerized Ollama for refinement only. | Must |
| REF-FR-003 | The LLM SHALL NOT participate in request routing. | Must |
| REF-FR-004 | The LLM SHALL be used only for: relabel suggestions, augmentation examples, ambiguity analysis. | Must |

## 4. Input and Output Requirements

### 4.1 Inputs

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-005 | The refiner SHALL read `train.csv` from the shared model volume. | Must |
| REF-FR-006 | The refiner SHALL read `misclassified.csv` produced by the trainer. | Must |
| REF-FR-007 | The refiner SHALL exit gracefully if `misclassified.csv` is missing or empty. | Must |

### 4.2 Outputs

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-008 | The refiner SHALL write `proposed_relabels.csv` with columns: `text`, `current_label`, `suggested_label`, `reason`, `confidence`. | Must |
| REF-FR-009 | The refiner SHALL write `proposed_examples.csv` with columns: `text`, `label`, `source_pattern`, `generator_model`. | Must |
| REF-FR-010 | The refiner MAY write `refinement_report.json` with summary counts and quality stats. | Should |
| REF-FR-011 | Only data that improves metrics SHALL be written to `train.csv`. The refiner writes `train_candidate.csv`; `scripts/promote.sh` retrains and promotes conditionally. | Must |

## 5. Pipeline Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-012 | The refiner SHALL ingest `train.csv` and `misclassified.csv`. | Must |
| REF-FR-013 | The refiner SHALL send prompts to the LLM with strict JSON output constraints. | Must |
| REF-FR-014 | The refiner SHALL validate LLM output against the expected JSON schema. | Must |
| REF-FR-015 | The refiner SHALL apply deterministic filters: exact-duplicate removal, near-duplicate checks, banned-pattern checks, minimum length. | Must |
| REF-FR-016 | The refiner SHALL write proposals to `train_candidate.csv`; promotion to `train.csv` SHALL occur only when retraining improves metrics. | Must |

## 6. Ollama Service Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-017 | Ollama SHALL run as a container in the same Docker Compose stack. | Must |
| REF-FR-018 | Ollama SHALL use the official `ollama/ollama:latest` image. | Must |
| REF-FR-019 | Ollama SHALL expose port 11434 for the API. | Must |
| REF-FR-020 | Ollama SHALL use a persistent volume for model storage (`ollama_data`). | Must |
| REF-FR-021 | The model `qwen2.5:7b-instruct` SHALL be pulled automatically when Compose brings up the ollama service; no manual pull command SHALL be required. | Must |
| REF-FR-022 | Ollama SHALL have a health check (e.g. `ollama list`). | Must |

## 7. Refiner Service Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-023 | The refiner SHALL be a Python service in `services/refiner/`. | Must |
| REF-FR-024 | The refiner SHALL use the `refine` Compose profile; it SHALL NOT start with default `docker compose up`. | Must |
| REF-FR-025 | The refiner SHALL depend on Ollama with `condition: service_healthy`. | Must |
| REF-FR-026 | The refiner SHALL connect to Ollama via `OLLAMA_HOST` (default `http://ollama:11434`). | Must |
| REF-FR-027 | The refiner SHALL use `OLLAMA_MODEL` (default `qwen2.5:7b-instruct`). | Must |
| REF-FR-028 | The refiner SHALL mount the shared model volume for read/write of proposal files. | Must |

## 8. Trigger and Workflow Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-FR-029 | Refinement SHALL be triggered via `docker compose --profile refine run --rm refiner`. | Must |
| REF-FR-030 | The refiner SHALL run after the trainer; the trainer SHALL produce `misclassified.csv` first. | Must |
| REF-FR-031 | Promotion of a new model SHALL occur only when metrics improve (accuracy, unknown recall, confusion pairs). | Must |

## 9. Non-Functional Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| REF-NFR-001 | The refiner SHALL run on CPU; GPU SHALL be optional. | Must |
| REF-NFR-002 | The refiner SHALL be reproducible across macOS, Linux, and Windows + WSL2. | Must |
| REF-NFR-003 | The refiner SHALL log progress (e.g. rows processed, files written). | Should |
| REF-NFR-004 | The refiner SHALL handle LLM timeouts and parse errors gracefully. | Must |

## 10. Acceptance Criteria

| ID | Criterion | Priority |
| --- | --- | --- |
| REF-AC-001 | `docker compose --profile refine run --rm refiner` SHALL succeed when `misclassified.csv` exists and Ollama is healthy. | Must |
| REF-AC-002 | After refinement, `train_candidate.csv` SHALL exist; promotion to `train.csv` SHALL occur only when `scripts/promote.sh` confirms metrics improvement. | Must |
| REF-AC-003 | The refiner SHALL exit with a clear message when `misclassified.csv` is missing or empty. | Must |
| REF-AC-004 | Ollama SHALL be reachable from the refiner container over the Compose network. | Must |

## 11. Out of Scope

- Evaluator and promoter services (future enhancement)
- GPU-accelerated Ollama (optional, platform-dependent)

## 12. Cross-References

- [REFINER_FLOW.md](REFINER_FLOW.md) - End-to-end flow
- [METRICS_JSON.md](docs/auxiliary/reference/METRICS_JSON.md) - metrics.json purpose
and usage
- [REFINER_PLAN.md](REFINER_PLAN.md)
- [REFINER_TECHNICAL.md](REFINER_TECHNICAL.md)
- [PRD.md](docs/auxiliary/requirements/PRD.md)
- [TECHNICAL.md](docs/auxiliary/architecture/TECHNICAL.md)
