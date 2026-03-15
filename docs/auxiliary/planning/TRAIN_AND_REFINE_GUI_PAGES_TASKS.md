# Train and Refine GUI Pages: Actionable Tasks

<!-- markdownlint-disable MD013 -->
<!-- TECH-REF: §1..§10 = sections in ../architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md -->

Step-by-step tasks to build the Train and Refine pages and backend. Tasks are
incremental, small to medium in size, ordered from base up, and grouped into
batches so you can control pace (e.g. "do batch 1", then "do batch 2").

**References:**

- [TRAIN_AND_REFINE_GUI_PAGES_PLAN.md](../planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md)
- [TRAIN_AND_REFINE_GUI_PAGES_PRD.md](../requirements/TRAIN_AND_REFINE_GUI_PAGES_PRD.md)
- [TRAIN_AND_REFINE_GUI_PAGES_TECH.md](../architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md)

## Batch 1: Redis and Training-API Skeleton

**TECH:** §1 Goals, §4 Training API, §8 Compose/Volumes

Foundation: Redis in Compose and a minimal training-api service that can run
and connect to Redis.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 1.1 | Add Redis service to compose (e.g. image redis:7-alpine). No public ports. | Use profile refine/ops if stack uses one. | [x] |
| 1.2 | Create services/training-api/ and requirements.txt: fastapi, uvicorn, redis, httpx. | Pin versions per project norms. | [x] |
| 1.3 | Add Dockerfile: Python image, COPY app and requirements, CMD uvicorn. | Default port 8000. | [x] |
| 1.4 | Add app package and main.py: minimal FastAPI, GET /health returns 200. | | [x] |
| 1.5 | Add training-api service in compose: build, depends_on redis, REDIS_URL env. | No volume/socket mounts yet. | [x] |
| 1.6 | Read REDIS_URL or REDIS_HOST/REDIS_PORT in training-api; validate on startup. | Document env in README. | [x] |

**Batch 1 done when:** docker compose (with profile) starts Redis and training-api;
GET /health on training-api returns 200.

## Batch 2: Redis Client and Job State Helpers

**TECH:** §3 Event-Driven Flow (keys, Pub/Sub, SSE)

Implement Redis connection and helpers for job keys and Pub/Sub used by train/refine flows.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 2.1 | Add redis_client: connect via REDIS_URL or REDIS_HOST/REDIS_PORT. | get_connection() for app. | [x] |
| 2.2 | set_job_state(key, payload, ttl). Keys job:train:{id}, job:refine:{id}. | TTL 24h. | [x] |
| 2.3 | get_job_state(key) returns parsed JSON or None. | For status endpoints. | [x] |
| 2.4 | publish_job_event(channel, payload). Channels job:train:events:{id}, etc. | Used when background job completes. | [x] |
| 2.5 | subscribe_to_job_channel(channel): yield first message. | Redis SUBSCRIBE for SSE. | [x] |

**Batch 2 done when:** Code can set/get job state with TTL and pub/sub to event channels;
verifiable by test or script.

## Batch 3: Canonical run_train Implementation

**TECH:** §2 Architecture, §4 Training API, §7.1–7.2 Data (metrics, misclassified)

Implement the Python logic that runs the trainer via Docker Compose and reads artifacts (no HTTP yet).

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 3.1 | Add jobs/runner module with run_train(): docker compose run trainer from project dir. | Document mounts; add in later batch. | [x] |
| 3.2 | On success read metrics.json and misclassified.csv; parse to result dict. | accuracy, report, matrix, misclassified. | [x] |
| 3.3 | On failure, raise or return error so callers can SET failed and PUBLISH. | | [x] |
| 3.4 | Add process timeout (e.g. 1h) around compose run. | | [x] |

**Batch 3 done when:** run_train() runs trainer via Compose and returns metrics +
misclassified or error.

## Batch 4: Canonical run_refine and run_promote

**TECH:** §4 (CLI, volume, endpoints), §7.3–7.4 Refine/Promote data

Implement run_refine() and run_promote() and a CLI entrypoint so the same code is used by HTTP and scripts.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 4.1 | run_refine(): compose run refiner; read report, CSVs; run trainer for metrics_after. | See TECH doc. | [x] |
| 4.2 | On refiner failure, return/raise error for SET/PUBLISH. Apply 1h timeout. | | [x] |
| 4.3 | run_promote(): require train_candidate; copy to promote target; compare metrics; return promoted, message, acc. | 400 if missing; 200 with promoted false if no improvement. | [x] |
| 4.4 | Add CLI (app/cli.py): subcommands train, refine, promote; no Redis/HTTP. | For compose run. | [x] |
| 4.5 | Dockerfile/compose CMD override: training-api train/refine/promote runs python -m app.cli. | | [x] |

