# Local AI Microservice Mesh Context

This document provides full, deep context awareness for AI agents working on the
docker-compose-ai-gateway project. It summarizes the architecture, developer
workflow, configuration hierarchy, and key operational concepts.

## System Architecture & Request Flow

The system is a locally runnable, multi-container microservice mesh where an AI
classifier (`ai_router`) predicts backend routing based on natural language
intent.

- **Gateway**: Serves the UI, applies routing policy (`T_ROUTE`, `T_MARGIN`),
  proxies requests, and aggregates application-level traces.
- **AI Router**: Lightweight intent classifier (TF-IDF + Logistic Regression).
  Returns `route`, `confidence`, `probabilities`, and `explanation` (top
  contributing tokens).
- **Backends**: `search_service`, `image_service`, `ops_service`.
- **Trainer Profile**: One-shot container that trains `model.joblib` from
  `train.csv` and outputs `metrics.json` and `misclassified.csv` to a shared
  volume (`model_artifacts`).
- **Refiner Profile / Training API**: Improves the dataset via relabeling and
  augmenting using Ollama (phi3:mini). Orchestrated via the `training-api`.
- **Redis**: Maintains job states and handles Pub/Sub for Server-Sent Events
  (SSE) to send completion events to the UI.

## Configuration & Environment Variables

Configuration follows a rigid hierarchy to ensure reproducibility:

1. **Source of Truth**: `config/PROJECT_CONFIG.yaml` (contains `default`, `dev`,
   etc. environment sections).
2. **Generation**: `scripts/generate_env.py <env>` parses the YAML and creates
   flat `.env` files (e.g., `env/.env.dev`).
3. **Consumption**: Docker compose files reference the generated `.env` file via
   the `env_file` directive.

**Critical Note**: Never hardcode configuration in code or Compose. Edit
`PROJECT_CONFIG.yaml` and regenerate the env files.

## Local LLM Integration (Ollama)

The Refiner relies on Ollama for dataset improvement. Two modes are supported,
defined in `OLLAMA_MODE`:

- `native`: Connects to Ollama running on the host machine.
- `container`: Spins up an `ollama` container alongside the stack via the
  `refine-container` profile.

## Key Developer Scripts

The `scripts/demo.sh` script is the primary control plane for local operations.

- **Start Stack**: `./scripts/demo.sh run [--dev]` (uses dev overlay for reload)
- **Stop/Teardown**: `./scripts/demo.sh stop` or `delete`
- **Testing**: `./scripts/demo.sh test [all|gateway|ai_router]` or raw `pytest`
- **Train Route**: `./scripts/demo.sh train`
- **Refiner Route**: `./scripts/demo.sh refine` (runs relabel & augment),
  followed by `./scripts/demo.sh promote` (promotes candidate if better).
- **Other utilities**: `logs`, `scaling`, `failure`, `curl`, `load-test`.

## Technical Policies for Agents

1. **Routing Thresholds**: AI Router returns raw probabilities. The *Gateway*
   enforces the actual routing via `T_ROUTE` (minimum confidence) and `T_MARGIN`
   (gap between top 2 routes). Do not implement policy in the model code.
2. **One-Shot Training**: Training is intentionally not a long-running API. The
   `trainer` container spins up, reads `train.csv`, writes `model.joblib`, and
   terminates.
3. **Security rules**: All operations are offline. Respect structural bounds
   and do not run `cat` in bash to write files. Always utilize `snyk_code_scan`
   for new lines of code.

> [!TIP]
> Always review `docs/auxiliary/architecture/TECHNICAL.md` before making
> structural changes to the AI router or gateway.
