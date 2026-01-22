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
    llm_check_json=""
    set +e
    llm_check_json=$(run_docker_compose exec -T api python -m app.cli llm check --json --strict)
    set -e
    llm_check_info=$(LLM_CHECK_JSON="$llm_check_json" python - <<'PY'
import json, os
raw = os.environ.get('LLM_CHECK_JSON', '')
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
ok = payload.get('ok')
if isinstance(ok, bool):
    ok_val = 1 if ok else 0
else:
    ok_val = 1 if str(ok).lower() in {'1', 'true', 'yes', 'on'} else 0
print(ok_val)
print(payload.get('url') or '')
print((payload.get('error') or '').replace('\n', ' '))
print(int(payload.get('latency_ms', 0) or 0))
PY
    )
    IFS=$'\n' read -r llm_ok llm_url llm_error llm_latency_ms <<<"$llm_check_info"
    llm_ok=${llm_ok:-0}
    if [ "$llm_ok" -ne 1 ]; then
      echo "LLM CHECK FAILED: url=${llm_url:-<missing>} error=${llm_error:-<no error>}" >&2
      echo "Ollama unreachable. If Ollama runs on host, ensure it listens on a reachable interface (e.g., OLLAMA_HOST=0.0.0.0:11434) or point OLLAMA_URL to a reachable endpoint." >&2
      fail "llm check failed"
    fi
    log "Rebuilding index for active bootstrap"
    set +e
    rebuild_summary=$(run_docker_compose exec -T api python -m app.cli index rebuild --json --strict)
    rebuild_status=$?
    set -e
    index_rebuild_meta=$(REBUILD_SUMMARY_JSON="$rebuild_summary" python - <<'PY'
import json
import os
raw = os.environ.get("REBUILD_SUMMARY_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
errors = payload.get("errors") or []
top_errors = errors[:5]
print(payload.get("error_count") or 0)
print(payload.get("failures_path") or "")
print(json.dumps(top_errors, ensure_ascii=False))
PY
    IFS=$'\n' read -r index_rebuild_error_count index_rebuild_failures_path index_rebuild_errors_json <<<"$index_rebuild_meta"
    index_rebuild_error_count=${index_rebuild_error_count:-0}
    index_rebuild_errors_json=${index_rebuild_errors_json:-[]}
    failures_path_display="${index_rebuild_failures_path:-<missing>}"
    if [ "$rebuild_status" -ne 0 ] || [ "$index_rebuild_error_count" -gt 0 ]; then
      echo "INDEX REBUILD FAILED: status=$rebuild_status errors=$index_rebuild_error_count failures_path=$failures_path_display" >&2
      if [ "${index_rebuild_errors_json:-[]}" != "[]" ]; then
        echo "INDEX REBUILD ERRORS:" >&2
        REBUILD_ERRORS_JSON="$index_rebuild_errors_json" python - <<'PY'
from __future__ import annotations
import json, os
errors = json.loads(os.environ.get("REBUILD_ERRORS_JSON", "[]"))
for err in errors:
    object_id = err.get("object_id") or "<unknown>"
    stage = err.get("stage") or "<stage>"
    exception_type = err.get("exception_type") or "<exception>"
    source_ref = err.get("source_ref") or "<no source>"
    print(f"  - object_id={object_id} stage={stage} exception={exception_type} source_ref={source_ref}")
PY
      fi
      fail "index rebuild failed"
    fi
    log "INDEX REBUILD succeeded"
  else
    log "Skipping index rebuild for bootstrap state $bootstrap_state"
  fi

  verify_api_ask
  log "Cold start successful: runtime mode healthy"
}

main
