# System Architecture

System design, request flow, and component roles for the Local AI
Microservice Mesh. Per NFR-035. Intended for Solution Architects and
technical stakeholders.

## Table of Contents

1. [Overview](#1-overview)
2. [Components](#2-components)
3. [Request Flow](#3-request-flow)
4. [Routing Model](#4-routing-model)
5. [Trace Contract](#5-trace-contract)
6. [Deployment](#6-deployment)
7. [Data Flow](#7-data-flow)
8. [Integration Points](#8-integration-points)
9. [Cross-Cutting Concerns](#9-cross-cutting-concerns)
10. [Error Handling](#10-error-handling)
11. [Related Documentation](#11-related-documentation)

## 1. Overview

### 1.1 Purpose

The system is a locally runnable, multi-container microservice mesh where
an AI classifier selects the backend service for each incoming request.
The browser UI displays the exact path taken (application-level tracing)
per action. It demonstrates Docker Compose advanced features (profiles,
health checks, anchors) and AI-driven intent routing without external
observability dependencies.

### 1.2 Architecture Principles

- **AI-driven routing:** Intent classification via scikit-learn (TF-IDF +
  Logistic Regression); no rule-based routing.
- **Application-level tracing:** End-to-end trace per request; no external
  APM or tracing stack required.
- **Profile-based deployment:** Runtime stack (gateway, ai-router, backends)
  runs by default; trainer and refiner run on demand via profiles.
- **Separation of concerns:** Inference (ai-router) and training (trainer)
  are separate; model artifact flows via shared volume.
- **Deterministic, reproducible:** Fixed random_state, CPU-only, cross-platform.

### 1.3 Technology Stack

| Layer | Technology |
| --- | --- |
| Runtime | Python 3.12, FastAPI, Uvicorn/Gunicorn |
| AI/ML | scikit-learn (TF-IDF, Logistic Regression), joblib |
| Refinement | Ollama (Qwen2.5 7B-Instruct) for dataset improvement |
| Containerization | Docker, Docker Compose |
| Platform | Linux, Mac, Windows |

### 1.4 Repository Structure

```text
compose/          # docker-compose.yaml (base), docker-compose.dev.yaml
services/         # gateway, ai_router, search_service, image_service,
                  # ops_service, trainer, refiner
scripts/          # demo.sh, load_test.sh, promote.sh
docs/auxiliary/   # architecture, demo, planning, refiner, requirements
```

## 2. Components

### 2.1 Gateway

- **Role:** Entry point for all requests. Serves static UI and main API.
- **Endpoints:**
  - `GET /` - Static web UI
  - `POST /api/request` - Main API entrypoint
  - `GET /routes` - List of route labels and backend URLs
  - `GET /health` - Health check
- **Responsibilities:**
  - Generate or accept `request_id` (UUID)
  - Call ai-router `POST /classify` with request text
  - Apply routing policy (confidence threshold, margin)
  - Return 404 if route is unknown or below threshold
  - Proxy to selected backend `POST /handle` otherwise
  - Aggregate trace and timings from all hops
  - Return 502 on backend failure, 503 on ai-router failure

### 2.2 AI Router

- **Role:** Intent classification. Runs lightweight text classifier.
- **Endpoints:**
  - `POST /classify` - Classify text, return route, confidence, explanation
  - `GET /health` - Health check
- **Responsibilities:**
  - Load model artifact at startup (from volume or build-time)
  - Vectorize input, predict route and probabilities
  - Return route, confidence, probabilities, explanation (top tokens)
  - Append trace entry for classification

### 2.3 Backend Services

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

### 2.4 Trainer

- **Role:** One-shot training container. Not part of the runtime stack.
- **Usage:** `docker compose --profile train run --rm trainer`
- **Responsibilities:**
  - Load `train.csv` from host (mounted at runtime)
  - Train model, write `model.joblib` to shared volume
  - Write `metrics.json` and `misclassified.csv`
  - Exit

### 2.5 Refiner

- **Role:** Offline dataset improvement via local LLM. Not part of the runtime stack.
- **Usage:** `docker compose --profile refine run --rm refiner` (after trainer)
- **Responsibilities:**
  - Read `misclassified.csv` and `train.csv` from shared volume
  - Call Ollama (Qwen2.5 7B-Instruct) for relabel suggestions and augmentation
  - Write `proposed_relabels.csv`, `proposed_examples.csv`, `train_candidate.csv`
  - Exit; promotion to `train.csv` via `scripts/promote.sh` only when metrics improve

### 2.6 Ollama

- **Role:** Local LLM server for the refiner. Profile `refine` only.
- **Usage:** Started automatically when `docker compose --profile refine up` runs.
- **Responsibilities:**
  - Serve Qwen2.5 7B-Instruct model (pulled on first run)
  - Expose API at `http://ollama:11434` for refiner to call
  - Persist model data in `ollama_data` volume

See [REFINER_PLAN.md](../refiner/REFINER_PLAN.md),
[REFINER_TECHNICAL.md](../refiner/REFINER_TECHNICAL.md),
[REFINER_FLOW.md](../refiner/REFINER_FLOW.md).

## 3. Request Flow

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

## 4. Routing Model

**Labels:** `search`, `image`, `ops`, `unknown`

**Policy (gateway):**

- `T_ROUTE` (default 0.60): minimum confidence to route
- `T_MARGIN` (default 0.10): minimum gap between top-1 and top-2
- If route is `unknown` or below threshold or margin: return 404, no proxy
- Otherwise: proxy to backend

## 5. Trace Contract

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

## 6. Deployment

### 6.1 Compose Configuration

- **Base:** `compose/docker-compose.yaml` - anchors (x-common-env,
  x-common-healthcheck, x-common-logging), health checks, profiles
- **Dev overlay:** `compose/docker-compose.dev.yaml` - hot reload, bind mounts

### 6.2 Profiles

| Profile | Services | When to Use |
| --- | --- | --- |
| (default) | gateway, ai_router, search_service, image_service, ops_service | Normal runtime |
| train | trainer | Retrain model: `--profile train run --rm trainer` |
| refine | ollama, refiner | Dataset refinement: `--profile refine up` or `run --rm refiner` |

### 6.3 Volumes

| Volume | Purpose |
| --- | --- |
| model_artifacts | Shared between trainer (write), ai_router (read), refiner (read/write) |
| ollama_data | Ollama model storage (Qwen2.5 7B-Instruct) |

### 6.4 Scaling

- **Horizontal scaling:** `docker compose up -d --scale search_service=3`
- **Load distribution:** DNS round-robin via Compose service discovery
- **Visibility:** Backend payload includes `instance` (hostname) for scaling demos

### 6.5 Health and Dependencies

- Gateway depends on ai_router and all backends with `condition: service_healthy`
- Refiner depends on Ollama with `condition: service_healthy`
- Health checks hit `GET /health` on each service (10s interval, 5s timeout)

## 7. Data Flow

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
train_candidate.csv -> promote.sh (retrain, compare metrics, promote if improved).
See [REFINER_FLOW.md](../refiner/REFINER_FLOW.md).

## 8. Integration Points

### 8.1 Client Interfaces

| Interface | Endpoint | Consumers |
| --- | --- | --- |
| Web UI | `GET /` | Browser (static HTML/JS/CSS) |
| Main API | `POST /api/request` | Browser, curl, scripts |
| Routes discovery | `GET /routes` | Clients needing backend URLs |
| Health | `GET /health` | Compose health checks, load balancers |

### 8.2 Internal Service Communication

- Gateway -> ai_router: `POST /classify` (synchronous)
- Gateway -> backends: `POST /handle` (synchronous, one per request)
- Refiner -> Ollama: HTTP API (relabel and augmentation prompts)
- All internal calls use service names (e.g., `http://ai_router:8000`)

## 9. Cross-Cutting Concerns

### 9.1 Observability

- **Tracing:** Application-level only; `request_id` propagated end-to-end
- **Logging:** JSON-file driver, 10MB max, 3 files; `request_id` in logs
- **Health:** `/health` on all services; Compose uses for startup ordering

### 9.2 Security

- **No external dependencies:** Runs fully offline; no cloud or third-party APIs
- **Non-root runtime:** Services run as non-root user in containers (per NFR-016)
- **Minimal surface:** Single exposed port (8000); refiner and trainer are
  on-demand, not long-running

### 9.3 Non-Functional Attributes

| Attribute | Approach |
| --- | --- |
| Cross-platform | Docker Compose on Linux, Mac, Windows |
| CPU-only | No GPU; scikit-learn and Ollama run on CPU |
| Deterministic | Fixed random_state in training; reproducible builds |
| Request timeout | Configurable via REQUEST_TIMEOUT env (default 30s) |

## 10. Error Handling

| Scenario | HTTP | Trace | Cause |
| --- | --- | --- | --- |
| Unknown | 404 | No backend hop | AI decision |
| Low confidence | 404 | No backend hop | Policy |
| Backend down | 502 | Attempted, failed | Infrastructure |
| AI router down | 503 | None | Infrastructure |
| Success | 200 | Full path | Normal |

## 11. Related Documentation

| Document | Description |
| --- | --- |
| [TECHNICAL.md](TECHNICAL.md) | Training pipeline, routing policy, model details |
| [PROJECT_PLAN.md](../planning/PROJECT_PLAN.md) | Project overview and technical requirements |
| [PRD.md](../requirements/PRD.md) | Product requirements and functional specs |
| [DEMO.md](../demo/DEMO.md) | Build, run, scaling, and failure demos |
| [REFINER_FLOW.md](../refiner/REFINER_FLOW.md) | Refiner end-to-end flow |
