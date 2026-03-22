# DEBUG RUNBOOK

This runbook contains copy-paste commands to debug and validate every stage
of the pipeline:

- `train`
- `refine` (split into `relabel` + `augment`)
- `relabel` only
- `augment` only
- `promote`

## Common Setup

Run from the repo root.

```bash
cd "$(git rev-parse --show-toplevel)"

COMPOSE_FILE="compose/docker-compose.yaml"
GATEWAY_URL="http://localhost:8000"
```

## Start and Stop the Stack

Start with the Refine profile (includes `training-api`, `redis`, and `refiner`).

```bash
CONFIG_ENV=dev ./scripts/demo.sh run
```

Stop containers (keeps volumes).

```bash
./scripts/demo.sh stop
```

Restart the stack (stop + start, accepts `--dev` and `--scale N`).

```bash
./scripts/demo.sh restart
```

Delete everything (containers, networks, volumes).

```bash
./scripts/demo.sh delete
```

Full teardown and rebuild (stop + delete + start,
accepts same flags as `run`).

```bash
./scripts/demo.sh reset
```

## Sanity Checks

Health endpoint.

```bash
curl -s "$GATEWAY_URL/health" | python3 -m json.tool
```

Route map (shows backend URLs).

```bash
curl -s "$GATEWAY_URL/routes" | python3 -m json.tool
```

Tail logs (add any service names you need).

```bash
docker compose -f "$COMPOSE_FILE" logs -f gateway ai_router training-api refiner trainer redis ollama
```

## Inspect Model Artifacts (Most Important)

These paths live on the shared `model_artifacts` volume, mounted at `/model`
inside the `training-api` container.

List top-level artifact dirs.

```bash
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc '
ls -la /model
ls -la /model/refine_runs 2>/dev/null || true
'
```

List latest relabel/augment runs.

```bash
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc '
ls -1 /model/refine_runs 2>/dev/null | tail -n 20 || true
'
```

## Train (Intent Router Model)

### Option A: CLI

```bash
./scripts/demo.sh train
```

### Option B: API (Gateway)

Create job.

```bash
curl -s -X POST "$GATEWAY_URL/api/train" | python3 -m json.tool
```

Let `JOB_ID` be the returned `job_id`.

Check status until completed.

```bash
JOB_ID="PASTE_JOB_ID"
curl -s "$GATEWAY_URL/api/train/status/$JOB_ID" | python3 -m json.tool
```

Stream progress events.

```bash
JOB_ID="PASTE_JOB_ID"
curl -sN "$GATEWAY_URL/api/train/events/$JOB_ID"
```

Fetch last successful train result (from the shared artifacts volume).

```bash
curl -s "$GATEWAY_URL/api/train/last" | python3 -m json.tool
```

### Verify Artifacts

```bash
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc '
echo "--- /model/metrics.json ---"
cat /model/metrics.json

echo "--- /model/misclassified.csv (head) ---"
if [ -f /model/misclassified.csv ]; then
  head -n 15 /model/misclassified.csv
else
  echo "misclassified.csv missing"
fi
'
```

## Capturing JOB_ID and RUN_ID

Many relabel and augment failures look the same at the UI level (for example,
identical before/after metrics). The fastest path to the correct artifacts
is to capture `JOB_ID`/`RUN_ID` from the API responses and then map them to
the `refine_runs/<run_id>/...` files.

### Expected JSON fields by endpoint

Train:

- `POST /api/train` returns: `{"job_id": "<uuid>"}`.
- `GET /api/train/status/{job_id}` returns:
  `{"job_id": "<uuid>", "status": "...", "result": {...}, "error": "..."}`
  (some keys may be `null`/missing depending on state).
- `GET /api/train/last` returns the last model artifacts summary (includes
  metrics and `misclassified` if present).

Relabel:

