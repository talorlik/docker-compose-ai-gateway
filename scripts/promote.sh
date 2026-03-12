#!/usr/bin/env bash
# Promote train_candidate.csv to train.csv only if retraining improves metrics.
# Run after: docker compose --profile refine run --rm refiner
#
# Flow:
#   1. Retrain with train_candidate.csv
#   2. Compare new metrics with metrics_before.json
#   3. If improved: copy candidate to train.csv and promote model
#   4. If not: discard candidate, keep current train.csv

set -e

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"
TRAIN_CSV="${COMPOSE_DIR}/services/trainer/train.csv"

cd "$COMPOSE_DIR"

# Check train_candidate exists
if ! docker compose -f "$COMPOSE_FILE" --profile refine run --rm --no-deps --entrypoint test refiner -f /data/train_candidate.csv 2>/dev/null; then
  echo "Error: train_candidate.csv not found. Run refiner first:" >&2
  echo "  docker compose -f compose/docker-compose.yaml --profile refine run --rm refiner" >&2
  exit 1
fi

# Retrain with candidate
echo "Retraining with train_candidate.csv..."
docker compose -f "$COMPOSE_FILE" --profile train run --rm --no-deps trainer \
  python train.py \
  --data /model/train_candidate.csv \
  --out /model/model_candidate.joblib \
  --metrics /model/metrics_candidate.json \
  --misclassified /model/misclassified_candidate.csv

# Extract metrics for comparison
TMP_BEFORE=$(mktemp)
TMP_AFTER=$(mktemp)
trap "rm -f $TMP_BEFORE $TMP_AFTER" EXIT
docker compose -f "$COMPOSE_FILE" --profile refine run --rm --no-deps --entrypoint cat refiner /data/metrics_before.json 2>/dev/null > "$TMP_BEFORE" || echo '{}' > "$TMP_BEFORE"
docker compose -f "$COMPOSE_FILE" --profile refine run --rm --no-deps --entrypoint cat refiner /data/metrics_candidate.json 2>/dev/null > "$TMP_AFTER" || echo '{}' > "$TMP_AFTER"

# Compare accuracy; output: PROMOTE acc_before acc_after
COMPARE=$(python3 -c "
import json
with open('$TMP_BEFORE') as f: before = json.load(f)
with open('$TMP_AFTER') as f: after = json.load(f)
acc_before = float(before.get('accuracy', 0) or 0)
acc_after = float(after.get('accuracy', 0) or 0)
promote = 1 if acc_before == 0 or acc_after > acc_before else 0
print(promote, acc_before, acc_after)
" 2>/dev/null || echo "0 0 0")

read -r PROMOTE acc_before acc_after <<< "$COMPARE"

if [[ "$PROMOTE" -eq 1 ]]; then
  if [[ "$acc_before" == "0" ]]; then
    echo "No previous metrics; promoting candidate."
  else
    echo "Metrics improved: $acc_before -> $acc_after. Promoting."
  fi
else
  echo "Metrics did not improve ($acc_before -> $acc_after). Discarding candidate."
fi

if [[ "$PROMOTE" -eq 1 ]]; then
  docker compose -f "$COMPOSE_FILE" --profile refine run --rm --no-deps --entrypoint cat refiner /data/train_candidate.csv > "$TRAIN_CSV"
  docker compose -f "$COMPOSE_FILE" --profile train run --rm --no-deps trainer sh -c "cp /model/model_candidate.joblib /model/model.joblib"
  docker compose -f "$COMPOSE_FILE" --profile train run --rm --no-deps trainer sh -c "cp /model/metrics_candidate.json /model/metrics.json"
  echo "Promoted. Restart ai_router to use new model:"
  echo "  docker compose -f compose/docker-compose.yaml restart ai_router"
else
  echo "train.csv unchanged. No promotion."
fi
