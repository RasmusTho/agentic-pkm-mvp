#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

load_dotenv() {
  if [ -f ".env" ]; then
    set -a
    # shellcheck disable=SC1090
    source ".env"
    set +a
  fi
}

load_dotenv

BOOTSTRAP_STATE="${BOOTSTRAP_STATE:-pending}"
BOOTSTRAP_REASON="${BOOTSTRAP_REASON:-preflight}"
export BOOTSTRAP_STATE BOOTSTRAP_REASON

START_MODE="${START_MODE:-runtime}"
startup_status_path="$ROOT/tmp/startup_status.json"
mkdir -p "$ROOT/tmp"

write_startup_status() {
  local passed="$1"
  local reason="$2"
  export START_MODE
  export PRE_FLIGHT_PASSED="$passed"
  export PRE_FLIGHT_REASON="${reason:-}"
  python - <<'PY' > "$startup_status_path"
import datetime
import json
import os

payload = {
    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    "start_mode": os.environ.get("START_MODE"),
    "llm_provider": os.environ.get("LLM_PROVIDER") or None,
    "preflight_passed": os.environ.get("PRE_FLIGHT_PASSED") == "1",
    "failure_reason": os.environ.get("PRE_FLIGHT_REASON") or None,
    "bootstrap_state": os.environ.get("BOOTSTRAP_STATE") or None,
    "bootstrap_reason": os.environ.get("BOOTSTRAP_REASON") or None,
}
print(json.dumps(payload, ensure_ascii=False))
PY
}

fail_preflight() {
  local reason="$1"
  write_startup_status 0 "$reason"
  echo "ERROR: Preflight failed: $reason" >&2
  exit 1
}

require_vars() {
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      fail_preflight "START_MODE runtime requires $var"
    fi
  done
}

preflight_runtime() {
  require_vars LLM_PROVIDER OPENAI_BASE_URL LLM_MODEL
  if [ "${LLM_PROVIDER_ENFORCE:-}" != "1" ]; then
    fail_preflight "runtime mode requires LLM_PROVIDER_ENFORCE=1"
  fi
  export LLM_PROVIDER_ENFORCE=1
}

preflight_infra() {
  if [ "${LLM_PROVIDER_ENFORCE:-}" != "0" ]; then
    fail_preflight "infra mode requires LLM_PROVIDER_ENFORCE=0"
  fi
  START_WATCHERS=0
  START_WORKER=0
}

preflight_diagnostic() {
  START_WATCHERS=0
  START_WORKER=0
}

run_preflight() {
  case "$START_MODE" in
    infra)
      preflight_infra
      ;;
    runtime)
      preflight_runtime
      ;;
    diagnostic)
      preflight_diagnostic
      ;;
    *)
      fail_preflight "Invalid START_MODE: $START_MODE"
      ;;
  esac
  write_startup_status 1 ""
}

optional_check() {
  local label="$1"
  shift
  if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
    "$@"
    return 0
  fi
  set +e
  "$@"
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    echo "INFO: optional check '$label' failed (ignored for fast start)"
  fi
  return 0
}


START_WATCHERS="${START_WATCHERS:-0}"
START_WORKER="${START_WORKER:-0}"
START_FLIGHT_RECORDER="${START_FLIGHT_RECORDER:-1}"
FLIGHT_RECORDER_INTERVAL="${FLIGHT_RECORDER_INTERVAL:-5}"
FLIGHT_RECORDER_DURATION="${FLIGHT_RECORDER_DURATION:-0}"
VERIFY_ACTIVE="${VERIFY_ACTIVE:-0}"
ALLOW_LEGACY_VAULT="${ALLOW_LEGACY_VAULT:-0}"
HEALTH_ENDPOINT="${HEALTH_ENDPOINT:-http://127.0.0.1:18000/healthz}"
HEALTH_MAX_ATTEMPTS="${HEALTH_MAX_ATTEMPTS:-12}"
HEALTH_SLEEP_SECONDS="${HEALTH_SLEEP_SECONDS:-2}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-5}"
WATCHER_HEARTBEAT_TIMEOUT="${WATCHER_HEARTBEAT_TIMEOUT:-30}"
WORKER_HEARTBEAT_TIMEOUT="${WORKER_HEARTBEAT_TIMEOUT:-30}"