- `POST /api/refine/relabel` returns: `{"job_id": "<uuid>", "run_id": "<uuid>"}`.
- `GET /api/refine/relabel/events/{job_id}` is an SSE stream.
  - Progress events look like: `{"status":"progress","detail":"...","phase":"relabel",...}`
    (exact fields can vary).
  - Completion event looks like:
    `{"status":"completed","result":{...}}` or `{"status":"failed","error":"..."}`.
  - Final `result` (from the relabel phase) includes keys:
    `run_id`, `batches`, `train_relabel_candidate_rows`, `metrics_before`,
    `metrics_after`, `proposed_relabels`.

Augment:

- `POST /api/refine/augment` returns: `{"job_id": "<uuid>", "run_id": "<uuid>"}`.
- `GET /api/refine/augment/events/{job_id}` is an SSE stream.
  - Completion event looks like: `{"status":"completed","result":{...}}`.
  - Final `result` includes keys:
    `run_id`, `labels`, `train_augment_candidate_rows`, `metrics_before`,
    `metrics_after`, `proposed_examples`, and often `label_counts` (per-label
    synthetic row targets for the run).

Promote:

- `POST /api/refine/promote` returns at least:
  `{"promoted": true|false, "message": "...",`
  `"acc_before": <float>, "acc_after": <float>,`
  `"promote_accuracy_tolerance": <float>,`
  `"used_tolerance": <bool>,`
  `"per_label_recall": {"<label>": {"recall_before", "recall_after", "delta"}}}`
  (exact shape can vary on errors; tolerance fields support debugging).

### Relabel: API start response

```bash
RESP="$(curl -s -X POST "$GATEWAY_URL/api/refine/relabel" \
  -H "Content-Type: application/json" \
  -d '{}' )"

echo "$RESP" | python3 -m json.tool

JOB_ID="$(echo "$RESP" | python3 - <<'PY'
import sys, json
d=json.load(sys.stdin)
print(d.get("job_id",""))
PY
)"

RUN_ID="$(echo "$RESP" | python3 - <<'PY'
import sys, json
d=json.load(sys.stdin)
print(d.get("run_id",""))
PY
)"

echo "JOB_ID=$JOB_ID"
echo "RUN_ID=$RUN_ID"
```

If `RUN_ID` is missing or empty, use the Redis job-state commands in the
`Redis Job Debugging` section at the end of this runbook.

### Relabel: stream events (job completion only)

```bash
JOB_ID="PASTE_JOB_ID"

curl -sN "$GATEWAY_URL/api/refine/relabel/events/$JOB_ID"
```

### Augment: API start response

```bash
RESP="$(curl -s -X POST "$GATEWAY_URL/api/refine/augment" \
  -H "Content-Type: application/json" \
  -d '{}' )"

echo "$RESP" | python3 -m json.tool

JOB_ID="$(echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("job_id",""))' <<<"$RESP")"
RUN_ID="$(echo "$RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("run_id",""))' <<<"$RESP")"

echo "JOB_ID=$JOB_ID"
echo "RUN_ID=$RUN_ID"
```

### Artifact correlation: where "before" and "after" live

These are the canonical paths used by the relabel and augment phases.

Relabel:

```bash
RUN_ID="PASTE_RUN_ID"
BEFORE="/model/refine_runs/$RUN_ID/metrics_before.json"
AFTER="/model/refine_runs/$RUN_ID/relabel/metrics_relabel_candidate.json"
echo "$BEFORE"
echo "$AFTER"
```

Augment:

```bash
RUN_ID="PASTE_RUN_ID"
BEFORE="/model/refine_runs/$RUN_ID/metrics_before.json"
AFTER="/model/refine_runs/$RUN_ID/augment/metrics_augment_candidate.json"
echo "$BEFORE"
echo "$AFTER"
```

### Optional: extract RUN_ID from the SSE stream (robust)

If you only have `JOB_ID` and the SSE parsing is brittle in your terminal,
use this regex-based approach to pull the first UUID-like run id from the
stream.

```bash
JOB_ID="PASTE_JOB_ID"
URL="$GATEWAY_URL/api/refine/relabel/events/$JOB_ID"

curl -sN "$URL" | python3 - <<'PY'
import sys,re
txt=sys.stdin.read()
m=re.search(r'"run_id"\s*:\s*"([0-9a-fA-F-]{36})"', txt)
print(m.group(1) if m else "")
PY
```

