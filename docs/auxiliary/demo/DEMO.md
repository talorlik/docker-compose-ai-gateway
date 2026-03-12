# Demo Runbook

Copy-paste commands for build, run, stop, delete, and demos.
Per PROJECT_PLAN Section 10 and NFR-034.

**Prerequisites:** Docker and Docker Compose. Run from project root.

## Quick Reference

| Action | Command |
| --- | --- |
| Build and start | `docker compose -f compose/docker-compose.yaml up --build -d` |
| Stop | `docker compose -f compose/docker-compose.yaml stop` |
| Delete (remove containers and volumes) | `docker compose -f compose/docker-compose.yaml down -v` |
| Dev mode (hot reload) | `docker compose -f compose/docker-compose.yaml -f compose/docker-compose.dev.yaml up --build -d` |
| Run tests | `pytest services/gateway/tests/ services/ai_router/tests/ -v` |
| Train model | `docker compose -f compose/docker-compose.yaml --profile train run --rm trainer` |
| Refine dataset | `demo.sh refine` then `demo.sh promote` |
| Refine (limit rows) | `demo.sh refine --limit 5` or `-e REFINER_LIMIT=5` |

## 1. Build

```bash
# From project root
docker compose -f compose/docker-compose.yaml build
```

## 2. Run

**Production (detached):**

```bash
# From project root
docker compose -f compose/docker-compose.yaml up --build -d
```

**Dev mode (hot reload):**

```bash
# From project root
docker compose -f compose/docker-compose.yaml -f compose/docker-compose.dev.yaml up --build -d
```

**Wait for health (~10s), then:**

- Browser UI: [http://localhost:8000](http://localhost:8000)
- Gateway API: `http://localhost:8000`
- Health: [http://localhost:8000/health](http://localhost:8000/health)
- Routes: [http://localhost:8000/routes](http://localhost:8000/routes)

## 3. Stop

```bash
# From project root
docker compose -f compose/docker-compose.yaml stop
```

## 4. Delete Everything

Remove containers, networks, and volumes:

```bash
# From project root
docker compose -f compose/docker-compose.yaml down -v
```

## 5. URLs and Curl Commands

**Base URL:** `http://localhost:8000`

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | GET | Frontend GUI |
| `/health` | GET | Health check |
| `/routes` | GET | Available routes (search, image, ops) |
| `/api/request` | POST | Route and proxy request (JSON body: `{"text": "..."}`) |

**Health check:**

```bash
curl http://localhost:8000/health
```

**List routes:**

```bash
curl http://localhost:8000/routes
```

**Search (route: search):**

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "compare nginx ingress vs traefik"}'
```

**Image (route: image):**

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "detect objects in an image and return labels"}'
```

**Ops (route: ops):**

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "kubectl pods CrashLoopBackOff, debug steps"}'
```

**Unknown (404):**

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```

**Verify response (pretty-print):**

```bash
curl -s -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "compare nginx ingress vs traefik"}' | python3 -m json.tool
```

## 6. Logs

**Follow gateway, ai_router, search_service:**

```bash
docker compose -f compose/docker-compose.yaml logs -f gateway ai_router search_service
```

**All services:**

```bash
docker compose -f compose/docker-compose.yaml logs -f
```

## 7. Scaling Demo

**Scale search_service to 3 replicas:**

```bash
docker compose -f compose/docker-compose.yaml up -d --scale search_service=3
```

**Run load test:**

```bash
./scripts/load_test.sh
```

**Verify distribution (instance hostnames in logs):**

```bash
docker compose -f compose/docker-compose.yaml logs gateway | grep -o '"instance":"[^"]*"' | sort | uniq -c
```

**Scale back to 1:**

```bash
docker compose -f compose/docker-compose.yaml up -d --scale search_service=1
```

## 8. Failure Demo

**Stop image_service:**

```bash
docker compose -f compose/docker-compose.yaml stop image_service
```

**Send image-like prompt (expect 502):**

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "detect objects in an image"}'
```

**Restart image_service:**

```bash
docker compose -f compose/docker-compose.yaml start image_service
```

## 9. Testing

**Prerequisites:** `pip install pytest httpx` (and service deps: fastapi, uvicorn,
scikit-learn, numpy, joblib).

**Run all unit tests (gateway + ai_router):**

```bash
# From project root
pytest services/gateway/tests/ services/ai_router/tests/ -v
```

**Run gateway tests only:**

```bash
cd services/gateway && pytest tests/ -v
```

**Run ai_router tests only:**

```bash
cd services/ai_router && pytest tests/ -v
```

## 10. Training

**Train new model (writes to shared volume):**

`train.csv` is mounted from the host at runtime, so edits to
`services/trainer/train.csv` take effect immediately without rebuilding.

```bash
# From project root
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer
```

**Reload ai_router to use new model:**

```bash
docker compose -f compose/docker-compose.yaml restart ai_router
```

**Verify after retrain:**

```bash
curl -s -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "compare nginx ingress vs traefik"}' | python3 -m json.tool
```

## 10.1 Refine Dataset (Runbook)

Refiner analyzes misclassified rows via local LLM (Ollama), produces proposals,
and writes `train_candidate.csv`. Only data that improves metrics is promoted
to `train.csv` via `scripts/promote.sh`.

See [REFINER_PLAN.md](docs/auxiliary/refiner/REFINER_PLAN.md),
[REFINER_FLOW.md](docs/auxiliary/refiner/REFINER_FLOW.md),
[REFINER_TECHNICAL.md](docs/auxiliary/refiner/REFINER_TECHNICAL.md) for full
documentation.

**Prerequisites:** Docker Compose, trainer run first (produces
`misclassified.csv`). Ollama pulls `qwen2.5:7b-instruct` on first refine run
(may take several minutes).

### 10.1.1 Quick Reference

| Action | Command |
| --- | --- |
| Full workflow | `demo.sh train` then `demo.sh refine` then `demo.sh promote` |
| Refine (all rows) | `docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner` |
| Refine (limit rows) | `docker compose ... -e REFINER_LIMIT=5 --profile refine run --rm refiner` |
| Promote | `./scripts/promote.sh` |
| Start Ollama only | `docker compose -f compose/docker-compose.yaml --profile refine up ollama -d` |

### 10.1.2 Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `REFINER_LIMIT` | 0 (no limit) | Max misclassified rows to process; use for faster runs |
| `REFINER_BANNED_PATTERNS` | (empty) | Comma-separated substrings to reject in proposals |
| `OLLAMA_HOST` | `http://ollama:11434` | Ollama API URL |
| `OLLAMA_MODEL` | `qwen2.5:7b-instruct` | Model for relabel and augmentation |

