# Training API

FastAPI service for train, refine, and promote flows. Uses Redis for job state
and event-driven completion (SSE). Part of the Train and Refine GUI; starts
with the default stack (no profile required for train).

**Execution:** Train and refine run the trainer and refiner **Python code**
(subprocess), not Docker Compose. Bash scripts (e.g. `scripts/promote.sh`) run
`docker compose`; this service runs Python only.

**Refine:** The refine flow runs the refiner Python script and requires Ollama.
Start Ollama (e.g. `docker compose --profile refine up -d ollama`) before
running refinement.

## Environment

| Variable | Description |
| --- | --- |
| `REDIS_URL` | Full Redis URL (e.g. `redis://redis:6379/0`). Preferred. |
| `REDIS_HOST` | Redis host when not using REDIS_URL (default: `redis`). |
| `REDIS_PORT` | Redis port when not using REDIS_URL (default: `6379`). |
| `COMPOSE_WORKING_DIR` | Repo root; used to find `services/trainer/train.py` and `services/refiner/app.py`. |
| `MODEL_ARTIFACTS_PATH` | Path to model_artifacts volume (default `/model`; set in Batch 7). |
| `PROMOTE_TARGET_PATH` | Directory to write promoted train.csv (default `/promote_target`; Batch 7). |

At least `REDIS_URL` or both `REDIS_HOST` and `REDIS_PORT` must be set.
Startup fails if Redis is not configured or unreachable.

## Run

With Compose (from repo root); training-api and Redis start by default:

```bash
docker compose -f compose/docker-compose.yaml up -d
```

Health check:

```bash
curl http://localhost:8000/health
```

(If training-api is not published, use the gateway proxy or exec into the
network.)

To verify Redis job state and Pub/Sub helpers, override entrypoint:

```bash
docker compose -f compose/docker-compose.yaml run --rm --entrypoint python training-api -m app.redis_client
```

## CLI (train, refine, promote)

Same Python logic as HTTP. Bash scripts invoke the container (e.g. `docker compose run training-api train`); inside the container, Python runs the trainer/refiner scripts (no Docker).

```bash
# Run training (Python runs services/trainer/train.py), return metrics + misclassified
docker compose -f compose/docker-compose.yaml run --rm training-api train

# Run refiner (Python runs services/refiner/app.py), then trainer on candidate
docker compose -f compose/docker-compose.yaml --profile refine run --rm training-api refine

# Require train_candidate.csv; compare metrics; if improved, copy to promote target
docker compose -f compose/docker-compose.yaml run --rm training-api promote
```

Default CMD is `server` (HTTP). Override by passing `train`, `refine`, or `promote` as the
container command so the entrypoint `python -m app.cli` receives the subcommand.

## Security and timeouts

- **Process timeout:** Background train jobs use a 1-hour process timeout;
  refine jobs use a 10-minute timeout (`RUN_REFINE_TIMEOUT_SECONDS=600`)
  so stuck runs do not leak resources (see `app/jobs/runner.py`).
- **Redis TTL:** Job keys in Redis have a 24-hour TTL to limit storage (see
  `app/redis_client.py`).
- **Promote:** The Promote button (UI) and `POST /refine/promote` (or CLI
  `training-api promote`) run synchronously; the gateway uses a longer timeout
  (e.g. 5 min) for the promote proxy.
- **Security:** Run Snyk (code + SCA) on this service per project rules after
  adding or changing dependencies or the Dockerfile.
