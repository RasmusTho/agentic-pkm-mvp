#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_CMD=${COMPOSE_CMD:-"docker compose"}
API_URL=${API_URL:-"http://127.0.0.1:18000"}
HEALTH_TIMEOUT=${HEALTH_TIMEOUT:-60}
SLEEP_SECONDS=${SLEEP_SECONDS:-5}
STARTUP_IGNORE_CHECKS=${STARTUP_IGNORE_CHECKS:-ffmpeg}

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

check_health_payload() {
  HEALTH_PAYLOAD="$1" STARTUP_IGNORE_CHECKS="$STARTUP_IGNORE_CHECKS" python - <<'PY'
import json, os, sys
payload = os.environ.get("HEALTH_PAYLOAD", "")
ignore = {p.strip() for p in os.environ.get("STARTUP_IGNORE_CHECKS", "").split(",") if p.strip()}
if not payload:
    print("pending parse_error:empty")
    sys.exit(1)
try:
    data = json.loads(payload)
except Exception as exc:
    print(f"pending parse_error:{exc}")
    sys.exit(1)
runtime = data.get("runtime", {})
checks = data.get("checks", {})
required = ["db", "watcher", "worker"]
runtime_fail = [k for k in required if not runtime.get(k, {}).get("ok")]
check_fail = [k for k, v in checks.items() if not isinstance(v, dict) or not v.get("ok")]
ignored = [k for k in check_fail if k in ignore]
other = [k for k in check_fail if k not in ignore]
if runtime_fail or other:
    reasons = []
    if runtime_fail:
        reasons.append("runtime:" + ",".join(runtime_fail))
    if other:
        reasons.append("checks:" + ",".join(other))
    if ignored:
        reasons.append("ignored:" + ",".join(sorted(ignored)))
    print("fail " + ";".join(reasons))
    sys.exit(2)
msg = "ok"
if ignored:
    msg += " ignored:" + ",".join(sorted(ignored))
print(msg)
sys.exit(0)
PY
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
last_info=""
while :; do
  health_payload=$(curl -sS "$API_URL/api/health" || true)
  set +e
  eval_output=$(check_health_payload "$health_payload")
  rc=$?
  set -e
  last_info=$eval_output
  if [ $rc -eq 0 ] && printf '%s' "$eval_output" | grep -q '^ok'; then
    if printf '%s' "$eval_output" | grep -q 'ignored:'; then
      info "Ignoring failing checks: $(printf '%s' "$eval_output" | sed -n 's/^ok ignored://p')"
    fi
    health_ok=1
    break
  fi
  if [ $rc -eq 2 ]; then
    printf 'ERROR: runtime or non-ignored checks failing\n' >&2
    printf '%s\n' "$eval_output"
    diagnose
    exit 1
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
  [ -n "$last_info" ] && printf 'Reason: %s\n' "$last_info" >&2
  diagnose
  exit 1
fi

info "Full system healthy"
info "Next steps:"
info "- Run scripts/gap_test_alpha.sh"
info "- Inspect /api/health for watcher/worker/db/llm"
