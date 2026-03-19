#!/usr/bin/env bash
# Demo script for Local AI Microservice Mesh (NFR-036)
# Per PROJECT_PLAN Section 10 and docs/auxiliary/demo/DEMO.md

set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"
COMPOSE_DEV="${COMPOSE_DIR}/compose/docker-compose.dev.yaml"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"
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

load_runtime_config() {
  ensure_env
  export PROJECT_ENV_FILE="../env/.env.${CONFIG_ENV}"
  # shellcheck disable=SC1090
  source "${COMPOSE_DIR}/env/.env.${CONFIG_ENV}"

  OLLAMA_MODE="${OLLAMA_MODE:-native}"
  OLLAMA_BACKEND_ENFORCE_EXCLUSIVE="${OLLAMA_BACKEND_ENFORCE_EXCLUSIVE:-true}"
  OLLAMA_CONTAINER_SERVICE="${OLLAMA_CONTAINER_SERVICE:-ollama}"
  OLLAMA_HOST="${OLLAMA_HOST:-http://host.docker.internal:11434}"
  DEMO_START_BACKEND="${DEMO_START_BACKEND:-true}"
  DEMO_RUN_RELABEL="${DEMO_RUN_RELABEL:-true}"
  DEMO_RUN_AUGMENT="${DEMO_RUN_AUGMENT:-true}"
}

ensure_cmd() {
  local name="$1"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "Missing required command: ${name}" >&2
    exit 1
  fi
}

check_endpoint() {
  local url="$1"
  curl -fsS --max-time 3 "${url}/api/tags" >/dev/null 2>&1
}

check_native_host_reachable() {
  # Preflight check runs on the host (not inside Docker).
  # On some setups, `host.docker.internal` may not resolve/reach from the host
  # shell even though it works from containers.
  local url="$1"
  if check_endpoint "${url}"; then
    return 0
  fi

  # Best-effort fallback for Docker-desktop defaults on macOS.
  if [[ "${url}" == *"host.docker.internal"* ]]; then
    local fallback="${url/host.docker.internal/localhost}"
    if check_endpoint "${fallback}"; then
      return 0
    fi
  fi

  return 1
}

is_container_running() {
  local svc="$1"
  local out
  out="$(docker compose -f "$COMPOSE_FILE" ps -q "$svc" 2>/dev/null || true)"
  [[ -n "$out" ]]
}

stop_container_backend_if_running() {
  local svc="$1"
  if is_container_running "$svc"; then
    echo "Stopping containerized Ollama (${svc}) to enforce native mode..."
    docker compose -f "$COMPOSE_FILE" --profile refine-container stop "$svc" >/dev/null
  fi
}

ensure_container_backend_running() {
  local svc="$1"
  echo "Starting containerized Ollama (${svc})..."
  docker compose -f "$COMPOSE_FILE" --profile refine-container up -d "$svc"
}

wait_for_backend() {
  local tries=0
  until check_endpoint "${OLLAMA_HOST}"; do
    tries=$((tries + 1))
    if [[ "$tries" -ge 60 ]]; then
      echo "Timed out waiting for ${OLLAMA_HOST}" >&2
      exit 1
    fi
    sleep 2
  done
}

preflight_backend_mode() {
  load_runtime_config
  ensure_cmd docker
  ensure_cmd curl

  if [[ "$OLLAMA_MODE" != "native" && "$OLLAMA_MODE" != "container" ]]; then
    echo "Invalid OLLAMA_MODE=${OLLAMA_MODE}. Use native or container." >&2
    exit 1
  fi

  if [[ "$OLLAMA_MODE" == "native" ]]; then
    if [[ "$OLLAMA_BACKEND_ENFORCE_EXCLUSIVE" == "true" ]]; then
      stop_container_backend_if_running "$OLLAMA_CONTAINER_SERVICE"
    fi
    if [[ "$DEMO_START_BACKEND" == "true" ]]; then
      if ! check_native_host_reachable "${OLLAMA_HOST}"; then
        cat >&2 <<EOF
Native Ollama not reachable.
Checked: ${OLLAMA_HOST}
If that includes host.docker.internal, also tried a localhost fallback.
Start native Ollama first, then retry.
EOF
        exit 1
      fi
    fi
  else
    if [[ "$OLLAMA_BACKEND_ENFORCE_EXCLUSIVE" == "true" ]] && \
       [[ "${OLLAMA_HOST}" != "http://ollama:11434" ]]; then
      echo "Container mode requires OLLAMA_HOST=http://ollama:11434." >&2
      exit 1
    fi
    if [[ "$DEMO_START_BACKEND" == "true" ]]; then
      ensure_container_backend_running "$OLLAMA_CONTAINER_SERVICE"
      wait_for_backend
    fi
  fi
}

