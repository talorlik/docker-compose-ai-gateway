# TECHNICAL BREAKDOWN

Technical specification for the AI router: training pipeline, artifacts,
routing policy, and explanation tokens. Training code lives in
`services/trainer/train.py`; review for any additions or changes.

<!-- CROSS-REF: Each ## section includes a "TASKS:" marker listing
     task IDs from TASKS.md that it implements. Search for "TASKS:"
     to jump between sections and tasks. Section 21 has the full
     bidirectional mapping. In TASKS.md, the "Tech spec" column
     points back to sections here using "TECH-{N}" format. -->

## 1. Dependencies (ai-router runtime)
<!-- TASKS: 1.4, 2.2 -->

```text
fastapi==0.115.6
uvicorn[standard]==0.32.1
joblib==1.4.2
```

## 2. Training Data and Commands
<!-- TASKS: 2.1, 2.2 -->

### Data format

- **File:** `train.csv` with columns `text` and `label`.
- **Labels:** `search`, `image`, `ops`, `unknown` (must match exactly; order in
  code is `["search", "image", "ops", "unknown"]`).
- **Balance:** Aim for at least ~160 examples per label for stable training
  (TASKS 2.1). Run a quick count per label; top up any class below that before
  relying on metrics.

### Running training

From `services/trainer/`:

```bash
python train.py --data ./train.csv --out ./model.joblib --metrics ./metrics.json
```

Optional: export misclassified validation samples:

```bash
python train.py --data ./train.csv --out ./model.joblib --metrics ./metrics.json --misclassified ./misclassified.csv
```

Use `--no-misclassified` to disable misclassified export.

## 3. Training Outputs: What They Are and What You Do
<!-- TASKS: 2.2, 2.3, 2.4 -->

### 3.1 model.joblib

**What it is:** The trained artifact the ai-router service loads at runtime.
Contains: TF-IDF vectorizer, LogisticRegression model, label list, and
training metadata.

**What you do:**

1. Keep it at `services/ai_router/model/model.joblib` (or load from path).
2. In ai-router startup: `artifact = joblib.load("model.joblib")`.
3. In `/classify`: vectorize text, call `predict_proba`, then apply your
   threshold/margin policy to choose route or unknown.

This is the model you ship.

### 3.2 metrics.json

**What it is:** Evaluation metrics on the held-out validation set: accuracy,
per-class precision/recall/F1, and confusion matrix.

**What you do:** Use it to sanity-check the model. Ensure `unknown` recall is
reasonable (otherwise 404 will rarely happen), and that `ops` is not often
confused with `search`. If a class is weak, add more examples for that class.

### 3.3 misclassified.csv (optional)

**What it is:** Rows from the validation set where `pred_label != true_label`.
Columns: `text`, `true_label`, `pred_label`, `pred_confidence`, `probs_json`.

**What you do:** Use it to improve the dataset and tune routing policy.

**Workflow:**

1. Open `misclassified.csv`.
2. For each row, classify the cause and act:

   - **Bad label:** Fix or remove the row in `train.csv`.
   - **Ambiguous text:** Add clearer examples for both labels, or move some to
     `unknown` for strict routing.
   - **Missing pattern:** Add 5–20 short, varied examples with that wording.
   - **Too confident but wrong (e.g. confidence > 0.75):** Add counterexamples
     and distinctive tokens for the intended label.
   - **Low confidence and wrong (e.g. < 0.55):** Rely on thresholding to send
     to `unknown`; consider raising threshold or adding a margin rule.

3. Retrain.
4. Repeat until misclassifications are acceptable.

Use misclassifications to tune gateway policy: if many wrong routes occur at
0.50–0.65 confidence, raise `T_route`; if two classes are often close, add
`T_margin`.

**Minimum practical usage:** Keep `model.joblib`, glance at `metrics.json`, and
optionally ignore `misclassified.csv`. For a solid router, use
`misclassified.csv` to refine data and thresholds.

## 4. Iteration Cycle (Data → Retrain → Evaluate → Policy)
<!-- TASKS: 6.11 -->

Refining data without retraining has no effect; the model is static.

**Correct loop:**

1. **Edit the dataset:** Fix wrong labels, add missing patterns, move ambiguous
   samples to `unknown`, remove misleading examples.
2. **Rerun training:** Run `train.py` again; new `model.joblib`, updated
   metrics and misclassifications.
3. **Evaluate:** Check `metrics.json`, review `misclassified.csv`, verify
   confidence distributions.
4. **Tune policy:** Adjust `T_route` and optional `T_margin` in the gateway
   only; do not change gateway logic, only thresholds.
5. **Repeat** until high-confidence misroutes are rare and most uncertainty goes
   to `unknown`.

**What changes between runs:** Model weights, decision boundaries, probability
calibration, and unknown behavior. Nothing else in the system needs to change.

**Practical workflow:** Keep `train.csv` in git; do not commit `model.joblib`
until satisfied; then commit the final artifact. Docker build uses that
artifact.

## 5. Threshold and Margin: Two Different Loops
<!-- TASKS: 4.3, 8.6 -->

### 5.1 Rerunning training (data-driven refinement)

This changes the **model**. Do it when you fix labels, add/remove examples,
improve coverage, or adjust class balance (especially `unknown`). Effect:
weights and decision boundaries change, probabilities recalibrate. Mechanism:
edit `train.csv`, run trainer, produce new `model.joblib`, restart ai-router.

### 5.2 Threshold and margin tuning (policy refinement)

This does **not** retrain. It changes how the gateway **interprets**
probabilities. Use when the model is broadly correct but too aggressive, or
you want fewer wrong routes and more `unknown`. Parameters: `T_route` (min
confidence to route), `T_margin` (min gap between top-1 and top-2). Effect:
same probabilities, different routing decisions, more or fewer 404s.

**Order of operations:** (1) Train; (2) inspect metrics and misclassified;
(3) fix data; (4) retrain; (5) repeat until misclassifications are mostly
low-confidence; (6) then tune thresholds/margin; (7) restart ai-router after
changes. Do not tune thresholds to compensate for bad data; do not retrain
only to change routing strictness.

