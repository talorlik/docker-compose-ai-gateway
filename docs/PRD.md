# Product Requirements Document: Local AI Microservice Mesh

Structured requirements for the locally runnable, multi-container microservice
system with AI-driven request routing and application-level tracing.

## 1. Document Control

| Attribute | Value |
| --- | --- |
| Document type | Product Requirements Document (PRD) |
| Format | Requirements specification |
| Source | PROJECT_PLAN.md |
| Scope | Full project |

## 2. Business and Project Requirements

### 2.1 Goals

| ID | Requirement | Priority |
| --- | --- | --- |
| BR-001 | The system SHALL provide a locally runnable multi-container microservice mesh. | Must |
| BR-002 | An AI classifier SHALL select the backend service for each incoming request. | Must |
| BR-003 | The system SHALL demonstrate Docker Compose advanced features and AI-driven routing. | Must |
| BR-004 | The browser UI SHALL display the exact path taken (application-level tracing) per action. | Must |

### 2.2 Demo and Observability

| ID | Requirement | Priority |
| --- | --- | --- |
| BR-005 | The project SHALL be demonstrable via a browser UI as the primary interface. | Must |
| BR-006 | The project SHALL be demonstrable via terminal commands (e.g., curl-based API testing) with trace visibility. | Must |
| BR-007 | The project SHALL support scaling scenarios that demonstrate load distribution across scaled services. | Must |
| BR-008 | The project SHALL support failure scenarios that demonstrate fallback or error behavior when backends fail. | Must |

## 3. Platform and Technical Constraints

### 3.1 Platform

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-001 | The system SHALL run cross-platform on Linux, Mac, and Windows. | Must |
| NFR-002 | All services SHALL be implemented in Python using FastAPI. | Must |
| NFR-003 | Tracing SHALL be application-level only; no external observability stack SHALL be required. | Must |
| NFR-004 | Docker SHALL be used with multi-stage Dockerfiles; model training SHALL occur at build time where applicable. | Must |
| NFR-005 | Docker Compose SHALL use advanced features: fragments, anchors, profiles, and health checks. | Must |

### 3.2 AI and Model

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-006 | The AI classifier SHALL use scikit-learn (TF-IDF + Logistic Regression) as specified in the project plan. | Must |
| NFR-007 | The classifier SHALL run on CPU; no GPU SHALL be required. | Must |
| NFR-008 | The model SHALL be deterministic and reproducible (fixed random_state, build-time training). | Must |

## 4. System Architecture Requirements

### 4.1 Services

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-001 | A **gateway** service (FastAPI) SHALL serve the static UI at `/`. | Must |
| FR-002 | The gateway SHALL expose the main API entrypoint `POST /api/request`. | Must |
| FR-003 | The gateway SHALL call the ai-router to classify each request. | Must |
| FR-004 | The gateway SHALL proxy the request to the selected backend service. | Must |
| FR-005 | The gateway SHALL aggregate and return the full request trace in the response. | Must |
| FR-006 | The gateway SHALL implement confidence thresholding and fallback logic per routing policy. | Must |
| FR-007 | An **ai-router** service (FastAPI) SHALL expose `POST /classify`. | Must |
| FR-008 | The ai-router SHALL run a lightweight text classifier and return route, confidence score, and explanation. | Must |
| FR-009 | The ai-router SHALL ship a pre-built model artifact (`model.joblib`) in its Docker image. | Must |
| FR-010 | A **search-service** (FastAPI) SHALL expose `POST /handle` and simulate information lookup/research responses. | Must |
| FR-011 | An **image-service** (FastAPI) SHALL expose `POST /handle` and simulate image-related request handling. | Must |
| FR-012 | An **ops-service** (FastAPI) SHALL expose `POST /handle` and simulate DevOps/infrastructure troubleshooting responses. | Must |
| FR-080 | A **trainer** service SHALL be a one-shot container that runs `train.py`, writes `model.joblib` to a shared volume, and exits. | Must |
| FR-081 | The trainer service SHALL be self-contained: `train.py` and `train.csv` SHALL live in `services/trainer/` and be included in the trainer Docker image at build time. | Must |
| FR-082 | The ai-router SHALL support loading model artifacts from a shared volume path specified by `MODEL_PATH` env var, falling back to the build-time artifact. | Must |
| FR-083 | The ai-router MAY expose `POST /reload-model` for hot-reload of the model without container restart. | Should |

