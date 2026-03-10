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

See [docs/DEMO.md](docs/DEMO.md) for full runbook, scaling, and failure demos.

## Documentation

| Document | Description |
| --- | --- |
| [docs/PRD.md](docs/PRD.md) | Product requirements and functional specs |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, components, request flow |
| [docs/TECHNICAL.md](docs/TECHNICAL.md) | Training pipeline, routing policy, model details |
| [docs/DEMO.md](docs/DEMO.md) | Build, run, stop, scaling, and failure demos |
| [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md) | Acceptance criteria and verification |
| [docs/PROJECT_PLAN.md](docs/PROJECT_PLAN.md) | Project overview and technical requirements |
| [docs/TASKS.md](docs/TASKS.md) | Actionable implementation tasks |

## Project Structure

```text
compose/          # Docker Compose definitions
services/         # Microservices (gateway, ai_router, search_service, etc.)
scripts/          # Demo and load-test scripts
docs/             # Project documentation
```
