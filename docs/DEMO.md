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

## 13. Browser Demo Prompts

| Prompt | Expected Route |
| --- | --- |
| compare nginx ingress vs traefik | search |
| detect objects in an image and return labels | image |
| kubectl pods CrashLoopBackOff, debug steps | ops |
| hello | unknown (404) |
| tell me a joke | unknown (404) |

## 14. Status Reference

| Scenario | HTTP | Trace backend hop |
| --- | --- | --- |
| Unknown classification | 404 | None |
| Low confidence / low margin | 404 | None |
| Backend unreachable | 502 | Attempted |
| AI router unreachable | 503 | None |
| Successful route | 200 | Yes |
