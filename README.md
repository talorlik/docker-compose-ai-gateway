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
  promotes when retrained accuracy meets the configured tolerance versus the
  previous model
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
# Generate env files (required before first compose up; needs Python 3)
python scripts/generate_env.py dev

# Build and start
docker compose -f compose/docker-compose.yaml up --build -d

# Browser UI: http://localhost:8000
# Health: http://localhost:8000/health
```

Alternatively, `./scripts/demo.sh run` generates env and starts the stack
automatically instead of the steps above.

**Train the model** (optional, uses pre-built model by default):

```bash
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer
```

**Refine the dataset** (optional, after training; requires Ollama):

Use the Refine UI at `http://localhost:8000/refine` to run relabeling and
augmentation independently, then promote. Or use the CLI:

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm training-api relabel
docker compose -f compose/docker-compose.yaml --profile refine run --rm training-api augment
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
| [docs/auxiliary/architecture/CONFIGURATION.md](docs/auxiliary/architecture/CONFIGURATION.md) | Centralized configuration and env generation |
| [docs/auxiliary/demo/DEMO.md](docs/auxiliary/demo/DEMO.md) | Build, run, stop, scaling, and failure demos |
| [docs/auxiliary/requirements/ACCEPTANCE.md](docs/auxiliary/requirements/ACCEPTANCE.md) | Acceptance criteria and verification |
| [docs/auxiliary/troubleshooting/DEBUG.md](docs/auxiliary/troubleshooting/DEBUG.md) | Debug runbook and common failures |
| [docs/auxiliary/planning/PROJECT_PLAN.md](docs/auxiliary/planning/PROJECT_PLAN.md) | Project overview and technical requirements |
| [docs/auxiliary/planning/TASKS.md](docs/auxiliary/planning/TASKS.md) | Actionable implementation tasks |
| [docs/auxiliary/planning/PERFORMANCE_IMPROVEMENTS.md](docs/auxiliary/planning/PERFORMANCE_IMPROVEMENTS.md) | Refinement performance tuning |
| [docs/auxiliary/planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md](docs/auxiliary/planning/AUGMENTATION_QUALITY_IMPROVEMENTS.md) | Augment quality gates and promotion tolerance |
| [docs/auxiliary/refiner/REFINER_PLAN.md](docs/auxiliary/refiner/REFINER_PLAN.md) | Refiner conceptual overview |
| [docs/auxiliary/refiner/REFINER_TECHNICAL.md](docs/auxiliary/refiner/REFINER_TECHNICAL.md) | Refiner technical specification |
| [docs/auxiliary/refiner/REFINER_FLOW.md](docs/auxiliary/refiner/REFINER_FLOW.md) | Refiner end-to-end flow |
| [docs/auxiliary/planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md](docs/auxiliary/planning/TRAIN_AND_REFINE_GUI_PAGES_PLAN.md) | Train and Refine GUI plan |
| [docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md](docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md) | Train and Refine GUI technical spec |
| [docs/auxiliary/requirements/TRAIN_AND_REFINE_GUI_PAGES_PRD.md](docs/auxiliary/requirements/TRAIN_AND_REFINE_GUI_PAGES_PRD.md) | Train and Refine GUI requirements |

## Testing

**Prerequisites:** Python 3.10+, pytest, and service dependencies
(install per-service `requirements.txt`).

```bash
# Run all tests
pytest

# Run tests for a specific service
pytest services/gateway/tests/ -v
pytest services/ai_router/tests/ -v
pytest services/trainer/tests/ -v
pytest services/training-api/tests/ -v

# Run backend service tests
pytest services/search_service/tests/ services/image_service/tests/ services/ops_service/tests/ -v

# Run compose validation tests
pytest compose/tests/ -v

# Run integration and e2e tests
pytest tests/ -v

# Run by marker
pytest -m unit
pytest -m integration
pytest -m e2e

# With coverage
pytest --cov --cov-report=html
```

The demo script also runs gateway and ai_router tests:

```bash
./scripts/demo.sh test
```

## Project Structure

```text
compose/          # Docker Compose definitions
config/           # Authoritative PROJECT_CONFIG.yaml (see CONFIGURATION.md)
env/              # Generated .env.<env> files for Compose
services/         # Microservices (gateway, ai_router, search_service, etc.)
scripts/          # Demo and load-test scripts
docs/             # Project documentation (auxiliary/ for detailed docs)
```