usage() {
  cat <<'EOF'
Usage: demo.sh [command] [options...]

Commands:
  build [SERVICE]       Build images. SERVICE: all (default), gateway, ai_router,
                        search_service, image_service, ops_service, trainer, refiner
  run [--dev] [--scale N]  Start the stack with selected Ollama mode.
  start                 Alias for run
  stop                  Stop the stack (containers remain)
  delete                Remove containers, networks, and volumes
  curl                  Run curl examples (search, image, ops, unknown)
  scaling               Demo load distribution (scale search_service=3, run load test)
  scale N               Scale search_service to N replicas
  failure               Demo backend failure (stop image_service, send request)
  load-test             Run load test script (REQUESTS=20 by default)
  logs [SERVICE...]     Follow logs. Default: gateway ai_router search_service
  test [SERVICE]        Run unit tests. SERVICE: all (default), gateway, ai_router
  train                 Train new model and reload ai_router
  relabel [--limit N]   Run relabel phase only
  augment --run-id ID   Run augment phase only for an existing run
  refine [--limit N]    Run split two-phase refine (relabel, then augment)
  promote               Promote candidate if metrics improve
  help, --help, -h      Show this help

Options:
  --dev                 With 'run': use dev overlay (hot reload)
  --scale N             With 'run': scale search_service to N replicas
  --limit N             With 'relabel'/'refine': max misclassified rows to process
  --run-id ID           With 'augment': shared run id

Environment:
  CONFIG_ENV            Env name used by env/.env.<env> (default: dev)
  OLLAMA_MODE           native | container
  OLLAMA_HOST           Active Ollama endpoint (must match selected mode)
  OLLAMA_BACKEND_ENFORCE_EXCLUSIVE  true | false
  DEMO_START_BACKEND    true | false
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

  preflight_backend_mode

  cd "$COMPOSE_DIR"
  local compose_args=(-f "$COMPOSE_FILE" --profile refine)
  if [[ "${OLLAMA_MODE}" == "container" ]]; then
    compose_args+=(--profile refine-container)
  fi
  [[ "$dev" == true ]] && compose_args+=(-f "$COMPOSE_DEV")
  compose_args+=(up --build -d)
  [[ -n "$scale" ]] && compose_args+=(--scale "search_service=$scale")

  docker compose "${compose_args[@]}"

  echo "Waiting for services to be healthy..."
  local retries=30
  while ! curl -sf "$GATEWAY_URL/health" >/dev/null 2>&1; do
    retries=$((retries - 1))
    if [[ $retries -le 0 ]]; then
      echo "Gateway health check timed out" >&2
      exit 1
    fi
    sleep 2
  done
  echo "Stack is up. Gateway: $GATEWAY_URL"
}

cmd_stop() {
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" --profile refine --profile refine-container stop
  echo "Stack stopped."
}

cmd_delete() {
  cd "$COMPOSE_DIR"
  docker compose -f "$COMPOSE_FILE" --profile refine --profile refine-container down -v
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
}

cmd_scaling() {
  echo "=== Scaling Demo ==="
  cd "$COMPOSE_DIR"
  echo "Scaling search_service to 3 replicas..."
  docker compose -f "$COMPOSE_FILE" up -d --scale search_service=3
  sleep 5
  for i in 1 2 3 4 5 6; do
    echo "--- Request $i ---"
    curl -s -X POST "$GATEWAY_URL/api/request" \
      -H "Content-Type: application/json" \
      -d '{"text": "compare nginx ingress vs traefik"}' \
      | python3 -c "import sys,json; d=json.load(sys.stdin); be=d.get('backend_response',{}); print('instance:', be.get('instance','N/A'), '| route:', d.get('route'))"
  done
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
  echo "Sending image-like prompt (backend will be unavailable)..."
  curl -s -w "\nHTTP Status: %{http_code}\n" -X POST "$GATEWAY_URL/api/request" \
    -H "Content-Type: application/json" \
    -d '{"text": "detect objects in an image"}' \
    | python3 -m json.tool 2>/dev/null || true
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
    docker compose -f "$COMPOSE_FILE" logs -f gateway ai_router search_service training-api
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
  preflight_backend_mode
  cd "$COMPOSE_DIR"
  echo "Training new model (via training-api)..."
  docker compose -f "$COMPOSE_FILE" --profile refine run --rm training-api train
  echo "Reloading ai_router..."
  docker compose -f "$COMPOSE_FILE" restart ai_router
}

cmd_relabel() {
  local limit=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  preflight_backend_mode
  local run_id
  run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
  if [[ -n "$limit" ]]; then
    "${COMPOSE_DIR}/scripts/refine_relabel.sh" --run-id "$run_id" --limit "$limit"
  else
    "${COMPOSE_DIR}/scripts/refine_relabel.sh" --run-id "$run_id"
  fi
  echo "Relabel complete. Run id: $run_id"
}

cmd_augment() {
  local run_id=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --run-id) run_id="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  if [[ -z "$run_id" ]]; then
    echo "augment requires --run-id <id>" >&2
    exit 1
  fi
  preflight_backend_mode
  "${COMPOSE_DIR}/scripts/refine_augment.sh" --run-id "$run_id"
}

cmd_refine() {
  local limit=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  preflight_backend_mode
  local run_id
  run_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"

  if [[ "${DEMO_RUN_RELABEL}" == "true" ]]; then
    if [[ -n "$limit" ]]; then
      "${COMPOSE_DIR}/scripts/refine_relabel.sh" --run-id "$run_id" --limit "$limit"
    else
      "${COMPOSE_DIR}/scripts/refine_relabel.sh" --run-id "$run_id"
    fi
  fi

  if [[ "${DEMO_RUN_AUGMENT}" == "true" ]]; then
    "${COMPOSE_DIR}/scripts/refine_augment.sh" --run-id "$run_id"
  fi

  echo "Refine complete for run id: $run_id"
  echo "Run demo.sh promote to retrain and promote if metrics improve."
}

cmd_promote() {
  cd "$COMPOSE_DIR"
  ./scripts/promote.sh
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
    relabel)
      cmd_relabel "$@"
      ;;
    augment)
      cmd_augment "$@"
      ;;
    refine)
      cmd_refine "$@"
      ;;
    promote)
      cmd_promote
      ;;
    *)
      echo "Unknown command: $cmd"
      usage
      exit 1
      ;;
  esac
}

main "$@"
