# Product Requirements Document: Train and Refine GUI Pages

Structured requirements for the Train and Refine frontend pages, training-api
service, Redis-backed job state, and event-driven completion via SSE.

## 1. Document Control

| Attribute | Value |
| --- | --- |
| Document type | Product Requirements Document (PRD) |
| Format | Requirements specification |
| Source | TRAIN_AND_REFINE_GUI_PAGES_PLAN.md |
| Scope | Train page, Refine page, training-api, Redis, gateway proxy, SSE |

## 2. Business and Project Requirements

### 2.1 Goals

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-BR-001 | The system SHALL add a **Train** page to the gateway web UI for running training and displaying metrics and misclassified data. | Must |
| TR-BR-002 | The system SHALL add a **Refine** page to the gateway web UI for running refinement, displaying report and comparison, and promoting the candidate dataset. | Must |
| TR-BR-003 | Job completion for train and refine SHALL be event-driven via Server-Sent Events (SSE); the UI SHALL receive a push when the job completes (no polling, no long timeouts, no sleep). | Must |
| TR-BR-004 | A single canonical implementation of train, refine, and promote SHALL be used for both (1) HTTP API (UI) and (2) CLI via Docker Compose (scripts). | Must |

### 2.2 Scope

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-BR-005 | The Train page SHALL allow running training from the UI and SHALL display metrics and a misclassified table. | Must |
| TR-BR-006 | The Refine page SHALL allow running refinement from the UI and SHALL display report, before/after comparison, tabulated proposed relabels/examples/train candidate, and a Promote button. | Must |
| TR-BR-007 | A **training-api** backend service SHALL trigger the trainer/refiner via Docker Compose and SHALL expose REST APIs for the UI and a CLI entrypoint for scripts. | Must |
| TR-BR-008 | Redis SHALL be used for job state and Pub/Sub so that completion is event-driven. | Must |
| TR-BR-009 | The gateway SHALL provide proxy routes for training-api and a streaming proxy for SSE endpoints. | Must |

## 3. Technical and Platform Requirements

### 3.1 Event-Driven and Single Implementation

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-NFR-001 | Job completion SHALL be notified via Redis PUBLISH and SSE stream to the client; the system SHALL NOT rely on polling. | Must |
| TR-NFR-002 | Train, refine, and promote SHALL be implemented once in Python and SHALL be triggered by (1) HTTP API (UI) and (2) CLI via Docker Compose (scripts). | Must |
| TR-NFR-003 | The platform SHALL use the same stack as the main project (Docker Compose, Python/FastAPI). | Must |
| TR-NFR-004 | A dedicated Redis service SHALL exist in the same Compose file; training-api SHALL connect via REDIS_URL or REDIS_HOST/REDIS_PORT. | Must |

## 4. System Architecture Requirements

### 4.1 Components

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-001 | The browser UI SHALL support hash-based navigation: Query, Train, Refine (hash `#`, `#train`, `#refine`). | Must |
| TR-FR-002 | The gateway SHALL proxy POST and GET requests to training-api and SHALL provide a streaming proxy for SSE. | Must |
| TR-FR-003 | The training-api SHALL be a FastAPI service that runs train, refine, and promote in Python, SHALL use Redis for job state and Pub/Sub, and SHALL read/write the model_artifacts volume. | Must |
| TR-FR-004 | Redis SHALL be a dedicated service with job keys (with TTL) and Pub/Sub channels for completion events. | Must |
| TR-FR-005 | The trainer and refiner SHALL remain existing one-shot containers invoked by training-api via Docker Compose. | Must |

### 4.2 Event-Driven Flow

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-006 | When a job is started, the API SHALL return `job_id` immediately; when the job completes, the backend SHALL publish to Redis and the client SHALL be notified via SSE. | Must |
| TR-FR-007 | Per-job state SHALL be stored at Redis keys `job:train:{job_id}` and `job:refine:{job_id}` (status, result, error) with TTL 24h (86400s). | Must |
| TR-FR-008 | On job completion, training-api SHALL PUBLISH to channel `job:train:events:{job_id}` or `job:refine:events:{job_id}` with final payload (e.g. status completed/ failed and result or error). | Must |
| TR-FR-009 | Training-api SHALL expose GET `/train/events/{job_id}` and GET `/refine/events/{job_id}` as SSE streams that SUBSCRIBE to the Redis channel and send the first message to the client then close the stream. | Must |
| TR-FR-010 | The frontend SHALL use EventSource for SSE; SHALL NOT poll for job status. | Must |

## 5. Training API Service Requirements

