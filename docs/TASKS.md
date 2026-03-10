# Actionable Tasks: Local AI Microservice Mesh

Step-by-step tasks derived from [PRD.md](PRD.md). Execute by batch: e.g.
"Do batch 1," then "Do batch 2." Tasks are small to medium and ordered
from foundation up.

> [!TIP]
> The **Tech spec** column references sections in
> [TECHNICAL.md](TECHNICAL.md) using the format `TECH-{section}`.
> When actioning a task, read the referenced section(s) for
> implementation details, code snippets, and design decisions.
> A dash (`-`) means no specific technical section applies.

## Batch 1: Repository and Compose Foundation

**Goal:** Repo structure and a minimal Compose stack that starts all
services with health checks.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 1.1 | Create directory structure: `compose/`, `services/gateway/`, `services/ai_router/`, `services/search_service/`, `services/image_service/`, `services/ops_service/`, `scripts/`, `docs/`. | NFR-009 | - | x |
| 1.2 | Create `compose/docker-compose.yaml` with anchors: `x-common-env`, `x-common-healthcheck`, `x-common-logging` (no services yet). | NFR-024, NFR-026 | TECH-16 | x |
| 1.3 | Add gateway service: `services/gateway/` with `Dockerfile` (multi-stage, Python 3.12-slim), `requirements.txt` (fastapi, uvicorn), `app/main.py` exposing `GET /` (placeholder) and `GET /health` returning 200. | FR-001, NFR-014, NFR-015, FR-060 | TECH-14.1 | x |
| 1.4 | Add ai_router service skeleton: same pattern (Dockerfile, requirements.txt, app/main.py) with `GET /health` only. | NFR-010, FR-063 | TECH-1, TECH-12 | x |
| 1.5 | Add search_service, image_service, ops_service skeletons: Dockerfile, requirements.txt, app/main.py, `GET /health` each. | FR-010, FR-067 | TECH-13 | x |
| 1.6 | Define all five services in `compose/docker-compose.yaml` using anchors; set healthcheck per service; no `depends_on` yet. | NFR-028 | TECH-16.1 | x |
| 1.7 | Run `docker compose -f compose/docker-compose.yaml up --build` and verify all five services start and `GET /health` returns 200 for each. | AC-001 | - | x |

## Batch 2: AI Router Model and Training

**Goal:** Training data, training script, build-time model artifact, and
ai-router `/classify` endpoint.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 2.1 | Create `services/trainer/` and add `train.csv` with `text,label`; minimum 160 examples per label (search-service, image-service, ops-service, unknown); balanced. | FR-039-FR-046 | TECH-2 | x |
| 2.2 | Implement `services/trainer/train.py`: load train.csv, TfidfVectorizer(ngram_range=(1,2), min_df=2), LogisticRegression(max_iter=2000, solver="lbfgs", multi_class="multinomial", random_state fixed), fit, save vectorizer + model + label list (e.g. joblib). | FR-047-FR-053 | TECH-1, TECH-2, TECH-3 | x |
| 2.3 | Update ai_router Dockerfile to copy pre-built `model.joblib` from `services/ai_router/model/`; no training stage (training is handled by the trainer service). | NFR-020, FR-054 | TECH-15 | x |
| 2.4 | Update ai_router runtime stage: copy model artifact from training stage; load model at startup. | NFR-021 | TECH-7.5, TECH-12.2, TECH-15 | x |
| 2.5 | Implement `POST /classify`: accept `request_id`, `text`; vectorize, predict route and probabilities; return `route`, `confidence`, `explanation` (top features), `trace_append`. | FR-062, FR-064, FR-055-FR-057 | TECH-8, TECH-12 | x |
| 2.6 | Add unit tests for ai-router classification (route output, confidence, explanation shape). | NFR-038 | - | x |

## Batch 3: Backend Services and Trace Contract

**Goal:** Backends implement `POST /handle` and return `trace_append`;
trace schema and request_id propagation defined.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 3.1 | Define trace entry schema: `service`, `event`, `ts` (ISO 8601), optional `meta`. Document in code or docs. | FR-034, FR-035 | TECH-11.2 | x |
| 3.2 | Implement search_service `POST /handle`: accept `request_id`, `text`; return simulated lookup payload and `trace_append` (one entry). | FR-010, FR-065, FR-066 | TECH-13 | x |
| 3.3 | Implement image_service `POST /handle`: accept `request_id`, `text`; return simulated image-handling payload and `trace_append`. | FR-011, FR-065, FR-066 | TECH-13 | x |
| 3.4 | Implement ops_service `POST /handle`: accept `request_id`, `text`; return simulated DevOps payload and `trace_append`. | FR-012, FR-065, FR-066 | TECH-13 | x |
| 3.5 | Ensure request_id is accepted in body for all backends and ai-router; propagate in gateway calls (header or body). | FR-029, FR-030 | TECH-11.1 | x |