flight_recorder_log_path="$ROOT/tmp/flightrecorder-$(date -u +"%Y%m%d-%H%M%S").log"
flight_recorder_pid=""
if [ "$START_FLIGHT_RECORDER" -eq 1 ]; then
  scripts/flight_recorder.sh --log-path "$flight_recorder_log_path" --interval "$FLIGHT_RECORDER_INTERVAL" --duration "$FLIGHT_RECORDER_DURATION" >/dev/null 2>&1 &
  flight_recorder_pid=$!
  echo "Flight recorder logging to $flight_recorder_log_path"
  for attempt in 1 2 3 4 5; do
    if [ -f "$flight_recorder_log_path" ]; then
      break
    fi
    sleep 0.1
  done
  trap '
    if [ -n "${flight_recorder_pid:-}" ]; then
      kill "$flight_recorder_pid" >/dev/null 2>&1 || true
    fi
  ' EXIT
fi

debug_dump() {
  echo "DEBUG: docker compose ps"
  run_docker_compose ps || true
  echo "DEBUG: docker compose logs --tail=200 watcher"
  run_docker_compose logs --tail=200 watcher || true
  echo "DEBUG: docker compose logs --tail=200 worker"
  run_docker_compose logs --tail=200 worker || true
  echo "DEBUG: docker compose logs --tail=200 api"
  run_docker_compose logs --tail=200 api || true
}

for dir in tmp logs tmp/startup-logs; do
  mkdir -p "$dir"
  if [ ! -w "$dir" ]; then
    uid="$(id -u)"
    gid="$(id -g)"
    echo "ERROR: $dir is not writable." >&2
    echo "Fix with:" >&2
    echo "  sudo chown -R $uid:$gid $dir" >&2
    echo "  sudo chmod -R u+rwX $dir" >&2
    exit 2
  fi
done

startup_log_dir="$ROOT/tmp/startup-logs"
startup_log_path="$startup_log_dir/startup-$(date -u +"%Y%m%dT%H%M%SZ").log"

check_docker_daemon() {
  if docker info >/dev/null 2>&1; then
    return
  fi
  if [ "${AUTO_START_COLIMA:-0}" = "1" ] && command -v colima >/dev/null 2>&1; then
    echo "Docker daemon unreachable; starting colima..." >&2
    colima start >/dev/null 2>&1
    if docker info >/dev/null 2>&1; then
      return
    fi
  fi
  echo "ERROR: Docker daemon is not reachable; ensure it is running and accessible (set AUTO_START_COLIMA=1 to allow starting Colima)." >&2
  exit 1
}


vault_host_path="${VAULT_ROOT:-}"
if [ -z "$vault_host_path" ]; then
  if [ "$ALLOW_LEGACY_VAULT" -ne 1 ]; then
    echo "ERROR: VAULT_ROOT is required (set ALLOW_LEGACY_VAULT=1 to default to ./vault)" >&2
    exit 2
  fi
  vault_host_path="./vault"
fi
if [ ! -d "$vault_host_path" ]; then
  echo "ERROR: Vault root is missing: $vault_host_path" >&2
  exit 1
fi
vault_host_path="$(cd "$vault_host_path" && pwd)"
export VAULT_ROOT="$vault_host_path"

runtime_env_path="${RUNTIME_ENV_PATH:-tmp/runtime.env}"
RUNTIME_ENV_PATH="$runtime_env_path"
bash scripts/export_runtime_env.sh
runtime_env="--env-file $runtime_env_path"

latest_tick_log_path="$ROOT/tmp/latest_watcher_tick_log"
tick_log_path="/app/tmp/watcher_tick-$(date -u +"%Y%m%d-%H%M%S").jsonl"
printf "WATCHER_TICK_LOG_PATH=%s\n" "$tick_log_path" >> "$runtime_env_path"
export WATCHER_TICK_LOG_PATH="$tick_log_path"
printf "%s\n" "$tick_log_path" > "$latest_tick_log_path"

echo "Vault host path: $vault_host_path -> /app/vault"

