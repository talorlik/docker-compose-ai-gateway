#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/compose/docker-compose.yaml"
CONFIG_ENV="${CONFIG_ENV:-dev}"

if [[ ! "$CONFIG_ENV" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "Invalid CONFIG_ENV: $CONFIG_ENV" >&2
  exit 1
fi

usage() {
  cat <<'EOF'
Usage: refine_relabel.sh [--run-id ID] [--limit N]

Options:
  --run-id ID   Shared refine run id to correlate relabel + augment outputs.
  --limit N     Max misclassified rows to process for relabel.
EOF
}

run_id="${REFINER_RUN_ID:-}"
limit=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      run_id="${2:-}"
      shift 2
      ;;
    --limit)
      limit="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$run_id" ]]; then
  run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
fi

env_file="${REPO_ROOT}/env/.env.${CONFIG_ENV}"
if [[ ! -f "$env_file" ]]; then
  python3 "${REPO_ROOT}/scripts/generate_env.py" "${CONFIG_ENV}"
fi
export PROJECT_ENV_FILE="../env/.env.${CONFIG_ENV}"
# shellcheck disable=SC1090
source "$env_file"

echo "Running relabel phase (run_id=${run_id})..."

run_args=(
  --rm
  -e "REFINER_RUN_ID=${run_id}"
  -e "OLLAMA_NUM_CTX=${REFINER_RELABEL_NUM_CTX:-1024}"
  -e "OLLAMA_NUM_PREDICT=${REFINER_RELABEL_NUM_PREDICT:-120}"
  -e "REFINER_TEMPERATURE=${REFINER_TEMPERATURE:-0.1}"
  -e "REFINER_SEED=${REFINER_SEED:-42}"
  -e "REFINER_STRUCTURED_OUTPUT_ENABLED=${REFINER_STRUCTURED_OUTPUT_ENABLED:-true}"
)
if [[ -n "$limit" ]]; then
  run_args+=(-e "REFINER_LIMIT=${limit}")
fi

docker compose -f "$COMPOSE_FILE" --profile refine run "${run_args[@]}" training-api relabel