### 4.2 Request Flow

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-013 | User requests SHALL be submitted via UI or curl to `gateway /api/request`. | Must |
| FR-014 | The gateway SHALL call `ai-router /classify` with the request text. | Must |
| FR-015 | The ai-router SHALL return `{route, confidence, explanation, trace_append}`. | Must |
| FR-016 | The gateway SHALL evaluate a configurable confidence threshold (e.g., T_route = 0.55). | Must |
| FR-017 | If route is `unknown` or confidence is below threshold, the gateway SHALL return a 404-equivalent response without proxying. | Must |
| FR-018 | Otherwise, the gateway SHALL proxy to the selected backend `POST /handle`. | Must |
| FR-019 | The gateway SHALL aggregate all trace entries and return the complete response with routing metadata. | Must |

## 5. Routing Model Requirements

### 5.1 Routes and Labels

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-020 | The model SHALL support exactly four labels: `search-service`, `image-service`, `ops-service`, `unknown`. | Must |
| FR-021 | `search-service` SHALL be used for lookup, explanation, comparison queries. | Must |
| FR-022 | `image-service` SHALL be used for image-related intents (detection, processing, etc.). | Must |
| FR-023 | `ops-service` SHALL be used for DevOps, infrastructure, and troubleshooting queries. | Must |
| FR-024 | `unknown` SHALL be used for out-of-scope, unclear, or irrelevant requests and SHALL result in a 404-equivalent response. | Must |

### 5.2 Routing Policy

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-025 | The model SHALL produce probabilities for all four labels. | Must |
| FR-026 | The gateway SHALL use a configurable confidence threshold (e.g., T_route = 0.55) for non-unknown routes. | Must |
| FR-027 | The system MAY support an optional margin check: if the difference between the top two routes is below a threshold, treat as unknown. | Should |
| FR-028 | If route is `unknown` or confidence is too low, the gateway SHALL return 404 without proxying to any backend. | Must |

## 6. Tracing Requirements

### 6.1 Trace Contract

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-029 | A `request_id` (UUID) SHALL be generated by the gateway if not provided by the client. | Must |
| FR-030 | `request_id` SHALL be propagated end-to-end via headers and/or body. | Must |
| FR-031 | Each service SHALL append exactly one trace entry per request. | Must |
| FR-032 | The gateway SHALL aggregate all trace entries into a single `trace` array. | Must |
| FR-033 | The complete trace SHALL be returned to the UI/client in the gateway response. | Must |

### 6.2 Trace Entry Schema

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-034 | Each trace entry SHALL include: `service`, `event`, `ts` (ISO 8601). | Must |
| FR-035 | Trace entries MAY include an optional `meta` object (e.g., `detail`, `route`, `confidence`, `status`). | Must |

### 6.3 Gateway Response Schema

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-036 | Successful gateway response SHALL include: `request_id`, `route`, `confidence`, `explanation`, `trace`, `backend_response`, `timings_ms`. | Must |
| FR-037 | Unknown-route (404-equivalent) response SHALL include: `request_id`, `route` (unknown), `confidence`, `message`, `trace` (no backend hop). | Must |
| FR-038 | `timings_ms` SHALL include at least: `classify`, `proxy`, `total`. | Must |

## 7. Repository and Structure Requirements

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-009 | The repository SHALL follow the structure defined in the project plan (compose/, services/, scripts/, docs/). | Must |
| NFR-010 | Each service SHALL have its own directory under `services/` with Dockerfile, requirements.txt, app/, and tests/ where specified. | Must |
| NFR-011 | Compose files SHALL reside in `compose/` (docker-compose.yaml base, docker-compose.dev.yaml for dev profile). | Must |
| NFR-012 | Demo and load-test scripts SHALL reside in `scripts/` (demo.sh, load_test.sh). | Must |
| NFR-013 | Documentation SHALL include architecture and demo instructions in `docs/`. | Must |

## 8. Training Data Requirements

### 8.1 Data Strategy

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-039 | Training data SHALL be synthetic and hand-written (curated examples). | Must |
| FR-040 | Minimum SHALL be 50-100 examples per label; recommended 150-300 per label. | Must |
| FR-041 | Data SHALL be balanced across all four labels (search, image, ops, unknown). | Must |
| FR-042 | Training data SHALL use `text,label` format (e.g., train.csv). | Must |