**Summary:** Training improves what the model knows; thresholds control how
willing the system is to act on that knowledge.

## 6. Where and How to Implement Thresholds
<!-- TASKS: 4.3, 8.6 -->

**Where:** In the **gateway**, not in the model or backends. The gateway is the
policy enforcement point.

**What to implement:**

- `T_ROUTE`: minimum confidence to route to a backend.
- `T_MARGIN`: minimum gap between top-1 and top-2 among non-unknown routes
  (optional but recommended).

Routing uses only non-unknown routes for "guessing"; otherwise fall back to
unknown (404).

**Implementation steps:**

1. **Env vars (e.g. in compose):** `T_ROUTE=0.60`, `T_MARGIN=0.10`. Parse as
   floats in gateway startup and validate in [0.0, 1.0].
2. **ai-router response:** Gateway must receive full probability distribution
   (or at least best_route among non-unknown, `p_best`, `p_second`, `p_unknown`).
   Best practice: return full probability map from ai-router.
3. **Policy logic:**

   - Best among `{search, image, ops}` → `best_route`, `p_best`.
   - Second-highest → `p_second`.
   - If `p_best >= T_ROUTE` and `(p_best - p_second) >= T_MARGIN`: route to
     `best_route`.
   - Else: route = `unknown`, return 404.

4. **Trace:** Add metadata for unknown: e.g. `policy: low_confidence` or
   `policy: low_margin`.
5. **Tuning:** Use `misclassified.csv` and real prompts: raise `T_ROUTE` if
   wrong routes at 0.55–0.65; raise `T_MARGIN` if two routes flip; lower
   thresholds if too many valid prompts become unknown. Restart gateway after
   env changes; no retraining needed.

**Note:** Thresholds are **not** implemented in the Python code you have so
far. `train.py` and ai-router produce probabilities; the gateway must
implement the decision logic that uses `T_ROUTE` and `T_MARGIN` to route or
return 404.

**Example gateway policy (pseudocode):**

```python
T_ROUTE = float(os.getenv("T_ROUTE", 0.60))
T_MARGIN = float(os.getenv("T_MARGIN", 0.10))

non_unknown = {k: v for k, v in probs.items() if k != "unknown"}
sorted_routes = sorted(non_unknown.items(), key=lambda x: x[1], reverse=True)
best_route, p_best = sorted_routes[0]
p_second = sorted_routes[1][1]

if p_best >= T_ROUTE and (p_best - p_second) >= T_MARGIN:
    route = best_route
else:
    route = "unknown"
```

If `route == "unknown"`: do not proxy; return HTTP 404 with trace and policy
reason.

## 7. Trainer Service
<!-- TASKS: 6.7, 6.8, 6.9, 6.10, 6.11 -->

Dedicated one-shot container for retraining the model, separate from
ai-router so inference stays small and stable. The trainer runs on demand,
writes `model.joblib` to a shared volume, then exits. Prefer this over a
long-running `POST /train` API: one-shot is simpler, avoids memory leaks,
and fits the data-then-retrain loop described in Section 4.

### 7.1 Directory Structure

```text
services/trainer/
  Dockerfile
  requirements.txt
  train.py
  train.csv
```

The trainer is self-contained: training code (`train.py`) and data
(`train.csv`) live in its own directory and are included in the Docker
image at build time. No files are shared with or bind-mounted from the
ai_router service.

### 7.2 Trainer Dockerfile

Single-stage image; no runtime server, just Python with training deps.

```dockerfile
ARG PY_IMAGE=python:3.12-slim-bookworm
FROM ${PY_IMAGE}
WORKDIR /train

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY train.py .
COPY train.csv .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

CMD ["python", "train.py", \
    "--data", "./train.csv", \
    "--out", "/model/model.joblib", \
    "--metrics", "/model/metrics.json", \
    "--misclassified", "/model/misclassified.csv"]
```

`requirements.txt` for the trainer (training deps only, no FastAPI):

```text
scikit-learn==1.5.2
numpy==2.1.3
joblib==1.4.2
```

The image contains everything needed to train. At runtime it writes
artifacts (`model.joblib`, `metrics.json`, `misclassified.csv`) into
`/model` (the shared volume mount point).

### 7.3 Compose Configuration

Add to `compose/docker-compose.yaml`:

```yaml
volumes:
  model_artifacts:

services:
  trainer:
    build:
      context: ../services/trainer
      dockerfile: Dockerfile
    profiles:
      - train
    volumes:
      - model_artifacts:/model
    environment:
      <<: *common-env
    logging:
      <<: *common-logging
```

Update `ai_router` to mount the shared volume so it can load the
trainer-produced artifact:

```yaml
  ai_router:
    # ... existing config ...
    volumes:
      - model_artifacts:/model:ro
    environment:
      <<: *common-env
      MODEL_PATH: /model/model.joblib
```

Key points:

- **Profile `train`:** The trainer only runs when explicitly requested;
  it is excluded from `docker compose up` by default.
- **Named volume `model_artifacts`:** Trainer writes, ai-router reads.
  Survives container restarts; artifacts persist until the volume is
  removed.
- **Baked-in code and data:** `train.py` and `train.csv` are copied
  into the trainer image at build time. To change training data, edit
  `services/trainer/train.csv` and rebuild the trainer image.

### 7.4 Running the Trainer

**Trigger training:**

```bash
docker compose -f compose/docker-compose.yaml \
  --profile train run --rm trainer
```

The container runs `train.py`, writes three files into the
`model_artifacts` volume (`model.joblib`, `metrics.json`,
`misclassified.csv`), prints accuracy, and exits.

**Reload the model in ai-router:**

```bash
docker compose -f compose/docker-compose.yaml restart ai_router
```

ai-router re-reads `MODEL_PATH` on startup and begins serving the new
model. No image rebuild is needed; only a container restart.

### 7.5 ai-router Model Loading

At startup, ai-router loads the model from the path given by the
`MODEL_PATH` env var (default: built-in artifact from the Docker build
stage). If `MODEL_PATH` is set and the file exists, load from there;
otherwise fall back to the build-time artifact. Fail fast if neither exists.

