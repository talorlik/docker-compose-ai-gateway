# System Architecture

System design, request flow, and component roles for the Local AI
Microservice Mesh. Per NFR-035.

## 1. Overview

The system is a locally runnable, multi-container microservice mesh where
an AI classifier selects the backend service for each incoming request.
The browser UI displays the exact path taken (application-level tracing)
per action.

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
  - Load `train.csv` from image
  - Train model, write `model.joblib` to shared volume
  - Write `metrics.json` and `misclassified.csv`
  - Exit

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

- **Compose:** `compose/docker-compose.yaml` - base config
- **Dev overlay:** `compose/docker-compose.dev.yaml` - hot reload, bind mounts
- **Scaling:** `docker compose up -d --scale search_service=3` - DNS round-robin
- **Profiles:** `train` for trainer service only

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

## 8. Error Handling

| Scenario | HTTP | Trace | Cause |
| --- | --- | --- | --- |
| Unknown | 404 | No backend hop | AI decision |
| Low confidence | 404 | No backend hop | Policy |
| Backend down | 502 | Attempted, failed | Infrastructure |
| AI router down | 503 | None | Infrastructure |
| Success | 200 | Full path | Normal |
