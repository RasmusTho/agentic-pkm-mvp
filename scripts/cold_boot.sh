#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

startup_status_path="$ROOT/tmp/startup_status.json"
runtime_env_path="${RUNTIME_ENV_PATH:-tmp/runtime.env}"

log() {
  printf "[cold-start] %s\n" "$*"
}

fail() {
  log "ERROR: $*"
  log "Refer to $startup_status_path for details"
  exit 1
}

ensure_dotenv() {
  if [ ! -f ".env" ]; then
    fail ".env is required before a cold start"
  fi
}

ensure_llm_provider() {
  if [ -z "${LLM_PROVIDER:-}" ]; then
    fail "LLM_PROVIDER must be set for cold start"
  fi
}

ensure_docker() {
  if ! docker info >/dev/null 2>&1; then
    fail "docker info failed; ensure Docker/Colima is running"
  fi
}

ensure_ollama_service() {
  local url="${OLLAMA_URL:-}"
  if [ -z "$url" ]; then
    fail "OLLAMA_URL must be set for cold start"
  fi
  if ! command -v ollama >/dev/null 2>&1; then
    fail "ollama CLI is required for cold start"
  fi
  local tags_url="${url%/}/api/tags"
  if ! curl -sSf --max-time 5 "$tags_url" >/dev/null 2>&1; then
    fail "Ollama API unreachable at $tags_url"
  fi
}

ensure_embedding_model() {
  local model="nomic-embed-text:latest"
  if ollama list | grep -q "$model"; then
    log "Embedding model $model already available"
    return
  fi
  log "Pulling embedding model $model"
  ollama pull "$model"
}

clean_all() {
  log "Running docker compose down -v"
  docker compose down -v >/dev/null 2>&1 || true
}

run_docker_compose() {
  if [ -f "$runtime_env_path" ]; then
    docker compose --env-file "$runtime_env_path" "$@"
  else
    docker compose "$@"
  fi
}

run_start_mode() {
  local mode="$1"
  log "Starting system in START_MODE=$mode"
  START_MODE="$mode" START_FLIGHT_RECORDER=1 scripts/start_full_system.sh
}

verify_startup_status() {
  local mode="$1"
  local require_provider="${2:-0}"
  local expected_bootstrap="${3:-}"
  if [ ! -f "$startup_status_path" ]; then
    fail "startup_status.json missing after START_MODE=$mode"
  fi
  EXPECTED_MODE="$mode" REQUIRE_PROVIDER="$require_provider" EXPECTED_BOOTSTRAP="$expected_bootstrap" STARTUP_STATUS_PATH="$startup_status_path" python - <<'PY'
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
expected_bootstrap = os.environ.get('EXPECTED_BOOTSTRAP', '')
bootstrap_state = payload.get('bootstrap_state')
if expected_bootstrap and bootstrap_state != expected_bootstrap:
    print(f'bootstrap_state {bootstrap_state!r} does not match expected {expected_bootstrap!r}', file=sys.stderr)
    sys.exit(1)
print('ok', end='')
PY
  log "startup_status.json indicates $mode preflight OK"
}

check_healthz() {
  if ! curl -sSf --max-time 5 http://127.0.0.1:18000/healthz >/dev/null 2>&1; then
    fail "/healthz unreachable"
  fi
  log "/healthz OK"
}

check_readyz() {
  if ! curl -sSf --max-time 5 http://127.0.0.1:18000/readyz >/dev/null 2>&1; then
    fail "/readyz unreachable"
  fi
  log "/readyz OK"
}

get_bootstrap_state() {
  python - <<'PY'
import json, os, sys
path = os.environ.get('STARTUP_STATUS_PATH', '')
if not path:
    print('unknown')
    sys.exit(0)
try:
    payload = json.load(open(path, encoding='utf-8'))
except Exception as exc:
    print(f'error reading {path}: {exc}', file=sys.stderr)
    sys.exit(1)
print(payload.get('bootstrap_state') or 'unknown')
PY
}

verify_api_ask() {
  local status
  status=$(curl -sS -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:18000/api/ask -H 'Content-Type: application/json' -d '{"query":"cold start check"}' || true)
  if [ "$status" != "200" ]; then
    fail "/api/ask returned $status"
  fi
  log "/api/ask OK"
}

main() {
  ensure_dotenv
  clean_all
  ensure_docker
  ensure_llm_provider
  ensure_ollama_service
  ensure_embedding_model

  run_start_mode runtime
  check_healthz
  check_readyz
  verify_startup_status runtime 1 active

  local bootstrap_state
  bootstrap_state=$(STARTUP_STATUS_PATH="$startup_status_path" get_bootstrap_state)
  log "BOOTSTRAP_STATE=$bootstrap_state"
  if [ "$bootstrap_state" = "active" ]; then
    log "Rebuilding index for active bootstrap"
    run_docker_compose exec -T api python -m app.cli index rebuild --profile default
  else
    log "Skipping index rebuild for bootstrap state $bootstrap_state"
  fi

  verify_api_ask
  log "Cold start successful: runtime mode healthy"
}

main
