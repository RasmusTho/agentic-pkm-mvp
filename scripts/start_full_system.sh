#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

app_code_bind_overlay=""
if [ "${APP_CODE_BIND_MOUNT:-1}" != "0" ]; then
  app_code_bind_overlay=":docker-compose.app-bind.yml"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker is required for scripts/start_full_system.sh. Install Docker Desktop or make docker available on PATH, then retry." >&2
  exit 127
fi

source "scripts/lib/load_env_defaults.sh"

# Load channel-specific local env override BEFORE base defaults so that
# per-channel vault paths (which may contain spaces) take precedence.
# Operators create .env.dev.local (or .env.test.local) with channel-specific
# VAULT_ROOT and layout vars; these files are gitignored and never committed.
# load_env_defaults_file handles paths with spaces safely (Python-based parser).
_pkm_caller_vault_root_set=0
if [ -n "${VAULT_ROOT+x}" ]; then
  _pkm_caller_vault_root_set=1
fi
_pkm_channel_vault_root_set=0
_pkm_initial_channel="${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}"
_pkm_initial_channel_lower="$(printf '%s' "${_pkm_initial_channel}" | tr '[:upper:]' '[:lower:]' | xargs 2>/dev/null || printf '%s' "${_pkm_initial_channel}")"
if [ -n "${_pkm_initial_channel_lower:-}" ]; then
  load_env_defaults_file ".env.${_pkm_initial_channel_lower}.local"
  if [ -n "${VAULT_ROOT+x}" ]; then
    _pkm_channel_vault_root_set=1
  fi
fi
unset _pkm_initial_channel _pkm_initial_channel_lower

load_env_defaults_file ".env"
load_env_defaults_file "config/runtime.defaults.env"
_pkm_deploy_pin_channel="${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}"
_pkm_deploy_pin_channel="$(printf '%s' "${_pkm_deploy_pin_channel}" | tr '[:upper:]' '[:lower:]' | xargs 2>/dev/null || printf '%s' "${_pkm_deploy_pin_channel}")"
case "${_pkm_deploy_pin_channel:-}" in
  dev|test|prod)
    load_env_defaults_file "config/deploy/${_pkm_deploy_pin_channel}.env"
    ;;
esac
unset _pkm_deploy_pin_channel

if [ "$_pkm_caller_vault_root_set" -eq 0 ] && [ "$_pkm_channel_vault_root_set" -eq 0 ]; then
  # A bare start with no caller- or channel-selected vault must stay in the
  # no-vault idle posture. Generic repo .env can still provide shared defaults
  # (LLM, DB, ports), but it must not silently bind an operator vault.
  unset VAULT_ROOT
  unset VAULT_HOST_ROOT
fi

compose_up_build_args=("--build")
if [ "${APP_CODE_BIND_MOUNT:-1}" = "0" ]; then
  compose_up_build_args=()
fi
unset _pkm_caller_vault_root_set _pkm_channel_vault_root_set

source "scripts/lib/runtime_endpoint_probe.sh"
source "scripts/lib/start_full_system_env.sh"
apply_start_full_system_defaults

if [ -n "${DATABASE_URL:-}" ] && [ -z "${DB_DSN:-}" ]; then
  DB_DSN="$DATABASE_URL"
fi
export DATABASE_URL="${DATABASE_URL:-}" DB_DSN="${DB_DSN:-}"

unset INDEX_REBUILD_SUMMARY INDEX_REBUILD_FAILURES_PATH

BOOTSTRAP_STATE="${BOOTSTRAP_STATE:-pending}"
BOOTSTRAP_REASON="${BOOTSTRAP_REASON:-preflight}"
export BOOTSTRAP_STATE BOOTSTRAP_REASON

START_MODE="${START_MODE:-runtime}"
PHASE="${PHASE:-init}"
LAST_OK_PHASE="${LAST_OK_PHASE:-}"
EXIT_CODE="${EXIT_CODE:-}"
EXIT_REASON="${EXIT_REASON:-}"
export PHASE LAST_OK_PHASE EXIT_CODE EXIT_REASON
startup_status_path="$ROOT/tmp/startup_status.json"
mkdir -p "$ROOT/tmp"

readiness_state="unknown"
api_health_ok="false"
api_health_required_ok="false"
api_health_failed="none"
vault_note_count="unknown"
object_count=0
vector_count=0
ingest_run="no"
search_results=0
index_rebuild_status="skipped"
index_doctor_status="skipped"
index_issue_count=0
bootstrap_next="none"
startup_watchdog_pid=""
obsidian_gate_enabled="false"
obsidian_gate_ok="not_run"
obsidian_gate_detail=""
startup_succeeded="false"
runtime_verified="false"
operator_interrupted="false"
ollama_endpoint_repaired="false"
ollama_endpoint_drift="false"
ollama_configured_base_url=""
ollama_effective_base_url=""
ollama_endpoint_persist_hint=""
export OBSIDIAN_GATE_ENABLED="$obsidian_gate_enabled"
export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
export STARTUP_SUCCEEDED="$startup_succeeded"
export RUNTIME_VERIFIED="$runtime_verified"
export OPERATOR_INTERRUPTED="$operator_interrupted"
export OLLAMA_ENDPOINT_REPAIRED="$ollama_endpoint_repaired"
export OLLAMA_ENDPOINT_DRIFT="$ollama_endpoint_drift"
export OLLAMA_CONFIGURED_BASE_URL="$ollama_configured_base_url"
export OLLAMA_EFFECTIVE_BASE_URL="$ollama_effective_base_url"
export OLLAMA_ENDPOINT_PERSIST_HINT="$ollama_endpoint_persist_hint"

write_startup_status() {
  local passed="${1:-${PRE_FLIGHT_PASSED:-0}}"
  local reason="${2:-${PRE_FLIGHT_REASON:-}}"
  export START_MODE
  export PRE_FLIGHT_PASSED="$passed"
  export PRE_FLIGHT_REASON="${reason:-}"
  STARTUP_STATUS_PATH="$startup_status_path" python - <<'PY'
import datetime
import json
import os
from pathlib import Path

def _coerce_int(name):
    val = os.environ.get(name)
    if not val:
        return None
    try:
        return int(val)
    except Exception:
        return None

def _load_json(name):
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw

def _coerce_bool(name):
    val = os.environ.get(name)
    if not val:
        return None
    return str(val).lower() in {"1", "true", "yes", "on"}

def _merge(existing, updated):
    if not isinstance(existing, dict):
        return updated
    clearable = {
        "failure_reason",
        "exit_reason",
        "exit_code",
        "json_parse_failure",
        "index_rebuild_summary",
        "index_rebuild_failures_path",
        "index_rebuild_errors_top",
        "index_rebuild_log_tail",
        "ingest_skipped_invalid_count",
        "ingest_invalid_report_path",
        "ingest_invalid_top",
        "llm_ok",
        "llm_url",
        "llm_error",
        "llm_latency_ms",
        "llm_probe_step",
        "llm_probe_cmd",
        "llm_probe_rc",
        "llm_probe_output_snippet",
        "db_probe_step",
        "db_probe_cmd",
        "db_probe_rc",
        "db_probe_output_snippet",
        "compose_up_step",
        "compose_up_cmd",
        "compose_up_rc",
        "compose_up_output_snippet",
        "obsidian_gate_enabled",
        "obsidian_gate_ok",
        "obsidian_gate_detail",
        "startup_succeeded",
        "runtime_verified",
        "operator_interrupted",
        "ollama_endpoint_repaired",
        "ollama_endpoint_drift",
        "ollama_configured_base_url",
        "ollama_effective_base_url",
        "ollama_endpoint_persist_hint",
    }
    merged = dict(existing)
    for key, value in updated.items():
        if value is None:
            if key in clearable:
                merged[key] = None
            elif key in merged and merged[key] is not None:
                continue
            else:
                merged[key] = None
        else:
            merged[key] = value
    return merged

path = Path(os.environ["STARTUP_STATUS_PATH"])
existing = {}
if path.exists():
    try:
        existing = json.loads(path.read_text())
    except Exception:
        existing = {}

payload = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
    "start_mode": os.environ.get("START_MODE"),
    "llm_provider": os.environ.get("LLM_PROVIDER") or None,
    "preflight_passed": os.environ.get("PRE_FLIGHT_PASSED") == "1",
    "failure_reason": os.environ.get("PRE_FLIGHT_REASON") or None,
    "phase": os.environ.get("PHASE") or None,
    "last_ok_phase": os.environ.get("LAST_OK_PHASE") or None,
    "exit_code": _coerce_int("EXIT_CODE"),
    "exit_reason": os.environ.get("EXIT_REASON") or None,
    "json_parse_failure": _load_json("JSON_PARSE_FAILURE"),
    "bootstrap_state": os.environ.get("BOOTSTRAP_STATE") or None,
    "bootstrap_reason": os.environ.get("BOOTSTRAP_REASON") or None,
    "objects_before": _coerce_int("OBJECTS_BEFORE"),
    "vectors_before": _coerce_int("VECTORS_BEFORE"),
    "outbox_count": _coerce_int("OUTBOX_COUNT"),
    "index_rebuild_summary": _load_json("INDEX_REBUILD_SUMMARY"),
    "index_rebuild_failures_path": os.environ.get("INDEX_REBUILD_FAILURES_PATH") or None,
    "index_rebuild_errors_top": _load_json("INDEX_REBUILD_ERRORS_TOP"),
    "index_rebuild_log_tail": os.environ.get("INDEX_REBUILD_LOG_TAIL") or None,
    "ingest_skipped_invalid_count": _coerce_int("INGEST_SKIPPED_INVALID_COUNT"),
    "ingest_invalid_report_path": os.environ.get("INGEST_INVALID_REPORT_PATH") or None,
    "ingest_invalid_top": _load_json("INGEST_INVALID_TOP"),
    "llm_ok": _coerce_bool("LLM_OK"),
    "llm_url": os.environ.get("LLM_URL") or None,
    "llm_error": os.environ.get("LLM_ERROR") or None,
    "llm_latency_ms": _coerce_int("LLM_LATENCY_MS"),
    "llm_probe_step": os.environ.get("LLM_PROBE_STEP") or None,
    "llm_probe_cmd": os.environ.get("LLM_PROBE_CMD") or None,
    "llm_probe_rc": _coerce_int("LLM_PROBE_RC"),
    "llm_probe_output_snippet": os.environ.get("LLM_PROBE_OUTPUT_SNIPPET") or None,
    "db_probe_step": os.environ.get("DB_PROBE_STEP") or None,
    "db_probe_cmd": os.environ.get("DB_PROBE_CMD") or None,
    "db_probe_rc": _coerce_int("DB_PROBE_RC"),
    "db_probe_output_snippet": os.environ.get("DB_PROBE_OUTPUT_SNIPPET") or None,
    "compose_up_step": os.environ.get("COMPOSE_UP_STEP") or None,
    "compose_up_cmd": os.environ.get("COMPOSE_UP_CMD") or None,
    "compose_up_rc": _coerce_int("COMPOSE_UP_RC"),
    "compose_up_output_snippet": os.environ.get("COMPOSE_UP_OUTPUT_SNIPPET") or None,
    "obsidian_gate_enabled": _coerce_bool("OBSIDIAN_GATE_ENABLED"),
    "obsidian_gate_ok": os.environ.get("OBSIDIAN_GATE_OK") or None,
    "obsidian_gate_detail": os.environ.get("OBSIDIAN_GATE_DETAIL") or None,
    "startup_succeeded": _coerce_bool("STARTUP_SUCCEEDED"),
    "runtime_verified": _coerce_bool("RUNTIME_VERIFIED"),
    "operator_interrupted": _coerce_bool("OPERATOR_INTERRUPTED"),
    "ollama_endpoint_repaired": _coerce_bool("OLLAMA_ENDPOINT_REPAIRED"),
    "ollama_endpoint_drift": _coerce_bool("OLLAMA_ENDPOINT_DRIFT"),
    "ollama_configured_base_url": os.environ.get("OLLAMA_CONFIGURED_BASE_URL") or None,
    "ollama_effective_base_url": os.environ.get("OLLAMA_EFFECTIVE_BASE_URL") or None,
    "ollama_endpoint_persist_hint": os.environ.get("OLLAMA_ENDPOINT_PERSIST_HINT") or None,
}

