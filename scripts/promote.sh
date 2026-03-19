#!/usr/bin/env bash
# Promote train_candidate.csv to train.csv only if retraining improves metrics.
# Uses the canonical training-api promote flow (same behavior as the Refine UI
# "Promote" button).
#
# Prerequisites: Run the refine pipeline first (via UI relabel + augment, or
# via CLI: ./scripts/demo.sh refine) so that train_candidate.csv and metrics
# artifacts exist for the most recent run.
# After promotion, restart ai_router to use the new model.

set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"
CONFIG_ENV="${CONFIG_ENV:-dev}"

if [[ ! "$CONFIG_ENV" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Invalid CONFIG_ENV: $CONFIG_ENV" >&2
  exit 1
fi

ensure_env() {
  local env_file="${COMPOSE_DIR}/env/.env.${CONFIG_ENV}"
  if [[ ! -f "$env_file" ]]; then
    echo "Generating $env_file from config/PROJECT_CONFIG.yaml (CONFIG_ENV=${CONFIG_ENV})..."
    python3 "${COMPOSE_DIR}/scripts/generate_env.py" "${CONFIG_ENV}"
  fi
}

cd "$COMPOSE_DIR"

ensure_env

docker compose -f "$COMPOSE_FILE" --profile refine run --rm training-api promote

echo ""
echo "If promoted, restart ai_router to use the new model:"
echo "  docker compose -f compose/docker-compose.yaml restart ai_router"
