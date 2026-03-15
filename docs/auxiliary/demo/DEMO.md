# Demo Runbook

Runbook for the Local AI Microservice Mesh: command-line and bash script
usage first, with clear instructions for using the frontend. Per PROJECT_PLAN
Section 10 and NFR-034.

**Prerequisites:** Docker and Docker Compose. Run all commands from the
project root unless noted.

## Quick Reference (Scripts)

| Action | Command |
| --- | --- |
| Build | `./scripts/demo.sh build` |
| Start stack | `./scripts/demo.sh run` |
| Start with Train/Refine UI | `docker compose -f compose/docker-compose.yaml --profile refine up -d` |
| Stop | `./scripts/demo.sh stop` |
| Delete (containers + volumes) | `./scripts/demo.sh delete` |
| Curl demos | `./scripts/demo.sh curl` |
| Scaling demo | `./scripts/demo.sh scaling` |
| Failure demo | `./scripts/demo.sh failure` |
| Load test | `./scripts/demo.sh load-test` |
| Logs | `./scripts/demo.sh logs` |
| Unit tests | `./scripts/demo.sh test` |
| Train model | `./scripts/demo.sh train` |
| Refine dataset | `./scripts/demo.sh refine` (option: `--limit 5`) |
| Promote candidate | `./scripts/promote.sh` |

## Part I: Command-Line and Script Runbook

### 1. Build

```bash
./scripts/demo.sh build
```

Build a single service:

```bash
./scripts/demo.sh build gateway
```

Without script (raw Compose):

```bash
docker compose -f compose/docker-compose.yaml build
```

### 2. Run the Stack

**Production (default profile):**

```bash
./scripts/demo.sh run
```

**With hot reload (dev overlay):**

```bash
./scripts/demo.sh run --dev
```

**With search_service scaled to 3:**

```bash
./scripts/demo.sh run --scale 3
```

**With Train and Refine UI (Redis + training-api):**

Start the stack including the refine profile so the frontend Train/Refine
tabs work:

```bash
docker compose -f compose/docker-compose.yaml --profile refine up -d
```

Wait for health (~10s). Gateway: <http://localhost:8000>. For Refine tab,
Ollama must be running (e.g. start Ollama first or use the same command;
Ollama is in the refine profile).

**Without script:**

```bash
docker compose -f compose/docker-compose.yaml up --build -d
```

### 3. Stop

```bash
./scripts/demo.sh stop
```

Without script:

```bash
docker compose -f compose/docker-compose.yaml stop
```

### 4. Delete Everything

Removes containers, networks, and volumes.

```bash
./scripts/demo.sh delete
```

Without script:

```bash
docker compose -f compose/docker-compose.yaml down -v
```

### 5. Curl Demos (API)

Ensure the stack is running. Base URL: `http://localhost:8000` (or set
`GATEWAY_URL`).

**Run all curl examples (search, image, ops, unknown):**

```bash
./scripts/demo.sh curl
```

**Manual curl examples:**

Health:

```bash
curl http://localhost:8000/health
```

List routes:

```bash
curl http://localhost:8000/routes
```

Search (route: search):

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "compare nginx ingress vs traefik"}'
```

Image (route: image):

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "detect objects in an image and return labels"}'
```

Ops (route: ops):

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "kubectl pods CrashLoopBackOff, debug steps"}'
```

Unknown (404):

```bash
curl -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "hello"}'
```

Pretty-print response:

```bash
curl -s -X POST http://localhost:8000/api/request \
  -H "Content-Type: application/json" \
  -d '{"text": "compare nginx ingress vs traefik"}' | python3 -m json.tool