## Batch 4: Gateway Routing and Proxy

**Goal:** Gateway calls ai-router, applies confidence threshold, proxies
to backends, aggregates trace and timings.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 4.1 | Gateway: generate `request_id` (UUID) if client does not send it; pass to ai-router and backends. | FR-029, FR-059 | TECH-11.1 | x |
| 4.2 | Gateway: implement call to ai-router `POST /classify` with `request_id`, `text`; parse `route`, `confidence`, `explanation`, `trace_append`. | FR-003, FR-014, FR-015 | TECH-10, TECH-14.3 | x |
| 4.3 | Gateway: add configurable confidence threshold (e.g. T_route=0.55). If route is `unknown` or confidence &lt; threshold, return 404-equivalent with `request_id`, `route`, `confidence`, `message`, `trace` (no backend call). | FR-006, FR-016, FR-017, FR-026, FR-028, FR-037 | TECH-5, TECH-6, TECH-9, TECH-14.4, TECH-19.1 | x |
| 4.4 | Gateway: map route to backend URL and proxy `POST /handle` with `request_id`, `text`; collect backend `trace_append`. | FR-004, FR-018 | TECH-10.2, TECH-14.3 | x |
| 4.5 | Gateway: aggregate trace (gateway + ai-router + backend entries); add `timings_ms` (classify, proxy, total); return `request_id`, `route`, `confidence`, `explanation`, `trace`, `backend_response`, `timings_ms`. | FR-005, FR-019, FR-032, FR-036, FR-038 | TECH-11.3, TECH-11.4, TECH-14.3 | x |
| 4.6 | Add `GET /routes` returning list of routes and backend URLs. | FR-061 | TECH-14.6 | x |
| 4.7 | Add unit tests for gateway routing with mocked ai-router and backends (known route, unknown, low confidence). | NFR-039 | - | x |

## Batch 5: Web UI

**Goal:** Static UI served by gateway: submit query, show route, trace,
and backend response.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 5.1 | Create static UI assets (HTML/JS): text input, submit button; on submit generate request_id, POST to gateway `/api/request` with `request_id`, `text`, optional initial trace entry. | FR-068, FR-074, FR-075 | TECH-17.1, TECH-17.2 | x |
| 5.2 | UI: display selected route name, confidence score (0.0-1.0), and explanation (top tokens/phrases). | FR-069 | TECH-17.3 | x |
| 5.3 | UI: display trace as a timeline list (each hop: service, event, ts, meta). | FR-070 | TECH-17.3 | x |
| 5.4 | UI: display hop diagram (e.g. web -> gateway -> ai-router -> gateway -> backend -> gateway -> web). | FR-071 | TECH-17.3 | x |
| 5.5 | UI: display backend response (formatted JSON) when route is not unknown; display timings (classify, proxy, total). | FR-072, FR-073 | TECH-17.3 | x |
| 5.6 | UI: handle unknown-route (404-equivalent) response with clear messaging and no backend payload. | FR-077 | TECH-17.3, TECH-19.1 | x |
| 5.7 | Configure gateway to serve static UI at `GET /` and keep `POST /api/request` for API. | FR-058, FR-078, FR-079 | TECH-14.5, TECH-17.1 | x |

## Batch 6: Docker and Compose Hardening

