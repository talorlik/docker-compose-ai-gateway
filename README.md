# Local AI Microservice Mesh

A locally runnable, multi-container microservice system where an AI classifier
selects the backend service for each incoming request. The browser UI displays
the exact path taken (application-level tracing) per action.

## Overview

- **Gateway** serves the static UI and main API (`POST /api/request`)
- **AI Router** classifies request text and returns route, confidence, and
  explanation
- **Backends** (search, image, ops) simulate domain-specific responses
- **Trainer** (optional profile) trains the classifier and writes the model
  artifact
- **Refiner** (optional profile) improves the dataset via local LLM (Ollama);
  promotes only when metrics improve
- **Redis** and **Training API** (refine profile) provide job state and HTTP
  endpoints for the Train/Refine UI; see `services/training-api/README.md`
  for env (REDIS_URL or REDIS_HOST/REDIS_PORT). Both run on the internal
  network only (no public ports); the gateway proxies to the training-api.
  **Promote** can be run from the UI or via CLI: `./scripts/promote.sh` or
  `demo.sh promote`. **Refine** requires Ollama (start with refine profile).

All services run in Python (FastAPI) with Docker Compose. No external
observability stack is required; tracing is application-level.

## Quick Start

**Prerequisites:** Docker and Docker Compose.

```bash
# Build and start
docker compose -f compose/docker-compose.yaml up --build -d

# Browser UI: http://localhost:8000
# Health: http://localhost:8000/health
```

**Train the model** (optional, uses pre-built model by default):

```bash
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer
```

**Refine the dataset** (optional, after training; requires Ollama):

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm training-api refine
./scripts/promote.sh
```

See [docs/auxiliary/demo/DEMO.md](docs/auxiliary/demo/DEMO.md) for full runbook,
scaling, and failure demos.

## Compose Files

- **Base:** `compose/docker-compose.yaml` defines the full stack (gateway,
  ai_router, backends, optional trainer/refiner/redis/training-api via
  profiles). Services run from built images with default commands.
- **Dev overlay:** `compose/docker-compose.dev.yaml` overrides the five app
  services with bind-mounted source and `uvicorn --reload` so code changes
  apply without rebuilding. Use both files together:

```bash
docker compose -f compose/docker-compose.yaml -f compose/docker-compose.dev.yaml up --build
```

Or use `./scripts/demo.sh run --dev`. See
[docs/auxiliary/architecture/TECHNICAL.md](docs/auxiliary/architecture/TECHNICAL.md)
(Section 16.2) for details.

## Documentation

| Document | Description |
| --- | --- |
| [docs/auxiliary/requirements/PRD.md](docs/auxiliary/requirements/PRD.md) | Product requirements and functional specs |
| [docs/auxiliary/architecture/ARCHITECTURE.md](docs/auxiliary/architecture/ARCHITECTURE.md) | System design, components, request flow |
| [docs/auxiliary/architecture/TECHNICAL.md](docs/auxiliary/architecture/TECHNICAL.md) | Training pipeline, routing policy, model details |
| [docs/auxiliary/demo/DEMO.md](docs/auxiliary/demo/DEMO.md) | Build, run, stop, scaling, and failure demos |
| [docs/auxiliary/requirements/ACCEPTANCE.md](docs/auxiliary/requirements/ACCEPTANCE.md) | Acceptance criteria and verification |
| [docs/auxiliary/planning/PROJECT_PLAN.md](docs/auxiliary/planning/PROJECT_PLAN.md) | Project overview and technical requirements |
| [docs/auxiliary/planning/TASKS.md](docs/auxiliary/planning/TASKS.md) | Actionable implementation tasks |
| [docs/auxiliary/refiner/REFINER_PLAN.md](docs/auxiliary/refiner/REFINER_PLAN.md) | Refiner conceptual overview |
| [docs/auxiliary/refiner/REFINER_TECHNICAL.md](docs/auxiliary/refiner/REFINER_TECHNICAL.md) | Refiner technical specification |
| [docs/auxiliary/refiner/REFINER_FLOW.md](docs/auxiliary/refiner/REFINER_FLOW.md) | Refiner end-to-end flow |
| [docs/auxiliary/planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md](docs/auxiliary/planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md) | Train and Refine GUI (training-api, Redis, SSE) |

## Project Structure

```text
compose/          # Docker Compose definitions
services/         # Microservices (gateway, ai_router, search_service, etc.)
scripts/          # Demo and load-test scripts
docs/             # Project documentation (auxiliary/ for detailed docs)
```