### 8.2 Data Content Guidelines

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-043 | search-service examples SHALL include patterns such as "what is...", "compare...", "explain...", "find...", "best way to...". | Should |
| FR-044 | image-service examples SHALL include image nouns, vision verbs, and file references. | Should |
| FR-045 | ops-service examples SHALL include tooling names, error words, and imperative debugging tone. | Should |
| FR-046 | unknown examples SHALL include chit-chat, vague questions, nonsense, and generic conversation. | Should |

## 9. AI Model Implementation Requirements

### 9.1 Algorithm

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-047 | Vectorization SHALL use TfidfVectorizer with ngram_range=(1,2) and min_df=2. | Must |
| FR-048 | Classification SHALL use LogisticRegression with max_iter=2000, solver="lbfgs", multi_class="multinomial". | Must |
| FR-049 | The model SHALL provide probability outputs (predict_proba) for confidence scoring. | Must |
| FR-050 | The model SHALL support explainability via top weighted features (e.g., 3-8 tokens/phrases). | Must |

### 9.2 Training Pipeline

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-051 | Training code and data SHALL be located in `services/trainer/` (train.py, train.csv). The trained artifact (`model.joblib`) SHALL be placed in `services/ai_router/model/` for inclusion in the ai-router image. | Must |
| FR-052 | Training SHALL use a fixed random_state for reproducibility. | Must |
| FR-053 | The training script SHALL fit TfidfVectorizer and LogisticRegression, evaluate accuracy/confusion matrix, and save vectorizer, model, and label mapping in the artifact. | Must |
| FR-054 | The model artifact (`model.joblib`) SHALL be pre-built by the trainer service and included in the ai-router Docker image at build time. | Must |

### 9.3 Inference

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-055 | The ai-router SHALL load model.joblib at service startup. | Must |
| FR-056 | Inference SHALL vectorize input text, compute probabilities, select route via argmax, and set confidence to max(probs). | Must |
| FR-057 | The ai-router SHALL return explanation (top features) along with route, confidence, and trace_append. | Must |

## 10. API Endpoint Requirements

### 10.1 Gateway

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-058 | Gateway SHALL expose `GET /` to serve static UI files. | Must |
| FR-059 | Gateway SHALL expose `POST /api/request` accepting body: `request_id` (optional), `text`, `trace` (optional). | Must |
| FR-060 | Gateway SHALL expose `GET /health` returning 200 when healthy. | Must |
| FR-061 | Gateway SHALL expose `GET /routes` returning list of available routes and backend URLs. | Must |

### 10.2 AI Router

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-062 | AI router SHALL expose `POST /classify` accepting `request_id`, `text`. | Must |
| FR-063 | AI router SHALL expose `GET /health` returning 200 when healthy. | Must |
| FR-064 | Classify response SHALL include `route`, `confidence`, `explanation`, `trace_append`. | Must |

### 10.3 Backend Services

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-065 | Each backend (search, image, ops) SHALL expose `POST /handle` accepting `request_id`, `text`. | Must |
| FR-066 | Handle response SHALL include `payload` and `trace_append`. | Must |
| FR-067 | Each backend SHALL expose `GET /health` returning 200 when healthy. | Must |

## 11. Web UI Requirements

### 11.1 Components

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-068 | The UI SHALL provide a text input field for user queries and a submit button. | Must |
| FR-069 | The UI SHALL display selected route name, confidence score (0.0-1.0), and explanation (top tokens/phrases). | Must |
| FR-070 | The UI SHALL display a trace visualization: timeline list of each hop. | Must |
| FR-071 | The UI SHALL display a hop diagram (e.g., web -> gateway -> ai-router -> gateway -> backend -> gateway -> web). | Must |
| FR-072 | The UI SHALL display the backend response (formatted JSON payload) when route is not unknown. | Must |
| FR-073 | The UI SHALL display timings: classification time, proxy time, total time. | Must |

