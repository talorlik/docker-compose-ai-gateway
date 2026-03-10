#!/usr/bin/env bash
# Demo script for Local AI Microservice Mesh (NFR-036)
# Per PROJECT_PLAN Section 10 and docs/DEMO.md

set -e

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"
COMPOSE_DEV="${COMPOSE_DIR}/compose/docker-compose.dev.yaml"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

usage() {
  cat <<'EOF'
Usage: demo.sh [command] [options...]

Commands:
  build [SERVICE]     Build images. SERVICE: all (default), gateway, ai_router,
                     search_service, image_service, ops_service, trainer
  run [--dev]        Start the stack (production). Use --dev for hot reload.
  start              Alias for run
  stop               Stop the stack (containers remain)
  delete             Remove containers, networks, and volumes
  curl               Run curl examples (search, image, ops, unknown)
  scaling            Demo load distribution (scale search_service=3, run load test)
  scale N            Scale search_service to N replicas (e.g. scale 1 to scale back)
  failure            Demo backend failure (stop image_service, send request)
  load-test          Run load test script (REQUESTS=20 by default)
  logs [SERVICE...]  Follow logs. Default: gateway ai_router search_service
  test [SERVICE]     Run unit tests. SERVICE: all (default), gateway, ai_router
  train              Train new model and reload ai_router
  help, --help, -h    Show this help

Options:
  --dev              With 'run': use dev overlay (hot reload)
  --scale N          With 'run': scale search_service to N replicas

Environment:
  GATEWAY_URL        Gateway base URL (default: http://localhost:8000)
  REQUESTS           With load-test: number of requests (default: 20)

Examples:
  demo.sh                    # Show help (no default command)
  demo.sh build              # Build all services
  demo.sh build gateway      # Build gateway only
  demo.sh run                # Start stack (production)
  demo.sh run --dev          # Start stack with hot reload
  demo.sh run --scale 3      # Start with search_service scaled to 3
  demo.sh scale 1            # Scale search_service back to 1
  demo.sh stop               # Stop stack
  demo.sh delete             # Remove everything including volumes
  demo.sh curl               # Run curl demos (stack must be running)
  demo.sh scaling            # Scaling demo
  demo.sh failure            # Failure demo
  demo.sh load-test          # Run load test
  demo.sh logs               # Follow gateway, ai_router, search_service logs
  demo.sh logs gateway       # Follow gateway logs only
  demo.sh test               # Run all unit tests
  demo.sh test gateway       # Run gateway tests only
  demo.sh train              # Train model and reload ai_router

See docs/DEMO.md for full runbook.
EOF
}

cmd_build() {
  local svc="${1:-}"
  cd "$COMPOSE_DIR"
  if [[ -z "$svc" || "$svc" == "all" ]]; then
    docker compose -f "$COMPOSE_FILE" build
  else
    docker compose -f "$COMPOSE_FILE" build "$svc"
  fi
}

cmd_run() {
  local dev=false
  local scale=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dev) dev=true; shift ;;
      --scale) scale="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  cd "$COMPOSE_DIR"
  local compose_args=(-f "$COMPOSE_FILE")
  [[ "$dev" == true ]] && compose_args+=(-f "$COMPOSE_DEV")
  compose_args+=(up --build -d)
  [[ -n "$scale" ]] && compose_args+=(--scale "search_service=$scale")

  docker compose "${compose_args[@]}"

  echo "Waiting for services to be healthy..."
  sleep 10
  echo "Stack is up. Gateway: $GATEWAY_URL"
  echo "Try: demo.sh curl"
  echo "Or open: $GATEWAY_URL in your browser"
}

cmd_stop() {
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" stop
  echo "Stack stopped."
}

cmd_delete() {
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" down -v
  echo "Containers, networks, and volumes removed."
}

cmd_curl() {
  echo "=== Curl Demo: Search (expected route: search) ==="
  curl -s -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "compare nginx ingress vs traefik"}' | python3 -m json.tool
  echo ""

  echo "=== Curl Demo: Image (expected route: image) ==="
  curl -s -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "detect objects in an image and return labels"}' \
    | python3 -m json.tool
  echo ""

  echo "=== Curl Demo: Ops (expected route: ops) ==="
  curl -s -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "kubectl pods CrashLoopBackOff, debug steps"}' \
    | python3 -m json.tool
  echo ""

  echo "=== Curl Demo: Unknown (expected: 404, route: unknown) ==="
  curl -s -w "\nHTTP Status: %{http_code}\n" -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "hello"}' | tail -20
  echo ""

  echo "=== Curl Demo: Unknown - tell me a joke ==="
  curl -s -w "\nHTTP Status: %{http_code}\n" -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "tell me a joke"}' | tail -20
}