```python
import os
import joblib

MODEL_PATH = os.getenv("MODEL_PATH", "/app/model/model.joblib")

def load_model():
    if not os.path.exists(MODEL_PATH):
        raise RuntimeError(f"Model not found: {MODEL_PATH}")
    artifact = joblib.load(MODEL_PATH)
    return artifact["vectorizer"], artifact["model"], artifact["labels"]
```

Call `load_model()` once in the FastAPI `lifespan` or module-level init.
Store the vectorizer, model, and labels in app state.

### 7.6 Optional: Hot-Reload Without Restart

For faster iteration, add a `POST /reload-model` endpoint to ai-router
instead of restarting the container. This is optional; restart is the
simplest correct approach.

```python
import threading

_model_lock = threading.Lock()

@app.post("/reload-model")
def reload_model():
    with _model_lock:
        new = joblib.load(MODEL_PATH)
        app.state.vectorizer = new["vectorizer"]
        app.state.model = new["model"]
        app.state.labels = new["labels"]
    return {"status": "reloaded", "path": MODEL_PATH}
```

Guard with a lock so in-flight `/classify` calls finish with the old model
before the swap. Do not expose this endpoint externally; it is an internal
admin action. If reload is not needed, skip this and use `restart`.

### 7.7 Full Retrain-and-Reload Workflow

Complete loop integrating Sections 4, 7.4, and 7.5:

1. Edit `services/trainer/train.csv` and rebuild the trainer image.
2. Run the trainer:

   ```bash
   docker compose -f compose/docker-compose.yaml \
     --profile train run --rm trainer
   ```

3. Inspect outputs on the shared volume (optional):

   ```bash
   docker compose -f compose/docker-compose.yaml \
     --profile train run --rm --entrypoint cat trainer /model/metrics.json
   ```

4. Reload ai-router:

   ```bash
   docker compose -f compose/docker-compose.yaml restart ai_router
   ```

5. Test with a curl request to verify the new model:

   ```bash
   curl -s -X POST http://localhost:8000/api/request \
     -H "Content-Type: application/json" \
     -d '{"text": "compare nginx ingress vs traefik"}' | python -m json.tool
   ```

6. Repeat until `metrics.json` accuracy and `misclassified.csv` errors are
   acceptable, then tune thresholds as described in Section 5.2.

### 7.8 When to Use the Trainer vs Local Training

| Scenario | Use |
| ---- | ----- |
| First build or CI/CD pipeline | Trainer service, then rebuild ai_router image |
| Iterating on `train.csv` locally | Trainer service (no rebuild) |
| Shipping a final model to production | Trainer service, then rebuild ai_router image |
| Quick experiment with hyperparams | Trainer service with CLI overrides |

The trainer produces `model.joblib` which can be used two ways:
(1) copy to `services/ai_router/model/` and rebuild the ai_router
image (artifact baked in), or (2) write to the shared volume and
restart ai_router (no rebuild). Choose based on whether you want the
artifact in the image or loaded from a volume.

## 8. Explanation Token Extraction
<!-- TASKS: 2.5 -->

**What it means:** When the model routes a request, return a short
human-readable reason such as `["kubectl", "pod", "crashloop"]`: the TF-IDF
features (tokens or n-grams) that most strongly pushed the classifier toward
the predicted label. This is deterministic "top contributing features" from
model weights, not full interpretability.

**Where:** In the **ai-router service**, inside `/classify`. The ai-router has
the vectorizer, vocabulary, LogisticRegression coefficients, and vectorized
input; the gateway should stay policy and proxy only.

**How (concept):** For LogisticRegression, per-class score is
`score_c = intercept_c + sum_j (x_j * coef_cj)`. For explanation, use
`contrib_j = x_j * coef_predicted_class_j`, then sort by contribution and map
feature indices to token strings via `vectorizer.get_feature_names_out()`;
return top N (e.g. 6).

**Drop-in helper (ai-router, `services/ai_router/app/main.py`):**

```python
from __future__ import annotations

from typing import Dict, List, Tuple
import numpy as np

def top_contributing_tokens(
    text: str,
    vectorizer,
    model,
    labels: List[str],
    top_n: int = 6,
) -> Tuple[str, float, Dict[str, float], List[str]]:
    """
    Returns:
      predicted_label, confidence, probs_map, top_tokens
    """
    X = vectorizer.transform([text])

    probs = model.predict_proba(X)[0]
    pred_idx = int(np.argmax(probs))
    pred_label = labels[pred_idx]
    confidence = float(probs[pred_idx])
    probs_map = {labels[i]: float(probs[i]) for i in range(len(labels))}

    feature_names = vectorizer.get_feature_names_out()
    class_coef = model.coef_[pred_idx]

    indices = X.indices
    values = X.data

    if indices.size == 0:
        return pred_label, confidence, probs_map, []

    contrib = values * class_coef[indices]
    order = np.argsort(contrib)[::-1]

    top_tokens: List[str] = []
    for i in order[:top_n]:
        top_tokens.append(str(feature_names[indices[i]]))

    return pred_label, confidence, probs_map, top_tokens
```

Call this in `/classify` and return probabilities, explanation tokens, and
optionally a short explanation string. With bigrams (`ngram_range=(1,2)`),
tokens may be phrases like `"crashloop backoff"`. Add the result to trace
metadata (e.g. `meta: {route, confidence, top_tokens}`) and show in the UI.

## 9. Recommended Starting Policy and Cross-Reference
<!-- TASKS: 4.3, 8.1 -->

**Starting values:** `T_route = 0.60`, `T_margin = 0.10`. Confident →
route to backend; not confident or ambiguous → `unknown` → 404.

**Alignment with TASKS.md:**

- **Batch 2 (AI router):** train.csv format and labels (Section 2), train.py
  and commands (Section 2), model.joblib and metrics (Section 3), build-time
  artifact and ai-router `/classify` with route, confidence, explanation
  (Sections 3.1, 6, 8).
- **Batch 4 (Gateway):** Threshold and margin in gateway (Section 6), env
  vars, policy logic, 404 for unknown, trace and timings (Section 6).