### 10.1.3 Step-by-Step Workflow

#### Step 1: Train

Produces misclassified.csv, metrics.json in model volume.

```bash
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer
```

#### Step 2: Refine

Requires Ollama; produces train_candidate.csv.

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner
```

#### Optional: Limit rows for faster runs

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm \
  -e REFINER_LIMIT=5 refiner
```

#### Optional: Reject proposals containing banned patterns

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm \
  -e REFINER_BANNED_PATTERNS="foo,bar" refiner
```

#### Step 3: Promote

Retrain and promote only if metrics improve.

```bash
./scripts/promote.sh
```

#### Step 4: If promoted, restart ai_router

```bash
docker compose -f compose/docker-compose.yaml restart ai_router
```

### 10.1.4 Outputs (in model volume)

| File | Purpose |
| --- | --- |
| `proposed_relabels.csv` | Audit: relabel proposals |
| `proposed_examples.csv` | Audit: augmentation proposals |
| `refinement_report.json` | Summary: rows_processed, relabels_proposed, examples_proposed, rows_skipped, errors |
| `train_candidate.csv` | Merged candidate; promote conditionally |

### 10.1.5 End-to-End Verification (REF-AC-001, REF-AC-002)

```bash
# 1. Train
docker compose -f compose/docker-compose.yaml --profile train run --rm trainer

# 2. Refine (limit rows for faster runs)
docker compose -f compose/docker-compose.yaml --profile refine run --rm \
  -e REFINER_LIMIT=5 refiner

# 3. Verify proposal files and train_candidate exist
docker compose -f compose/docker-compose.yaml --profile refine run --rm \
  --no-deps --entrypoint sh refiner -c \
  "test -f /data/proposed_relabels.csv && test -f /data/proposed_examples.csv \
   && test -f /data/refinement_report.json && test -f /data/train_candidate.csv \
   && echo OK"

# 4. Promote (retrains and promotes only if metrics improve)
./scripts/promote.sh