cmd_scaling() {
  echo "=== Scaling Demo ==="
  cd "$COMPOSE_DIR"
  echo "Scaling search_service to 3 replicas..."
  docker compose -f "$COMPOSE_FILE" up -d --scale search_service=3
  sleep 5
  echo ""
  echo "Sending 6 search requests to observe round-robin distribution..."
  echo "Check trace entries for different 'instance' hostnames."
  echo ""
  for i in 1 2 3 4 5 6; do
    echo "--- Request $i ---"
    curl -s -X POST "$GATEWAY_URL/api/request" \
      -H "Content-Type: application/json" \
      -d '{"text": "compare nginx ingress vs traefik"}' \
      | python3 -c "import sys,json; d=json.load(sys.stdin); be=d.get('backend_response',{}); print('instance:', be.get('instance','N/A'), '| route:', d.get('route'))"
  done
  echo ""
  echo "Scale back: demo.sh scale 1"
}

cmd_scale() {
  local n="${1:?Usage: demo.sh scale N}"
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" up -d --scale "search_service=$n"
  echo "search_service scaled to $n"
}

cmd_failure() {
  echo "=== Failure Demo ==="
  cd "$COMPOSE_DIR"
  echo "Stopping image_service..."
  docker compose -f "$COMPOSE_FILE" stop image_service
  echo ""
  echo "Sending image-like prompt (backend will be unavailable)..."
  curl -s -w "\nHTTP Status: %{http_code}\n" -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "detect objects in an image"}' \
    | python3 -m json.tool 2>/dev/null || true
  echo ""
  echo "Expected: 502, route=image, trace shows classification + backend failure"
  echo ""
  echo "Restart: docker compose -f $COMPOSE_FILE start image_service"
}

cmd_load_test() {
  cd "$COMPOSE_DIR"
  "${COMPOSE_DIR}/scripts/load_test.sh"
}

cmd_logs() {
  cd "$COMPOSE_DIR"
  if [[ $# -gt 0 ]]; then
    docker compose -f "$COMPOSE_FILE" logs -f "$@"
  else
    docker compose -f "$COMPOSE_FILE" logs -f gateway ai_router search_service
  fi
}

cmd_test() {
  local svc="${1:-all}"
  cd "$COMPOSE_DIR"
  case "$svc" in
    all)
      pytest services/gateway/tests/ services/ai_router/tests/ -v
      ;;
    gateway)
      (cd services/gateway && pytest tests/ -v)
      ;;
    ai_router)
      (cd services/ai_router && pytest tests/ -v)
      ;;
    *)
      echo "Unknown service: $svc (use: all, gateway, ai_router)"
      exit 1
      ;;
  esac
}

cmd_train() {
  cd "$COMPOSE_DIR"
  echo "Training new model..."
  docker compose -f "$COMPOSE_FILE" --profile train run --rm trainer
  echo ""
  echo "Reloading ai_router..."
  docker compose -f "$COMPOSE_FILE" restart ai_router
  echo ""
  echo "Verify: demo.sh curl"
}

main() {
  local cmd="${1:-}"
  shift 2>/dev/null || true

  case "$cmd" in
    help|--help|-h|"")
      usage
      exit 0
      ;;
    build)
      cmd_build "${1:-all}"
      ;;
    run|start)
      cmd_run "$@"
      ;;
    stop)
      cmd_stop
      ;;
    delete)
      cmd_delete
      ;;
    curl)
      cmd_curl
      ;;
    scaling)
      cmd_scaling
      ;;
    scale)
      cmd_scale "$@"
      ;;
    failure)
      cmd_failure
      ;;
    load-test)
      cmd_load_test
      ;;
    logs)
      cmd_logs "$@"
      ;;
    test)
      cmd_test "${1:-all}"
      ;;
    train)
      cmd_train
      ;;
    *)
      echo "Unknown command: $cmd"
      usage
      exit 1
      ;;
  esac
}

main "$@"