- **Batch 6/7:** Trainer service Dockerfile, Compose config, shared volume,
  retrain-and-reload workflow, hot-reload option (Section 7).

Training code and artifact format are correct; threshold and explanation logic
must be implemented in gateway and ai-router respectively as described above.

## 10. Service Communication
<!-- TASKS: 4.2, 4.4 -->

### 10.1 Internal HTTP Client

The gateway makes async HTTP calls to ai-router and backends using
`httpx.AsyncClient`. Add `httpx` to the gateway `requirements.txt`:

```text
httpx>=0.27.0
```

Create a single `AsyncClient` in the FastAPI `lifespan` so connections
are pooled and the client is cleaned up on shutdown:

```python
from contextlib import asynccontextmanager
import httpx

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=0,
        ),
    )
    yield
    await app.state.http.aclose()

app = FastAPI(lifespan=lifespan)
```

Setting `max_keepalive_connections=0` forces fresh DNS resolution per
request, which is needed for round-robin distribution across scaled
replicas (Section 18). If latency matters more than even distribution,
keep the default and accept slightly uneven load.

### 10.2 Service URL Resolution

Inside Compose, services resolve by name on the default bridge network.
The gateway reads backend URLs from environment variables with defaults
matching Compose service names:

```python
import os

AI_ROUTER_URL = os.getenv("AI_ROUTER_URL", "http://ai_router:8000")
ROUTE_MAP = {
    "search": os.getenv(
        "SEARCH_SERVICE_URL", "http://search_service:8000"
    ),
    "image": os.getenv(
        "IMAGE_SERVICE_URL", "http://image_service:8000"
    ),
    "ops": os.getenv(
        "OPS_SERVICE_URL", "http://ops_service:8000"
    ),
}
```

Labels from the model (`search`, `image`, `ops`) map directly to these
keys. If a label is not in `ROUTE_MAP` or is `unknown`, the gateway
does not proxy.

### 10.3 Timeout Configuration

Read `REQUEST_TIMEOUT` from the environment (set by `x-common-env` in
Compose). Use it to configure the `httpx` client timeout. The default
is 30 seconds:

```python
TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "30"))
```

## 11. Request ID and Trace Protocol
<!-- TASKS: 3.1, 3.5, 4.1, 4.5 -->

### 11.1 Request ID Generation and Propagation

The gateway generates a UUID v4 if the client does not supply one.
Propagate it to downstream services via both the JSON body
(`request_id` field) and the `X-Request-ID` HTTP header:

```python
import uuid

def ensure_request_id(body: dict) -> str:
    return body.get("request_id") or str(uuid.uuid4())
```

### 11.2 Trace Entry Schema

**Authoritative schema:** Each trace entry has `service` (string),
`event` (string), `ts` (ISO 8601 datetime string, UTC), and optional
`meta` (object). Every service appends exactly one trace entry per
request. Use a shared Pydantic model so all services produce consistent
structure:

```python
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel

class TraceEntry(BaseModel):
    service: str
    event: str
    ts: str
    meta: Optional[Dict[str, Any]] = None

def make_trace_entry(
    service: str,
    event: str,
    meta: Optional[Dict[str, Any]] = None,
) -> TraceEntry:
    return TraceEntry(
        service=service,
        event=event,
        ts=datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        ),
        meta=meta,
    )
```

This helper can live in a shared utility module or be duplicated in
each service (it is small enough that duplication is acceptable for
a project with no shared library).

### 11.3 Trace Aggregation

The gateway builds the trace array by collecting `trace_append` entries
from each downstream call and merging them with its own entries:

1. **Client trace** (optional): if the request body includes a `trace`
   array (e.g. the web UI sends `{service: "web", event: "submit"}`),
   start from that array.
2. **Gateway received**: append when `/api/request` handler begins.
3. **AI router classified**: append `trace_append` from the `/classify`
   response.
4. **Backend handled**: append `trace_append` from the `/handle`
   response (only if a backend is called).
5. **Gateway responded**: append just before returning the final
   response.

### 11.4 Timing Capture

Wrap each outbound HTTP call in a timer:

```python
import time

async def timed_post(client, url, json_body, headers):
    t0 = time.monotonic()
    resp = await client.post(url, json=json_body, headers=headers)
    elapsed_ms = round((time.monotonic() - t0) * 1000)
    return resp, elapsed_ms
```

The gateway returns three timing values in `timings_ms`:

- `classify`: wall-clock time for the ai-router `/classify` call.
- `proxy`: wall-clock time for the backend `/handle` call (0 if route
  is unknown).
- `total`: wall-clock from gateway receipt to response.

## 12. AI Router `/classify` Endpoint
<!-- TASKS: 2.4, 2.5 -->

Wire the `top_contributing_tokens` helper from Section 8 into a FastAPI
endpoint. The ai-router loads the model once at startup and uses it
for every request.

### 12.1 Pydantic Models

```python
from pydantic import BaseModel
from typing import Any, Dict, List

class ClassifyRequest(BaseModel):
    request_id: str
    text: str

class ClassifyResponse(BaseModel):
    route: str
    confidence: float
    probabilities: Dict[str, float]
    explanation: str
    top_tokens: List[str]
    trace_append: Dict[str, Any]
```

### 12.2 Startup Model Loading

Use the `load_model()` function from Section 7.5 in the FastAPI
lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    vec, mdl, labels = load_model()
    app.state.vectorizer = vec
    app.state.model = mdl
    app.state.labels = labels
    yield

app = FastAPI(title="AI Router", lifespan=lifespan)
```

### 12.3 Endpoint Implementation

```python
@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest):
    pred_label, confidence, probs_map, tokens = (
        top_contributing_tokens(
            req.text,
            app.state.vectorizer,
            app.state.model,
            app.state.labels,
            top_n=6,
        )
    )

    explanation = (
        f"top tokens: {', '.join(tokens)}" if tokens else ""
    )

    trace = make_trace_entry(
        service="ai-router",
        event="classified",
        meta={
            "route": pred_label,
            "confidence": round(confidence, 4),
        },
    )

    return ClassifyResponse(
        route=pred_label,
        confidence=round(confidence, 4),
        probabilities={
            k: round(v, 4) for k, v in probs_map.items()
        },
        explanation=explanation,
        top_tokens=tokens,
        trace_append=trace.model_dump(),
    )
