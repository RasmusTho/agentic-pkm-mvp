#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

startup_status_path="$ROOT/tmp/startup_status.json"

log() {
  printf "[cold-boot] %s\n" "$*"
}

fail() {
  log "ERROR: $*"
  log "Refer to $startup_status_path for details"
  exit 1
}

ensure_dotenv() {
  if [ ! -f ".env" ]; then
    fail ".env is required before a cold boot"
  fi
}

ensure_docker() {
  if ! docker info >/dev/null 2>&1; then
    fail "docker info failed; ensure Docker/Colima is running"
  fi
}

clean_all() {
  log "Running docker compose down -v"
  docker compose down -v >/dev/null 2>&1 || true
}

run_start_mode() {
  local mode="$1"
  log "Starting system in START_MODE=$mode"
  START_MODE="$mode" START_FLIGHT_RECORDER=1 scripts/start_full_system.sh
}

verify_startup_status() {
  local mode="$1"
  local require_provider="${2:-0}"
  if [ ! -f "$startup_status_path" ]; then
    fail "startup_status.json missing after START_MODE=$mode"
  fi
  EXPECTED_MODE="$mode" REQUIRE_PROVIDER="$require_provider" STARTUP_STATUS_PATH="$startup_status_path" python - <<'PY'
import json, os, sys
path = os.environ['STARTUP_STATUS_PATH']
mode = os.environ['EXPECTED_MODE']
require_provider = os.environ.get('REQUIRE_PROVIDER') == '1'
try:
    payload = json.load(open(path, encoding='utf-8'))
except Exception as exc:
    print(f'ERROR reading {path}: {exc}', file=sys.stderr)
    sys.exit(1)
start_mode = payload.get('start_mode')
if start_mode != mode:
    print(f'Unexpected start_mode: {start_mode!r} (expected {mode!r})', file=sys.stderr)
    sys.exit(1)
if not payload.get('preflight_passed'):
    reason = payload.get('failure_reason') or '<none>'
    print(f'Preflight failed: {reason}', file=sys.stderr)
    sys.exit(1)
if require_provider and not payload.get('llm_provider'):
    print('llm_provider missing in startup_status.json', file=sys.stderr)
    sys.exit(1)
print('ok', end='')
PY
  log "startup_status.json indicates $mode preflight OK"
}

check_healthz() {
  local mode="$1"
  if ! curl -sSf --max-time 5 http://127.0.0.1:18000/healthz >/dev/null 2>&1; then
    fail "/healthz unreachable after START_MODE=$mode"
  fi
  log "/healthz OK for START_MODE=$mode"
}

main() {
  ensure_dotenv
  clean_all
  ensure_docker

  run_start_mode infra
  verify_startup_status infra 0
  check_healthz infra

  log "Tearing down infra containers"
  docker compose down >/dev/null 2>&1 || true

  run_start_mode runtime
  verify_startup_status runtime 1
  check_healthz runtime

  log "Cold boot successful: runtime mode healthy"
}

main