### 11.2 Behavior

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-074 | The UI SHALL generate request_id when the user clicks Send. | Must |
| FR-075 | The UI SHALL POST to gateway `/api/request` with `request_id`, `text`, and initial trace entry (e.g., service: "web", event: "submit"). | Must |
| FR-076 | The UI SHALL render the complete response including full trace. | Must |
| FR-077 | The UI SHALL handle unknown-route (404-equivalent) responses with appropriate messaging. | Must |

### 11.3 Serving

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-078 | The UI SHALL be served from the gateway as static files; no separate web container SHALL be required. | Must |
| FR-079 | Gateway SHALL expose `/` for UI and `/api/request` for API. | Must |

## 12. Docker Requirements

### 12.1 Multi-Stage Dockerfiles

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-014 | All Python services (gateway, backends) SHALL use a multi-stage Dockerfile: builder (wheels) and runtime. | Must |
| NFR-015 | Base image SHALL be Python 3.12-slim (e.g., bookworm). | Must |
| NFR-016 | The runtime stage SHALL create a non-root user (e.g., appuser/appgroup) and run the application as that user. | Must |
| NFR-017 | The runtime stage SHALL set PYTHONDONTWRITEBYTECODE=1 and PYTHONUNBUFFERED=1. | Must |
| NFR-018 | Production CMD SHALL use gunicorn with uvicorn workers, bind 0.0.0.0:8000, with access and error log to stdout. | Must |
| NFR-019 | Each service Dockerfile SHALL include a HEALTHCHECK that hits the service /health endpoint. | Must |

### 12.2 AI Router Dockerfile

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-020 | The ai-router Dockerfile SHALL copy a pre-built `model.joblib` artifact into the image; training is handled by the separate trainer service. | Must |
| NFR-021 | The runtime stage SHALL copy `model.joblib` from the build context (`services/ai_router/model/`). | Must |
| NFR-022 | Dependencies SHALL include gunicorn and uvicorn[standard] for production. | Must |

### 12.3 Trainer Dockerfile

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-041 | The trainer SHALL have its own directory `services/trainer/` with Dockerfile and requirements.txt. | Must |
| NFR-042 | The trainer Dockerfile SHALL be single-stage (no runtime server); only training dependencies (scikit-learn, numpy, joblib). | Must |
| NFR-043 | The trainer SHALL include `train.py` and `train.csv` in its Docker image at build time; the trainer is self-contained. | Must |

### 12.4 Dev Target

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-023 | An optional dev target MAY override CMD to use uvicorn with --reload. | Should |

## 13. Docker Compose Requirements

### 13.1 File Structure

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-024 | Base configuration SHALL be in `compose/docker-compose.yaml`. | Must |
| NFR-025 | Dev overrides SHALL be in `compose/docker-compose.dev.yaml` with profile usage. | Must |

### 13.2 Advanced Features

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-026 | Compose SHALL use anchors (e.g., x-common-env, x-common-healthcheck, x-common-logging) for shared configuration. | Must |
| NFR-027 | Compose SHALL define profiles: core (default) and dev. | Must |
| NFR-028 | Each service SHALL have a health check defined (e.g., `curl -f http://localhost:8000/health`). | Must |
| NFR-029 | Gateway SHALL have depends_on with condition: service_healthy for ai-router and all backends. | Must |
| NFR-030 | Services SHALL support horizontal scaling (e.g., docker compose up --scale search-service=3). | Must |
| NFR-031 | Gateway SHALL distribute requests across scaled backend replicas (e.g., round-robin at DNS or load balancer). | Must |

### 13.3 Trainer Profile and Shared Volume

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-044 | Compose SHALL define a `train` profile containing the trainer service; the trainer SHALL NOT start with default `docker compose up`. | Must |
| NFR-045 | Compose SHALL define a named volume `model_artifacts` shared between the trainer (read-write) and ai-router (read-only). | Must |
| NFR-046 | The trainer SHALL use `train.py` and `train.csv` from its own build context (`services/trainer/`); no bind-mounts from other services are required. | Must |
| NFR-047 | Training SHALL be triggered via `docker compose --profile train run --rm trainer`; ai-router SHALL reload the new model after `docker compose restart ai_router`. | Must |

### 13.4 Dev Profile

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-032 | Dev profile SHALL support bind mounts for hot reload where applicable. | Must |
| NFR-033 | Dev profile MAY expose additional debug ports. | Should |

## 14. Testing and Demonstration Requirements

### 14.1 Browser Demo