```

The response includes the full probability distribution so the gateway
can apply its own threshold and margin policy (Section 6) without
the ai-router making routing decisions.

## 13. Backend Services `/handle` Pattern
<!-- TASKS: 1.5, 3.2, 3.3, 3.4 -->

All three backends (search, image, ops) share the same endpoint
contract. Each returns a service-specific simulated payload and a
single trace entry.

### 13.1 Shared Request and Response Models

```python
from pydantic import BaseModel
from typing import Any, Dict

class HandleRequest(BaseModel):
    request_id: str
    text: str

class HandleResponse(BaseModel):
    payload: Dict[str, Any]
    trace_append: Dict[str, Any]
```

### 13.2 Endpoint Pattern

All three backends follow the same structure. Example for
`search_service`:

```python
import socket

@app.post("/handle", response_model=HandleResponse)
async def handle(req: HandleRequest):
    payload = {
        "service": "search-service",
        "result": f"Search results for: {req.text}",
        "instance": socket.gethostname(),
    }

    trace = make_trace_entry(
        service="search-service",
        event="handled",
        meta={
            "status": 200,
            "instance": socket.gethostname(),
        },
    )

    return HandleResponse(
        payload=payload,
        trace_append=trace.model_dump(),
    )
```

### 13.3 Per-Service Response Variations

Each backend varies the `service` name and `result` content:

- **search_service**: returns mock lookup/research response. Payload
  includes a summary string and optionally a list of mock result
  titles.
- **image_service**: returns mock image processing metadata (e.g.
  detected labels, dimensions, format).
- **ops_service**: returns mock troubleshooting steps or diagnostic
  output (e.g. a list of suggested commands or status checks).

Include `socket.gethostname()` in both the payload and trace so
scaled replicas are distinguishable in the trace visualization
(the hostname is the container ID prefix in Docker).

## 14. Gateway Service
<!-- TASKS: 1.3, 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 5.7 -->

### 14.1 Dependencies

Gateway `requirements.txt`:

```text
fastapi>=0.109.0
gunicorn>=21.0.0
uvicorn[standard]>=0.27.0
httpx>=0.27.0
```

### 14.2 Pydantic Models

```python
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class ApiRequest(BaseModel):
    request_id: Optional[str] = None
    text: str
    trace: Optional[List[Dict[str, Any]]] = None

class ApiResponse(BaseModel):
    request_id: str
    route: str
    confidence: float
    explanation: str
    trace: List[Dict[str, Any]]
    backend_response: Optional[Dict[str, Any]] = None
    timings_ms: Dict[str, int]

class UnknownResponse(BaseModel):
    request_id: str
    route: str
    confidence: float
    message: str
    trace: List[Dict[str, Any]]
```

### 14.3 `/api/request` Implementation

Core orchestration logic (pseudocode-level; see Sections 10-11 for
helpers):

```python
from fastapi.responses import JSONResponse

@app.post("/api/request")
async def api_request(req: ApiRequest):
    request_id = req.request_id or str(uuid.uuid4())
    trace: List[Dict] = list(req.trace or [])
    t_start = time.monotonic()
    http = app.state.http
    headers = {"X-Request-ID": request_id}

    trace.append(
        make_trace_entry("gateway", "received").model_dump()
    )

    # 1. Classify
    classify_body = {
        "request_id": request_id,
        "text": req.text,
    }
    classify_resp, classify_ms = await timed_post(
        http, f"{AI_ROUTER_URL}/classify",
        classify_body, headers,
    )
    classify_resp.raise_for_status()
    cdata = classify_resp.json()
    trace.append(cdata["trace_append"])

    route = cdata["route"]
    confidence = cdata["confidence"]
    probabilities = cdata.get("probabilities", {})
    explanation = cdata.get("explanation", "")

    # 2. Apply routing policy (Section 6)
    effective_route = _apply_policy(route, probabilities)

    # 3a. Unknown - return 404 without proxy
    if effective_route == "unknown":
        trace.append(make_trace_entry(
            "gateway", "responded",
            meta={"status": 404},
        ).model_dump())
        total_ms = round(
            (time.monotonic() - t_start) * 1000
        )
        return JSONResponse(
            status_code=404,
            content=UnknownResponse(
                request_id=request_id,
                route="unknown",
                confidence=confidence,
                message=(
                    "Unable to determine a suitable backend"
                    " for this request"
                ),
                trace=trace,
            ).model_dump(),
        )

    # 3b. Proxy to backend
    backend_url = ROUTE_MAP[effective_route]
    handle_body = {
        "request_id": request_id,
        "text": req.text,
    }
    handle_resp, proxy_ms = await timed_post(
        http, f"{backend_url}/handle",
        handle_body, headers,
    )
    handle_resp.raise_for_status()
    hdata = handle_resp.json()
    trace.append(hdata["trace_append"])
    backend_response = hdata.get("payload")

    trace.append(make_trace_entry(
        "gateway", "responded",
        meta={"status": 200},
    ).model_dump())
    total_ms = round(
        (time.monotonic() - t_start) * 1000
    )

    return ApiResponse(
        request_id=request_id,
        route=effective_route,
        confidence=confidence,
        explanation=explanation,
        trace=trace,
        backend_response=backend_response,
        timings_ms={
            "classify": classify_ms,
            "proxy": proxy_ms,
            "total": total_ms,
        },
    )
```

### 14.4 Routing Policy Helper

Combines threshold and margin logic from Section 6 into a single
function called inside `/api/request`:

```python
def _apply_policy(
    raw_route: str,
    probabilities: Dict[str, float],
) -> str:
    if raw_route == "unknown":
        return "unknown"

    non_unknown = {
        k: v for k, v in probabilities.items()
        if k != "unknown"
    }
    if not non_unknown:
        return "unknown"

    sorted_routes = sorted(
        non_unknown.items(),
        key=lambda x: x[1],
        reverse=True,
    )
    best_route, p_best = sorted_routes[0]
    p_second = (
        sorted_routes[1][1] if len(sorted_routes) > 1 else 0.0
    )

    if p_best < T_ROUTE:
        return "unknown"
    if (p_best - p_second) < T_MARGIN:
        return "unknown"

    return best_route