**Batch 4 done when:** docker compose run training-api train/refine/promote runs
canonical Python; mounts in Batch 7.

## Batch 5: Train HTTP Endpoints and Background Jobs

**TECH:** §3 Event flow, §4.3–4.4 Endpoints and background jobs

Wire run_train() into HTTP: create job, run in background, store result in Redis, publish event. Expose POST /train, GET /train/events, GET /train/status, GET /train/last.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 5.1 | job_id (UUID); background runner: SET pending, run_train(), SET result, PUBLISH. | Return immediately. | [x] |
| 5.2 | POST /train: job_id, SET pending in Redis, start background task, return job_id JSON. | | [x] |
| 5.3 | GET /train/status/{job_id}: read Redis key; return job_id, status, result, error; 404 if missing. | | [x] |
| 5.4 | GET /train/events/{job_id} SSE: SUBSCRIBE channel; first msg as SSE; close. | Handle disconnect. | [x] |
| 5.5 | GET /train/last: read last run from volume. 404 if absent. | Fixed path convention. | [x] |

**Batch 5 done when:** POST /train returns job_id; GET /train/events streams one SSE on completion;
GET /train/status and GET /train/last work. (Mounts added in Batch 7.)

## Batch 6: Refine and Promote HTTP Endpoints

**TECH:** §4.3–4.4 Endpoints, §7.4 Promote response

Same pattern as train for refine; synchronous endpoint for promote.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 6.1 | Background task for refine: run_refine(), keys job:refine:{id}, job:refine:events:{id}. | | [x] |
| 6.2 | POST /refine: job_id, SET pending, spawn run_refine task, return job_id JSON. | | [x] |
| 6.3 | GET /refine/status, GET /refine/events (SSE), GET /refine/last; same pattern as train. | | [x] |
| 6.4 | POST /refine/promote: sync run_promote(); return promoted, message, acc. | 400/200; gateway 5 min. | [x] |

**Batch 6 done when:** POST /refine and GET /refine/events, status, last work; POST /refine/promote runs promote and returns the expected JSON.

## Batch 7: Compose Mounts and Gateway Proxy (Non-SSE)

**TECH:** §5 Gateway Proxy, §8.2–8.3 Compose mounts and stack

Add full training-api service mounts in Compose and gateway proxy for all training-api routes except SSE (SSE in Batch 8).

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 7.1 | Compose: mount model_artifacts, socket, project dir, train.csv at promote_target. | | [x] |
| 7.2 | Gateway main.py: config TRAINING_API_URL (env). | | [x] |
| 7.3 | Proxy POST /api/train to training-api POST /train; normal timeout. | | [x] |
| 7.4 | Proxy GET /api/train/status/{job_id} and GET /api/train/last. | | [x] |
| 7.5 | Proxy POST /api/refine, GET /api/refine/status, GET /api/refine/last. | | [x] |
| 7.6 | Proxy POST /api/refine/promote with long timeout (e.g. 5 min). | | [x] |
| 7.7 | Training-api and Redis on internal network only. | | [x] |

**Batch 7 done when:** Gateway proxies train, refine, status, last, promote (SSE in Batch 8).

## Batch 8: Gateway SSE Streaming Proxy

**TECH:** §3.3 SSE endpoints, §5.3 Streaming proxy

Stream SSE from training-api to the client so EventSource can connect to the gateway origin.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 8.1 | Proxy GET /api/train/events/{job_id}: stream training-api response to client. | Chunk-by-chunk, no full buffer. | [x] |
| 8.2 | Same streaming proxy for GET /api/refine/events/{job_id}. | | [x] |
| 8.3 | No short timeout on events; close when API closes after one event. | | [x] |

**Batch 8 done when:** EventSource to gateway events/{job_id} receives SSE on completion.

## Batch 9: Frontend Navigation and Train/Refine Layout

**TECH:** §6 Frontend (nav, Train/Refine sections, styling)

