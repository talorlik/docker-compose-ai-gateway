#!/usr/bin/env bash
# Promote train_candidate.csv to train.csv only if retraining improves metrics.
# Uses the canonical training-api promote flow (same as the UI Promote button).
#
# Prerequisites: Run refinement first (e.g. via UI or: docker compose run training-api refine).
# After promotion, restart ai_router to use the new model.

set -e

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"

cd "$COMPOSE_DIR"

docker compose -f "$COMPOSE_FILE" --profile refine run --rm training-api promote

echo ""
echo "If promoted, restart ai_router to use the new model:"
echo "  docker compose -f compose/docker-compose.yaml restart ai_router"