```

### 14.5 Static UI Serving

Serve the web UI from the gateway using FastAPI's `StaticFiles` and a
`FileResponse` for the root path:

```python
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)

@app.get("/")
async def root():
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html")
    )
```

Static files live in `services/gateway/app/static/`:

```text
services/gateway/app/static/
  index.html
  app.js
  styles.css
```

Mount `/static` before defining API routes so asset requests
(`/static/app.js`, `/static/styles.css`) are served directly.
The `GET /` route returns `index.html` which loads the JS and CSS
from `/static/`.

### 14.6 `/routes` Endpoint

Returns the mapping of route labels to backend URLs so the UI or
operators can inspect available routes:

```python
@app.get("/routes")
async def routes():
    return {
        "routes": [
            {"label": k, "backend_url": v}
            for k, v in ROUTE_MAP.items()
        ]
    }
```

## 15. AI Router Dockerfile
<!-- TASKS: 2.3, 2.4, 6.2, 6.3 -->

The ai_router Dockerfile is a standard two-stage build. It copies a
pre-built `model.joblib` from the build context; training is handled
separately by the trainer service (Section 7).

```dockerfile
ARG PY_IMAGE=python:3.12-slim-bookworm

# Stage 1: Build wheels
FROM ${PY_IMAGE} AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir -r requirements.txt -w /wheels

# Stage 2: Runtime
FROM ${PY_IMAGE} AS runtime
ENV DEBIAN_FRONTEND=noninteractive

RUN groupadd -r appgroup \
    && useradd -r -g appgroup -m -d /home/appuser \
       -s /usr/sbin/nologin appuser

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index \
    --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

COPY model/model.joblib ./model/

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY --chown=appuser:appgroup app/ ./app/

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s \
    --start-period=5s --retries=3 \
    CMD python -c \
    "import sys,urllib.request; \
     urllib.request.urlopen( \
       'http://127.0.0.1:8000/health', timeout=2 \
     ); sys.exit(0)"

CMD ["gunicorn", "app.main:app", \
    "--bind", "0.0.0.0:8000", \
    "--workers", "2", \
    "--worker-class", "uvicorn.workers.UvicornWorker", \
    "--access-logfile", "-", \
    "--error-logfile", "-"]
```

`COPY model/model.joblib ./model/` copies the pre-built artifact into
the runtime image at `/app/model/model.joblib`. When the trainer
service is used instead (Section 7), the `MODEL_PATH` env var
overrides this path.

## 16. Docker Compose: Dependencies and Dev Overlay
<!-- TASKS: 1.2, 1.6, 6.4, 6.5 -->

### 16.1 Service Dependencies

Add `depends_on` to the gateway so it waits for healthy downstreams
before accepting traffic:

```yaml
services:
  gateway:
    depends_on:
      ai_router:
        condition: service_healthy
      search_service:
        condition: service_healthy
      image_service:
        condition: service_healthy
      ops_service:
        condition: service_healthy
    environment:
      <<: *common-env
      AI_ROUTER_URL: "http://ai_router:8000"
      SEARCH_SERVICE_URL: "http://search_service:8000"
      IMAGE_SERVICE_URL: "http://image_service:8000"
      OPS_SERVICE_URL: "http://ops_service:8000"
      T_ROUTE: "0.60"
      T_MARGIN: "0.10"
```

Service URL env vars are not strictly required (the defaults in code
match Compose service names), but making them explicit aids clarity
and allows overriding in non-Compose environments.

### 16.2 Dev Overlay

`compose/docker-compose.dev.yaml` overrides the CMD for hot reload
and adds bind mounts so source changes take effect without rebuilding:

```yaml
services:
  gateway:
    volumes:
      - ../services/gateway/app:/app/app:ro
    command:
      - uvicorn
      - app.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload
    user: root

  ai_router:
    volumes:
      - ../services/ai_router/app:/app/app:ro
    command:
      - uvicorn
      - app.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload
    user: root

  search_service:
    volumes:
      - ../services/search_service/app:/app/app:ro
    command:
      - uvicorn
      - app.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload
    user: root

  image_service:
    volumes:
      - ../services/image_service/app:/app/app:ro
    command:
      - uvicorn
      - app.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload
    user: root

  ops_service:
    volumes:
      - ../services/ops_service/app:/app/app:ro
    command:
      - uvicorn
      - app.main:app
      - --host
      - "0.0.0.0"
      - --port
      - "8000"
      - --reload
    user: root
```

Launch with dev overlay:

```bash
docker compose \
  -f compose/docker-compose.yaml \
  -f compose/docker-compose.dev.yaml up --build