### 5.1 Location and Role

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-011 | The training-api service SHALL be located at `services/training-api/`. | Must |
| TR-FR-012 | Training-api SHALL hold the canonical Python implementation of train, refine, and promote. | Must |
| TR-FR-013 | Training-api SHALL expose HTTP endpoints that call this Python code (for the UI). | Must |
| TR-FR-014 | Training-api SHALL expose a CLI/entrypoint that bash scripts invoke via Docker Compose (e.g. `docker compose run training-api promote`). | Must |
| TR-FR-015 | For the UI, the API SHALL wrap train/refine in job state and Redis Pub/Sub and SHALL read artifacts from the volume. | Must |

### 5.2 Redis Integration

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-016 | Per-job state SHALL be stored at `job:train:{job_id}` / `job:refine:{job_id}` as JSON: status, result (when completed), error (when failed), created_at. | Must |
| TR-FR-017 | Job keys SHALL have a TTL of 24h (86400s). | Must |
| TR-FR-018 | On job completion, a background task SHALL PUBLISH to the corresponding Redis events channel with the same payload. | Must |
| TR-FR-019 | Training-api SHALL connect to Redis via the Redis service name (e.g. `redis:6379`) or REDIS_URL / REDIS_HOST / REDIS_PORT. | Must |

### 5.3 Volume and Artifacts

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-020 | Training-api SHALL mount the model_artifacts volume at one path to read trainer and refiner outputs. | Must |
| TR-FR-021 | When a background task finishes, training-api SHALL read artifact files and SHALL put the parsed result into Redis so the status endpoint can return it without re-reading the volume. | Must |
| TR-FR-022 | Promotion SHALL use a read-write mount of host `train.csv` (e.g. at `/promote_target/train.csv`) so POST /refine/promote can write the promoted dataset. | Must |

### 5.4 Image Modes

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-023 | The default CMD of the training-api image SHALL run the HTTP server (FastAPI app). | Must |
| TR-FR-024 | CLI mode SHALL be available via override (e.g. `docker compose run training-api promote`, `train`, `refine` subcommands) so scripts run the same Python code. | Must |

## 6. Gateway Proxy Requirements

### 6.1 Configuration and Routes

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-025 | The gateway SHALL have configuration for training-api base URL (e.g. env var `TRAINING_API_URL`). | Must |
| TR-FR-026 | The UI SHALL communicate only with the gateway; the gateway SHALL proxy to training-api. | Must |
| TR-FR-027 | The gateway SHALL proxy POST /api/train to training-api POST /train and SHALL return job_id with normal timeout. | Must |
| TR-FR-028 | The gateway SHALL proxy GET /api/train/events/{job_id} to training-api GET /train/events/{job_id} as a streaming proxy (SSE). | Must |
| TR-FR-029 | The gateway SHALL proxy GET /api/train/status/{job_id} and GET /api/train/last to the corresponding training-api endpoints. | Must |
| TR-FR-030 | The gateway SHALL proxy POST /api/refine/relabel, POST /api/refine/augment, GET /api/refine/relabel/events/{job_id}, GET /api/refine/augment/events/{job_id} to training-api. | Must |
| TR-FR-031 | The gateway SHALL proxy POST /api/refine/promote with a longer timeout of 5 min (300s). | Must |
| TR-FR-032 | For GET .../events/{job_id}, the gateway SHALL stream the SSE response from training-api to the client so EventSource works against the gateway origin. | Must |

## 7. Frontend Requirements

### 7.1 Navigation

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-033 | The UI SHALL provide navigation "Query \| Train \| Refine" that sets `location.hash` to `#`, `#train`, `#refine`. | Must |
| TR-FR-034 | On load and on hashchange, the UI SHALL show the corresponding section and SHALL hide the others. | Must |
| TR-FR-035 | The default view SHALL remain the existing query form and result section. | Must |

### 7.2 Train Page

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-036 | The Train page SHALL provide a "Run training" button that POSTs to /api/train, receives job_id, shows a progress bar, and opens EventSource to /api/train/events/{job_id}. | Must |
| TR-FR-037 | On receipt of one SSE event (completed or failed), the Train page SHALL close the EventSource, hide the progress bar, and render the result or error. | Must |
| TR-FR-038 | A progress bar SHALL be visible from POST until the SSE event is received and SHALL be indeterminate (animated). | Must |
| TR-FR-039 | The Train page MAY support "Load last run" via GET /api/train/last when no run has been triggered in the session. | Should |
| TR-FR-040 | Metrics SHALL be displayed in tabulated format: one row/summary for overall accuracy; table for classification_report (rows = labels, columns = precision, recall, f1-score, support); table for confusion_matrix with row/column labels. | Must |
| TR-FR-041 | Misclassified data SHALL be displayed in a table with columns: text, true_label, pred_label, pred_confidence, probs_json (or truncated). | Must |