```

### 6. Logs

**Follow gateway, ai_router, search_service:**

```bash
./scripts/demo.sh logs
```

**Follow a specific service:**

```bash
./scripts/demo.sh logs gateway
```

Without script:

```bash
docker compose -f compose/docker-compose.yaml logs -f gateway ai_router search_service
```

### 7. Scaling Demo

Scale search_service to 3, run load test, then scale back:

```bash
./scripts/demo.sh scaling
```

Scale back to 1:

```bash
./scripts/demo.sh scale 1
```

Load test only (default 20 requests):

```bash
./scripts/demo.sh load-test
```

### 8. Failure Demo

Stop image_service, send a request (expect 502), then restart:

```bash
./scripts/demo.sh failure
```

Restart image_service:

```bash
docker compose -f compose/docker-compose.yaml start image_service
```

### 9. Unit Tests

**All (gateway + ai_router):**

```bash
./scripts/demo.sh test
```

**Gateway only:**

```bash
./scripts/demo.sh test gateway
```

Without script:

```bash
pytest services/gateway/tests/ services/ai_router/tests/ -v
```

### 10. Training (CLI)

Train writes to the shared model volume. Edits to
`services/trainer/train.csv` take effect on the next train (no rebuild).

**Train and reload ai_router:**

```bash
./scripts/demo.sh train
```

This runs training via training-api and restarts ai_router. Verify:

```bash
./scripts/demo.sh curl
```

Without script:

```bash
docker compose -f compose/docker-compose.yaml --profile refine run --rm training-api train
docker compose -f compose/docker-compose.yaml restart ai_router
```

### 11. Refine and Promote (CLI)

Refiner uses a local LLM (Ollama). Run trainer first to produce
`misclassified.csv`. See
[REFINER_PLAN.md](docs/auxiliary/refiner/REFINER_PLAN.md),
[REFINER_FLOW.md](docs/auxiliary/refiner/REFINER_FLOW.md),
[TRAIN_AND_REFINE_GUI_PAGES_TECH.md](docs/auxiliary/architecture/TRAIN_AND_REFINE_GUI_PAGES_TECH.md).

**Full workflow (train, refine, promote):**

```bash
./scripts/demo.sh train
./scripts/demo.sh refine
./scripts/promote.sh
```

**Refine with row limit (faster):**

```bash
./scripts/demo.sh refine --limit 5
```

**Promote only (after refine):**

```bash
./scripts/promote.sh
```

If promotion succeeded, restart ai_router:

```bash
docker compose -f compose/docker-compose.yaml restart ai_router
```

**Environment variables (refine):** `REFINER_LIMIT` (max rows, 0 = no limit),
`REFINER_BANNED_PATTERNS` (comma-separated substrings to reject),
`OLLAMA_HOST`, `OLLAMA_MODEL`. See refiner docs.

### 12. Demo Script Reference

Full usage:

```bash
./scripts/demo.sh --help
```

Commands:

```bash
./scripts/demo.sh build [SERVICE]   # Build all or one service
./scripts/demo.sh run [--dev] [--scale N]
./scripts/demo.sh stop
./scripts/demo.sh delete
./scripts/demo.sh curl
./scripts/demo.sh scaling
./scripts/demo.sh scale N          # e.g. scale 1
./scripts/demo.sh failure
./scripts/demo.sh load-test
./scripts/demo.sh logs [SERVICE...]
./scripts/demo.sh test [gateway|ai_router]
./scripts/demo.sh train
./scripts/demo.sh refine [--limit N]
./scripts/demo.sh promote          # Wrapper for promote.sh
```

### 13. Promote Script

`scripts/promote.sh` retrains with `train_candidate.csv`, compares
accuracy to the previous run, and promotes to `train.csv` only if metrics
improve. No arguments. Run after refine (via UI or CLI).

### 14. Load Test Script

`scripts/load_test.sh` sends multiple requests to the gateway. Default
request count: 20 (set `REQUESTS` to override). Stack must be running.

## Part II: Using the Frontend

The gateway serves a web UI at <http://localhost:8000> (or your
`GATEWAY_URL`). Use it for query routing, and optionally for training and
refinement when the stack is run with the refine profile.

### Opening the UI

1. Start the stack (see [Run the Stack](#2-run-the-stack)).
2. Open a browser and go to <http://localhost:8000>.

### Navigation

The UI has three tabs in the header:

- **Query** – Route a request and view the trace (default).
- **Train** – Run training and view metrics and misclassified table.
- **Refine** – Run refinement and view report, comparison, and Promote.

Switch tabs by clicking **Query**, **Train**, or **Refine**. The Train and
Refine tabs require the stack to be started with the **refine** profile
(Redis and training-api running). If they are not available, the UI shows
a message that the Training API is not available.

### Query Tab

1. In the **Query** tab, type a question or phrase in the text area (e.g.
   "compare nginx ingress vs traefik").
2. Click **Submit**.
3. View the result:
   - **Route** – Selected route (search, image, ops, or unknown) and
     confidence.
   - **Explanation** – Tokens that influenced the classification.
   - **Request Flow** – Hop diagram (web -> gateway -> ai-router -> backend).
   - **Trace** – Timeline of events with timestamps.
   - **Timings** – Classify, proxy, and total latency (ms).
   - **Backend Response** – JSON from the backend (hidden for unknown).
4. For **unknown** (404): Message "Unable to determine a suitable backend."
5. For **502/503**: Message "Service temporarily unavailable."

### Train Tab

Use this tab to run training from the UI and see metrics and
misclassified rows without using the command line.

1. Ensure the stack is running with the **refine** profile (Redis and
   training-api). See [Run the Stack](#2-run-the-stack).
2. Open the **Train** tab.
3. Start a training run (e.g. click the button to start training).
4. Wait for completion. The UI receives the result via Server-Sent Events
   (no polling). A progress indicator may be shown while the job runs.
5. When the job completes, view:
   - **Metrics** – Accuracy, classification report, confusion matrix.
   - **Misclassified table** – Rows the model got wrong (text, true label,
     predicted label, confidence).

If the Training API is not available, start the stack with
`docker compose -f compose/docker-compose.yaml --profile refine up -d`.

### Refine Tab

Use this tab to run refinement from the UI, view the report and
before/after comparison, and promote the candidate dataset when metrics
improve.

1. Ensure the stack is running with the **refine** profile and **Ollama**
   is running (required for the refiner). Start with the refine profile;
   Ollama is typically part of that profile.
2. Open the **Refine** tab.
3. Start a refinement run (e.g. click the button to start refinement).
4. Wait for completion (event-driven via SSE). View:
   - **Report** – Rows processed, relabels proposed, examples proposed.
   - **Comparison** – Metrics before and after (candidate vs current).
   - **Tables** – Proposed relabels, proposed examples, train candidate.
5. If the comparison shows improvement, click **Promote** to run
   promotion. Promotion retrains with the candidate and updates
   `train.csv` only if metrics improve. The request may take a few
   minutes; the UI uses a longer timeout for the promote call.

If the Training API or Ollama is not available, start the stack with the
refine profile and ensure Ollama is up (e.g. first run may pull the
model).

## Reference

### API Endpoints

| Endpoint | Method | Description |
| --- | --- | --- |
| `/` | GET | Frontend GUI |
| `/health` | GET | Health check |
| `/routes` | GET | Available routes |
| `/api/request` | POST | Route and proxy (JSON: `{"text": "..."}`) |

### Status Reference

| Scenario | HTTP | Trace backend hop |
| --- | --- | --- |
| Unknown classification | 404 | None |
| Low confidence / low margin | 404 | None |
| Backend unreachable | 502 | Attempted |
| AI router unreachable | 503 | None |
| Successful route | 200 | Yes |

### Demo Prompts by Label

Example prompts for demos (10 per label). Distinct from training data in
`services/trainer/train.csv`.

**Search (10):** what is exponential backoff in retries; explain
consensus algorithm in distributed systems; how does consistent hashing
work for load balancing; what is eventual consistency in databases;
compare kafka vs rabbitmq for message queues; what is a dead letter
queue; explain leader election in raft protocol; what is database
sharding; how does bloom filter work; what is circuit breaker in
resilience patterns.

**Image (10):** redact sensitive information from a screenshot; find text
in a screenshot and highlight it; create a collage from multiple photos;
apply vintage filter to portrait; identify breed of dog from pet photo;
generate alt text for accessibility; detect whether photo is indoors or
outdoors; estimate time of day from photo lighting; identify landmarks in
a vacation photo; create thumbnail for video preview.

**Ops (10):** npm install fails with ENOENT - how to fix; jest tests
timeout in CI - increase timeout; redis connection refused - firewall
rules; elasticsearch cluster yellow - replica allocation; gunicorn workers
dying - memory leak; postgres deadlock - identify blocking queries; kafka
consumer lag increasing - scale consumers; s3 multipart upload fails -
retry strategy; slack webhook returns 400 - payload format; datadog
metrics not appearing - agent config.

**Unknown (10):** good morning sunshine; howdy partner; what's for lunch;
i'm bored; entertain me; spin a yarn; knock knock; are we good; right on;
all good.