```

The `user: root` override is needed because bind mounts may have
different ownership than the `appuser` created in the Dockerfile.
uvicorn `--reload` watches for file changes and restarts the worker.

## 17. Web UI
<!-- TASKS: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7 -->

### 17.1 File Structure

Three static files in `services/gateway/app/static/`:

- `index.html` - page layout, input form, result display areas.
- `app.js` - fetch logic, trace rendering, hop diagram.
- `styles.css` - layout and visual theme.

### 17.2 Core JavaScript

The UI generates a `request_id`, sends the request, and renders the
response:

```javascript
async function submitRequest(text) {
  const requestId = crypto.randomUUID();
  const body = {
    request_id: requestId,
    text: text,
    trace: [{
      service: "web",
      event: "submit",
      ts: new Date().toISOString(),
    }],
  };

  const resp = await fetch("/api/request", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  const data = await resp.json();
  renderResult(data, resp.status);
}
```

Handle both 200 (successful route) and 404 (unknown) responses. The
JSON body is present in both cases; the 404 body uses the
`UnknownResponse` schema (Section 14.2).

### 17.3 Rendering Components

Display sections (see PROJECT_PLAN Section 7.1 for requirements):

- **Route card**: route label, confidence bar (0.0 - 1.0), explanation
  tokens as tags or inline text.
- **Trace timeline**: ordered list of trace entries with service name,
  event, timestamp, and metadata. Highlight the active hop.
- **Hop diagram**: text or SVG rendering of the service chain, e.g.
  `web -> gateway -> ai-router -> gateway -> ops-service -> gateway`.
  Build from the `trace` array by extracting service names in order.
- **Backend response**: formatted JSON payload (hidden when route is
  unknown).
- **Timings**: classify, proxy, and total in milliseconds.
- **Unknown handling**: when `route == "unknown"` or HTTP 404, show the
  `message` field, hide backend payload, and indicate no backend hop in
  the diagram.

## 18. Scaling and DNS Round-Robin
<!-- TASKS: 6.6, 7.2 -->

### 18.1 How It Works

When a backend is scaled with `docker compose up --scale
search_service=3`, Compose registers multiple container IPs under the
same DNS name (`search_service`). Docker's embedded DNS resolves the
name to all IPs in round-robin order, so
`httpx.AsyncClient.post("http://search_service:8000/handle", ...)`
distributes requests across replicas automatically.

No gateway-side load balancing logic is required.

### 18.2 Identifying Replicas in Traces

Each backend includes `socket.gethostname()` in its trace entry and
payload (Section 13.2). In a scaled deployment, each container gets a
unique hostname (the container ID prefix), making it visible in the
trace which replica handled the request.

### 18.3 Scaling Command

```bash
docker compose -f compose/docker-compose.yaml \
  up -d --scale search_service=3
```

Then send multiple requests and observe the `instance` field in traces
cycling through different container hostnames.

## 19. Error Handling: Unknown vs Backend Failure
<!-- TASKS: 4.3, 8.2, 8.4, 8.5 -->

The gateway produces two distinct error responses. The trace shape
and HTTP status differ so the UI can distinguish them.

### 19.1 Unknown Classification (AI Decision)

- **Cause**: model returns `unknown`, or confidence below `T_ROUTE`,
  or margin below `T_MARGIN`.
- **Gateway behavior**: does not proxy to any backend.
- **HTTP status**: 404.
- **Trace shape**: gateway-received, ai-router-classified,
  gateway-responded. No backend hop.
- **Response body**: `UnknownResponse` (Section 14.2) with `message`.

### 19.2 Backend Failure (Infrastructure)

- **Cause**: ai-router classifies to a known route, but the backend
  is down, unreachable, or times out.
- **Gateway behavior**: catches the proxy error.
- **HTTP status**: 502.
- **Trace shape**: gateway-received, ai-router-classified,
  gateway-responded with `meta.error` and `meta.status: 502`. No
  backend-handled entry.
- **Response body**: includes `route` (the intended backend), the
  classification trace, and an error message about unavailability.

Implementation in the proxy section of `/api/request`:

```python
try:
    handle_resp, proxy_ms = await timed_post(
        http, f"{backend_url}/handle",
        handle_body, headers,
    )
    handle_resp.raise_for_status()
except (
    httpx.ConnectError,
    httpx.TimeoutException,
) as exc:
    trace.append(make_trace_entry(
        "gateway", "responded",
        meta={"status": 502, "error": str(exc)},
    ).model_dump())
    total_ms = round(
        (time.monotonic() - t_start) * 1000
    )
    return JSONResponse(
        status_code=502,
        content={
            "request_id": request_id,
            "route": effective_route,
            "confidence": confidence,
            "message": (
                f"Backend {effective_route} unavailable"
            ),
            "trace": trace,
            "timings_ms": {
                "classify": classify_ms,
                "proxy": proxy_ms,
                "total": total_ms,
            },
        },
    )
```

### 19.3 AI Router Failure

If the ai-router itself is unreachable, the gateway cannot classify
and should return HTTP 503:

```python
try:
    classify_resp, classify_ms = await timed_post(
        http, f"{AI_ROUTER_URL}/classify",
        classify_body, headers,
    )
    classify_resp.raise_for_status()
except (
    httpx.ConnectError,
    httpx.TimeoutException,
) as exc:
    trace.append(make_trace_entry(
        "gateway", "responded",
        meta={
            "status": 503,
            "error": "AI router unavailable",
        },
    ).model_dump())
    return JSONResponse(
        status_code=503,
        content={
            "request_id": request_id,
            "route": None,
            "message": (
                "Classification service unavailable"
            ),
            "trace": trace,
        },
    )
```

### 19.4 Summary Table

| Scenario | HTTP | Trace backend hop | Cause |
| ---- | ---- | ---- | ---- |
| Unknown classification | 404 | None | AI decision |
| Low confidence / low margin | 404 | None | Policy decision |
| Backend unreachable | 502 | None (attempted) | Infrastructure |
| AI router unreachable | 503 | None | Infrastructure |
| Successful route | 200 | Yes | Normal flow |

## 20. Structured Logging
<!-- TASKS: 8.3 -->

### 20.1 Logger Configuration

Use Python `logging` with JSON-structured output so Docker log drivers
can parse fields. A minimal config shared across services:

```python
import json
import logging
import sys

class JsonFormatter(logging.Formatter):
    def format(self, record):
        obj = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "service": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            obj["request_id"] = record.request_id
        return json.dumps(obj)

def setup_logging(
    service_name: str, level: str = "INFO",
):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(service_name)
    logger.setLevel(
        getattr(logging, level.upper(), logging.INFO)
    )
    logger.addHandler(handler)
    return logger
```

### 20.2 Usage in Endpoints

Pass `request_id` as an extra field so it appears in every log line:

```python
logger = setup_logging("gateway")

logger.info(
    "classify route=%s confidence=%.4f",
    route,
    confidence,
    extra={"request_id": request_id},
)
```

Read `LOG_LEVEL` from the environment (set via `x-common-env` in
Compose) to control verbosity at runtime without code changes.

### 20.3 Log Correlation

Every service logs `request_id` on every significant action (request
received, classification done, handle processed, response sent). To
follow a single request through the system:

```bash
docker compose logs -f | grep "request_id.*c7a8"
```

This gives the same end-to-end visibility as the in-response trace,
but via log aggregation rather than the API response.

## 21. Cross-Reference: Sections to Tasks

<!-- This section provides bidirectional mappings between TECHNICAL.md
     sections and TASKS.md task IDs. Use 21.1 to find which tasks a
     section implements; use 21.2 to find which sections to read for
     a given task. -->

### 21.1 Section to Tasks

| Section | Tasks | What to implement |
| ---- | ---- | ---- |
| 1 (Dependencies) | 1.4, 2.2 | ai-router pip packages |
| 2 (Training Data) | 2.1, 2.2 | train.csv format, labels, training commands |
| 3 (Training Outputs) | 2.2, 2.3, 2.4 | model.joblib, metrics.json, misclassified.csv |
| 4 (Iteration Cycle) | 6.11 | Data, retrain, evaluate, policy loop |
| 5 (Threshold and Margin) | 4.3, 8.6 | T_ROUTE, T_MARGIN, two tuning loops |
| 6 (Threshold Implementation) | 4.3 | Gateway policy logic, env vars, pseudocode |
| 7 (Trainer Service) | 6.7-6.11 | Dockerfile, Compose, volume, model loading, workflow |
| 8 (Explanation Tokens) | 2.5 | top_contributing_tokens helper |
| 9 (Starting Policy) | 4.3, 8.1 | Default thresholds, policy alignment |
| 10 (Service Communication) | 4.2, 4.4 | httpx client, service URLs, timeout |
| 11 (Request ID and Trace) | 3.1, 3.5, 4.1, 4.5 | UUID generation, TraceEntry, aggregation, timings |
| 12 (AI Router /classify) | 2.4, 2.5 | Pydantic models, startup loading, endpoint |
| 13 (Backend /handle) | 1.5, 3.2, 3.3, 3.4 | HandleRequest/Response, per-service payload |
| 14 (Gateway Service) | 1.3, 4.1-4.6, 5.7 | Dependencies, /api/request, policy, static UI, /routes |
| 15 (AI Router Dockerfile) | 2.3, 2.4, 6.2, 6.3 | Two-stage build, pre-built model |
| 16 (Compose: deps, dev) | 1.2, 1.6, 6.4, 6.5 | Anchors, depends_on, env vars, dev overlay |
| 17 (Web UI) | 5.1-5.7 | HTML/JS/CSS, fetch, rendering, unknown handling |
| 18 (Scaling) | 6.6, 7.2 | DNS round-robin, hostname in trace, scaling cmd |
| 19 (Error Handling) | 4.3, 8.2, 8.4, 8.5 | Unknown vs failure, 502/503 paths |
| 20 (Structured Logging) | 8.3 | JsonFormatter, request_id in logs, correlation |

### 21.2 Task to Sections

| Task | Sections to read | Summary |
| ---- | ---- | ---- |
| 1.2 | 16 | Compose anchors and structure |
| 1.3 | 14.1 | Gateway dependencies |
| 1.4 | 1, 12 | AI router dependencies and endpoint shape |
| 1.5 | 13 | Backend service pattern |
| 1.6 | 16.1 | Compose service definitions |
| 2.1 | 2 | Training data format, labels, balance |
| 2.2 | 1, 2, 3 | Dependencies, training commands, output artifacts |
| 2.3 | 15 | AI router Dockerfile with pre-built model |
| 2.4 | 7.5, 12.2, 15 | Model loading, lifespan init, Dockerfile runtime |
| 2.5 | 8, 12 | Explanation tokens, /classify endpoint and models |
| 3.1 | 11.2 | TraceEntry schema and helper |
| 3.2 | 13 | search_service /handle pattern |
| 3.3 | 13 | image_service /handle pattern |
| 3.4 | 13 | ops_service /handle pattern |
| 3.5 | 11.1 | Request ID generation and propagation |
| 4.1 | 11.1 | UUID generation, X-Request-ID header |
| 4.2 | 10, 14.3 | httpx client, /classify call, response parsing |
| 4.3 | 5, 6, 9, 14.4, 19.1 | Thresholds, policy logic, unknown 404 |
| 4.4 | 10.2, 14.3 | Service URL resolution, proxy to backend |
| 4.5 | 11.3, 11.4, 14.3 | Trace aggregation, timing capture |
| 4.6 | 14.6 | /routes endpoint |
| 5.1 | 17.1, 17.2 | File structure, JS fetch logic |
| 5.2 | 17.3 | Route card rendering |
| 5.3 | 17.3 | Trace timeline rendering |
| 5.4 | 17.3 | Hop diagram rendering |
| 5.5 | 17.3 | Backend response and timings display |
| 5.6 | 17.3, 19.1 | Unknown route handling in UI |
| 5.7 | 14.5, 17.1 | Static file serving, file structure |
| 6.1 | 14.1 | Gateway Dockerfile pattern |
| 6.2 | 15 (pattern) | Backend Dockerfile (same pattern as ai-router) |
| 6.3 | 15 | AI router Dockerfile production CMD |
| 6.4 | 16.2 | Dev overlay with hot reload |
| 6.5 | 16.1 | depends_on with service_healthy |
| 6.6 | 18 | Scaling, DNS round-robin |
| 6.7 | 7.1, 7.2 | Trainer directory and Dockerfile |
| 6.8 | 7.3 | Trainer Compose config with profile |
| 6.9 | 7.3 | Named volume model_artifacts |
| 6.10 | 7.5 | MODEL_PATH env var and fallback loading |
| 6.11 | 4, 7.4, 7.7 | Full retrain-and-reload workflow |
| 7.2 | 18.3 | Scaling command for load test |
| 8.1 | 9 | Starting policy and expected routes |
| 8.2 | 19.1 | Unknown classification trace shape |
| 8.3 | 20.3 | Log correlation by request_id |
| 8.4 | 19.2, 19.3 | Backend and AI router failure handling |
| 8.5 | 19.4 | Error scenario summary table |
| 8.6 | 5.2, 6 | Margin tuning and threshold implementation |