| ID | Requirement | Priority |
| --- | --- | --- |
| AC-001 | `docker compose -f compose/docker-compose.yaml up --build` SHALL start all services successfully. | Must |
| AC-002 | Opening the gateway URL in a browser SHALL show the UI and allow submitting queries. | Must |
| AC-003 | Test cases SHALL verify: "compare nginx ingress vs traefik" -> search-service; image intent -> image-service; ops intent -> ops-service; "hello"/"tell me a joke" -> unknown. | Must |
| AC-004 | For unknown, trace SHALL show no backend hop and 404 status. | Must |

### 14.2 Terminal Demo

| ID | Requirement | Priority |
| --- | --- | --- |
| AC-005 | curl POST to /api/request SHALL return JSON with route, confidence, explanation, trace, backend_response (or message for unknown). | Must |
| AC-006 | Logs SHALL be correlatable by request_id (e.g., docker compose logs filtered by request_id). | Must |

### 14.3 Scaling Demo

| ID | Requirement | Priority |
| --- | --- | --- |
| AC-007 | Scaling a backend (e.g., search-service=3) and running a load test SHALL show requests distributed across replicas. | Must |
| AC-008 | Trace SHALL indicate which backend instance handled the request where visible. | Should |

### 14.4 Failure Demo

| ID | Requirement | Priority |
| --- | --- | --- |
| AC-009 | When a backend is stopped, gateway SHALL attempt proxy, fail, and return an error response with trace showing classification and backend failure. | Must |
| AC-010 | Unknown (AI decision) SHALL be distinguishable from backend failure: unknown has no backend hop and 404 message; failure has backend hop attempted and service unavailability message. | Must |

## 15. Documentation and Deliverables

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-034 | `docs/demo.md` SHALL provide copy-paste commands for browser, curl, scaling, and failure demos. | Must |
| NFR-035 | `docs/architecture.md` SHALL describe system design and request flow. | Must |
| NFR-036 | `scripts/demo.sh` SHALL implement the full demo sequence as specified in the project plan. | Must |
| NFR-037 | `scripts/load_test.sh` SHALL implement load testing for scaling verification. | Must |

## 16. Quality and Definition of Done

### 16.1 Unit and Integration Tests

| ID | Requirement | Priority |
| --- | --- | --- |
| NFR-038 | Unit tests SHALL exist for ai-router classification logic. | Must |
| NFR-039 | Unit tests SHALL exist for gateway routing logic with mocked dependencies. | Must |
| NFR-040 | Integration tests SHALL run against the full compose stack where feasible. | Should |

### 16.2 Definition of Done (Summary)

| ID | Requirement | Priority |
| --- | --- | --- |
| DoD-001 | docker compose up --build SHALL succeed on Linux, Mac, and Windows. | Must |
| DoD-002 | Browser UI SHALL display correct routing for all four route types and full trace visualization. | Must |
| DoD-003 | Curl demos SHALL produce deterministic, traceable outputs. | Must |
| DoD-004 | Scaling demo SHALL distribute load across replicas. | Must |
| DoD-005 | Failure demo SHALL show distinct behavior from unknown classification. | Must |
| DoD-006 | Multi-stage Dockerfiles, build-time model training, compose anchors/fragments/profiles, and health checks SHALL be implemented. | Must |
| DoD-007 | All services SHALL log request_id for correlation. | Must |
| DoD-008 | Unknown route SHALL return 404-equivalent without backend call; confidence thresholding SHALL prevent low-confidence routing. | Must |

## 17. Requirements Traceability Summary

| Category | Count | IDs |
| --- | --- | --- |
| Business | 8 | BR-001 to BR-008 |
| Functional | 83 | FR-001 to FR-083 |
| Non-Functional | 47 | NFR-001 to NFR-047 |
| Acceptance / DoD | 18 | AC-001 to AC-010, DoD-001 to DoD-008 |

## 18. Optional / Future Enhancements

The following are out of scope for the current release but may be considered later:

- Explicit unknown-label training refinement
- Enhanced explanations (top n-grams with weights)
- Request replay endpoint for debugging
- Metrics endpoint (request rate, latency per route)
- Additional backend services
- More sophisticated load balancing in gateway
- External training data sources (e.g., Stack Overflow, intent datasets)
  as optional augmentation
