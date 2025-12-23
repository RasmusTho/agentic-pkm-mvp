#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_CMD=${COMPOSE_CMD:-"docker compose"}
API_URL=${API_URL:-"http://127.0.0.1:18000"}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-60}
SLEEP_SECONDS=${SLEEP_SECONDS:-5}

info() {
  printf '[start] %s\n' "$1"
}

diagnose() {
  info "Diagnostics: docker compose ps"
  $COMPOSE_CMD ps || true
  info "api logs (tail 120)"
  docker logs --tail 120 workspace-api-1 || true
  info "worker logs (tail 120)"
  docker logs --tail 120 workspace-worker-1 || true
  info "watcher logs (tail 120)"
  docker logs --tail 120 workspace-watcher-1 || true
  info "/api/health payload"
  curl -sS "$API_URL/api/health" || true
}

info "Bringing up services (db, api, worker, watcher)"
$COMPOSE_CMD up -d --build db api worker watcher

info "Waiting for /api/status"
status_ok=0
status_attempts=0
while [ $status_attempts -lt 30 ]; do
  if curl -sS "$API_URL/api/status" >/dev/null 2>&1; then
    status_ok=1
    break
  fi
  status_attempts=$((status_attempts + 1))
  sleep 2
done

if [ $status_ok -ne 1 ]; then
  printf 'ERROR: /api/status did not respond in time\n' >&2
  diagnose
  exit 1
fi

info "Polling /api/health for ok=true (timeout ${HEALTH_TIMEOUT}s)"
health_ok=0
start_ts=$(date +%s)
while :; do
  health_payload=$(curl -sS "$API_URL/api/health" || true)
  if printf '%s' "$health_payload" | grep -q '"ok": true'; then
    health_ok=1
    break
  fi
  now_ts=$(date +%s)
  elapsed=$((now_ts - start_ts))
  if [ $elapsed -ge $HEALTH_TIMEOUT ]; then
    break
  fi
  sleep "$SLEEP_SECONDS"
done

if [ $health_ok -ne 1 ]; then
  printf 'ERROR: /api/health did not report ok within timeout\n' >&2
  diagnose
  exit 1
fi

info "Full system healthy"
info "Next steps:"
info "- Run scripts/gap_test_alpha.sh"
info "- Inspect /api/health for watcher/worker/db/llm"