## Refine (Full Pipeline: Relabel + Augment)

The "full refine" flow uses the CLI and runs split phases with a shared
`run_id`.

### CLI (recommended for end-to-end testing)

```bash
CONFIG_ENV=dev ./scripts/demo.sh refine --limit 5
```

If you want explicit split control, use `scripts/demo.sh relabel` and
`scripts/demo.sh augment` with a shared `run_id`:

```bash
RUN_ID="$(python3 -c 'import uuid; print(uuid.uuid4())')"

./scripts/demo.sh relabel --limit 5
# If relabel prints a run id, use that. Otherwise, rerun with:
# REFINER_RUN_ID="$RUN_ID" ./scripts/demo.sh relabel --limit 5

# Use the run id produced by relabel:
./scripts/demo.sh augment --run-id "$RUN_ID"
```

Then promote.

```bash
./scripts/demo.sh promote
```

## Relabel Only (Debugging the Data ETL)

### Option A: CLI

```bash
./scripts/demo.sh relabel --limit 5
```

This prints a `Run id: ...` value. Capture it as `RUN_ID`.

### Option B: API (Gateway)

Start relabel job.

```bash
RESP="$(curl -s -X POST "$GATEWAY_URL/api/refine/relabel" -H "Content-Type: application/json")"
echo "$RESP"
echo "$RESP" | python3 -m json.tool
```

From the response, capture:

- `JOB_ID`
- `RUN_ID`

Stream job events (until completed/failed).

```bash
JOB_ID="PASTE_JOB_ID"
curl -sN "$GATEWAY_URL/api/refine/relabel/events/$JOB_ID"
```

### Verify Candidate vs Base (Before/After Metrics)

```bash
RUN_ID="PASTE_RUN_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
set -e
BEFORE='/model/refine_runs/$RUN_ID/metrics_before.json'
AFTER='/model/refine_runs/$RUN_ID/relabel/metrics_relabel_candidate.json'

echo \"Before: \$BEFORE\"
echo \"After:  \$AFTER\"

if cmp -s \"\$BEFORE\" \"\$AFTER\"; then
  echo 'metrics_before.json and metrics_relabel_candidate.json are byte-identical'
else
  echo 'metrics differ:'
  diff -u \"\$BEFORE\" \"\$AFTER\" | head -n 200
fi
"
```

### Confirm Whether Labels Actually Changed

```bash
RUN_ID="PASTE_RUN_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
python3 - <<'PY'
import pandas as pd

rid='$RUN_ID'
cand_path=f'/model/refine_runs/{rid}/relabel/train_relabel_candidate.csv'
base_path='/promote_target/train.csv'

cand=pd.read_csv(cand_path)
base=pd.read_csv(base_path)

m=cand.merge(base[['text','label']], on='text', how='inner',
              suffixes=('_cand','_base'))
diff=(m['label_cand']!=m['label_base'])

print('cand_rows:', len(cand))
print('overlap_rows:', len(m))
print('label_changes:', int(diff.sum()))
PY
"
```

### ETL Artifacts Created Per Batch

List batch files.

```bash
RUN_ID="PASTE_RUN_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
ls -1 /model/refine_runs/$RUN_ID/relabel/batches
"
```

For each `batch_XXXX`, check:

- prompt sent to Ollama: `prompt_relabel.batch_XXXX.txt`
- raw Ollama response: `raw_proposed_relabels.batch_XXXX.txt`
- parse/sanitize summary: `proposed_relabels.batch_XXXX.validation.json`
- rejected rows: `proposed_relabels.batch_XXXX.rejected_items.csv`
- sanitized proposals used for training:
  `proposed_relabels.batch_XXXX.csv`

Example (batch `0000`).