payload = _merge(existing, payload)

path.parent.mkdir(parents=True, exist_ok=True)
tmp_path = path.with_suffix(".tmp")
tmp_path.write_text(json.dumps(payload, ensure_ascii=False))
tmp_path.replace(path)
PY
}

cleanup() {
  local exit_status=$?
  if [ -n "${startup_watchdog_pid:-}" ]; then
    kill "$startup_watchdog_pid" >/dev/null 2>&1 || true
  fi
  if [ -n "${flight_recorder_pid:-}" ]; then
    kill "$flight_recorder_pid" >/dev/null 2>&1 || true
  fi
  if [ -z "${EXIT_CODE:-}" ]; then
    EXIT_CODE="$exit_status"
    export EXIT_CODE
  fi
  if [ -z "${EXIT_REASON:-}" ] && [ -n "${PRE_FLIGHT_REASON:-}" ]; then
    EXIT_REASON="$PRE_FLIGHT_REASON"
    export EXIT_REASON
  fi
  if [ -z "${EXIT_REASON:-}" ] && [ "$exit_status" -ne 0 ]; then
    EXIT_REASON="exit_${exit_status}"
    export EXIT_REASON
  fi
  write_startup_status || true
}

trap cleanup EXIT
trap 'PRE_FLIGHT_REASON=${PRE_FLIGHT_REASON:-terminated}; PRE_FLIGHT_PASSED=${PRE_FLIGHT_PASSED:-0}; EXIT_REASON=${EXIT_REASON:-$PRE_FLIGHT_REASON}; EXIT_CODE=${EXIT_CODE:-1}; OPERATOR_INTERRUPTED=true; export EXIT_REASON EXIT_CODE OPERATOR_INTERRUPTED; write_startup_status "$PRE_FLIGHT_PASSED" "$PRE_FLIGHT_REASON" || true; exit 1' TERM INT

fail_preflight() {
  local reason="$1"
  write_startup_status 0 "$reason"
  echo "ERROR: Preflight failed: $reason" >&2
  exit 1
}

check_startup_disk_space() {
  # Operator escape hatch for one-off recovery: STARTUP_DISK_CHECK=0.
  if [ "${STARTUP_DISK_CHECK:-1}" != "1" ]; then
    return 0
  fi

  local check_path="${STARTUP_DISK_CHECK_PATH:-$ROOT}"
  local min_free_mib="${STARTUP_DISK_MIN_FREE_MIB:-1024}"
  local warn_free_mib="${STARTUP_DISK_WARN_FREE_MIB:-5120}"
  local free_kib free_mib reason

  if ! [ "$min_free_mib" -ge 0 ] 2>/dev/null; then
    min_free_mib=1024
  fi
  if ! [ "$warn_free_mib" -ge 0 ] 2>/dev/null; then
    warn_free_mib=5120
  fi

  if ! free_kib=$(df -Pk "$check_path" 2>/dev/null | awk 'NR == 2 {print $4}'); then
    echo "WARNING: disk-space preflight could not inspect $check_path" >&2
    return 0
  fi
  case "$free_kib" in
    ""|*[!0-9]*)
      echo "WARNING: disk-space preflight returned an unexpected value for $check_path: ${free_kib:-<empty>}" >&2
      return 0
      ;;
  esac

  free_mib=$((free_kib / 1024))
  if [ "$free_mib" -lt "$min_free_mib" ]; then
    reason="host disk free space ${free_mib} MiB is below STARTUP_DISK_MIN_FREE_MIB=${min_free_mib} for $check_path"
    PRE_FLIGHT_REASON="$reason"
    EXIT_REASON="$reason"
    EXIT_CODE=3
    export PRE_FLIGHT_REASON EXIT_REASON EXIT_CODE
    write_startup_status 0 "$reason" >/dev/null 2>&1 || true
    echo "ERROR: $reason" >&2
    echo "Safe cleanup candidates before retrying startup:" >&2
    echo "  find tmp -maxdepth 1 -type f \\( -name 'flightrecorder-*.log' -o -name 'watcher_tick-*.jsonl' \\) -delete" >&2
    echo "Do not delete live undated runtime files such as tmp/runtime.env, tmp/index-outbox.jsonl, or tmp/watcher_tick.jsonl as a routine startup cleanup." >&2
    exit 3
  fi

  if [ "$warn_free_mib" -gt 0 ] && [ "$free_mib" -lt "$warn_free_mib" ]; then
    echo "WARNING: host disk free space is ${free_mib} MiB below STARTUP_DISK_WARN_FREE_MIB=${warn_free_mib} for $check_path; Docker builds may fail. See docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md for safe cleanup guidance." >&2
  fi
}

require_vars() {
  for var in "$@"; do
    if [ -z "${!var:-}" ]; then
      fail_preflight "START_MODE runtime requires $var"
    fi
  done
}

require_db_outbox_env() {
  if [ -z "${DATABASE_URL:-}" ] && [ -z "${DB_DSN:-}" ]; then
    fail_preflight "runtime mode requires DATABASE_URL or DB_DSN for db outbox"
  fi
}

preflight_obsidian_check() {
  obsidian_gate_enabled="false"
  obsidian_gate_ok="not_run"
  obsidian_gate_detail=""
  export OBSIDIAN_GATE_ENABLED="$obsidian_gate_enabled"
  export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
  export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"

  local check_enabled="${STARTUP_CHECK_OBSIDIAN:-1}"
  local obsidian_required="0"
  local enforce_enabled="${STARTUP_ENFORCE_OBSIDIAN:-0}"
  if [ "$enforce_enabled" = "1" ]; then
    check_enabled="1"
    export KNOWLEDGE_PRIMARY_ADAPTER="${KNOWLEDGE_PRIMARY_ADAPTER:-obsidian_cli}"
    export KNOWLEDGE_FALLBACK_ADAPTER="${KNOWLEDGE_FALLBACK_ADAPTER:-fs_vault}"
    export KNOWLEDGE_STRICT_STARTUP="${KNOWLEDGE_STRICT_STARTUP:-1}"
    export KNOWLEDGE_ALLOW_FALLBACK="${KNOWLEDGE_ALLOW_FALLBACK:-0}"
  fi
  obsidian_required=$(python - <<'PY'
from app.cli.health import _obsidian_required

print("1" if _obsidian_required() else "0")
PY
  )
  if [ "$check_enabled" != "1" ]; then
    obsidian_gate_ok="skipped"
    obsidian_gate_detail="STARTUP_CHECK_OBSIDIAN!=1"
    export OBSIDIAN_GATE_ENABLED="$obsidian_gate_enabled"
    export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
    export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
    write_startup_status "${PRE_FLIGHT_PASSED:-0}" "${PRE_FLIGHT_REASON:-}"
    return 0
  fi
  obsidian_gate_enabled="true"
  obsidian_gate_ok="checking"
  obsidian_gate_detail=""
  export OBSIDIAN_GATE_ENABLED="$obsidian_gate_enabled"
  export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
  export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
  write_startup_status "${PRE_FLIGHT_PASSED:-0}" "${PRE_FLIGHT_REASON:-}"

  obsidian_gate_json=$(python - <<'PY'
import json
from app.knowledge.health import obsidian_dependency_status
from app.cli.health import _get_obsidian_installer_version, _obsidian_required

status = obsidian_dependency_status(get_installer_version=_get_obsidian_installer_version)
print(
    json.dumps(
        {
            "ok": status.ok,
            "details": status.details,
            "required": _obsidian_required(),
        },
        ensure_ascii=False,
    )
)
PY
)
  obsidian_gate_detail="$obsidian_gate_json"
  export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
  obsidian_ok=$(OBSIDIAN_GATE_JSON="$obsidian_gate_json" python - <<'PY'
import json
import os
payload = json.loads(os.environ.get("OBSIDIAN_GATE_JSON", "{}"))
print("1" if payload.get("ok") else "0")
PY
)
  if [ "$obsidian_ok" = "1" ]; then
    obsidian_gate_ok="passed"
  else
    obsidian_gate_ok="failed"
  fi
  export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
  write_startup_status "${PRE_FLIGHT_PASSED:-0}" "${PRE_FLIGHT_REASON:-}"
  if [ "$obsidian_ok" != "1" ] && [ "$obsidian_required" = "1" ]; then
    obsidian_gate_ok="failed"
    obsidian_gate_detail="$obsidian_gate_json"
    export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
    export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
    fail_preflight "runtime mode Obsidian strict gate failed: $obsidian_gate_json"
  fi
  if [ "$obsidian_ok" != "1" ]; then
    obsidian_gate_ok="warning"
  else
    obsidian_gate_ok="passed"
  fi
  obsidian_gate_detail="$obsidian_gate_json"
  export OBSIDIAN_GATE_OK="$obsidian_gate_ok"
  export OBSIDIAN_GATE_DETAIL="$obsidian_gate_detail"
  if [ "$obsidian_ok" != "1" ]; then
    echo "WARNING: Obsidian compatibility check failed (strict gate disabled): $obsidian_gate_json" >&2
  fi
}