### 7.3 Refine Page

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-042 | The Refine page SHALL provide a "Run refinement" button that POSTs to /api/refine, receives job_id, shows a progress bar, and opens EventSource to /api/refine/events/{job_id}. | Must |
| TR-FR-043 | On receipt of one SSE event, the Refine page SHALL close the EventSource and render the results. | Must |
| TR-FR-044 | The Refine page MAY support "Load last run" via GET /api/refine/last. | Should |
| TR-FR-045 | The Refine page SHALL display a report summary (rows_processed, relabels_proposed, examples_proposed, rows_skipped, errors) as a small table or definition list. | Must |
| TR-FR-046 | The Refine page SHALL display comparison (before vs after): metrics before and metrics after in the same structure as the Train page, side-by-side or with Before/After columns. | Must |
| TR-FR-047 | The Refine page SHALL provide a Promote button that POSTs to /api/refine/promote; SHALL show loading (promotion may take several minutes). | Must |
| TR-FR-048 | On promote success, the UI SHALL display the response (e.g. "Promoted" with acc_before/acc_after, or "Metrics did not improve; candidate discarded"); MAY remind the user to restart ai_router if promoted. | Must |
| TR-FR-049 | On promote error (e.g. train_candidate missing), the UI SHALL show an error message. | Must |
| TR-FR-050 | The Refine page SHALL display tabulated data: proposed relabels table, proposed examples table, train candidate table (sample or full with pagination if large). | Must |

### 7.4 Styling and UX

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-051 | The Train and Refine pages SHALL reuse existing CSS variables and layout from `services/gateway/app/static/styles.css`. | Must |
| TR-FR-052 | Table styles SHALL be added (e.g. .data-table, borders, alternating rows) and section classes (e.g. .train-section, .refine-section). | Must |
| TR-FR-053 | Trigger buttons SHALL be disabled and SHALL show "Running..." while EventSource is open or promote is in flight. | Must |
| TR-FR-054 | Errors SHALL be displayed in a message area. | Must |

## 8. Data and API Contract Requirements

### 8.1 Metrics (from trainer)

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-055 | Metrics SHALL include accuracy, classification_report (per-label precision, recall, f1-score, support), and confusion_matrix. | Must |
| TR-FR-056 | The classification_report SHALL be flattenable to table rows; confusion_matrix SHALL have row/column headers from label order. | Must |

### 8.2 Misclassified and Refine Data

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-057 | Misclassified entries SHALL include text, true_label, pred_label, pred_confidence, probs_json. | Must |
| TR-FR-058 | Refine response SHALL include report (rows_processed, relabels_proposed, examples_proposed, rows_skipped, errors), metrics_before, metrics_after, proposed_relabels, proposed_examples, train_candidate_sample (or equivalent). | Must |

### 8.3 Training API Endpoints

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-059 | POST /train SHALL create a job (generate job_id), store status "pending" in Redis, spawn a background task that runs the same Python train logic as CLI, and return immediately `{ "job_id": "..." }`. | Must |
| TR-FR-060 | On train completion, the background task SHALL read artifacts, SET Redis, and PUBLISH to job:train:events:{job_id}; on failure SHALL SET and PUBLISH error. | Must |
| TR-FR-061 | GET /train/events/{job_id} (SSE) SHALL subscribe to Redis channel job:train:events:{job_id} and SHALL send the first message (completed or failed) as an SSE event to the client then close the stream. | Must |
| TR-FR-062 | GET /train/status/{job_id} SHALL read from Redis and return job_id, status, result, error; SHALL return 404 if unknown or expired. | Must |
| TR-FR-063 | GET /train/last SHALL read the last run from the volume and return the same shape; SHALL return 404 if not present. | Must |
| TR-FR-064 | POST /refine/relabel and POST /refine/augment SHALL each create a job and run the same pattern as train (background task, SET Redis, PUBLISH to respective events channel); SHALL return `{ "job_id": "...", "run_id": "..." }` immediately. | Must |
| TR-FR-065 | GET /refine/relabel/events/{job_id} and GET /refine/augment/events/{job_id} SHALL stream progress and terminal events via SSE. | Must |
| TR-FR-066 | POST /refine/promote (or POST /promote) SHALL call the same Python promote logic as CLI; SHALL be synchronous with longer timeout. | Must |
| TR-FR-067 | POST /refine/promote SHALL return JSON with promoted (true/false), message, acc_before, acc_after; SHALL return 400 if train_candidate is missing; SHALL return 200 with promoted: false if metrics did not improve. | Must |