```bash
RUN_ID="PASTE_RUN_ID"
BATCH_ID="0000"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
set -e
DIR=\"/model/refine_runs/$RUN_ID/relabel/batches\"

echo '--- prompt ---'
sed -n '1,200p' \"\$DIR/prompt_relabel.batch_${BATCH_ID}.txt\"

echo '--- raw response ---'
sed -n '1,200p' \"\$DIR/raw_proposed_relabels.batch_${BATCH_ID}.txt\"

echo '--- validation summary ---'
cat \"\$DIR/proposed_relabels.batch_${BATCH_ID}.validation.json\" | head -n 200

echo '--- rejected items (head) ---'
if [ -f \"\$DIR/proposed_relabels.batch_${BATCH_ID}.rejected_items.csv\" ]; then
  head -n 50 \"\$DIR/proposed_relabels.batch_${BATCH_ID}.rejected_items.csv\"
else
  echo 'no rejected items file'
fi
"
```

### Merge-Level ETL Validation

```bash
RUN_ID="PASTE_RUN_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
cat /model/refine_runs/$RUN_ID/relabel/merge_relabel.validation.json | head -n 200
"
```

### Inspect Misclassified Input

The relabel worker consumes `/model/misclassified.csv`.

```bash
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc '
echo "--- misclassified.csv (head) ---"
head -n 30 /model/misclassified.csv
'
```

## Augment Only (Debugging the Data ETL)

### Option A: CLI (best for "augment matching a prior relabel run")

```bash
RUN_ID="PASTE_RUN_ID_FROM_RELABEL"
./scripts/demo.sh augment --run-id "$RUN_ID"
```

### Option B: API (Gateway)

Start augment job (creates a new `run_id`).

```bash
RESP="$(curl -s -X POST "$GATEWAY_URL/api/refine/augment" -H "Content-Type: application/json")"
echo "$RESP"
echo "$RESP" | python3 -m json.tool
```

From the response, capture `JOB_ID` and `RUN_ID`.

Stream job events.

```bash
JOB_ID="PASTE_JOB_ID"
curl -sN "$GATEWAY_URL/api/refine/augment/events/$JOB_ID"
```

### Verify Candidate vs Base (Before/After Metrics)

```bash
RUN_ID="PASTE_RUN_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
set -e
BEFORE='/model/refine_runs/$RUN_ID/metrics_before.json'
AFTER='/model/refine_runs/$RUN_ID/augment/metrics_augment_candidate.json'

echo \"Before: \$BEFORE\"
echo \"After:  \$AFTER\"

if cmp -s \"\$BEFORE\" \"\$AFTER\"; then
  echo 'metrics_before.json and metrics_augment_candidate.json are byte-identical'
else
  echo 'metrics differ:'
  diff -u \"\$BEFORE\" \"\$AFTER\" | head -n 200
fi
"
```

### ETL Artifacts Created Per Label

List augment label task output.

```bash
RUN_ID="PASTE_RUN_ID"
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
ls -1 /model/refine_runs/$RUN_ID/augment/labels
"
```

For label `search`, example files include:

- `raw_augment.label_search.txt`
- `prompt_augment.label_search.txt`
- `augment.label_search.validation.json`
- `augment.label_search.rejected_items.csv`
- `proposed_examples.label_search.csv`

Example inspection.

```bash
RUN_ID="PASTE_RUN_ID"
LABEL="search"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
DIR=\"/model/refine_runs/$RUN_ID/augment/labels\"
SAFE=\"$LABEL\"
echo '--- raw response ---'
sed -n '1,200p' \"\$DIR/raw_augment.label_${SAFE}.txt\"

echo '--- validation summary ---'
cat \"\$DIR/augment.label_${SAFE}.validation.json\" | head -n 200

echo '--- rejected items (head) ---'
if [ -f \"\$DIR/augment.label_${SAFE}.rejected_items.csv\" ]; then
  head -n 50 \"\$DIR/augment.label_${SAFE}.rejected_items.csv\"
fi
"
```

### Merge-Level ETL Validation

