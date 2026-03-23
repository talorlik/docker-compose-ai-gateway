# CREATE DRAW.IO ARCHITECTURE DIAGRAMS - LOCAL AI MICROSERVICE MESH

Use this document as the **user prompt** when generating architecture diagrams
for this project. The output is one unified architectural diagram (or a small
set of coherent views) rendered in multiple formats (`.png`, `.dot`,
`.drawio`) as specified in `AGENT.md`.

The agent has system-level rules in `AGENT.md`. This prompt complements those
rules by specifying what to draw and how to lay it out for this repository.

## OUTPUTS

Produce one unified architectural diagram for **docker-compose-ai-gateway**,
which runs a local, Docker Compose based AI-routed microservice mesh.

The diagram must reflect:

- Query flow: browser/CLI -> gateway -> ai_router -> selected backend service.
- Train flow: browser -> gateway -> training-api -> trainer -> model artifacts.
- Refine flow: browser -> gateway -> training-api -> refiner -> Ollama ->
  artifacts -> promote.
- Event flow: training-api job state and completion events via Redis Pub/Sub
  and SSE streams proxied by gateway.
- Deployment model: Compose services, profiles, dependencies, shared volumes,
  and localhost-exposed ports.

## EXECUTION MODEL

Show a clear boundary between always-on services and profile-scoped services.

**Default runtime (always-on in base compose up):**

- `gateway`
- `ai_router`
- `search_service`
- `image_service`
- `ops_service`
- `redis`
- `training-api`

**Profile services (on-demand):**

- `trainer` - profile `train`
- `refiner` - profile `refine`
- `ollama` - profile `refine-container`

## PREREQUISITES (PRE-EXISTING ELEMENTS)

Include these explicitly because they are foundational to flows:

- Shared volume `model_artifacts` for model and training outputs.
- Shared volume `ollama_data` for local LLM persistence.
- Generated env file model from `config/PROJECT_CONFIG.yaml` via
  `scripts/generate_env.py`.
- Localhost exposure policy:
  - `127.0.0.1:8000` for gateway UI/API.
  - `127.0.0.1:8001` for ai_router debug endpoint.
  - `127.0.0.1:11434` for Ollama when profile is active.

## COMPONENTS TO INCLUDE

Group components logically. Use local/runtime-oriented icons rather than
cloud-specific architecture unless explicitly required.

### Client and entrypoint

- Browser UI (`/`, Query, Train, Refine pages).
- Optional CLI/script callers.
- Gateway as the primary API and static UI entrypoint.

### Core runtime routing path

- `ai_router` classification service.
- `search_service`, `image_service`, `ops_service` backend handlers.
- Routing policy context: unknown or low-confidence results remain in gateway.

### Train and refine orchestration path

- `training-api` as canonical train/refine/promote orchestrator.
- Redis as job-state and Pub/Sub event broker.
- `trainer` one-shot container for model creation.
- `refiner` one-shot container for dataset improvement.
- `ollama` local LLM endpoint consumed by refine workflows.

### Data and shared state

- `model_artifacts` shared volume (read/write edges per service role).
- `ollama_data` persisted model cache for Ollama.

## CONNECTIONS TO SHOW

Use arrows and label important flows (API path or mechanism). Keep query
data-plane flows visually distinct from train/refine control-event flows.

### User traffic (query data plane)

- User -> gateway (`GET /`, `POST /api/request`).
- Gateway -> ai_router (`POST /classify`).
- Gateway -> one backend (`POST /handle`) based on predicted route.
- Backend -> gateway response payload with trace append.
- Gateway -> user final response with aggregated trace.

### Train and refine control/event plane

- User -> gateway train/refine endpoints:
  - `POST /api/train`
  - `POST /api/refine/relabel`
  - `POST /api/refine/augment`
  - `POST /api/refine/promote`
- Gateway -> training-api proxy for the above APIs.
- Training-api -> Redis:
  - Job key state storage.
  - Publish completion event.
- User EventSource -> gateway SSE endpoint ->
  training-api SSE endpoint subscribed to Redis Pub/Sub.
- Training-api -> trainer/refiner (Compose run model).
- Refiner -> Ollama for LLM calls.

### Artifact and volume flows

- Trainer writes model and metrics to `model_artifacts`.
- AI router reads model artifact from `model_artifacts`.
- Refiner reads/writes datasets/artifacts via shared data path.
- Training-api reads artifacts for result payloads and promotion checks.
- Ollama persists local model data in `ollama_data`.

## UNIFIED DIAGRAM CONTENT

The unified output must include:

- Runtime topology with client, gateway, classifier, and backends.
- Train/refine orchestration with Redis and SSE eventing.
- Optional profile services marked as on-demand, not always running.
- Internal-only nature of `training-api` and Redis (no host-exposed ports in
  base Compose).
- Shared volume ownership and access direction.

Output in formats required by `AGENT.md` under
`docs/architecture-diagrams/diagrams/`.

## LAYOUT

- Top row: clients (browser and optional CLI).
- Upper middle: gateway and public entry ports.
- Middle: ai_router and backend services for query runtime.
- Side or lower lane: training-api, Redis, trainer/refiner, Ollama for
  train/refine workflow.
- Bottom: shared volumes (`model_artifacts`, `ollama_data`).

### Tier colors (local stack style)

- **Client/Edge:** light blue.
- **Gateway/API mediation:** light indigo.
- **Inference runtime:** light green.
- **Training/Refine control:** light purple.
- **Eventing/State:** light yellow.
- **LLM path:** light cyan.
- **Storage/Artifacts:** light orange.

## DIAGRAM REQUIREMENTS

- Use repository terminology exactly (`gateway`, `ai_router`, `training-api`,
  `search_service`, `image_service`, `ops_service`, `trainer`, `refiner`,
  `ollama`, `model_artifacts`, `ollama_data`).
- Label key API edges with route names and methods.
- Mark profile-scoped services as conditional/on-demand.
- Distinguish internal Compose network traffic from localhost-exposed ingress.
- Do not include secret values or irrelevant implementation minutiae.

## AUTHORITATIVE REFERENCES

Use these sources in this order:

1. `AGENT.md` in this directory.
2. `docs/auxiliary/architecture/ARCHITECTURE.md`.
3. `docs/auxiliary/architecture/TECHNICAL.md`.
4. `docs/auxiliary/architecture/CONFIGURATION.md`.
5. `docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md`.
6. `compose/docker-compose.yaml` and `compose/docker-compose.dev.yaml`.
7. `config/PROJECT_CONFIG.yaml` and relevant service READMEs.

If something is ambiguous, add a callout:
`ASSUMPTION: ...` and cite the file that should confirm it.

## INVARIANTS CHECKLIST

Before finalizing, ensure the diagram reflects:

- Gateway is the primary user entrypoint and proxy.
- AI router determines backend route selection for `POST /api/request`.
- Backends are internal handler services and not direct public entrypoints.
- Train/refine completion is event-driven through Redis Pub/Sub and SSE.
- `trainer`, `refiner`, and `ollama` are profile-bound optional services.
- `model_artifacts` is the shared contract across trainer, ai_router,
  training-api, and refiner paths.