## 9. Docker Compose Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-068 | One Compose stack SHALL deploy the entire operation (gateway, Redis, training-api, ai_router, backends, etc.). | Must |
| TR-FR-069 | Redis SHALL be defined as a dedicated service (e.g. image redis:7-alpine) in the Compose file. | Must |
| TR-FR-070 | Training-api SHALL depend on Redis and SHALL have model_artifacts volume mount, Docker socket mount, Compose project directory mount, REDIS_URL (or REDIS_HOST/REDIS_PORT), and read-write mount for promotion (host train.csv at e.g. /promote_target/train.csv). | Must |
| TR-FR-071 | Training-api and Redis MAY be placed in an appropriate profile (e.g. ops or refine) so one deployment deploys all; the gateway MAY show "Training API not available" when the profile is inactive. | Should |
| TR-FR-072 | Default CMD of the training-api service SHALL be the HTTP server; override for CLI SHALL be e.g. `docker compose run training-api promote`. | Must |

## 10. Security and Robustness Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-NFR-005 | Training-api and Redis SHALL be restricted to the internal network; Docker socket and Redis SHALL NOT be exposed publicly. | Must |
| TR-NFR-006 | The gateway SHALL proxy to training-api on the internal network only. | Must |
| TR-NFR-007 | Process timeouts SHALL be applied for background jobs: train 1h (`RUN_TRAIN_TIMEOUT_SECONDS=3600`) and refine 10 min (`RUN_REFINE_TIMEOUT_SECONDS=600`) so a stuck run does not leak resources. | Must |
| TR-NFR-008 | Redis TTL on job keys SHALL be set to limit storage. | Must |
| TR-NFR-009 | Gateway proxy timeouts SHALL be normal (`REQUEST_TIMEOUT=30`) except for POST /api/refine/promote (`PROMOTE_TIMEOUT=300`, 5 min). | Must |
| TR-NFR-010 | After adding new Python dependencies (e.g. redis) and Dockerfile, the project SHALL run Snyk or project security check per project rules. | Must |
| TR-NFR-011 | Redis and training-api SHALL be documented in the stack; the Promote button and CLI trigger SHALL be documented. | Must |

## 11. Scripts and Single Implementation

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-FR-073 | Bash scripts (e.g. scripts/promote.sh) SHALL be updated to invoke training-api via Docker Compose (e.g. `docker compose run training-api promote`) instead of inlining business logic. | Must |
| TR-FR-074 | Any train/refine scripts SHALL use `docker compose run training-api train` and `docker compose run training-api refine` where applicable. | Must |

## 12. Definition of Done

The Train and Refine GUI Pages work SHALL be considered complete when:

| ID | Requirement | Priority |
| --- | --- | --- |
| TR-DOD-001 | Training-api service runs with HTTP server and CLI entrypoint; the same Python code is used for train, refine, and promote from both UI and scripts. | Must |
| TR-DOD-002 | Redis is a dedicated service in Compose; training-api uses it for job state and Pub/Sub; job completion is event-driven (no polling). | Must |
| TR-DOD-003 | POST /train and POST /refine return job_id immediately; GET .../events/{job_id} streams one SSE event on completion. | Must |
| TR-DOD-004 | The gateway proxies all training-api routes and streams SSE for events endpoints; POST /api/refine/promote has a longer timeout. | Must |
| TR-DOD-005 | The UI has Query \| Train \| Refine navigation with hash-based routing. | Must |
| TR-DOD-006 | Train page: Run training, progress bar, EventSource, metrics and misclassified tables rendered on completion; optional Load last run. | Must |
| TR-DOD-007 | Refine page: run refinement, progress bar, EventSource; on completion show report, comparison, tables; Promote button with result. | Must |
| TR-DOD-008 | scripts/promote.sh invokes training-api via Docker Compose. | Must |
| TR-DOD-009 | Training-api and Redis are on the internal network only; timeouts and TTL are applied; security check is run and documented. | Must |

## 13. References

- Plan: [TRAIN_AND_REFINE_GUI_PAGES_PLAN.md](../planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md)
- Trainer/refiner: PROJECT_PLAN.md Section 2.1 (trainer, refiner), Section 9.3
- Refiner flow and promote: REFINER_PLAN.md, REFINER_TECHNICAL.md,
  REFINER_FLOW.md in docs/auxiliary/refiner/
