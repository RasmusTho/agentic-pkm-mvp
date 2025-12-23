#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

STATUS_URL="http://127.0.0.1:18000/api/status"
MAX_ATTEMPTS=30
SLEEP_SECONDS=2

echo "Bringing up db+api+worker on pg backend..."
docker compose up -d --build db api worker

echo -n "Waiting for API ($STATUS_URL)"
for attempt in $(seq 1 $MAX_ATTEMPTS); do
  if curl -sSf "$STATUS_URL" >/dev/null 2>&1; then
    echo " success after $((attempt * SLEEP_SECONDS))s"
    break
  fi
  if [ "$attempt" -eq "$MAX_ATTEMPTS" ]; then
    echo ""
    echo "ERROR: API health check failed after $((MAX_ATTEMPTS * SLEEP_SECONDS))s" >&2
    docker compose ps api worker
    exit 1
  fi
  echo -n "."
  sleep $SLEEP_SECONDS
done

echo "Dashboard: http://127.0.0.1:18000"
echo "Health/status: $STATUS_URL"
echo "OpenAPI: http://127.0.0.1:18000/openapi.json"