run_docker_compose() {
  if [ -n "${runtime_env:-}" ]; then
    docker compose $runtime_env "$@"
  else
    docker compose "$@"
  fi
}

run_preflight

alpha_rebuild="${ALPHA_REBUILD:-0}"
alpha_rebuild_pull="${ALPHA_REBUILD_PULL:-0}"
if [ "$alpha_rebuild" -eq 1 ]; then
  build_flags=""
  if [ "$alpha_rebuild_pull" -eq 1 ]; then
    build_flags="--pull"
  fi
  echo "ALPHA_REBUILD: docker compose build $build_flags api worker watcher"
  run_docker_compose build $build_flags api worker watcher
fi

compose_up() {
  local extra=()
  local services=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --build)
        extra+=("--build")
        ;;
      *)
        services+=("$1")
        ;;
    esac
    shift
  done
  run_docker_compose up -d "${extra[@]}" "${services[@]}"
}

append_startup_log() {
  printf "%s\n" "$*" >>"$startup_log_path"
}

log_section() {
  append_startup_log ""
  append_startup_log "=== $1 ==="
}

log_command_output() {
  local title="$1"
  shift
  log_section "$title"
  if [ $# -eq 0 ]; then
    append_startup_log "<no command>"
    return
  fi
  if ! "$@" >>"$startup_log_path" 2>&1; then
    append_startup_log "COMMAND FAILED: $*"
  fi
}

log_service_tail() {
  local service="$1"
  log_section "docker compose logs --tail=200 $service"
  local service_id
  service_id=$(run_docker_compose ps -q "$service" 2>/dev/null || true)
  if [ -n "$service_id" ]; then
    run_docker_compose logs --tail=200 "$service" >>"$startup_log_path" 2>&1 || true
  else
    append_startup_log "service $service is not running, skipping logs"
  fi
}

log_layout_info() {
  log_section "vault layout"
  append_startup_log "inbox: ${layout_inbox:-<missing>}"
  append_startup_log "system: ${layout_system:-<missing>}"
  append_startup_log "layout note: ${layout_note:-<missing>}"
}

log_tick_log_path() {
  log_section "watcher tick log"
  append_startup_log "WATCHER_TICK_LOG_PATH=${WATCHER_TICK_LOG_PATH:-<not set>}"
}

log_flight_recorder_path() {
  log_section "flight recorder"
  if [ -n "${flight_recorder_log_path:-}" ]; then
    append_startup_log "flight recorder log: $flight_recorder_log_path"
  else
    append_startup_log "flight recorder disabled"
  fi
}

log_worker_heartbeat_snapshot() {
  log_section "worker heartbeat"
  if [ -f tmp/worker_heartbeat.json ]; then
    tail -n 20 tmp/worker_heartbeat.json >>"$startup_log_path" 2>&1 || true
  else
    append_startup_log "tmp/worker_heartbeat.json missing"
  fi
}

capture_startup_logs() {
  log_section "timestamp $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  log_command_output "docker info" docker info
  log_command_output "docker compose ps" run_docker_compose ps
  log_service_tail "api"
  log_service_tail "watcher"
  log_service_tail "worker"
  log_layout_info
  log_tick_log_path
  log_flight_recorder_path
  log_worker_heartbeat_snapshot
  append_startup_log ""
  append_startup_log "startup log available at: $startup_log_path"
}

run_db_probe() {
  local skip="${SKIP_DB_PROBE:-0}"
  if [ "$skip" -eq 1 ]; then
    return
  fi
  echo "--- DB PROBE ---"
  local db_cid
  db_cid=$(run_docker_compose ps -q db)
  if [ -z "$db_cid" ]; then
    echo "ERROR: db container not found" >&2
    run_docker_compose ps
    exit 1
  fi
  local db_user
  local db_name
  local db_pwd
  db_user=$(docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_USER"')
  db_name=$(docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_DB"')
  db_pwd=$(docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_PASSWORD"')
  db_user=${db_user:-app}
  db_name=${db_name:-app}
  local db_start
  db_start=$SECONDS
  local db_ready=0
  while [ $((SECONDS - db_start)) -lt 30 ]; do
    if docker exec "$db_cid" env PGPASSWORD="$db_pwd" pg_isready -U "$db_user" -d "$db_name" >/dev/null 2>&1; then
      db_ready=1
      break
    fi
    sleep 1
  done
  if [ "$db_ready" -ne 1 ]; then
    echo "ERROR: PostgreSQL did not become ready in 30 seconds" >&2
    run_docker_compose ps
    run_docker_compose logs --tail=200 db || true
    exit 1
  fi
  echo "DB credentials: user=$db_user db=$db_name"
  docker exec "$db_cid" env PGPASSWORD="$db_pwd" psql -U "$db_user" -d "$db_name" -c "select current_user, current_database();"
}

run_worker_probe() {
  local skip="${SKIP_WORKER_PROBE:-0}"
  if [ "$skip" -eq 1 ]; then
    return
  fi
  echo "--- WORKER HEARTBEAT ---"
  local worker_start
  worker_start=$SECONDS
  local heartbeat_ready=0
  while [ $((SECONDS - worker_start)) -lt "$WORKER_HEARTBEAT_TIMEOUT" ]; do
    if [ -s tmp/worker_heartbeat.json ]; then
      heartbeat_ready=1
      break
    fi
    sleep 1
  done
  if [ "$heartbeat_ready" -ne 1 ]; then
    echo "ERROR: worker heartbeat file missing after $WORKER_HEARTBEAT_TIMEOUT seconds" >&2
    run_docker_compose logs --tail=200 worker || true
    exit 1
  fi
  tail -n 1 tmp/worker_heartbeat.json
}

wait_for_healthz() {
  local endpoint="${HEALTH_ENDPOINT}"
  local attempt=1
  while [ "$attempt" -le "$HEALTH_MAX_ATTEMPTS" ]; do
    if curl -sSf --max-time "$HEALTH_TIMEOUT_SECONDS" "$endpoint" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$HEALTH_SLEEP_SECONDS"
    attempt=$((attempt + 1))
  done
  echo "ERROR: /healthz did not respond on $endpoint after $HEALTH_MAX_ATTEMPTS attempts" >&2
  exit 1
}

ollama_preflight_ok=0
run_ollama_preflight() {
  if run_docker_compose exec -T api sh -c 'python - <<'"'"'PY'"'"'
from __future__ import annotations
import os, sys
import httpx

try:
    base = os.environ.get("OLLAMA_URL")
    if not base:
        print("INFO: optional preflight failed: OLLAMA_URL missing", file=sys.stderr)
        raise SystemExit(0)
    model = os.environ.get("OLLAMA_EMBED_MODEL") or os.environ.get("EMBED_MODEL", "nomic-embed-text:latest")
    with httpx.Client(timeout=10.0) as client:
        tags_resp = client.get(f"{base}/api/tags")
        tags_resp.raise_for_status()
        models = tags_resp.json().get("models") or []
        print(f"Ollama tags ok ({len(models)} models)")
        embed_resp = client.post(
            f"{base}/api/embed",
            json={"model": model, "input": ["startup-check"], "truncate": True},
        )
        embed_resp.raise_for_status()
        data = embed_resp.json()
        embeddings = data.get("embeddings") or data.get("embedding")
        if not embeddings:
            raise SystemExit(0)
        entry = embeddings[0] if isinstance(embeddings, list) and isinstance(embeddings[0], (list, tuple)) else embeddings
        print(f"Ollama embed dim: {len(entry)}")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY'; then
    echo "Ollama preflight succeeded"
    ollama_preflight_ok=1
 else
   echo "WARNING: Ollama preflight failed; skipping /api/ask bootstrap" >&2
   ollama_preflight_ok=0
 fi
}


if [ "$START_MODE" = "diagnostic" ]; then
  echo "START_MODE=diagnostic: running API in the foreground (no detach)"
  run_docker_compose up --build db api
  exit $?
fi

compose_up --build db api
run_db_probe
wait_for_healthz

store_stats_json=$(run_docker_compose exec -T api python -m app.cli store stats --json || true)
extract_stat() {
  local key="$1"
STAT_KEY="$key" STORE_STATS_JSON="$store_stats_json" python - <<'PY'
import json, os
raw = os.environ.get("STORE_STATS_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
print(payload.get(os.environ.get("STAT_KEY", "")) or 0)
PY
}
objects_before=$(extract_stat objects)
vectors_before=$(extract_stat vectors)
outbox_count=0
if outbox_result=$(run_docker_compose exec -T api python - <<'PY'
from app.events.outbox import read_outbox
try:
    print(len(read_outbox()))
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}")
PY
); then
  outbox_count=$(echo "$outbox_result" | tr -d '[:space:]')
fi
objects_before=${objects_before:-0}
vectors_before=${vectors_before:-0}
outbox_count=${outbox_count:-0}
if [ "$objects_before" -le 0 ] && [ "$outbox_count" -le 0 ]; then
  BOOTSTRAP_STATE="empty"
  BOOTSTRAP_REASON="no objects ingested yet"
  echo "BOOTSTRAP: empty system, awaiting first ingest"
else
  BOOTSTRAP_STATE="active"
  BOOTSTRAP_REASON="objects or outbox events detected"
fi
export BOOTSTRAP_STATE BOOTSTRAP_REASON
write_startup_status 1 ""

layout_json=""
if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
  layout_json=$(run_docker_compose exec -T api python -m app.cli vault-layout-ensure --vault-root /app/vault --json)
else
  set +e
  layout_json=$(run_docker_compose exec -T api python -m app.cli vault-layout-ensure --vault-root /app/vault --json) || layout_json=""
  status=$?
  set -e
  if [ "$status" -ne 0 ]; then
    echo "INFO: vault layout ensure failed (ignored for fast start)"
  fi
fi


extract_layout_field() {
  local key="$1"
  LAYOUT_JSON="$layout_json" LAYOUT_KEY="$key" python - <<'PY'
from __future__ import annotations
import json, os, sys
try:
    raw = os.environ.get("LAYOUT_JSON", "")
    payload = json.loads(raw)
    print(payload.get(os.environ.get("LAYOUT_KEY", ""), ""))
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
}

layout_inbox=$(extract_layout_field inbox_folder)
layout_system=$(extract_layout_field system_folder)
layout_note=$(extract_layout_field layout_note)

if [ -n "$layout_inbox" ]; then
  printf "VAULT_INBOX_DIR_REL=%s\n" "$layout_inbox" >> "$runtime_env_path"
fi
if [ -n "$layout_system" ]; then
  printf "VAULT_SYSTEM_DIR_REL=%s\n" "$layout_system" >> "$runtime_env_path"
fi

if [ -n "$layout_inbox" ] && [ -n "$layout_system" ]; then
  echo "--- VAULT LAYOUT ---"
  echo "inbox: $layout_inbox"
  echo "system: $layout_system"
  echo "layout note: $layout_note"
fi



optional_check "Ollama preflight" run_ollama_preflight

services_to_start=()
if [ "$START_WATCHERS" -eq 1 ]; then
  services_to_start+=("watcher")
fi
if [ "$START_WORKER" -eq 1 ]; then
  services_to_start+=("worker")
fi
if [ "${#services_to_start[@]}" -gt 0 ]; then
  compose_up --build "${services_to_start[@]}"
fi

if [ "$START_WORKER" -eq 1 ]; then
  run_worker_probe
fi

reset_runtime_state="${RESET_RUNTIME_STATE:-1}"
if [ "$reset_runtime_state" -eq 1 ] && { [ "$START_WATCHERS" -eq 1 ] || [ "$START_WORKER" -eq 1 ]; }; then
  run_docker_compose exec -T api sh -c 'rm -f /app/tmp/index-outbox.jsonl /app/tmp/watcher_heartbeat.json /app/tmp/worker_heartbeat.json'
  if [ "$START_WATCHERS" -eq 1 ]; then
    run_docker_compose exec -T watcher sh -c 'rm -f /app/tmp/watcher_heartbeat.json' || true
  fi
fi

if [ "$START_WATCHERS" -eq 1 ]; then
  watcher_ready=0
  watcher_deadline=$((SECONDS + WATCHER_HEARTBEAT_TIMEOUT))
  while [ $SECONDS -lt $watcher_deadline ]; do
    if run_docker_compose exec -T watcher sh -c 'test -s /app/tmp/watcher_heartbeat.json' >/dev/null 2>&1; then
      watcher_ready=1
      break
    fi
    sleep 2
  done
  if [ "$watcher_ready" -ne 1 ]; then
    echo "ERROR: watcher heartbeat not detected at /app/tmp/watcher_heartbeat.json after $WATCHER_HEARTBEAT_TIMEOUT seconds" >&2
    exit 1
  fi
fi

ready_payload=$(curl -sS http://127.0.0.1:18000/readyz || true)
readiness_state=$(READY_JSON="$ready_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("READY_JSON", "")
    data = json.loads(raw)
    detail = data.get("detail") or {}
    state = data.get("state") or detail.get("state") or "unknown"
    reason = data.get("reason") or detail.get("reason") or ""
    if reason:
        print(f"{state} ({reason})")
    else:
        print(state)
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}")
    sys.exit(0)
PY
)

api_health_payload=$(curl -sS http://127.0.0.1:18000/api/health || true)
update_health_state() {
  api_health_ok=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("API_HEALTH_JSON", "")
    data = json.loads(raw)
    value = data.get("ok")
    print("true" if value else "false")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  api_health_required_ok=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("API_HEALTH_JSON", "")
    data = json.loads(raw)
    value = data.get("required_ok")
    print("true" if value else "false")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  api_health_index_rebuild=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("API_HEALTH_JSON", "")
    data = json.loads(raw)
    actions = data.get("suggested_actions") or []
    needed = False
    for action in actions:
        if isinstance(action, dict) and action.get("id") == "index_rebuild":
            severity = str(action.get("severity") or "").lower()
            if severity == "required":
                needed = True
                break
    print("1" if needed else "0")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  api_health_failed=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("API_HEALTH_JSON", "")
    data = json.loads(raw)
    checks = data.get("checks") or {}
    items = []
    for key, val in checks.items():
        if isinstance(val, dict) and not val.get("ok", True):
            detail = val.get("detail")
            if detail:
                items.append(f"{key}: {detail}")
            else:
                items.append(key)
    print(", ".join(items))
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  api_health_failed=${api_health_failed:-none}
}

update_health_state

auto_bootstrap="${AUTO_BOOTSTRAP:-0}"
if [ "$auto_bootstrap" -eq 1 ]; then
  set +e
  settings_validate_json=$(run_docker_compose exec -T api python -m app.cli settings validate --json)
  settings_validate_status=$?
  set -e
  if [ "$settings_validate_status" -ne 0 ]; then
    echo "ERROR: settings validate failed" >&2
    echo "$settings_validate_json" >&2
    echo "Run: docker compose exec -T api python -m app.cli settings validate --json" >&2
    exit 1
  fi
fi

index_rebuild_status="skipped"
if [ "$BOOTSTRAP_STATE" = "empty" ]; then
  echo "INDEX: not required (no objects yet)"
  index_rebuild_status="skipped (empty)"
elif [ "$api_health_index_rebuild" -eq 1 ] && [ "$auto_bootstrap" -ne 1 ]; then
  index_rebuild_status="required"
  if [ "$VERIFY_ACTIVE" -eq 1 ]; then
    echo "INDEX: required (AUTO_BOOTSTRAP=1 to run)" >&2
    echo "Run: docker compose exec -T api python -m app.cli index rebuild --profile default" >&2
    debug_dump
    exit 1
  else
    echo "INFO: index rebuild is required but deferred (AUTO_BOOTSTRAP=1 to run)"
  fi
fi

if ! run_docker_compose exec -T api sh -c '[ -d /app/vault ]' >/dev/null 2>&1; then
  echo "ERROR: /app/vault mount is missing inside the api container" >&2
  exit 1
fi

vault_note_count=$(run_docker_compose exec -T api sh -c 'find /app/vault -name "*.md" | wc -l' | tr -d '[:space:]')
vault_note_count=${vault_note_count:-0}
if [ "$vault_note_count" -le 0 ]; then
  echo "INFO: /app/vault contains no markdown files for the watcher scope"
else
  echo "INFO: /app/vault contains $vault_note_count markdown files"
fi

ingest_run="no"
max_notes="${BOOTSTRAP_INGEST_MAX_NOTES:-500}"
object_count="$objects_before"
vector_count="$vectors_before"
ingest_summary_json="{}"
if [ "$objects_before" -le 0 ]; then
  ingest_run="yes"
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    set +e
    ingest_summary_json=$(run_docker_compose exec -T api env STORE_BACKEND=pg DATABASE_URL=postgresql://app:app@db:5432/app python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force --json)
    ingest_status=$?
    set -e
    if [ "$ingest_status" -ne 0 ]; then
      echo "INFO: bootstrap ingest failed but will be retried after first ingest (empty system)"
      ingest_run="no"
      ingest_summary_json="{}"
    fi
  else
    ingest_summary_json=$(run_docker_compose exec -T api env STORE_BACKEND=pg DATABASE_URL=postgresql://app:app@db:5432/app python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force --json)
  fi
  store_stats_json=$(run_docker_compose exec -T api python -m app.cli store stats --json || true)
  objects_after=$(extract_stat objects)
  vectors_after=$(extract_stat vectors)
  object_count="$objects_after"
  vector_count="$vectors_after"
fi

if [ "$auto_bootstrap" -eq 1 ]; then
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    echo "INDEX: not required (no objects yet)"
  else
    api_health_payload=$(curl -sS http://127.0.0.1:18000/api/health || true)
    update_health_state
    if [ "$api_health_index_rebuild" -eq 1 ]; then
      echo "INDEX REBUILD: running"
      set +e
      run_docker_compose exec -T api sh -lc "python -m app.cli index rebuild --profile default"
      rebuild_status=$?
      set -e
      if [ "$rebuild_status" -ne 0 ]; then
        echo "INDEX REBUILD: failed (exit $rebuild_status)" >&2
        debug_dump
        exit 1
      fi
      index_rebuild_status="ran"
      api_health_payload=$(curl -sS http://127.0.0.1:18000/api/health || true)
      update_health_state
      if [ "$api_health_index_rebuild" -eq 1 ]; then
        echo "INDEX REBUILD: failed (still required)" >&2
        debug_dump
        exit 1
      fi
    else
      echo "INDEX REBUILD: skipped (not required)"
    fi
  fi
fi

ingested_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("INGEST_JSON", "")
    payload = json.loads(raw)
    print(payload.get("ingested", 0) or 0)
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
skipped_locked_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("INGEST_JSON", "")
    payload = json.loads(raw)
    print(payload.get("skipped_locked", 0) or 0)
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)

search_payload=$(curl -sS "http://127.0.0.1:18000/search?q=test&k=3" || true)
search_results=$(SEARCH_JSON="$search_payload" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("SEARCH_JSON", "")
    payload = json.loads(raw)
    print(len(payload.get("results") or []))
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
if [ "$BOOTSTRAP_STATE" = "active" ]; then
  if [ "$ingest_run" = "yes" ] && [ "$search_results" -eq 0 ]; then
    if [ "$ingested_count" -eq 0 ] && [ "$skipped_locked_count" -gt 0 ]; then
      echo "WARNING: search returned zero results after bootstrap ingest; all candidates were locked (errno=35)."
    else
      if [ "$VERIFY_ACTIVE" -eq 1 ]; then
        echo "ERROR: search returned zero results after bootstrap ingest; check vault mount/store mismatch" >&2
        exit 1
      else
        echo "INFO: search returned zero results after bootstrap ingest; run 'make verify' for strict checks"
      fi
    fi
  fi
else
  echo "BOOTSTRAP: empty system, awaiting first ingest"
fi

if [ "$VERIFY_ACTIVE" -eq 1 ]; then
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    echo "VERIFY: requires ingested objects; system is empty" >&2
    exit 1
  fi
  if [ "$ollama_preflight_ok" -ne 1 ]; then
    echo "VERIFY: Ollama preflight must succeed (set OLLAMA_URL/LLM_PROVIDER)" >&2
    exit 1
  fi
  if [ "$object_count" -le 0 ]; then
    echo "VERIFY: index missing objects" >&2
    exit 1
  fi
  ask_status=$(curl -sS -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:18000/api/ask -H 'Content-Type: application/json' -d '{"query":"startup verify"}' || true)
  if [ "$ask_status" != "200" ]; then
    echo "VERIFY: /api/ask returned $ask_status" >&2
    exit 1
  fi
fi

alpha_bootstrap="${ALPHA_BOOTSTRAP:-0}"
bootstrap_next="none"
index_doctor_status="skipped"
index_issue_count=0
if [ "$alpha_bootstrap" -eq 1 ]; then
  index_doctor_json=$(run_docker_compose exec -T api python -m app.cli index doctor --json || true)
  index_doctor_status=$(INDEX_JSON="$index_doctor_json" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("INDEX_JSON", "")
    payload = json.loads(raw)
    print(payload.get("status") or "unknown")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  index_issue_count=$(INDEX_JSON="$index_doctor_json" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("INDEX_JSON", "")
    payload = json.loads(raw)
    issues = payload.get("issues") or []
    print(len(issues))
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  rebuild_safe=$(INDEX_JSON="$index_doctor_json" OBJECT_COUNT="$object_count" VECTOR_COUNT="$vector_count" python - <<'PY'
import json, os, sys
try:
    raw = os.environ.get("INDEX_JSON", "")
    payload = json.loads(raw)
    issues = payload.get("issues") or []
    warnings = payload.get("warnings") or []
    issue_text = " ".join([str(item).lower() for item in (issues + warnings)])
    objects = int(os.environ.get("OBJECT_COUNT", "0") or 0)
    vectors = int(os.environ.get("VECTOR_COUNT", "0") or 0)
    safe = (
        objects > 0
        and vectors == 0
        and ("embeddings must be rebuilt" in issue_text or "no recorded embedding identity" in issue_text or "empty index" in issue_text)
    )
    print("1" if safe else "0")
except Exception as exc:
    print(f"INFO: optional preflight failed: {exc}", file=sys.stderr)
    sys.exit(0)
PY
)
  if [ "$rebuild_safe" -eq 1 ]; then
    run_docker_compose exec -T api python -m app.cli index rebuild --backend pg --json || true
    bootstrap_next="re-run: python -m app.cli index doctor --json"
  elif [ "$index_doctor_status" != "ok" ]; then
    bootstrap_next="python -m app.cli index rebuild --backend pg"
  fi
fi

if [ "$START_WATCHERS" -eq 1 ]; then
  watchers_status="enabled"
else
  watchers_status="disabled"
fi
if [ "$START_WORKER" -eq 1 ]; then
  worker_status="enabled"
else
  worker_status="disabled"
fi
capture_startup_logs
echo "Startup log: $startup_log_path"
echo "Watcher tick log: ${WATCHER_TICK_LOG_PATH:-<not set>}"
echo "Flight recorder log: ${flight_recorder_log_path:-<disabled>}"
echo "Tail: docker compose exec watcher sh -lc 'tail -n 20 \"${WATCHER_TICK_LOG_PATH:-/app/tmp/watcher_tick.jsonl}\"'"

echo "--- STARTUP COMPLETE ---"

cat <<SUMMARY
SUMMARY:
  healthz OK
  readyz: $readiness_state
  api health ok: $api_health_ok
  api health required_ok: $api_health_required_ok
  api health failed: $api_health_failed
  vault notes: $vault_note_count
  store objects: $object_count
  vector entries: $vector_count
  ingest run: $ingest_run
  search results: $search_results
  index rebuild: $index_rebuild_status
  index doctor: $index_doctor_status (issues=$index_issue_count)
  bootstrap next: $bootstrap_next
  watchers: $watchers_status
  worker: $worker_status
  note: /api/health ok=false can be expected when optional tools (e.g., ffmpeg) are missing; Stage0 ingest/search/ask can still work.
  next: curl -sS http://127.0.0.1:18000/search?q=test&k=3
SUMMARY

if [ "$START_WATCHERS" -eq 1 ]; then
  echo "Stop watcher: docker compose exec watcher sh -c 'touch /app/tmp/WATCHER_STOP'"
fi
echo "URLs: http://127.0.0.1:18000  |  http://127.0.0.1:18000/api/status"