**Goal:** Production-ready Dockerfiles and Compose with profiles,
health-based startup, and scaling.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 6.1 | Gateway Dockerfile: full multi-stage (builder + runtime), non-root user, PYTHONDONTWRITEBYTECODE=1, PYTHONUNBUFFERED=1; CMD gunicorn with uvicorn workers, bind 0.0.0.0:8000; HEALTHCHECK on /health. | NFR-014, NFR-016-NFR-019 | TECH-14.1 | x |
| 6.2 | Backend Dockerfiles (search, image, ops): same multi-stage, non-root, gunicorn+uvicorn, HEALTHCHECK. | NFR-014, NFR-016-NFR-019 | TECH-15 (pattern) | x |
| 6.3 | Ai_router Dockerfile: ensure production CMD and HEALTHCHECK; add gunicorn/uvicorn deps if missing. | NFR-022 | TECH-15 | x |
| 6.4 | Add `compose/docker-compose.dev.yaml` with profile `dev`: override CMD to uvicorn --reload where desired; bind mounts for hot reload. | NFR-025, NFR-027, NFR-032 | TECH-16.2 | x |
| 6.5 | Gateway `depends_on` with condition: service_healthy for ai-router and all three backends. | NFR-029 | TECH-16.1 | x |
| 6.6 | Verify scaling: `docker compose up --scale search-service=3`; ensure gateway can reach replicas (Compose DNS round-robin or equivalent). | NFR-030, NFR-031, AC-007 | TECH-18 | x |
| 6.7 | Create `services/trainer/` with `Dockerfile` (single-stage, Python 3.12-slim, training deps only) and `requirements.txt` (scikit-learn, numpy, joblib). | NFR-041, NFR-042 | TECH-7.1, TECH-7.2 | x |
| 6.8 | Add `trainer` service to `compose/docker-compose.yaml` with profile `train`; trainer image is self-contained with `train.py` and `train.csv` baked in; mount `model_artifacts` volume at `/model/`. | NFR-043, NFR-044, NFR-046 | TECH-7.3 | x |
| 6.9 | Add named volume `model_artifacts` in Compose; mount read-write in trainer, read-only in ai_router; set `MODEL_PATH=/model/model.joblib` env var on ai_router. | NFR-045, FR-082 | TECH-7.3 | x |
| 6.10 | Update ai-router startup to load model from `MODEL_PATH` if set and exists, otherwise fall back to build-time artifact; fail fast if neither found. | FR-082 | TECH-7.5 | x |
| 6.11 | Verify retrain-and-reload workflow: `docker compose --profile train run --rm trainer` produces artifacts; `docker compose restart ai_router` loads new model; curl confirms updated predictions. | NFR-047, FR-080 | TECH-4, TECH-7.4, TECH-7.7 | x |

## Batch 7: Scripts and Documentation

**Goal:** Demo script, load-test script, and docs for architecture and
demo commands.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 7.1 | Implement `scripts/demo.sh`: start stack, optional browser/curl examples for search, image, ops, unknown; scaling and failure demos as per project plan. | NFR-036 | - | x |
| 7.2 | Implement `scripts/load_test.sh`: send multiple requests to gateway, optionally with scaled backends; document how to verify distribution. | NFR-037, AC-007 | TECH-18.3 | x |
| 7.3 | Write `docs/DEMO.md`: copy-paste commands for browser, curl, scaling, and failure demos. | NFR-034 | - | x |
| 7.4 | Write `docs/ARCHITECTURE.md`: system design, request flow, and component roles. | NFR-035 | - | x |

## Batch 8: Acceptance and Failure Scenarios

**Goal:** Validate acceptance criteria and unknown vs backend-failure
behavior.

| # | Task | PRD refs | Tech spec | Done |
| --- | --- | --- | --- | --- |
| 8.1 | Verify AC-002 and AC-003: browser UI shows correct routing for "compare nginx ingress vs traefik" (search), image intent (image), ops intent (ops), "hello"/"tell me a joke" (unknown). | AC-002, AC-003 | TECH-9 | x |
| 8.2 | Verify AC-004: for unknown, trace has no backend hop and 404-style response. | AC-004 | TECH-19.1 | x |
| 8.3 | Verify AC-005 and AC-006: curl to `/api/request` returns full JSON; logs correlatable by request_id. | AC-005, AC-006 | TECH-20.3 | x |
| 8.4 | Failure demo: stop one backend; gateway attempts proxy, fails; response includes trace showing classification and backend failure (not 404). | AC-009, AC-010 | TECH-19.2, TECH-19.3 | x |
| 8.5 | Document distinction: unknown = no backend hop + 404 message; backend failure = backend hop attempted + service unavailability. | AC-010 | TECH-19.4 | x |
| 8.6 | Optional: add margin check (top-two route difference threshold -> treat as unknown). | FR-027 | TECH-5.2, TECH-6 | x |
| 8.7 | Final check: `docker compose up --build` succeeds; all services log request_id; run on target OS (Linux/Mac/Windows) if available. | DoD-001, DoD-006, DoD-007 | - | x |

## Batch Summary

| Batch | Focus | Task count |
| --- | --- | --- |
| 1 | Repository and Compose foundation | 7 |
| 2 | AI router model and training | 6 |
| 3 | Backend services and trace contract | 5 |
| 4 | Gateway routing and proxy | 7 |
| 5 | Web UI | 7 |
| 6 | Docker and Compose hardening | 11 |
| 7 | Scripts and documentation | 4 |
| 8 | Acceptance and failure scenarios | 7 |

Use this document to drive implementation: complete a batch, then say
"Do batch N" to proceed to the next.
