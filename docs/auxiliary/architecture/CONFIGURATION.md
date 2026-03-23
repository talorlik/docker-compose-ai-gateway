# Configuration Overview

Centralized configuration for the project is managed via a single YAML file and
small generation script. This document explains how values flow from the
repository config into Docker Compose and runtime services.

## 1. Configuration Sources

- **Project config (authoritative):**
  - `config/PROJECT_CONFIG.yaml`
- **Generated env files (per environment):**
  - `env/.env.<env>` (for example, `env/.env.dev`)
- **Docker Compose:**
  - `compose/docker-compose.yaml`
  - `compose/docker-compose.dev.yaml`

## 2. PROJECT_CONFIG.yaml

`config/PROJECT_CONFIG.yaml` is the single source of truth for project-wide
settings. It is organized by top-level environment keys:

- `default`: shared values for all environments
- `dev`: overrides for local development
- `prod`: overrides for production

`default` also defines `ENV` (for example `dev`), which is the default
environment selector when generating env files and when Compose chooses
`env/.env.<env>`.

Typical keys include:

- Logging and runtime:
  - `LOG_LEVEL`
  - `REQUEST_TIMEOUT`
  - `PYTHONDONTWRITEBYTECODE`
  - `PYTHONUNBUFFERED`
- Paths:
  - `MODEL_ARTIFACTS_PATH`
  - `PROMOTE_TARGET_PATH`
  - `COMPOSE_WORKING_DIR`
- Redis:
  - `REDIS_URL`
- Ollama and refiner:
  - `OLLAMA_MODE`
  - `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE`
  - `OLLAMA_CONTAINER_SERVICE`
  - `OLLAMA_MODEL`
  - `OLLAMA_URLS`
  - `OLLAMA_HOST`
  - `OLLAMA_TIMEOUT_SECONDS`
  - `OLLAMA_MAX_INFLIGHT_PER_INSTANCE`
  - `OLLAMA_MAX_LOADED_MODELS`
  - `OLLAMA_NUM_PARALLEL`
  - `OLLAMA_MAX_QUEUE`
  - `OLLAMA_KEEP_ALIVE`
  - `OLLAMA_NUM_CTX`
  - `OLLAMA_NUM_PREDICT`
  - `OLLAMA_FLASH_ATTENTION`
  - `OLLAMA_KV_CACHE_TYPE`
  - `REFINER_RELABEL_NUM_CTX`
  - `REFINER_AUGMENT_NUM_CTX`
  - `REFINER_RELABEL_NUM_PREDICT`
  - `REFINER_AUGMENT_NUM_PREDICT`
  - `REFINER_TEMPERATURE`
  - `REFINER_SEED`
  - `REFINER_STRUCTURED_OUTPUT_ENABLED`
  - `REFINER_RELABEL_BATCH_SIZE`
  - `REFINER_RELABEL_MAX_PARALLEL_BATCHES`
  - `REFINER_AUGMENT_N_PER_LABEL`
  - `REFINER_AUGMENT_MAX_PARALLEL_LABELS`
  - `REFINER_RELABEL_MAX_RETRIES`
  - `REFINER_AUGMENT_MAX_RETRIES`
  - `REFINER_AUGMENT_VERIFY_LABELS`
  - `REFINER_AUGMENT_VERIFY_MIN_CONFIDENCE`
  - `REFINER_AUGMENT_MAX_TEXT_LENGTH`
  - `REFINER_AUGMENT_SEED_EXAMPLES`
  - `REFINER_PROMOTE_ACCURACY_TOLERANCE`
  - `REFINER_LIMIT`
  - `DEMO_START_BACKEND`
  - `DEMO_RUN_RELABEL`
  - `DEMO_RUN_AUGMENT`
  - `BENCH_PROFILE`
  - `BENCH_EXPERIMENT_ID`
  - `BENCH_METRICS_INTERVAL_SEC`
  - `BENCH_MAX_RETRIES`

Edit this file to change configuration globally instead of editing individual
Compose files or service-specific env vars.

## 3. Env File Generation

`scripts/generate_env.py` reads `PROJECT_CONFIG.yaml` and writes flat env files
for a specific environment.

### 3.1 Usage

From the repository root:

```bash
python scripts/generate_env.py
```

This command:

- Reads `default.ENV` from `PROJECT_CONFIG.yaml` (falls back to `dev`)
- Loads `default` and the selected environment section
- Merges them (environment section overrides `default`)
- Writes `env/.env.<env>` with `KEY=VALUE` lines

Override explicitly when needed:

```bash
python scripts/generate_env.py prod
```

## 4. Docker Compose Integration

### 4.1 Env File Consumption

The base Compose file defines a small anchor for services that should consume
the generated env file. For example, `training-api` uses:

- `env_file: ../env/.env.${ENV:-dev}` (via a shared anchor)
- `environment: <<: *common-env` for a minimal set of inline defaults

Other services can be wired the same way if they need centralized values.

### 4.2 Profiles and Dev Overlay

- `compose/docker-compose.yaml`:
  - Core services, health checks, volumes, and profiles
  - References `env/.env.${ENV:-dev}` for runtime configuration
- `compose/docker-compose.dev.yaml`:
  - Dev-only overrides (bind mounts, `uvicorn --reload`)

Start the full stack in dev mode after generating the env file:

```bash
python scripts/generate_env.py

docker compose \
  -f compose/docker-compose.yaml \
  -f compose/docker-compose.dev.yaml \
  up --build
```

## 5. Service-Level Configuration

### 5.1 Training API and Refiner Pipeline

The training-api and refiner-related code uses environment variables (for
example `REDIS_URL`, `MODEL_ARTIFACTS_PATH`, `PROMOTE_TARGET_PATH`,
`OLLAMA_URLS`, `OLLAMA_MODEL`, `REFINER_*`) as inputs. These values are now
expected to come from the generated env file rather than being hard-coded
inside Compose.

Changing any of these values in `PROJECT_CONFIG.yaml` and regenerating the env
file is sufficient to:

- Point training-api at a different Redis instance
- Adjust refine batching, retries, and concurrency
- Change Ollama mode, host, model, keep-alive, queue, or token budgets
- Move artifact and promotion paths

### 5.2 Backend Selection And Mutual Exclusion

The project supports two Ollama modes:

- `OLLAMA_MODE=native`: host-native Ollama endpoint.
- `OLLAMA_MODE=container`: Compose-managed `ollama` service.

`scripts/demo.sh` reads mode settings from generated env files and enforces
backend exclusivity when `OLLAMA_BACKEND_ENFORCE_EXCLUSIVE=true`. This keeps
resource usage predictable by ensuring only one backend is active.

### 5.3 Other Services

Gateway, ai-router, and backend services continue to read configuration via env
vars, but they can also be wired to the generated env files when needed. The
recommended pattern is:

- Keep service code reading `os.environ[...]` only
- Drive actual values via:
  - `PROJECT_CONFIG.yaml` → `env/.env.<env>` → Compose `env_file`
  - Minimal inline Compose overrides where environment-specific tuning is
    required

## 6. Making Configuration Changes

1. Edit `config/PROJECT_CONFIG.yaml` (default and environment-specific
   sections).
2. Regenerate the env file:

   ```bash
   python scripts/generate_env.py
   ```

3. Restart the relevant services via Docker Compose.

This flow keeps all configuration changes centralized and reproducible across
environments.