preflight_runtime() {
  require_vars LLM_PROVIDER LLM_MODEL
  if [ "${LLM_PROVIDER_ENFORCE:-}" != "1" ]; then
    fail_preflight "runtime mode requires LLM_PROVIDER_ENFORCE=1"
  fi
  llm_validation_json=$(python - <<'PYLLM'
import json
import os
from app.runtime.startup_env import validate_llm_env

result = validate_llm_env(os.environ)
print(json.dumps(result, ensure_ascii=False))
PYLLM
)
  export LLM_ENV_VALIDATION="$llm_validation_json"
  llm_ok=$(python - <<'PYLLM'
import json
import os

payload = json.loads(os.environ.get("LLM_ENV_VALIDATION", "{}"))
print("1" if payload.get("ok") else "0")
PYLLM
)
  if [ "$llm_ok" != "1" ]; then
    llm_missing_msg=$(python - <<'PYLLM'
import json
import os

payload = json.loads(os.environ.get("LLM_ENV_VALIDATION", "{}"))
missing_any = payload.get("missing_any_of") or []
missing_all = payload.get("missing_all_of") or []
parts = []
if missing_all:
    parts.append("missing required vars: " + ", ".join(missing_all))
if missing_any:
    groups = ["/".join(group) for group in missing_any]
    parts.append("missing any-of: " + "; ".join(groups))
print("; ".join(parts) if parts else "missing LLM env requirements")
PYLLM
)
    fail_preflight "runtime mode LLM env invalid: $llm_missing_msg"
  fi
  if [ "${START_WATCHERS:-0}" -eq 1 ] || [ "${START_WORKER:-0}" -eq 1 ]; then
    require_db_outbox_env
  fi
  preflight_obsidian_check
  export LLM_PROVIDER_ENFORCE=1
}