```bash
RUN_ID="PASTE_RUN_ID"
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
cat /model/refine_runs/$RUN_ID/augment/merge_augment.validation.json | head -n 200
# Expects counts: input_rows_count, accepted_rows_count, invalid_rows_count,
# duplicate_existing_count, fuzzy_duplicate_count
"
```

## Promote (Apply Candidate if Metrics Improve)

### CLI

```bash
./scripts/demo.sh promote
```

### Option B: API (Gateway)

Promote a specific run:

```bash
RUN_ID="PASTE_RUN_ID"
curl -s -X POST "$GATEWAY_URL/api/refine/promote" \
  -H "Content-Type: application/json" \
  -d \"{\\\"run_id\\\": \\\"$RUN_ID\\\"}\" | python3 -m json.tool
```

If `run_id` is omitted, it uses legacy behavior (expects the most recent
`train_candidate.csv` in `/model`).

```bash
curl -s -X POST "$GATEWAY_URL/api/refine/promote" \
  -H "Content-Type: application/json" \
  -d '{}' | python3 -m json.tool
```

### Verify Promotion Artifacts

If promotion succeeded and updated the model:

```bash
docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc '
ls -la /model/model.joblib /model/metrics.json
echo "--- /model/metrics.json ---"
cat /model/metrics.json
'
```

Restart `ai_router` to use the newly promoted model:

```bash
docker compose -f "$COMPOSE_FILE" restart ai_router
```

## Redis Job Debugging (Optional but Useful)

This is helpful when your job appears to hang or your artifacts are missing.

### List Job Keys

```bash
docker compose -f "$COMPOSE_FILE" exec -T redis redis-cli keys 'job:*'
```

### Inspect a Specific Job State (Relabel)

```bash
JOB_ID="PASTE_JOB_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
python3 - <<'PY'
from app.redis_client import get_job_state
job_id='$JOB_ID'
key='job:refine:relabel:' + job_id
st=get_job_state(key)
print('key:', key)
print('present:', st is not None)
print('status:', (st or {}).get('status'))
print('run_id:', ((st or {}).get('result') or {}).get('run_id'))
print('result_keys:', sorted(((st or {}).get('result') or {}).keys()))
PY
"
```

### Inspect a Specific Job State (Augment)

```bash
JOB_ID="PASTE_JOB_ID"

docker compose -f "$COMPOSE_FILE" exec -T training-api sh -lc "
python3 - <<'PY'
from app.redis_client import get_job_state
job_id='$JOB_ID'
key='job:refine:augment:' + job_id
st=get_job_state(key)
print('key:', key)
print('present:', st is not None)
print('status:', (st or {}).get('status'))
print('run_id:', ((st or {}).get('result') or {}).get('run_id'))
print('result_keys:', sorted(((st or {}).get('result') or {}).keys()))
PY
"
```

## Common Failure Modes and What to Check

### "Before and After metrics are identical"

Check:

1. Whether relabel/augment changed the candidate dataset.
2. Whether the ETL rejected almost everything (look at
   `*.validation.json` and `*.rejected_items.csv`).
3. Whether the only accepted proposal produced no effective label change.

Use the "Verify Candidate vs Base" and "ETL Artifacts" sections above.

### "Only 0 to 1 proposals/examples appear"

For relabel:

1. Count misclassified rows vs batch output rows.
2. Inspect `raw_proposed_relabels.batch_*.txt` and
   `proposed_relabels.batch_*.validation.json`.

For augment:

1. Inspect `augment.label_*.validation.json` (check `verified_count`,
   `verification_rejected_count` when verification is on) and
   `augment.label_*.rejected_items.csv`.
2. Inspect `merge_augment.validation.json` (including `fuzzy_duplicate_count`).
3. Confirm `train.csv` has enough rows per label for seeds when using
   `REFINER_AUGMENT_SEED_EXAMPLES`.

### "Job appears stuck"

1. Tail `training-api` logs and `refiner`/Ollama logs.
2. Inspect Redis job state using the Redis section above.
3. Check whether output files exist under `/model/refine_runs/<run_id>/...`.