Add navigation, hash-based routing, and the static structure and styles for Train and Refine sections.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 9.1 | index.html: nav Query / Train / Refine setting location.hash to #, #train, #refine. | | [x] |
| 9.2 | Sections for Query, Train, Refine; IDs/data attrs for show/hide. | | [x] |
| 9.3 | app.js: on load and hashchange, show section for current hash; hide others. | Default # stays query form. | [x] |
| 9.4 | Train: Run training button, progress bar, metrics and table placeholders. | | [x] |
| 9.5 | Refine section: Run refinement button, progress bar, report, comparison, tables, Promote. | | [x] |
| 9.6 | styles.css: .data-table, .train-section, .refine-section, progress bar animation. | Reuse existing vars. | [x] |

**Batch 9 done when:** Switching hash to #train or #refine shows the corresponding section with buttons and placeholders; progress bar style is defined; tables have basic styling.

## Batch 10: Frontend Train Page Behavior

**TECH:** §3.4 Client flow, §6.2 Train page, §7.1–7.2 Metrics/misclassified

Wire the Train section to the API: run training, EventSource, and render results.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 10.1 | Run training click: POST /api/train, get job_id; show progress, disable button, "Running...". | | [x] |
| 10.2 | EventSource to events/{job_id}; on event close, hide progress, render or error. | | [x] |
| 10.3 | Render metrics: accuracy, classification_report table, confusion_matrix table. | | [x] |
| 10.4 | Render misclassified table: text, true_label, pred_label, pred_confidence, probs_json. | | [x] |
| 10.5 | (Optional) Load last run: GET /api/train/last; render same tables. | | [x] |

**Batch 10 done when:** User can click "Run training", see progress until completion, then see metrics and misclassified tables; errors are shown in message area.

## Batch 11: Frontend Refine Page Behavior

**TECH:** §6.3 Refine page, §7.3–7.4 Refine result and Promote

Wire the Refine section to the API: run refinement, EventSource, render report and tables, and Promote with result.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 11.1 | Run refinement click: POST /api/refine, EventSource events; on event render or error. | | [x] |
| 11.2 | Render report: rows_processed, relabels_proposed, examples_proposed, rows_skipped, errors. | | [x] |
| 11.3 | Render comparison: metrics before/after (same as Train); side-by-side or Before/After columns. | | [x] |
| 11.4 | Render proposed relabels, proposed examples, train candidate tables (sample or paginated). | | [x] |
| 11.5 | Promote: POST promote, loading; show promoted or discarded. | Optionally remind restart ai_router. | [x] |
| 11.6 | (Optional) Load last run: GET /api/refine/last; render same result. | | [x] |
| 11.7 | Disable buttons, "Running..." while busy; errors in message area. | | [x] |

**Batch 11 done when:** User runs refinement, sees report and tables, uses Promote with feedback.

## Batch 12: Scripts and Security

**TECH:** §9 Security, §10 File summary, §4.1 CLI

Update scripts to use training-api CLI and apply security and documentation checks.

| # | Task | Notes | Done |
| --- | --- | --- | --- |
| 12.1 | Update scripts/promote.sh to docker compose run training-api promote. | Correct compose file and profile. | [x] |
| 12.2 | Update any train/refine scripts to use training-api train/refine. | | [x] |
| 12.3 | Verify training-api and Redis not on public ports; document in README. | | [x] |
| 12.4 | Confirm process timeout and Redis TTL applied; document in training-api. | | [x] |
| 12.5 | Run Snyk on training-api (deps, Dockerfile) per project rules. | Run `snyk auth` and `snyk trust` then snyk_code_scan + snyk_sca_scan on services/training-api. | [x] |
| 12.6 | Document Redis, training-api, Promote, CLI; note Ollama for Refine. | | [x] |

**Batch 12 done when:** promote.sh uses training-api; security and docs are in place.

## Summary

| Batch | Focus |
| --- | --- |
| 1 | Redis + training-api skeleton (Compose, Dockerfile, health) |
| 2 | Redis client and job state / Pub/Sub helpers |
| 3 | Canonical run_train (Compose run trainer, read artifacts) |
| 4 | Canonical run_refine, run_promote, CLI entrypoint |
| 5 | Train HTTP endpoints (POST, events SSE, status, last) |
| 6 | Refine and Promote HTTP endpoints |
| 7 | Compose mounts + gateway proxy (non-SSE) |
| 8 | Gateway SSE streaming proxy |
| 9 | Frontend nav, hash routing, Train/Refine layout and CSS |
| 10 | Frontend Train page behavior (POST, EventSource, tables) |
| 11 | Frontend Refine page behavior (POST, EventSource, Promote) |
| 12 | Scripts and security |

Execute batches in order. Within a batch, do tasks in sequence; see Notes for dependencies.
