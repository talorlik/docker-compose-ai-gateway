# System Architecture

System design, request flow, and component roles for the Local AI
Microservice Mesh. Per NFR-035. Intended for Solution Architects and
technical stakeholders.

## Table of Contents

1. [Overview](#1-overview)
2. [System Diagram](#2-system-diagram)
3. [Components](#3-components)
4. [Request Flow](#4-request-flow)
5. [Routing Model](#5-routing-model)
6. [Trace Contract](#6-trace-contract)
7. [Deployment](#7-deployment)
8. [Data Flow](#8-data-flow)
9. [Integration Points](#9-integration-points)
10. [Cross-Cutting Concerns](#10-cross-cutting-concerns)
11. [Error Handling](#11-error-handling)
12. [Related Documentation](#12-related-documentation)

## 1. Overview

### 1.1 Purpose

The system is a locally runnable, multi-container microservice mesh where
an AI classifier selects the backend service for each incoming request.
The browser UI provides Query (main API and trace), Train (run training,
view metrics and misclassified table), and Refine (run relabeling or
augmentation, view comparison, promote candidate). Train and Refine job
completion is event-driven via Redis Pub/Sub and Server-Sent Events (no
polling). The stack demonstrates Docker Compose advanced features
(profiles, health checks, anchors) and AI-driven intent routing without
external observability dependencies.

### 1.2 Architecture Principles

- **AI-driven routing:** Intent classification via scikit-learn (TF-IDF +
  Logistic Regression); no rule-based routing.
- **Application-level tracing:** End-to-end trace per request; no external
  APM or tracing stack required.
- **Profile-based deployment:** Runtime stack (gateway, ai-router, backends)
  runs by default; trainer and refiner run on demand via profiles.
- **Separation of concerns:** Inference (ai-router) and training (trainer)
  are separate; model artifact flows via shared volume. Training-api is the
  single implementation for train, refine, and promote (HTTP and CLI).
- **Event-driven train/refine:** Redis job state and Pub/Sub; SSE streams
  one completion event to the UI (no polling or long timeouts).
- **Deterministic, reproducible:** Fixed random_state, CPU-only, cross-platform.

### 1.3 Technology Stack

| Layer | Technology |
| --- | --- |
| Runtime | Python 3.12, FastAPI, Uvicorn/Gunicorn |
| AI/ML | scikit-learn (TF-IDF, Logistic Regression), joblib |
| Refinement | Ollama (phi3:mini) for dataset improvement |
| Job state / events | Redis (job keys with TTL, Pub/Sub for SSE) |
| Containerization | Docker, Docker Compose |
| Platform | Linux, Mac, Windows |

### 1.4 Repository Structure

```text
compose/          # docker-compose.yaml (base), docker-compose.dev.yaml
services/         # gateway, ai_router, search_service, image_service,
                  # ops_service, trainer, refiner, training-api
scripts/          # demo.sh, load_test.sh, promote.sh,
                  # refine_relabel.sh, refine_augment.sh, generate_env.py
docs/auxiliary/   # architecture, demo, planning, refiner, requirements
```

## 2. System Diagram

The following diagram shows the full project: query path (gateway, ai-router,
backends), train/refine path (gateway, training-api, Redis, trainer/refiner),
and shared model artifacts.

```mermaid
flowchart TB
  subgraph browser [Browser]
    UI[Query / Train / Refine]
  end

  subgraph gateway_svc [Gateway]
    GW[Gateway]
  end

  subgraph runtime [Runtime Stack]
    AR[AI Router]
    SS[search_service]
    IS[image_service]
    OS[ops_service]
  end

  subgraph training_stack [Training Stack - API & Redis always on; trainer/refiner on-demand]
    subgraph training_api_svc [Training API]
      API[Training API]
    end
    Redis[Redis]
    Trainer[trainer]
    Refiner[refiner (legacy)]
  end

  subgraph ollama_svc [Ollama - profile refine-container]
    Ollama[ollama]
  end

  subgraph volumes [Volumes]
    MA[model_artifacts]
    OD[ollama_data]
  end

  UI -->|GET /, POST /api/request| GW
  UI -->|POST /api/train, POST /api/refine/relabel_or_augment, SSE events, POST promote| GW

  GW -->|POST /classify| AR
  GW -->|POST /handle| SS
  GW -->|POST /handle| IS
  GW -->|POST /handle| OS
  GW -->|proxy train/relabel/augment/promote, proxy SSE| API

  API -->|job state, PUBLISH/SUBSCRIBE| Redis
  API -->|docker compose run| Trainer
  API -->|docker compose run| Refiner
  Trainer -->|read/write| MA
  Refiner -->|read/write| MA
  API -->|read artifacts| MA
  AR -->|load model| MA
  API -->|LLM prompts (refine workers)| Ollama
  Ollama -->|persist| OD
```

**Flows:**

- **Query:** User -> Gateway -> AI Router (classify) -> Gateway -> Backend
  (handle) -> Gateway -> User. Model loaded from model_artifacts.
- **Train:** User -> Gateway (POST /api/train) -> Training API -> job_id; UI
  opens SSE to gateway -> training-api subscribes to Redis; background task
  runs trainer via Compose, writes to model_artifacts, then PUBLISHes;
  client gets one SSE event and renders metrics/misclassified.
- **Refine:** Same job pattern, but split into relabeling and augmentation
  endpoints. Training API enqueues tasks into Redis Streams, workers call the
  Ollama service (single Compose service; client-side pool may target one URL),
  then UI renders before/after metrics and proposed rows; Promote calls POST
  /api/refine/promote with run_id.

## 3. Components

### 3.1 Gateway

- **Role:** Entry point for all requests. Serves static UI and main API;
  proxies to ai-router, backends, and training-api.
- **Endpoints:**
  - `GET /` - Static web UI (Query, Train, Refine via hash routing)
  - `POST /api/request` - Main API entrypoint
  - `GET /routes` - List of route labels and backend URLs
  - `GET /health` - Health check
  - `POST /api/train`, `GET /api/train/events/{job_id}`,
    `GET /api/train/status/{job_id}`, `GET /api/train/last` - Proxy to training-api
  - `POST /api/refine/relabel`, `GET /api/refine/relabel/events/{job_id}` - Proxy
  to training-api
  - `POST /api/refine/augment`, `GET /api/refine/augment/events/{job_id}` - Proxy
  to training-api
  - `POST /api/refine/promote` - Proxy to training-api
    (longer timeout, 5 min / 300s)
- **Responsibilities:**
  - Generate or accept `request_id` (UUID)
  - Call ai-router `POST /classify` with request text
  - Apply routing policy (confidence threshold, margin)
  - Return 404 if route is unknown or below threshold
  - Proxy to selected backend `POST /handle` otherwise
  - Aggregate trace and timings from all hops
  - Return 502 on backend failure, 503 on ai-router failure
  - Stream SSE from training-api for GET .../events/{job_id} so the UI
    receives job completion via EventSource without polling

### 3.2 AI Router

- **Role:** Intent classification. Runs lightweight text classifier.
- **Endpoints:**
  - `POST /classify` - Classify text, return route, confidence, explanation
  - `GET /health` - Health check
- **Responsibilities:**
  - Load model artifact at startup (from volume or build-time)
  - Vectorize input, predict route and probabilities
  - Return route, confidence, probabilities, explanation (top tokens)
  - Append trace entry for classification

### 3.3 Backend Services

| Service | Role | Simulates |
| --- | --- | --- |
| search_service | Information lookup | Research, comparison queries |
| image_service | Image handling | Detection, processing |
| ops_service | DevOps | Troubleshooting, infrastructure |

Each backend:

- Exposes `POST /handle` and `GET /health`
- Accepts `request_id` and `text`
- Returns `payload` and `trace_append`
- Includes `instance` (hostname) in payload for scaling visibility

### 3.4 Trainer

- **Role:** One-shot training container. Invoked by training-api (or directly
  via profile). Not part of the default runtime stack.
- **Usage:** `docker compose --profile train run --rm trainer`, or via
  training-api when the UI starts a train job.
- **Responsibilities:**
  - Load `train.csv` from host (mounted at runtime)
  - Train model, write `model.joblib` to shared volume
  - Write `metrics.json` and `misclassified.csv`
  - Exit

### 3.5 Refiner

- **Role:** Offline dataset improvement via local LLM. Invoked by training-api
  (or directly via profile). Not part of the default runtime stack.
- **Usage:** `docker compose --profile refine run --rm refiner` (after trainer),
  or via training-api when the UI starts a refine job.
- **Responsibilities:**
  - Read `misclassified.csv` and `train.csv` from shared volume
  - Call Ollama (phi3:mini) for relabel suggestions and augmentation
  - Write `proposed_relabels.csv`, `proposed_examples.csv`, `train_candidate.csv`
  - Exit; promotion to `train.csv` via training-api (POST /refine/promote) or
    `scripts/promote.sh` when metrics improve

### 3.6 Ollama

- **Role:** Local LLM server for the refiner. Profile `refine` only.
- **Usage:** Started automatically when `docker compose --profile refine up` runs.
- **Responsibilities:**
  - Serve phi3:mini model (pulled on first run)
  - Expose API at `http://ollama:11434` for refiner to call
  - Persist model data in `ollama_data` volume

See [REFINER_PLAN.md](../refiner/REFINER_PLAN.md),
[REFINER_TECHNICAL.md](../refiner/REFINER_TECHNICAL.md),
[REFINER_FLOW.md](../refiner/REFINER_FLOW.md).

### 3.7 Training API

- **Role:** Canonical Python implementation of train, refine, and promote.
  Exposes HTTP API for the UI and CLI entrypoint for scripts (e.g.
  `docker compose run training-api promote`). Same code for both triggers.
- **Location:** `services/training-api/`. Profile `ops` or `refine`.
- **Endpoints:** POST /train, GET /train/events/{job_id}, GET /train/status/{job_id},
  GET /train/last; POST /refine/relabel, GET /refine/relabel/events/{job_id};
  POST /refine/augment, GET /refine/augment/events/{job_id};
  POST /refine/promote.
- **Responsibilities:**
  - Create jobs (job_id), store state in Redis (TTL e.g. 24h), spawn background
    task that runs trainer/refiner via Docker Compose
  - On completion: read artifacts from model_artifacts volume, SET Redis key,
    PUBLISH to Redis channel; GET .../events/{job_id} SUBSCRIBEs to channel and
    streams one SSE event to client then closes
  - POST /refine/promote: synchronous run_promote(), write promoted dataset to
    mounted train.csv; return promoted flag, acc_before/acc_after, tolerance
    metadata, and per-label recall comparison
- **Event-driven:** No polling; job completion notified via Redis Pub/Sub and
  SSE. See [TRAIN_AND_REFINE_GUI_PAGES_TECH.md](TRAIN_AND_REFINE_GUI_PAGES_TECH.md).

### 3.8 Redis

- **Role:** Dedicated service for training-api job state and Pub/Sub. Enables
  event-driven completion (SSE) without polling or long timeouts.
- **Usage:** Runs when training-api profile is active. Training-api connects via
  REDIS_URL or REDIS_HOST/REDIS_PORT (e.g. `redis:6379`).
- **Responsibilities:**
  - Job keys `job:train:{job_id}` and `job:refine:{job_id}` with JSON state
    (status, result, error, created_at) and TTL
  - Pub/Sub channels `job:train:events:{job_id}` and `job:refine:events:{job_id}`;
    training-api PUBLISHes on job completion; SSE endpoint SUBSCRIBEs and streams
    first message to client
- **Network:** Internal only; not exposed publicly.

## 4. Request Flow

```ascii
User (browser/curl)
    |
    v
Gateway (POST /api/request)
    |
    +---> AI Router (POST /classify)
    |         |
    |         v
    |     route, confidence, probabilities, explanation
    |
    +---> [if route != unknown and confidence OK]
    |         |
    |         v
    |     Backend (POST /handle)
    |         |
    |         v
    |     payload, trace_append
    |
    v
Gateway aggregates trace, returns response
```

**Train / Refine flow (event-driven):**

```ascii
User (Train or Refine page)
    |
    v
Gateway (POST /api/train or POST /api/refine/relabel or /augment) -> Training API
    |
    v
Training API: create job_id, store "pending" in Redis, spawn background task,
              return { job_id } immediately
    |
    +---> Background: docker compose run trainer|refiner -> read artifacts
    |              -> SET Redis key, PUBLISH to job:train:events:{id} or
    |                 job:refine:events:{id}
    |
User opens EventSource to Gateway (GET /api/train/events/{job_id} or refine)
    |
    v
Gateway streams SSE from Training API <- Training API SUBSCRIBEs to Redis channel
    |
    v
First message (completed|failed) -> client closes EventSource, renders result
```

Promote is synchronous: POST /api/refine/promote -> gateway -> training-api
run_promote() -> response with promoted, acc_before, acc_after, tolerance fields,
per_label_recall.

## 5. Routing Model

**Labels:** `search`, `image`, `ops`, `unknown`

**Policy (gateway):**

- `T_ROUTE` (runtime 0.60 via Compose; code fallback 0.55): minimum
  confidence to route
- `T_MARGIN` (default 0.10): minimum gap between top-1 and top-2
- If route is `unknown` or below threshold or margin: return 404, no proxy
- Otherwise: proxy to backend

## 6. Trace Contract

Each trace entry: `service`, `event`, `ts` (ISO 8601), optional `meta`.

**Typical trace sequence (success):**

1. web - submit
2. gateway - received
3. ai-router - classified
4. gateway - (internal)
5. backend - handled
6. gateway - responded

**Unknown (404):** No backend hop. Trace ends at gateway-responded.

**Backend failure (502):** Backend hop attempted, failed. Trace shows error in meta.

## 7. Deployment

### 7.1 Compose Configuration

- **Base:** `compose/docker-compose.yaml` - anchors (x-common-env,
  x-common-healthcheck, x-common-logging), health checks, profiles. Services
  run from built images.
- **Central config:** `config/PROJECT_CONFIG.yaml` - single source of truth for
  project-wide settings (paths, Redis URL, Ollama URLs, refine knobs); see
  `CONFIGURATION.md` for details. Env files such as `env/.env.dev` are
  generated from this file via `scripts/generate_env.py` and consumed by
  Docker Compose (`env_file`).
- **Dev overlay:** `compose/docker-compose.dev.yaml` - overlay merged with the
  base via a second `-f`; adds bind mounts and `uvicorn --reload` for the five
  app services so source changes apply without rebuild. Launch with both files:

  ```bash
  docker compose -f compose/docker-compose.yaml -f compose/docker-compose.dev.yaml up --build
  ```

### 7.2 Profiles

| Profile | Services | When to Use |
| --- | --- | --- |
| (default) | gateway, ai_router, search_service, image_service, ops_service, redis, training-api | Normal runtime (includes Train/Refine API proxy and SSE) |
| train | trainer | Retrain model: `--profile train run --rm trainer` |
| refine | refiner | Dataset refinement: `run --rm refiner` (with Ollama up; see refine-container) |
| refine-container | ollama | Long-running Ollama for refine workers: e.g. `--profile refine-container up -d ollama` |

### 7.3 Volumes

| Volume | Purpose |
| --- | --- |
| model_artifacts | Shared between trainer (write), ai_router (read), refiner (read/write), training-api (read) |
| ollama_data | Ollama model storage (phi3:mini) |

### 7.4 Scaling

- **Horizontal scaling:** `docker compose up -d --scale search_service=3`
- **Load distribution:** DNS round-robin via Compose service discovery
- **Visibility:** Backend payload includes `instance` (hostname) for scaling demos

### 7.5 Health and Dependencies

- Gateway depends on ai_router and all backends with `condition: service_healthy`
- Training-api depends on Redis (e.g. `depends_on: redis`)
- Refiner depends on Ollama with `condition: service_healthy`
- Health checks hit `GET /health` on each service (10s interval, 5s timeout)

## 8. Data Flow

```ascii
train.csv (trainer)
    |
    v
model.joblib (shared volume or build-time)
    |
    v
ai_router (loads at startup)
    |
    v
/classify -> route, confidence, probabilities
    |
    v
gateway (applies policy, proxies or 404)
```

**Refined dataset flow:** trainer -> misclassified.csv -> refiner (Ollama) ->
train_candidate.csv -> training-api (POST /refine/promote or scripts/promote.sh):
retrain, compare metrics, promote if improved. See [REFINER_FLOW.md](../refiner/REFINER_FLOW.md).

**Train/Refine UI flow:** UI POSTs to gateway -> training-api creates job, returns
job_id; UI opens EventSource to gateway -> training-api SSE endpoint SUBSCRIBEs
to Redis; background task runs trainer/refiner, then PUBLISHes; client receives
one SSE event and renders result. No polling. See
[TRAIN_AND_REFINE_GUI_PAGES_TECH.md](TRAIN_AND_REFINE_GUI_PAGES_TECH.md).

## 9. Integration Points

### 9.1 Client Interfaces

| Interface | Endpoint | Consumers |
| --- | --- | --- |
| Web UI | `GET /` | Browser (Query, Train, Refine via hash routing) |
| Main API | `POST /api/request` | Browser, curl, scripts |
| Train API | `POST /api/train`, `GET /api/train/events/{job_id}`, etc. | Browser (Train page) |
| Refine API | `POST /api/refine/relabel`, `POST /api/refine/augment`, `GET /api/refine/*/events/{job_id}`, `POST /api/refine/promote` | Browser (Refine page) |
| Routes discovery | `GET /routes` | Clients needing backend URLs |
| Health | `GET /health` | Compose health checks, load balancers |

### 9.2 Internal Service Communication

- Gateway -> ai_router: `POST /classify` (synchronous)
- Gateway -> backends: `POST /handle` (synchronous, one per request)
- Gateway -> training-api: proxy POST/GET (including streaming SSE for
  .../events/{job_id}); TRAINING_API_URL env
- Training-api -> Redis: job keys (SET/GET), Pub/Sub (PUBLISH/SUBSCRIBE)
- Training-api -> trainer/refiner: Docker Compose run (one-shot)
- Refiner -> Ollama: HTTP API (relabel and augmentation prompts)
- All internal calls use service names (e.g., `http://ai_router:8000`)

## 10. Cross-Cutting Concerns

### 10.1 Observability

- **Tracing:** Application-level only; `request_id` propagated end-to-end
- **Logging:** JSON-file driver, 10MB max, 3 files; `request_id` in logs
- **Health:** `/health` on all services; Compose uses for startup ordering

### 10.2 Security

- **No external dependencies:** Runs fully offline; no cloud or third-party APIs
- **Non-root runtime:** Services run as non-root user in containers (per NFR-016)
- **Minimal surface:** Single exposed port (8000); refiner and trainer are
  on-demand, not long-running; training-api and Redis are internal only (no
  public ports)
- **Internal only:** Redis and training-api are not exposed publicly; gateway
  proxies to training-api on internal network

### 10.3 Non-Functional Attributes

| Attribute | Approach |
| --- | --- |
| Cross-platform | Docker Compose on Linux, Mac, Windows |
| CPU-only | No GPU; scikit-learn and Ollama run on CPU |
| Deterministic | Fixed random_state in training; reproducible builds |
| Request timeout | Configurable via REQUEST_TIMEOUT env (default 30s) |

## 11. Error Handling

| Scenario | HTTP | Trace | Cause |
| --- | --- | --- | --- |
| Unknown | 404 | No backend hop | AI decision |
| Low confidence | 404 | No backend hop | Policy |
| Backend down | 502 | Attempted, failed | Infrastructure |
| AI router down | 503 | None | Infrastructure |
| Success | 200 | Full path | Normal |

## 12. Related Documentation

| Document | Description |
| --- | --- |
| [TECHNICAL.md](TECHNICAL.md) | Training pipeline, routing policy, model details |
| [TRAIN_AND_REFINE_GUI_PAGES_TECH.md](TRAIN_AND_REFINE_GUI_PAGES_TECH.md) | Train/Refine UI, training-api, Redis, SSE, data contracts |
| [PROJECT_PLAN.md](../planning/PROJECT_PLAN.md) | Project overview and technical requirements |
| [PRD.md](../requirements/PRD.md) | Product requirements and functional specs |
| [DEMO.md](../demo/DEMO.md) | Build, run, scaling, and failure demos |
| [REFINER_FLOW.md](../refiner/REFINER_FLOW.md) | Refiner end-to-end flow |