probe_vault_mount_rw() {
  local probe_json
  set +e
  probe_json=$(run_docker_compose exec -T api python - <<'PY'
import json
from pathlib import Path

target = Path("/app/vault/.startup_rw_probe.md")
payload = {"ok": False, "path": str(target), "step": "write"}
try:
    target.write_text("startup probe\n", encoding="utf-8")
    payload["step"] = "read"
    _ = target.read_text(encoding="utf-8")
    payload["step"] = "unlink"
    target.unlink()
    payload["ok"] = True
except Exception as exc:
    payload["error_type"] = type(exc).__name__
    payload["error"] = str(exc)
    payload["errno"] = getattr(exc, "errno", None)
print(json.dumps(payload, ensure_ascii=False))
PY
  )
  local rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    probe_json="${probe_json:-{\"ok\":false,\"error\":\"probe command failed\",\"rc\":$rc}}"
  fi

  local probe_ok
  probe_ok=$(VAULT_RW_PROBE_JSON="$probe_json" python - <<'PY'
import json
import os
try:
    payload = json.loads(os.environ.get("VAULT_RW_PROBE_JSON", "{}"))
except Exception:
    payload = {}
print("1" if payload.get("ok") else "0")
PY
  )
  if [ "$probe_ok" = "1" ]; then
    echo "Vault rw probe: ok"
    return 0
  fi

  local is_icloud=0
  case "$vault_host_path" in
    */Library/Mobile\ Documents/com~apple~CloudDocs/*) is_icloud=1 ;;
  esac

  if [ "${STARTUP_REQUIRE_VAULT_RW:-0}" = "1" ] || [ "${VERIFY_ACTIVE:-0}" = "1" ]; then
    fail_preflight "vault rw probe failed: $probe_json"
  fi

  if [ "$is_icloud" -eq 1 ]; then
    echo "WARNING: iCloud vault mount is not writable from container: $probe_json" >&2
    echo "WARNING: ensure LOCAL_UID/LOCAL_GID mapping is active and iCloud files are locally downloaded." >&2
  else
    echo "WARNING: vault mount rw probe failed: $probe_json" >&2
  fi
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
  PHASE="preflight"
  export PHASE
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
  mark_phase_ok "preflight"
}

optional_check() {
  local label="$1"
  shift
  if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
    "$@"
    return $?
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

set_phase() {
  local phase="$1"
  PHASE="$phase"
  export PHASE
  write_startup_status 1 ""
}

mark_phase_ok() {
  local phase="$1"
  LAST_OK_PHASE="$phase"
  export LAST_OK_PHASE
  write_startup_status 1 ""
}
start_startup_watchdog() {
  local timeout="${1:-0}"
  if [ "${VERIFY_ACTIVE:-0}" -ne 1 ]; then
    return
  fi
  if ! [ "$timeout" -ge 0 ] 2>/dev/null; then
    return
  fi
  if [ "$timeout" -le 0 ]; then
    return
  fi
  local pid=$$
  (
    sleep "$timeout"
    export PRE_FLIGHT_PASSED="${PRE_FLIGHT_PASSED:-0}"
    export PRE_FLIGHT_REASON="${PRE_FLIGHT_REASON:-startup timeout after ${timeout}s}"
    write_startup_status "$PRE_FLIGHT_PASSED" "$PRE_FLIGHT_REASON" || true
    echo "ERROR: startup timeout after ${timeout}s" >&2
    kill -TERM "$pid" >/dev/null 2>&1 || true
  ) &
  startup_watchdog_pid=$!
}


START_WATCHERS="${START_WATCHERS:-}"
START_WORKER="${START_WORKER:-}"
if [ -z "${START_WATCHERS:-}" ]; then
  if [ "$START_MODE" = "runtime" ]; then
    START_WATCHERS=1
  else
    START_WATCHERS=0
  fi
fi
if [ -z "${START_WORKER:-}" ]; then
  if [ "$START_MODE" = "runtime" ]; then
    START_WORKER=1
  else
    START_WORKER=0
  fi
fi
resolve_channel_defaults() {
  local raw_env normalized_env
  raw_env="${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}"
  normalized_env="$(printf "%s" "$raw_env" | tr '[:upper:]' '[:lower:]' | xargs)"
  case "$normalized_env" in
    dev)
      COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml${app_code_bind_overlay}:docker-compose.dev.yml}"
      COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pkm-dev}"
      API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18001}"
      ;;
    test)
      COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml${app_code_bind_overlay}:docker-compose.test.yml}"
      COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pkm-test}"
      API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18002}"
      ;;
    prod)
      COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yaml${app_code_bind_overlay}:docker-compose.prod.yml}"
      COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-pkm-prod}"
      API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
      ;;
    "")
      # Unset: inherit caller/Compose defaults without forcing prod overlay
      API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
      ;;
    *)
      API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
      ;;
  esac
  export COMPOSE_FILE COMPOSE_PROJECT_NAME API_BASE_URL
}

export_prod_build_identity() {
  local should_export=0
  case "${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}" in
    prod) should_export=1 ;;
  esac
  case "${COMPOSE_PROJECT_NAME:-}" in
    pkm-prod) should_export=1 ;;
  esac
  if [ "$should_export" -ne 1 ]; then
    return 0
  fi
  if [ -z "${VCS_REF:-}" ] || [ "${VCS_REF:-}" = "unknown" ]; then
    VCS_REF="$(git rev-parse HEAD 2>/dev/null || printf '%s' "${VCS_REF:-unknown}")"
  fi
  if [ -z "${BUILT_AT:-}" ] || [ "${BUILT_AT:-}" = "unknown" ]; then
    BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  fi
  export VCS_REF BUILT_AT
}

START_FLIGHT_RECORDER="${START_FLIGHT_RECORDER:-1}"
FLIGHT_RECORDER_INTERVAL="${FLIGHT_RECORDER_INTERVAL:-5}"
FLIGHT_RECORDER_DURATION="${FLIGHT_RECORDER_DURATION:-0}"
VERIFY_ACTIVE="${VERIFY_ACTIVE:-0}"
ALLOW_LEGACY_VAULT="${ALLOW_LEGACY_VAULT:-0}"
resolve_channel_defaults
export_prod_build_identity
API_BASE_URL="${API_BASE_URL%/}"
HEALTH_ENDPOINT="${HEALTH_ENDPOINT:-$API_BASE_URL/healthz}"
HEALTH_MAX_ATTEMPTS="${HEALTH_MAX_ATTEMPTS:-12}"
HEALTH_SLEEP_SECONDS="${HEALTH_SLEEP_SECONDS:-2}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-5}"
WATCHER_HEARTBEAT_TIMEOUT="${WATCHER_HEARTBEAT_TIMEOUT:-30}"
WORKER_HEARTBEAT_TIMEOUT="${WORKER_HEARTBEAT_TIMEOUT:-30}"
STARTUP_TIMEOUT_SECONDS="${STARTUP_TIMEOUT_SECONDS:-120}"
INDEX_REBUILD_TIMEOUT_SECONDS="${INDEX_REBUILD_TIMEOUT_SECONDS:-1800}"
JSON_PARSE_ATTEMPTS="${JSON_PARSE_ATTEMPTS:-3}"
JSON_PARSE_SLEEP_SECONDS="${JSON_PARSE_SLEEP_SECONDS:-1}"
DB_PROBE_MAX_ATTEMPTS="${DB_PROBE_MAX_ATTEMPTS:-30}"
DB_PROBE_SLEEP_SECONDS="${DB_PROBE_SLEEP_SECONDS:-2}"

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

watcher_heartbeat_ready() {
  run_docker_compose exec -T watcher sh -c "test -s ${container_watcher_heartbeat_path}" >/dev/null 2>&1
}

wait_for_watcher_heartbeat() {
  local watcher_deadline watcher_sleep remaining sleep_for
  watcher_deadline=$((SECONDS + WATCHER_HEARTBEAT_TIMEOUT))
  watcher_sleep="${WATCHER_HEARTBEAT_POLL_SECONDS:-2}"

  while true; do
    if watcher_heartbeat_ready; then
      return 0
    fi
    if [ "$SECONDS" -ge "$watcher_deadline" ]; then
      break
    fi
    remaining=$((watcher_deadline - SECONDS))
    if [ "$remaining" -lt "$watcher_sleep" ]; then
      sleep_for="$remaining"
    else
      sleep_for="$watcher_sleep"
    fi
    if [ "$sleep_for" -le 0 ]; then
      break
    fi
    sleep "$sleep_for"
  done

  # Boundary check: accept a heartbeat that arrived before the configured
  # timeout but would otherwise be missed by the poll sleep.
  if watcher_heartbeat_ready; then
    return 0
  fi

  EXIT_REASON="watcher_heartbeat_timeout"
  EXIT_CODE=1
  export EXIT_REASON EXIT_CODE
  write_startup_status 0 "$EXIT_REASON"
  echo "ERROR: watcher heartbeat not detected at ${container_watcher_heartbeat_path} after $WATCHER_HEARTBEAT_TIMEOUT seconds" >&2
  capture_startup_logs || true
  debug_dump
  return 1
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

check_startup_disk_space

if [ "${BUILDEROPS_BOOTSTRAP:-1}" = "1" ] && [ "${PKM_ENVIRONMENT:-}" = "dev" ]; then
  set_phase "builderops_bootstrap"
  if ! scripts/start_builderops_services.sh \
    --repo "${BUILDEROPS_BOOTSTRAP_REPO:-RasmusTho/agentic-pkm-mvp}" \
    --startup-status-path "$startup_status_path" \
    --status-output "$ROOT/tmp/builderops_startup_status.json"; then
    echo "WARNING: BuilderOps bootstrap failed unexpectedly; continuing runtime startup in degraded BuilderOps mode" >&2
  fi
  mark_phase_ok "builderops_bootstrap"
fi

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
fi

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


# Vault binding. Three distinct states (issue #2005 flips the #1991 fail-exit
# to idle-until-opened, the symmetric reverse of an invariant):
#   - VAULT_ROOT unset            -> NO-VAULT IDLE posture (boot, no exit 2).
#   - VAULT_ROOT set but missing  -> FAIL LOUD (exit 1) — unchanged regression
#                                    guard (open-vault-on-missing-vault).
#   - VAULT_ROOT set and present  -> normal vault bring-up.
NO_VAULT_MODE=0
vault_host_path="${VAULT_ROOT:-}"
if [ -z "$vault_host_path" ]; then
  if [ "$ALLOW_LEGACY_VAULT" -eq 1 ]; then
    vault_host_path="./vault"
  else
    NO_VAULT_MODE=1
  fi
fi
if [ "$NO_VAULT_MODE" -eq 1 ]; then
  # No vault bound: the stack comes up, the watcher idles, the API serves the
  # picker state. No vault dir, mount, rw probe, layout, ingest, index rebuild,
  # or ask-verify is attempted — those resume when a vault is opened.
  echo "Vault env: VAULT_ROOT=<unset> — no-vault idle posture (open a vault to activate)"
  unset VAULT_ROOT
  unset VAULT_HOST_ROOT
  export WATCHER_VAULT_PATH=""
  # No vault to watch: force the watcher off so startup does not wait on a
  # watcher heartbeat that never arrives. The generated runtime env already
  # writes WATCHER_ENABLE=0, and `watcher run` raises before emitting a
  # heartbeat, so START_WATCHERS=1 (the runtime default decided above) would
  # hang the no-vault idle boot until WATCHER_HEARTBEAT_TIMEOUT (#2184). The
  # watcher resumes when a vault is opened and the stack is re-armed.
  START_WATCHERS=0
else
  if [ ! -d "$vault_host_path" ]; then
    echo "ERROR: Vault root is missing: $vault_host_path" >&2
    exit 1
  fi
  vault_host_path="$(cd "$vault_host_path" && pwd)"
  export VAULT_ROOT="$vault_host_path"
  # Distinct host-path var for the compose bind-mount source. The generated
  # runtime env sets the container's VAULT_ROOT to /app/vault, so the mount
  # source must come from VAULT_HOST_ROOT, not VAULT_ROOT (issue #2141).
  export VAULT_HOST_ROOT="$vault_host_path"
  apply_start_full_system_vault_defaults "$vault_host_path"
  # Legacy /app/vault compatibility mount (#2386, Slice 05D of #2311): the base
  # compose no longer binds /app/vault, so an explicitly bound vault includes the
  # docker-compose.legacy-vault.yml overlay here. It is appended ONLY on this
  # explicit-vault branch — never in the no-vault idle posture — and its source
  # ${VAULT_HOST_ROOT:?...} errors rather than falling back to ./vault. Skip the
  # duplicate append if COMPOSE_FILE already names the overlay (operator override).
  # When COMPOSE_FILE is unset (no channel selected), seed the base compose first
  # so the overlay augments rather than replaces it. Setting COMPOSE_FILE switches
  # Compose from its implicit docker-compose.yaml + docker-compose.override.yml load
  # to an explicit file list, which drops the automatic override; preserve it
  # explicitly so a bare active-vault start keeps the override's worker env
  # (OPENAI_BASE_URL / OPENAI_API_KEY).
  if [ -z "${COMPOSE_FILE:-}" ]; then
    COMPOSE_FILE="docker-compose.yaml${app_code_bind_overlay}"
    if [ -f "docker-compose.override.yml" ]; then
      COMPOSE_FILE="${COMPOSE_FILE}:docker-compose.override.yml"
    fi
  fi
  case ":${COMPOSE_FILE}:" in
    *":docker-compose.legacy-vault.yml:"*) ;;
    *) COMPOSE_FILE="${COMPOSE_FILE}:docker-compose.legacy-vault.yml" ;;
  esac
  export COMPOSE_FILE
fi

# Full-host mounts (/Users, /Volumes) for in-process vault selection are
# compose-static (#2310) so any disk's vault is reachable at its host-absolute
# path; activation requires Colima to share those dirs
# (docs/ops/COLIMA_FULL_HOST_MOUNT.md).
echo "Vault mounts: /Users + /Volumes are compose-static (#2310) — requires Colima to share them"

if [ "$NO_VAULT_MODE" -ne 1 ]; then
  echo "Vault env: VAULT_ROOT=${VAULT_ROOT}"
  echo "Vault env: VAULT_SYSTEM_DIR_REL=${VAULT_SYSTEM_DIR_REL:-<not set>}"
  echo "Vault env: VAULT_INBOX_DIR_REL=${VAULT_INBOX_DIR_REL:-<not set>}"
  echo "Vault env: VAULT_DESK_DIR_REL=${VAULT_DESK_DIR_REL:-<not set>}"

  if [ -z "${VAULT_LAYOUT_NOTE_REL:-}" ]; then
    layout_count=$(find "$vault_host_path" -mindepth 2 -maxdepth 2 -type f -name "vault.layout.md" 2>/dev/null | wc -l | tr -d '[:space:]')
    if [ "${layout_count:-0}" -gt 1 ]; then
      preferred_layout=""
      if [ -n "${VAULT_SYSTEM_DIR_REL:-}" ] && [ -f "$vault_host_path/${VAULT_SYSTEM_DIR_REL}/vault.layout.md" ]; then
        preferred_layout="${VAULT_SYSTEM_DIR_REL}/vault.layout.md"
      fi
      if [ -n "$preferred_layout" ]; then
        export VAULT_LAYOUT_NOTE_REL="$preferred_layout"
        echo "Vault layout note: auto-selected '$VAULT_LAYOUT_NOTE_REL' (multiple candidates detected)"
      fi
    fi
  fi
fi

runtime_env_path="${RUNTIME_ENV_PATH:-}"
if [ -z "$runtime_env_path" ]; then
  case "${COMPOSE_PROJECT_NAME:-}" in
    pkm-test) runtime_env_path="tmp-test/runtime.env" ;;
    *) runtime_env_path="tmp/runtime.env" ;;
  esac
fi
RUNTIME_ENV_PATH="$runtime_env_path"
NO_VAULT_MODE="$NO_VAULT_MODE" bash scripts/export_runtime_env.sh
scope_glob_raw="${WATCHER_SCOPE_GLOB:-}"
scope_glob_raw="${scope_glob_raw#"${scope_glob_raw%%[![:space:]]*}"}"
scope_glob_raw="${scope_glob_raw%"${scope_glob_raw##*[![:space:]]}"}"
if [ -z "$scope_glob_raw" ] && grep -qE "^WATCHER_SCOPE_GLOB=" "$runtime_env_path" 2>/dev/null; then
  tmpfile="$(mktemp)"
  grep -vE "^WATCHER_SCOPE_GLOB=" "$runtime_env_path" > "$tmpfile"
  mv "$tmpfile" "$runtime_env_path"
  echo "NOTE: ignoring WATCHER_SCOPE_GLOB from runtime env file (not explicitly set by operator)"
fi
if [ -n "$scope_glob_raw" ]; then
  echo "Watcher scope_glob: from env (WATCHER_SCOPE_GLOB set)"
else
  echo "Watcher scope_glob: computed at runtime from vault layout inbox"
fi
unset scope_glob_raw
runtime_env="--env-file $runtime_env_path"

# Derive the channel-specific tmp dir for runtime artifacts written from
# inside the container.  For pkm-test the container path is /app/tmp-test/;
# for all other channels it is /app/tmp/ (prod/dev defaults).
case "${COMPOSE_PROJECT_NAME:-}" in
  pkm-test) _container_tmp_dir="/app/tmp-test" ;;
  *)        _container_tmp_dir="/app/tmp" ;;
esac
# Channel-correct host-side tmp dir for reading container-written runtime
# artifacts back through the shared bind mount. For pkm-test the container
# writes worker/watcher heartbeats under /app/tmp-test/, which maps to the host
# tmp-test/ directory; reading host tmp/ would falsely report a missing
# heartbeat (issue #1997 symptom 3). Prod/dev keep tmp/ — no runtime change.
case "${COMPOSE_PROJECT_NAME:-}" in
  pkm-test) host_tmp_dir="tmp-test" ;;
  *)        host_tmp_dir="tmp" ;;
esac
# The host-side "latest tick log" pointer always lives under the host tmp/
# directory for operator convenience regardless of channel.
latest_tick_log_path="$ROOT/tmp/latest_watcher_tick_log"
tick_log_path="${_container_tmp_dir}/watcher_tick-$(date -u +"%Y%m%d-%H%M%S").jsonl"
printf "WATCHER_TICK_LOG_PATH=%s\n" "$tick_log_path" >> "$runtime_env_path"
export WATCHER_TICK_LOG_PATH="$tick_log_path"
printf "%s\n" "$tick_log_path" > "$latest_tick_log_path"
# Channel-correct container path for the watcher heartbeat artifact. For pkm-test
# it is /app/tmp-test/; reading the hardcoded /app/tmp/watcher_heartbeat.json
# would falsely report a missing heartbeat for the test stack (issue #1997
# symptom 3). Prod/dev keep /app/tmp/ — no runtime change.
container_watcher_heartbeat_path="${_container_tmp_dir}/watcher_heartbeat.json"
unset _container_tmp_dir

if [ "$NO_VAULT_MODE" -eq 1 ]; then
  echo "Vault host path: <none> — no-vault idle posture (no /app/vault bind)"
else
  echo "Vault host path: $vault_host_path -> /app/vault"
fi

run_docker_compose() {
  if [ -n "${runtime_env:-}" ]; then
    docker compose $runtime_env "$@"
  else
    docker compose "$@"
  fi
}

check_compose_port_conflicts() {
  local target_services=("$@")
  local config_json
  if ! config_json=$(run_docker_compose config --format json 2>/dev/null); then
    return 0
  fi
  CONFIG_JSON="$config_json" TARGET_SERVICES="${target_services[*]:-}" python - <<'PY'
import json
import os
import re
import subprocess
import sys

project = os.environ.get("COMPOSE_PROJECT_NAME", "<default>")
environment = os.environ.get("PKM_ENVIRONMENT") or os.environ.get("ENVIRONMENT") or "prod(default)"

try:
    config = json.loads(os.environ["CONFIG_JSON"])
except Exception:
    sys.exit(0)

target_services_raw = (os.environ.get("TARGET_SERVICES") or "").strip()
if target_services_raw:
    target_services = set(target_services_raw.split())
else:
    target_services = set()

ps = subprocess.run(
    ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
    capture_output=True,
    text=True,
    check=False,
)
running = []
for line in ps.stdout.splitlines():
    parts = line.split("\t", 1)
    if len(parts) == 2:
        running.append((parts[0], parts[1]))

collisions = []
for service_name, service in (config.get("services") or {}).items():
    if target_services and service_name not in target_services:
        continue
    for port in service.get("ports") or []:
        published = str(port.get("published") or "").strip()
        if not published:
            continue
        pattern = re.compile(rf"(^|[^\d]){re.escape(published)}->")
        for container_name, ports in running:
            if container_name.startswith(f"{project}-"):
                continue
            if pattern.search(ports):
                collisions.append((service_name, published, container_name))
                break

if collisions:
    print("ERROR: Port preflight failed before compose up.", file=sys.stderr)
    print(f"Target environment={environment}, compose project={project}", file=sys.stderr)
    for service_name, published, owner in collisions:
        print(
            f"  service '{service_name}' needs host port {published}, already used by '{owner}'",
            file=sys.stderr,
        )
    print("Safe next actions:", file=sys.stderr)
    print("  - Start with the canonical env-specific target (prod/test/dev).", file=sys.stderr)
    print("  - If owner is stale same-environment stack, stop only that project.", file=sys.stderr)
    print("  - Do not blindly stop unrelated prod/test containers.", file=sys.stderr)
    sys.exit(19)
PY
}

run_preflight
start_startup_watchdog "$STARTUP_TIMEOUT_SECONDS"

llm_provider="${LLM_PROVIDER:-}"
llm_provider=$(printf "%s" "$llm_provider" | tr '[:upper:]' '[:lower:]')
llm_requires_ollama=0
if [ "$llm_provider" = "ollama" ]; then
  llm_requires_ollama=1
fi
preflight_services=(db api)
if [ "$START_WORKER" -eq 1 ]; then
  preflight_services+=(worker)
fi
if [ "$START_WATCHERS" -eq 1 ]; then
  preflight_services+=(watcher)
fi
if [ "${AUTO_BOOTSTRAP:-0}" -eq 1 ] && [ "$llm_requires_ollama" -eq 1 ]; then
  preflight_services+=(ollama)
fi
check_compose_port_conflicts "${preflight_services[@]}"

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
      --force-recreate)
        extra+=("--force-recreate")
        ;;
      *)
        services+=("$1")
        ;;
    esac
    shift
  done
  if [ "${#extra[@]}" -gt 0 ]; then
    run_docker_compose up -d "${extra[@]}" "${services[@]}"
  else
    run_docker_compose up -d "${services[@]}"
  fi
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
  if [ -f "${host_tmp_dir:-tmp}/worker_heartbeat.json" ]; then
    tail -n 20 "${host_tmp_dir:-tmp}/worker_heartbeat.json" >>"$startup_log_path" 2>&1 || true
  else
    append_startup_log "${host_tmp_dir:-tmp}/worker_heartbeat.json missing"
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


capture_step() {
  local prefix="$1"
  local step="$2"
  shift 2
  local output rc
  local cmd_str="$*"
  local prefix_upper
  local had_errexit=0
  prefix_upper=$(printf "%s" "$prefix" | tr '[:lower:]' '[:upper:]')
  case $- in
    *e*) had_errexit=1 ;;
  esac
  set +e
  output=$("$@" 2>&1)
  rc=$?
  if [ "$had_errexit" -eq 1 ]; then
    set -e
  else
    set +e
  fi
  local snippet
  snippet=$(printf "%s" "$output" | tail -c 400)
  if printf "%s" "$step" | grep -qi "password"; then
    snippet="[redacted]"
  fi
  local key_step="${prefix_upper}_STEP"
  local key_cmd="${prefix_upper}_CMD"
  local key_rc="${prefix_upper}_RC"
  local key_out="${prefix_upper}_OUTPUT_SNIPPET"
  printf -v "$key_step" "%s" "$step"
  printf -v "$key_cmd" "%s" "$cmd_str"
  printf -v "$key_rc" "%s" "$rc"
  printf -v "$key_out" "%s" "$snippet"
  export "$key_step" "$key_cmd" "$key_rc" "$key_out"
  write_startup_status "${PRE_FLIGHT_PASSED:-0}" "${PRE_FLIGHT_REASON:-}"
  printf "%s" "$output"
  return "$rc"
}

run_db_probe() {
  local skip="${SKIP_DB_PROBE:-0}"
  if [ "$skip" -eq 1 ]; then
    return
  fi
  echo "--- DB PROBE ---"
  local db_cid
  local ps_rc
  set +e
  db_cid=$(capture_step db_probe "compose_ps_db" run_docker_compose ps -q db)
  ps_rc=$?
  set -e
  if [ "$ps_rc" -ne 0 ] || [ -z "$db_cid" ]; then
    EXIT_REASON="db_probe_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "ERROR: db container not found" >&2
    run_docker_compose ps || true
    exit 1
  fi
  local db_user
  local db_name
  local db_pwd
  local env_attempts=3
  local env_sleep=1
  local env_try=1
  local env_ok=0
  while [ "$env_try" -le "$env_attempts" ]; do
    local rc_user=0
    local rc_name=0
    local rc_pwd=0
    set +e
    db_user=$(capture_step db_probe "db_env_user" docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_USER"')
    rc_user=$?
    db_name=$(capture_step db_probe "db_env_name" docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_DB"')
    rc_name=$?
    db_pwd=$(capture_step db_probe "db_env_password" docker exec "$db_cid" sh -lc 'printf "%s" "$POSTGRES_PASSWORD"')
    rc_pwd=$?
    set -e
    if [ "$rc_user" -eq 0 ] && [ "$rc_name" -eq 0 ] && [ "$rc_pwd" -eq 0 ]; then
      env_ok=1
      break
    fi
    if [ "$env_try" -lt "$env_attempts" ]; then
      sleep "$env_sleep"
    fi
    env_try=$((env_try + 1))
  done
  if [ "$env_ok" -ne 1 ]; then
    EXIT_REASON="db_probe_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "ERROR: DB probe failed to read database env after ${env_attempts} attempts" >&2
    run_docker_compose ps || true
    exit 1
  fi
  db_user=${db_user:-app}
  db_name=${db_name:-app}
  echo "DB credentials: user=$db_user db=$db_name"
  local max_attempts="${DB_PROBE_MAX_ATTEMPTS:-30}"
  local sleep_seconds="${DB_PROBE_SLEEP_SECONDS:-2}"
  local attempt=1
  local last_error=""
  local ok=0
  local psql_output=""
  local had_errexit=0
  case $- in
    *e*) had_errexit=1 ;;
  esac
  while [ "$attempt" -le "$max_attempts" ]; do
    set +e
    psql_output=$(docker exec "$db_cid" env PGPASSWORD="$db_pwd" psql -U "$db_user" -d "$db_name" -c "select current_user, current_database();" 2>&1)
    status=$?
    if [ "$had_errexit" -eq 1 ]; then
      set -e
    fi
    if [ "$status" -eq 0 ]; then
      ok=1
      break
    fi
    last_error="$psql_output"
    if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
      echo "DB probe attempt ${attempt}/${max_attempts} failed"
    fi
    if [ "$attempt" -lt "$max_attempts" ]; then
      if printf '%s' "$psql_output" | grep -Eqi "shutting down|could not connect|connection refused|the database system is starting up|terminating connection"; then
        sleep "$sleep_seconds"
        attempt=$((attempt + 1))
        continue
      fi
      sleep "$sleep_seconds"
      attempt=$((attempt + 1))
      continue
    fi
    break
  done
  if [ "$ok" -ne 1 ]; then
    EXIT_REASON="db_probe_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "ERROR: DB probe failed after ${max_attempts} attempts" >&2
    if [ "${VERIFY_ACTIVE:-0}" -eq 1 ] && [ -n "$last_error" ]; then
      echo "$last_error" >&2
    fi
    run_docker_compose ps
    run_docker_compose logs --tail=200 db || true
    exit 1
  fi
  echo "$psql_output"
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
    if [ -s "${host_tmp_dir:-tmp}/worker_heartbeat.json" ]; then
      heartbeat_ready=1
      break
    fi
    sleep 1
  done
  if [ "$heartbeat_ready" -ne 1 ]; then
    echo "ERROR: worker heartbeat file missing after $WORKER_HEARTBEAT_TIMEOUT seconds (looked in ${host_tmp_dir:-tmp}/worker_heartbeat.json)" >&2
    run_docker_compose logs --tail=200 worker || true
    exit 1
  fi
  tail -n 1 "${host_tmp_dir:-tmp}/worker_heartbeat.json"
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
ollama_endpoint_probe_json=""

auto_configure_ollama_runtime_endpoint() {
  local runtime_env_file="${1:?runtime env file required}"
  local container_id="${2:?api container required}"
  local probe_json changed chosen_base current_base

  probe_json=$(auto_resolve_ollama_runtime_endpoint "$runtime_env_file" "$container_id")
  current_base="$(normalize_ollama_base_url "${OLLAMA_BASE_URL:-${OLLAMA_URL:-${OLLAMA_HOST:-${OPENAI_BASE_URL:-}}}}")"
  changed=$(OLLAMA_PROBE_JSON="$probe_json" CURRENT_BASE="$current_base" python3 - <<'PY'
from __future__ import annotations

import json
import os

payload = json.loads(os.environ.get("OLLAMA_PROBE_JSON", "{}"))
chosen = payload.get("chosen_base") or ""
current = os.environ.get("CURRENT_BASE", "")
print("1" if chosen and chosen != current else "0")
PY
)
  chosen_base=$(OLLAMA_PROBE_JSON="$probe_json" python3 - <<'PY'
from __future__ import annotations

import json
import os

payload = json.loads(os.environ.get("OLLAMA_PROBE_JSON", "{}"))
print(payload.get("chosen_base") or "")
PY
)
  ollama_configured_base_url="$current_base"
  ollama_effective_base_url="$chosen_base"
  if [ "$changed" = "1" ]; then
    ollama_endpoint_repaired="true"
    ollama_endpoint_drift="true"
    ollama_endpoint_persist_hint="make persist-runtime-repairs"
  else
    ollama_endpoint_repaired="false"
    ollama_endpoint_drift="false"
    ollama_endpoint_persist_hint=""
  fi
  export OLLAMA_ENDPOINT_REPAIRED="$ollama_endpoint_repaired"
  export OLLAMA_ENDPOINT_DRIFT="$ollama_endpoint_drift"
  export OLLAMA_CONFIGURED_BASE_URL="$ollama_configured_base_url"
  export OLLAMA_EFFECTIVE_BASE_URL="$ollama_effective_base_url"
  export OLLAMA_ENDPOINT_PERSIST_HINT="$ollama_endpoint_persist_hint"
  ollama_endpoint_probe_json="$probe_json"
  export OLLAMA_ENDPOINT_PROBE_JSON="$probe_json"
  export LLM_PROBE_STEP="ollama_endpoint_probe"
  export LLM_PROBE_CMD="auto_resolve_ollama_runtime_endpoint"
  export LLM_PROBE_RC=0
  export LLM_PROBE_OUTPUT_SNIPPET="$(printf "%s" "$probe_json" | head -c 400)"
  write_startup_status 1 ""
  if [ "$changed" = "1" ]; then
    echo "Ollama endpoint: auto-selected $chosen_base"
    echo "Ollama endpoint drift: configured='${current_base:-<unset>}' effective='$chosen_base'"
    echo "Persist repair: make persist-runtime-repairs"
    compose_up api --force-recreate
    wait_for_healthz
  else
    echo "Ollama endpoint: using $chosen_base"
  fi
}

run_ollama_preflight() {
  local output rc
  output=$(run_docker_compose exec -T api env VERIFY_ACTIVE="${VERIFY_ACTIVE:-0}" python - <<'PYOLLAMA'
from __future__ import annotations
import os
import sys
import httpx


def _error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            detail = err.get("message") or err.get("error")
        else:
            detail = err or payload.get("message")
    else:
        detail = None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    text = response.text.strip()
    if text:
        return text
    return None


def _fail(message: str, verbose: bool) -> None:
    if verbose:
        print(message, file=sys.stderr)
    raise SystemExit(1)


def _normalize_base(url: str) -> str:
    clean = url.rstrip("/")
    if clean.endswith("/v1"):
        clean = clean[:-3]
    return clean


def _resolve_base() -> str | None:
    base = (
        os.environ.get("OLLAMA_BASE_URL")
        or os.environ.get("OLLAMA_URL")
        or os.environ.get("OLLAMA_HOST")
        or os.environ.get("OPENAI_BASE_URL")
    )
    if not base:
        return None
    return _normalize_base(base)


def _extract_embedding(payload: dict) -> list[float] | None:
    value = payload.get("embeddings") or payload.get("embedding")
    if isinstance(value, list):
        if not value:
            return None
        first = value[0]
        if isinstance(first, list):
            return first
        if isinstance(first, (int, float)):
            return value
    return None


verbose = os.environ.get("VERIFY_ACTIVE") == "1"
base = _resolve_base()
if not base:
    _fail("INFO: Ollama preflight failed: OLLAMA_BASE_URL/OLLAMA_URL/OLLAMA_HOST/OPENAI_BASE_URL missing", verbose)
model = os.environ.get("OLLAMA_EMBED_MODEL") or os.environ.get("EMBED_MODEL", "nomic-embed-text:latest")
with httpx.Client(timeout=10.0) as client:
    tags_resp = client.get(f"{base}/api/tags")
    if tags_resp.is_error:
        detail = _error_detail(tags_resp)
        message = f"INFO: Ollama preflight failed: /api/tags returned HTTP {tags_resp.status_code}"
        if detail:
            message = f"{message}: {detail}"
        _fail(message, verbose)
    tags_payload = tags_resp.json() if tags_resp.headers.get("Content-Type", "").startswith("application/json") else {}
    models = tags_payload.get("models") if isinstance(tags_payload, dict) else None
    if verbose:
        print(f"Ollama tags ok ({len(models or [])} models)")
    embed_resp = client.post(
        f"{base}/api/embeddings",
        json={"model": model, "prompt": "startup-check"},
    )
    if embed_resp.is_error:
        detail = _error_detail(embed_resp)
        message = f"INFO: Ollama preflight failed: /api/embeddings returned HTTP {embed_resp.status_code}"
        if detail:
            message = f"{message}: {detail}"
        _fail(message, verbose)
    data = embed_resp.json() if embed_resp.headers.get("Content-Type", "").startswith("application/json") else {}
    embedding = _extract_embedding(data) if isinstance(data, dict) else None
    if not embedding:
        _fail("INFO: Ollama preflight failed: embeddings payload missing vectors", verbose)
    if verbose:
        print(f"Ollama embed dim: {len(embedding)}")
PYOLLAMA
  )
  rc=$?
  if [ "$rc" -eq 0 ]; then
    if [ -n "$output" ]; then
      printf "%s\n" "$output"
    fi
    echo "Ollama preflight succeeded"
    ollama_preflight_ok=1
  else
    export LLM_PROBE_STEP="ollama_preflight"
    export LLM_PROBE_CMD="run_docker_compose exec -T api env VERIFY_ACTIVE=${VERIFY_ACTIVE:-0} python - <ollama preflight>"
    export LLM_PROBE_RC="$rc"
    export LLM_PROBE_OUTPUT_SNIPPET="$(printf "%s" "$output" | head -c 400)"
    write_startup_status 1 ""
    echo "WARNING: Ollama preflight failed; skipping /api/ask bootstrap" >&2
    ollama_preflight_ok=0
    if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
      return 1
    fi
  fi
}


run_and_capture_json() {
  local step="$1"
  shift
  local output rc json_ok
  local cmd_str="$*"
  local had_errexit=0
  case $- in
    *e*) had_errexit=1 ;;
  esac
  output=$("$@" 2>&1)
  rc=$?
  export LLM_PROBE_STEP="$step"
  export LLM_PROBE_CMD="$cmd_str"
  export LLM_PROBE_RC="$rc"
  export LLM_PROBE_OUTPUT_SNIPPET="$(printf "%s" "$output" | head -c 400)"
  write_startup_status 1 ""
  if [ "$rc" -ne 0 ]; then
    if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
      echo "ERROR: $step failed (rc=$rc)" >&2
      printf "%s\n" "$LLM_PROBE_OUTPUT_SNIPPET" >&2
      exit 1
    fi
    echo "INFO: optional check '$step' failed (ignored for fast start)" >&2
  fi
  json_ok=0
  set +e
  JSON_RAW="$output" python - <<'PYJSON'
import json, os, sys
raw = os.environ.get("JSON_RAW", "")
try:
    json.loads(raw)
except Exception:
    sys.exit(1)
sys.exit(0)
PYJSON
  parse_rc=$?
  if [ "$had_errexit" -eq 1 ]; then
    set -e
  fi
  if [ "$parse_rc" -eq 0 ]; then
    json_ok=1
  fi
  if [ "$json_ok" -ne 1 ]; then
    if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
      echo "ERROR: $step returned non-JSON output" >&2
      printf "%s\n" "$LLM_PROBE_OUTPUT_SNIPPET" >&2
      exit 1
    fi
    echo "INFO: optional check '$step' returned non-JSON output (ignored for fast start)" >&2
  fi
  RUN_CAPTURE_OUTPUT="$output"
  return "$rc"
}

run_llm_check_container() {
  local container_id="${1:-}"
  if [ -z "$container_id" ]; then
    container_id=$(run_docker_compose ps -q api | head -n1 || true)
  fi
  if [ -z "$container_id" ]; then
    export LLM_OK=0
    export LLM_URL=""
    export LLM_ERROR="api container not found"
    export LLM_LATENCY_MS=0
    write_startup_status 1 ""
    echo "LLM CHECK FAILED: url=<missing> error=api container not found" >&2
    echo "LLM endpoint unreachable. Ensure the api container is running and LLM_PROVIDER is configured." >&2
    return 1
  fi
  local llm_check_json=""
  local llm_status=0
  set +e
  run_and_capture_json "llm_check" docker exec "$container_id" python -m app.cli llm check --json --strict
  llm_status=$?
  llm_check_json="$RUN_CAPTURE_OUTPUT"
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
url = payload.get('url') or ''
error = (payload.get('error') or '').replace('\n', ' ')
latency = int(payload.get('latency_ms', 0) or 0)
sep = "\x1f"
print(f"{ok_val}{sep}{url}{sep}{error}{sep}{latency}")
PY
  )
  IFS=$'\x1f' read -r llm_ok llm_url llm_error llm_latency_ms <<<"$llm_check_info"
  llm_ok=${llm_ok:-0}
  llm_url=${llm_url:-}
  llm_error=${llm_error:-}
  llm_latency_ms=${llm_latency_ms:-0}
  export LLM_OK="$llm_ok"
  export LLM_URL="$llm_url"
  export LLM_ERROR="$llm_error"
  export LLM_LATENCY_MS="$llm_latency_ms"
  write_startup_status 1 ""
  if [ "$llm_ok" -ne 1 ] || [ "$llm_status" -ne 0 ]; then
    echo "LLM CHECK FAILED: url=${llm_url:-<missing>} error=${llm_error:-<no error>}" >&2
    echo "LLM endpoint unreachable. If LLM_PROVIDER=ollama and Ollama runs on host, ensure it listens on a reachable interface (e.g., OLLAMA_HOST=0.0.0.0:11434) or set OPENAI_BASE_URL for non-Ollama providers." >&2
    return 1
  fi
  return 0
}

if [ "$START_MODE" = "diagnostic" ]; then
  echo "START_MODE=diagnostic: running API in the foreground (no detach)"
  run_docker_compose up "${compose_up_build_args[@]}" db api
  exit $?
fi

if ! capture_step compose_up "db_api" compose_up "${compose_up_build_args[@]}" db api; then
  EXIT_REASON="compose_up_failed"
  EXIT_CODE=1
  export EXIT_REASON EXIT_CODE
  write_startup_status 0 "$EXIT_REASON"
  echo "ERROR: compose_up failed for db/api" >&2
  exit 1
fi
if [ "${AUTO_BOOTSTRAP:-0}" -eq 1 ] && [ "$llm_requires_ollama" -eq 1 ]; then
  compose_up ollama
fi
api_container_id=$(run_docker_compose ps -q api | head -n1 || true)
if [ "$llm_requires_ollama" -eq 1 ]; then
  set_phase "ollama_endpoint_probe"
  if ! auto_configure_ollama_runtime_endpoint "$runtime_env_path" "$api_container_id"; then
    EXIT_REASON="ollama_endpoint_probe_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    exit 1
  fi
  api_container_id=$(run_docker_compose ps -q api | head -n1 || true)
  mark_phase_ok "ollama_endpoint_probe"
fi
set_phase "db_probe"
run_db_probe
mark_phase_ok "db_probe"
wait_for_healthz
if [ "$NO_VAULT_MODE" -ne 1 ]; then
  set_phase "vault_rw_probe"
  probe_vault_mount_rw
  mark_phase_ok "vault_rw_probe"
fi

set_phase "object_stats"
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
ensure_json_or_fail() {
  local label="$1"
  local raw="$2"
  local command="$3"
  local rc="${4:-0}"
  local attempts="${JSON_PARSE_ATTEMPTS:-3}"
  local sleep_s="${JSON_PARSE_SLEEP_SECONDS:-1}"
  local last_error=""
  local ok=0
  local had_errexit=0
  case $- in
    *e*) had_errexit=1 ;;
  esac
  for attempt in $(seq 1 "$attempts"); do
    set +e
    parse_error=$(JSON_RAW="$raw" python - <<'PY'
import json
import os
import sys
raw = os.environ.get("JSON_RAW", "")
try:
    json.loads(raw)
    sys.exit(0)
except Exception as exc:
    print(str(exc))
    sys.exit(1)
PY
    )
    status=$?
    if [ "$had_errexit" -eq 1 ]; then
      set -e
    fi
    if [ "$status" -eq 0 ]; then
      ok=1
      break
    fi
    last_error="$parse_error"
    sleep "$sleep_s"
  done
  if [ "$ok" -eq 1 ]; then
    return 0
  fi
  snippet=$(printf '%s' "$raw" | tail -c 400)
  JSON_PARSE_FAILURE=$(PARSE_LABEL="$label" PARSE_COMMAND="$command" PARSE_RC="$rc" PARSE_ERROR="$last_error" PARSE_SNIPPET="$snippet" python - <<'PY'
import json
import os
print(json.dumps({
    "label": os.environ.get("PARSE_LABEL"),
    "command": os.environ.get("PARSE_COMMAND"),
    "rc": int(os.environ.get("PARSE_RC", "0") or 0),
    "error": os.environ.get("PARSE_ERROR") or None,
    "snippet": os.environ.get("PARSE_SNIPPET") or None,
}, ensure_ascii=False))
PY
  )
  export JSON_PARSE_FAILURE
  if [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
    EXIT_REASON="json_parse_failed:${label}"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "ERROR: JSON parse failed for $label after $attempts attempts: $last_error" >&2
    exit 1
  fi
  echo "INFO: optional preflight failed: $last_error" >&2
  return 0
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
else
  BOOTSTRAP_STATE="active"
  BOOTSTRAP_REASON="objects or outbox events detected"
fi
export BOOTSTRAP_STATE BOOTSTRAP_REASON
export OBJECTS_BEFORE="$objects_before"
export VECTORS_BEFORE="$vectors_before"
export OUTBOX_COUNT="$outbox_count"
mark_phase_ok "object_stats"
set_phase "bootstrap_determined"
mark_phase_ok "bootstrap_determined"

if [ "${VERIFY_ACTIVE:-0}" -eq 1 ] && [ "$BOOTSTRAP_STATE" = "active" ]; then
  set_phase "llm_probe"
  if ! run_llm_check_container "$api_container_id"; then
    EXIT_REASON="llm_probe_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    exit 1
  fi
  mark_phase_ok "llm_probe"
fi
if [ "$NO_VAULT_MODE" -eq 1 ]; then
  echo "INFO: no-vault idle posture — skipping vault layout ensure"
fi

if [ "$NO_VAULT_MODE" -ne 1 ] && [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
  set_phase "vault_layout"
fi

layout_json=""
if [ "$NO_VAULT_MODE" -eq 1 ]; then
  layout_json=""
elif [ "${VERIFY_ACTIVE:-0}" -eq 1 ]; then
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
if [ -n "$layout_inbox" ] && [ -z "${WATCHER_SCOPE_GLOB:-}" ]; then
  layout_scope_glob="$(derive_start_full_system_scope_glob "$layout_inbox")"
  if [ -n "$layout_scope_glob" ]; then
    printf "WATCHER_SCOPE_GLOB=%s\n" "$layout_scope_glob" >> "$runtime_env_path"
    export WATCHER_SCOPE_GLOB="$layout_scope_glob"
  fi
fi

if [ -n "$layout_inbox" ] && [ -n "$layout_system" ]; then
  echo "--- VAULT LAYOUT ---"
  echo "inbox: $layout_inbox"
  echo "system: $layout_system"
  echo "layout note: $layout_note"
fi



reset_runtime_state="${RESET_RUNTIME_STATE:-1}"
if [ "$reset_runtime_state" -eq 1 ] && { [ "$START_WATCHERS" -eq 1 ] || [ "$START_WORKER" -eq 1 ]; }; then
  run_docker_compose exec -T api sh -c "rm -f /app/tmp/index-outbox.jsonl /app/tmp/worker_heartbeat.json ${container_watcher_heartbeat_path}"
  if [ "$START_WATCHERS" -eq 1 ]; then
    run_docker_compose exec -T watcher sh -c "rm -f ${container_watcher_heartbeat_path}" || true
  fi
fi

if [ "${VERIFY_ACTIVE:-0}" -eq 1 ] && [ "$llm_requires_ollama" -eq 1 ]; then
  optional_check "Ollama preflight" run_ollama_preflight
fi

# Colima on demerzel previously needed more than 2 GB to keep worker and watcher
# startup from OOM-killing each other. Keep the startup order staggered and
# leave the host configured with at least 4 GB for this wrapper.
if [ "$START_WORKER" -eq 1 ]; then
  compose_up "${compose_up_build_args[@]}" worker
  run_worker_probe
fi

if [ "$START_WATCHERS" -eq 1 ]; then
  compose_up "${compose_up_build_args[@]}" watcher
fi

if [ "$START_WATCHERS" -eq 1 ]; then
  if ! wait_for_watcher_heartbeat; then
    exit 1
  fi
fi
ready_payload=$(curl -sS "$API_BASE_URL/readyz" || true)
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

api_health_payload=$(curl -sS "$API_BASE_URL/api/health" || true)
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

ingest_run="no"
ingested_count=0
skipped_locked_count=0
search_results=0
vault_note_count="unknown"
index_rebuild_status="skipped"
bootstrap_next="none"
index_doctor_status="skipped"
index_issue_count=0

auto_bootstrap="${AUTO_BOOTSTRAP:-0}"
if [ "${VERIFY_ACTIVE:-0}" -eq 1 ] && [ "$auto_bootstrap" -eq 1 ]; then
  set +e
  settings_validate_json=$(run_docker_compose exec -T api python -m app.cli settings validate --json)
  settings_validate_status=$?
  set -e
  if [ "$settings_validate_status" -ne 0 ]; then
    EXIT_REASON="settings_validate_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
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

if [ "$NO_VAULT_MODE" -ne 1 ]; then
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
else
  vault_note_count=0
  echo "INFO: no-vault idle posture — no /app/vault mount; ingest/index/verify skipped"
fi

if [ "$BOOTSTRAP_STATE" = "empty" ]; then
  echo "BOOTSTRAP: empty system, awaiting first ingest"
fi


ingest_run="no"
max_notes="${BOOTSTRAP_INGEST_MAX_NOTES:-500}"
object_count="$objects_before"
vector_count="$vectors_before"
ingest_summary_json="{}"
ingest_status=0
if [ "$NO_VAULT_MODE" -ne 1 ] && [ "$objects_before" -le 0 ]; then
  ingest_run="yes"
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    set +e
    ingest_summary_json=$(run_docker_compose exec -T api python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force --json)
    ingest_status=$?
    set -e
    if [ "$ingest_status" -ne 0 ]; then
      echo "INFO: bootstrap ingest failed but will be retried after first ingest (empty system)"
      ingest_run="no"
      ingest_summary_json="{}"
    fi
  else
    set +e
    ingest_summary_json=$(run_docker_compose exec -T api python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force --json)
    ingest_status=$?
    set -e
    if [ "$ingest_status" -ne 0 ]; then
      if [ "$VERIFY_ACTIVE" -eq 1 ]; then
        EXIT_REASON="bootstrap_ingest_failed"
        EXIT_CODE=1
        export EXIT_REASON EXIT_CODE
        write_startup_status 0 "$EXIT_REASON"
        echo "ERROR: bootstrap ingest failed" >&2
        exit 1
      else
        echo "INFO: bootstrap ingest failed (ignored for fast start)" >&2
        ingest_run="no"
        ingest_summary_json="{}"
      fi
    fi
  fi
  store_stats_json=$(run_docker_compose exec -T api python -m app.cli store stats --json || true)
  objects_after=$(extract_stat objects)
  vectors_after=$(extract_stat vectors)
  object_count="$objects_after"
  vector_count="$vectors_after"
fi

ensure_json_or_fail "vault-alpha-ingest" "$ingest_summary_json" "vault-alpha-ingest --json" "$ingest_status"

if [ "$auto_bootstrap" -eq 1 ]; then
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    echo "INDEX: not required (no objects yet)"
  else
    api_health_payload=$(curl -sS "$API_BASE_URL/api/health" || true)
    update_health_state
    if [ "$api_health_index_rebuild" -eq 1 ]; then
      set_phase "index_rebuild"
      echo "INDEX REBUILD: running"
      index_rebuild_stdout_path="$ROOT/tmp/index_rebuild.stdout"
      : > "$index_rebuild_stdout_path"
      rebuild_cmd="python -m app.cli index rebuild --json --strict --time-budget-seconds $INDEX_REBUILD_TIMEOUT_SECONDS"
      set +e
      run_docker_compose exec -T api sh -lc "$rebuild_cmd" > "$index_rebuild_stdout_path" 2>&1
      rebuild_status=$?
      set -e
      index_rebuild_status="ran"
      rebuild_snippet=$(tail -n 30 "$index_rebuild_stdout_path" || true)
      index_rebuild_summary=$(INDEX_REBUILD_STDOUT_PATH="$index_rebuild_stdout_path" python - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ.get("INDEX_REBUILD_STDOUT_PATH", ""))
if not path.exists():
    raise SystemExit(1)
lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
for raw in reversed(lines):
    raw = raw.strip()
    if not raw:
        continue
    try:
        payload = json.loads(raw)
    except Exception:
        continue
    if isinstance(payload, dict):
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(0)
raise SystemExit(1)
PY
      )
      summary_status=$?
      if [ "$summary_status" -ne 0 ] || [ -z "$index_rebuild_summary" ]; then
        JSON_PARSE_FAILURE=$(PARSE_LABEL="index_rebuild" PARSE_COMMAND="$rebuild_cmd" PARSE_RC="$rebuild_status" PARSE_ERROR="missing json summary" PARSE_SNIPPET="$rebuild_snippet" python - <<'PY'
import json
import os
print(json.dumps({
    "label": os.environ.get("PARSE_LABEL"),
    "command": os.environ.get("PARSE_COMMAND"),
    "rc": int(os.environ.get("PARSE_RC", "0") or 0),
    "error": os.environ.get("PARSE_ERROR") or None,
    "snippet": os.environ.get("PARSE_SNIPPET") or None,
}, ensure_ascii=False))
PY
        )
        export JSON_PARSE_FAILURE
        EXIT_REASON="index_rebuild_parse_failed"
        EXIT_CODE=1
        export EXIT_REASON EXIT_CODE
        export INDEX_REBUILD_LOG_TAIL="$rebuild_snippet"
        write_startup_status 0 "$EXIT_REASON"
        if [ "$VERIFY_ACTIVE" -eq 1 ]; then
          echo "ERROR: index rebuild did not emit JSON summary" >&2
          exit 1
        else
          echo "INFO: index rebuild summary missing (ignored for fast start)" >&2
        fi
      fi
      index_rebuild_meta=$(REBUILD_SUMMARY_JSON="$index_rebuild_summary" python - <<'PY'
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
print(payload.get("exit_reason") or "")
PY
)
      IFS=$'\n' read -r index_rebuild_error_count index_rebuild_failures_path index_rebuild_errors_json index_rebuild_exit_reason <<<"$index_rebuild_meta"
      index_rebuild_error_count=${index_rebuild_error_count:-0}
      index_rebuild_failures_path=${index_rebuild_failures_path:-}
      index_rebuild_errors_json=${index_rebuild_errors_json:-[]}
      index_rebuild_exit_reason=${index_rebuild_exit_reason:-}
      export INDEX_REBUILD_SUMMARY="$index_rebuild_summary"
      export INDEX_REBUILD_FAILURES_PATH="$index_rebuild_failures_path"
      export INDEX_REBUILD_ERRORS_TOP="$index_rebuild_errors_json"
      export INDEX_REBUILD_LOG_TAIL="$rebuild_snippet"
      write_startup_status 1 ""
      failures_path_display="${index_rebuild_failures_path:-<missing>}"
      if [ "$rebuild_status" -ne 0 ] || [ "$index_rebuild_error_count" -gt 0 ] || [ -n "$index_rebuild_exit_reason" ]; then
        reason_suffix=""
        if [ -n "$index_rebuild_exit_reason" ]; then
          reason_suffix=" exit_reason=$index_rebuild_exit_reason"
        fi
        echo "INDEX REBUILD FAILED: status=$rebuild_status errors=$index_rebuild_error_count failures_path=$failures_path_display$reason_suffix" >&2
        if [ "$index_rebuild_errors_json" != "[]" ]; then
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
        if [ "$index_rebuild_exit_reason" = "time_budget_exceeded" ]; then
          EXIT_REASON="index_rebuild_timeout"
        else
          EXIT_REASON="index_rebuild_failed"
        fi
        EXIT_CODE=1
        export EXIT_REASON EXIT_CODE
        export INDEX_REBUILD_LOG_TAIL="$rebuild_snippet"
        write_startup_status 0 "$EXIT_REASON"
        debug_dump
        exit 1
      fi
      mark_phase_ok "index_rebuild"
      api_health_payload=$(curl -sS "$API_BASE_URL/api/health" || true)
      update_health_state
      if [ "$api_health_index_rebuild" -eq 1 ]; then
        EXIT_REASON="index_rebuild_still_required"
        EXIT_CODE=1
        export EXIT_REASON EXIT_CODE
        write_startup_status 0 "$EXIT_REASON"
        echo "INDEX REBUILD: failed (still required)" >&2
        debug_dump
        exit 1
      fi
    else
      echo "INDEX REBUILD: skipped (not required)"
    fi
  fi
fi
ingest_invalid_meta=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os
raw = os.environ.get("INGEST_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
count = payload.get("skipped_invalid") or 0
report_path = payload.get("invalid_report_path") or ""
top = payload.get("invalid_examples") or []
print(f"{count}{report_path}{json.dumps(top[:5], ensure_ascii=False)}")
PY
)
IFS=$'' read -r ingest_skipped_invalid_count ingest_invalid_report_path ingest_invalid_top_json <<<"$ingest_invalid_meta"
ingest_skipped_invalid_count=${ingest_skipped_invalid_count:-0}
ingest_invalid_report_path=${ingest_invalid_report_path:-}
ingest_invalid_top_json=${ingest_invalid_top_json:-[]}
export INGEST_SKIPPED_INVALID_COUNT="$ingest_skipped_invalid_count"
export INGEST_INVALID_REPORT_PATH="$ingest_invalid_report_path"
export INGEST_INVALID_TOP="$ingest_invalid_top_json"
write_startup_status 1 ""

ingested_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os
raw = os.environ.get("INGEST_JSON", "")
payload = json.loads(raw) if raw else {}
print(payload.get("ingested", 0) or 0)
PY
)
skipped_locked_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os
raw = os.environ.get("INGEST_JSON", "")
payload = json.loads(raw) if raw else {}
print(payload.get("skipped_locked", 0) or 0)
PY
)

search_payload=$(curl -sS "$API_BASE_URL/search?q=test&k=3" || true)
ensure_json_or_fail "search" "$search_payload" "GET /search?q=test&k=3" "0"
search_results=$(SEARCH_JSON="$search_payload" python - <<'PY'
import json, os
raw = os.environ.get("SEARCH_JSON", "")
payload = json.loads(raw) if raw else {}
print(len(payload.get("results") or []))
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
fi

if [ "$VERIFY_ACTIVE" -eq 1 ] && [ "$NO_VAULT_MODE" -eq 1 ]; then
  echo "VERIFY: skipped — no-vault idle posture (open a vault, then re-run verify)"
elif [ "$VERIFY_ACTIVE" -eq 1 ]; then
  if [ "$BOOTSTRAP_STATE" = "empty" ]; then
    EXIT_REASON="verify_empty_system"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "VERIFY: requires ingested objects; system is empty" >&2
    exit 1
  fi
  if [ "$llm_requires_ollama" -eq 1 ] && [ "$ollama_preflight_ok" -ne 1 ]; then
    EXIT_REASON="verify_ollama_preflight_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "VERIFY: Ollama preflight must succeed (set OLLAMA_URL/LLM_PROVIDER)" >&2
    exit 1
  fi
  if [ "$object_count" -le 0 ]; then
    EXIT_REASON="verify_missing_objects"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "VERIFY: index missing objects" >&2
    exit 1
  fi
  if [ "${LLM_OK:-}" != "1" ]; then
    if ! run_llm_check_container "$api_container_id"; then
      EXIT_REASON="verify_llm_probe_failed"
      EXIT_CODE=1
      export EXIT_REASON EXIT_CODE
      write_startup_status 0 "$EXIT_REASON"
      exit 1
    fi
  fi
  set_phase "verify_ask"
  ask_status=$(curl -sS -o /dev/null -w "%{http_code}" -X POST "$API_BASE_URL/api/ask" -H 'Content-Type: application/json' -d '{"query":"startup verify"}' || true)
  if [ "$ask_status" != "200" ]; then
    EXIT_REASON="verify_ask_failed"
    EXIT_CODE=1
    export EXIT_REASON EXIT_CODE
    write_startup_status 0 "$EXIT_REASON"
    echo "VERIFY: /api/ask returned $ask_status" >&2
    exit 1
  fi
  mark_phase_ok "verify_ask"
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

set_phase "runtime_verify"
runtime_verify_allow_deferred_index_rebuild=0
runtime_verify_channel="$(printf "%s" "${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}" | tr '[:upper:]' '[:lower:]' | xargs)"
if [ "${VERIFY_ACTIVE:-0}" -ne 1 ] && [ "$index_rebuild_status" = "required" ] && [ "$runtime_verify_channel" = "dev" ]; then
  runtime_verify_allow_deferred_index_rebuild=1
fi
if ! RUNTIME_ENV_PATH="$runtime_env_path" API_BASE_URL="$API_BASE_URL" RUNTIME_VERIFY_ALLOW_DEFERRED_INDEX_REBUILD="$runtime_verify_allow_deferred_index_rebuild" bash scripts/verify_runtime_stack.sh; then
  EXIT_REASON="runtime_verify_failed"
  EXIT_CODE=1
  export EXIT_REASON EXIT_CODE
  export RUNTIME_VERIFIED=false
  write_startup_status 0 "$EXIT_REASON"
  exit 1
fi
runtime_verified="true"
export RUNTIME_VERIFIED="$runtime_verified"
mark_phase_ok "runtime_verify"

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

set_phase "done"
startup_succeeded="true"
export STARTUP_SUCCEEDED="$startup_succeeded"
mark_phase_ok "done"
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
  obsidian gate: enabled=$obsidian_gate_enabled status=$obsidian_gate_ok
  runtime verified: $runtime_verified
  ollama configured: ${ollama_configured_base_url:-<unset>}
  ollama effective: ${ollama_effective_base_url:-<unset>}
  ollama repaired: $ollama_endpoint_repaired
  note: /api/health ok=false can be expected when optional tools (e.g., ffmpeg) are missing; Stage0 ingest/search/ask can still work.
  next: curl -sS $API_BASE_URL/search?q=test&k=3
SUMMARY

if [ "$ollama_endpoint_drift" = "true" ]; then
  echo "Persist runtime repair: make persist-runtime-repairs"
fi

if [ "$START_WATCHERS" -eq 1 ]; then
  echo "Stop watcher: docker compose exec watcher sh -c 'touch /app/tmp/WATCHER_STOP'"
fi
echo "URLs: $API_BASE_URL  |  $API_BASE_URL/api/status"
