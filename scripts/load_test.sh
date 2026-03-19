#!/usr/bin/env bash
# Load test script for Local AI Microservice Mesh (NFR-037, AC-007)
# Sends multiple requests to gateway; use with scaled backends to verify
# distribution. Per TECH-18.3.

set -euo pipefail

COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_DIR}/compose/docker-compose.yaml"
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

# Default: 20 requests. Override: REQUESTS=50 ./scripts/load_test.sh
REQUESTS="${REQUESTS:-20}"

# Prompts that route to search (for distribution verification when scaled)
SEARCH_PROMPTS=(
  "compare nginx ingress vs traefik"
  "how does kubernetes scheduling work"
  "best practices for docker multi-stage builds"
  "terraform vs pulumi comparison"
  "search for microservice patterns"
)

usage() {
  cat <<EOF
Usage: $0 [options]

Sends multiple requests to the gateway. With scaled backends (e.g.
search_service=3), verify distribution by checking trace 'instance'
fields for different container hostnames.

Options:
  REQUESTS=N    Number of requests (default: 20)
  GATEWAY_URL   Gateway base URL (default: http://localhost:8000)

Verify distribution:
  1. Scale: docker compose -f compose/docker-compose.yaml up -d --scale search_service=3
  2. Run:   $0
  3. Check: docker compose logs gateway | grep -o '"instance":"[^"]*"' | sort | uniq -c

Or inspect responses: each backend_response includes "instance" (container hostname).
EOF
}

main() {
  if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
  fi

  cd "$COMPOSE_DIR"

  echo "Load test: $REQUESTS requests to $GATEWAY_URL"
  echo ""

  success=0
  fail=0
  instances=""

  for ((i=0; i<REQUESTS; i++)); do
    prompt="${SEARCH_PROMPTS[$((i % ${#SEARCH_PROMPTS[@]}))]}"
    json_body=$(python3 -c "import json; print(json.dumps({'text': '''$prompt'''}))" 2>/dev/null)
    resp=$(curl -s -w "\n%{http_code}" -X POST "$GATEWAY_URL/api/request" \
      -H "Content-Type: application/json" \
      -d "$json_body" 2>/dev/null) || { fail=$((fail + 1)); continue; }

    http_code=$(echo "$resp" | tail -1)
    body=$(echo "$resp" | sed '$d')

    if [[ "$http_code" == "200" ]]; then
      success=$((success + 1))
      inst=$(echo "$body" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('backend_response', {}).get('instance', 'N/A'))
except: print('N/A')
" 2>/dev/null)
      instances="$instances$inst"$'\n'
    else
      fail=$((fail + 1))
    fi

    printf "\rProgress: %d/%d (ok=%d fail=%d)" "$((i+1))" "$REQUESTS" "$success" "$fail"
  done

  echo ""
  echo ""
  echo "Results: $success succeeded, $fail failed"

  if [[ $success -gt 0 ]]; then
    echo ""
    echo "Instance distribution (backend hostnames):"
    echo "$instances" | grep -v '^$' | sort | uniq -c | sort -rn
  fi
}

main "$@"