# 5. If promoted, restart ai_router
docker compose -f compose/docker-compose.yaml restart ai_router
```

### 10.1.6 Promote Script

`scripts/promote.sh` retrains with `train_candidate.csv`, compares accuracy
to `metrics_before.json`, and promotes to `train.csv` only if metrics improve.
No parameters. Run after refiner.

## 11. Demo Script

Run `./scripts/demo.sh --help` for full options.

```bash
./scripts/demo.sh build              # Build all services
./scripts/demo.sh build gateway      # Build gateway only
./scripts/demo.sh run                # Start stack
./scripts/demo.sh run --dev          # Start with hot reload
./scripts/demo.sh run --scale 3      # Start with search_service=3
./scripts/demo.sh stop               # Stop stack
./scripts/demo.sh delete             # Remove containers and volumes
./scripts/demo.sh curl               # Run curl examples
./scripts/demo.sh scaling            # Scaling demo
./scripts/demo.sh scale 1            # Scale search_service back to 1
./scripts/demo.sh failure            # Failure demo
./scripts/demo.sh load-test          # Run load test
./scripts/demo.sh logs               # Follow logs
./scripts/demo.sh test               # Run unit tests
./scripts/demo.sh test gateway       # Run gateway tests only
./scripts/demo.sh train              # Train model and reload ai_router
./scripts/demo.sh refine             # Run refiner (after train)
./scripts/demo.sh refine --limit 5   # Refine with row limit (faster)
./scripts/demo.sh promote            # Promote candidate if metrics improve
```

## 12. Frontend GUI

**URL:** [http://localhost:8000](http://localhost:8000)

**How to use:**

1. Open the URL in a browser.

2. Enter a query in the text area (e.g. "compare nginx ingress vs traefik").
3. Click **Submit**.
4. View the result:
   - **Route** – Selected route (search, image, ops, or unknown) and
     confidence %
   - **Explanation** – Top tokens that influenced the classification
   - **Request Flow** – Hop diagram (web -> gateway -> ai-router -> backend)
   - **Trace** – Timeline of events with timestamps
   - **Timings** – Classify, proxy, and total latency (ms)
   - **Backend Response** – JSON from the backend (hidden for unknown)
5. For **unknown** (404): Message "Unable to determine a suitable backend."
6. For **502/503**: Message "Service temporarily unavailable."

## 13. Demo Prompts by Label

40 example prompts for demos (10 per label). These are distinct from the
training data in `services/trainer/train.csv`.

### Search (10)

| # | Text |
| --- | --- |
| 1 | what is exponential backoff in retries |
| 2 | explain consensus algorithm in distributed systems |
| 3 | how does consistent hashing work for load balancing |
| 4 | what is eventual consistency in databases |
| 5 | compare kafka vs rabbitmq for message queues |
| 6 | what is a dead letter queue |
| 7 | explain leader election in raft protocol |
| 8 | what is database sharding |
| 9 | how does bloom filter work |
| 10 | what is circuit breaker in resilience patterns |

### Image (10)

| # | Text |
| --- | --- |
| 1 | redact sensitive information from a screenshot |
| 2 | find text in a screenshot and highlight it |
| 3 | create a collage from multiple photos |
| 4 | apply vintage filter to portrait |
| 5 | identify breed of dog from pet photo |
| 6 | generate alt text for accessibility |
| 7 | detect whether photo is indoors or outdoors |
| 8 | estimate time of day from photo lighting |
| 9 | identify landmarks in a vacation photo |
| 10 | create thumbnail for video preview |

### Ops (10)

| # | Text |
| --- | --- |
| 1 | npm install fails with ENOENT - how to fix |
| 2 | jest tests timeout in CI - increase timeout |
| 3 | redis connection refused - firewall rules |
| 4 | elasticsearch cluster yellow - replica allocation |
| 5 | gunicorn workers dying - memory leak |
| 6 | postgres deadlock - identify blocking queries |
| 7 | kafka consumer lag increasing - scale consumers |
| 8 | s3 multipart upload fails - retry strategy |
| 9 | slack webhook returns 400 - payload format |
| 10 | datadog metrics not appearing - agent config |

### Unknown (10)

| # | Text |
| --- | --- |
| 1 | good morning sunshine |
| 2 | howdy partner |
| 3 | what's for lunch |
| 4 | i'm bored |
| 5 | entertain me |
| 6 | spin a yarn |
| 7 | knock knock |
| 8 | are we good |
| 9 | right on |
| 10 | all good |

## 14. Status Reference

| Scenario | HTTP | Trace backend hop |
| --- | --- | --- |
| Unknown classification | 404 | None |
| Low confidence / low margin | 404 | None |
| Backend unreachable | 502 | Attempted |
| AI router unreachable | 503 | None |
| Successful route | 200 | Yes |
