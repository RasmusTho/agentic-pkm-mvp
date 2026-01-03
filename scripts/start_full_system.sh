#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

debug_dump() {
  echo "DEBUG: docker compose ps"
  docker compose ps || true
  echo "DEBUG: docker compose logs --tail=200 watcher"
  docker compose logs --tail=200 watcher || true
  echo "DEBUG: docker compose logs --tail=200 worker"
  docker compose logs --tail=200 worker || true
  echo "DEBUG: docker compose logs --tail=200 api"
  docker compose logs --tail=200 api || true
}

mkdir -p tmp logs
for dir in tmp logs; do
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

runtime_env=""
vault_host_path="${VAULT_ROOT:-./vault}"
if [ -n "${VAULT_ROOT:-}" ]; then
  bash scripts/export_runtime_env.sh
  runtime_env="--env-file tmp/runtime.env"
fi

echo "Vault host path: $vault_host_path -> /app/vault"

alpha_rebuild=${ALPHA_REBUILD:-0}
alpha_rebuild_pull=${ALPHA_REBUILD_PULL:-0}
if [ "$alpha_rebuild" -eq 1 ]; then
  build_flags=""
  if [ "$alpha_rebuild_pull" -eq 1 ]; then
    build_flags="--pull"
  fi
  echo "ALPHA_REBUILD: docker compose build $build_flags api worker watcher"
  if [ -n "$runtime_env" ]; then
    docker compose $runtime_env build $build_flags api worker watcher
  else
    docker compose build $build_flags api worker watcher
  fi
fi

if [ -n "$runtime_env" ]; then
  docker compose $runtime_env up -d db api worker watcher
else
  docker compose up -d db api worker watcher
fi

reset_runtime_state=${RESET_RUNTIME_STATE:-1}
if [ "$reset_runtime_state" -eq 1 ]; then
  docker compose exec -T api sh -c 'rm -f /app/tmp/index-outbox.jsonl /app/tmp/watcher_heartbeat.json /app/tmp/worker_heartbeat.json'
  docker compose exec -T watcher sh -c 'rm -f /app/tmp/watcher_heartbeat.json' || true
fi

HEALTH_ENDPOINT="http://127.0.0.1:18000/healthz"
for attempt in $(seq 1 30); do
  if curl -sf "$HEALTH_ENDPOINT" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
if ! curl -sf "$HEALTH_ENDPOINT" >/dev/null 2>&1; then
  echo "ERROR: /healthz did not respond on 127.0.0.1:18000" >&2
  exit 1
fi

watcher_ready=0
for attempt in $(seq 1 30); do
  if docker compose exec -T watcher sh -c 'test -s /app/tmp/watcher_heartbeat.json' >/dev/null 2>&1; then
    watcher_ready=1
    break
  fi
  sleep 2
done
if [ "$watcher_ready" -ne 1 ]; then
  echo "ERROR: watcher heartbeat not detected at /app/tmp/watcher_heartbeat.json" >&2
  exit 1
fi

ready_payload=$(curl -sS http://127.0.0.1:18000/readyz || true)
readiness_state=$(READY_JSON="$ready_payload" python - <<'PY'
import json, os
raw = os.environ.get("READY_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("unknown")
    raise SystemExit(0)
detail = data.get("detail") or {}
state = data.get("state") or detail.get("state") or "unknown"
reason = data.get("reason") or detail.get("reason") or ""
if reason:
    print(f"{state} ({reason})")
else:
    print(state)
PY
)

api_health_payload=$(curl -sS http://127.0.0.1:18000/api/health || true)
update_health_state() {
  api_health_ok=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os
raw = os.environ.get("API_HEALTH_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("unknown")
    raise SystemExit(0)
value = data.get("ok")
print("true" if value else "false")
PY
)
  api_health_required_ok=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os
raw = os.environ.get("API_HEALTH_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("unknown")
    raise SystemExit(0)
value = data.get("required_ok")
print("true" if value else "false")
PY
)
  api_health_index_rebuild=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os
raw = os.environ.get("API_HEALTH_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("0")
    raise SystemExit(0)
actions = data.get("suggested_actions") or []
needed = False
for action in actions:
    if isinstance(action, dict) and action.get("id") == "index_rebuild":
        severity = str(action.get("severity") or "").lower()
        if severity == "required":
            needed = True
            break
print("1" if needed else "0")
PY
)
  api_health_failed=$(API_HEALTH_JSON="$api_health_payload" python - <<'PY'
import json, os
raw = os.environ.get("API_HEALTH_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("")
    raise SystemExit(0)
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
PY
)
  api_health_failed=${api_health_failed:-none}
}

update_health_state

auto_bootstrap=${AUTO_BOOTSTRAP:-0}
if [ "$auto_bootstrap" -eq 1 ]; then
  set +e
  settings_validate_json=$(docker compose exec -T api python -m app.cli settings validate --json)
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
if [ "$api_health_index_rebuild" -eq 1 ] && [ "$auto_bootstrap" -ne 1 ]; then
  echo "INDEX REBUILD: required (AUTO_BOOTSTRAP=1 to run)" >&2
  echo "Run: docker compose exec -T api python -m app.cli index rebuild --profile default" >&2
  debug_dump
  exit 1
fi

if ! docker compose exec -T api sh -c '[ -d /app/vault ]' >/dev/null 2>&1; then
  echo "ERROR: /app/vault mount is missing inside the api container" >&2
  exit 1
fi

layout_json=$(docker compose exec -T api python -m app.cli vault-layout-ensure --vault-root /app/vault --json)

vault_note_count=$(docker compose exec -T api sh -c 'find /app/vault -name "*.md" | wc -l' | tr -d '[:space:]')
vault_note_count=${vault_note_count:-0}
if [ "$vault_note_count" -le 0 ]; then
  echo "ERROR: /app/vault contains no markdown files for the watcher scope" >&2
  exit 1
fi

store_stats_json=$(docker compose exec -T api python -m app.cli store stats --json || true)
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

ingest_run="no"
max_notes=${BOOTSTRAP_INGEST_MAX_NOTES:-500}
object_count="$objects_before"
vector_count="$vectors_before"
ingest_summary_json="{}"
if [ "$objects_before" -le 0 ]; then
  ingest_run="yes"
  ingest_summary_json=$(docker compose exec -T api env STORE_BACKEND=pg DATABASE_URL=postgresql://app:app@db:5432/app python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force --json)
  store_stats_json=$(docker compose exec -T api python -m app.cli store stats --json || true)
  objects_after=$(extract_stat objects)
  vectors_after=$(extract_stat vectors)
  object_count="$objects_after"
  vector_count="$vectors_after"
fi

if [ "$auto_bootstrap" -eq 1 ]; then
  api_health_payload=$(curl -sS http://127.0.0.1:18000/api/health || true)
  update_health_state
  if [ "$api_health_index_rebuild" -eq 1 ]; then
    echo "INDEX REBUILD: running"
    set +e
    docker compose exec -T api sh -lc "python -m app.cli index rebuild --profile default"
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

ingested_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os
raw = os.environ.get("INGEST_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
print(payload.get("ingested", 0) or 0)
PY
)
skipped_locked_count=$(INGEST_JSON="$ingest_summary_json" python - <<'PY'
import json, os
raw = os.environ.get("INGEST_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
print(payload.get("skipped_locked", 0) or 0)
PY
)

search_payload=$(curl -sS "http://127.0.0.1:18000/search?q=test&k=3" || true)
search_results=$(SEARCH_JSON="$search_payload" python - <<'PY'
import json, os
raw = os.environ.get("SEARCH_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
print(len(payload.get("results") or []))
PY
)
if [ "$ingest_run" = "yes" ] && [ "$search_results" -eq 0 ]; then
  if [ "$ingested_count" -eq 0 ] && [ "$skipped_locked_count" -gt 0 ]; then
    echo "WARNING: search returned zero results after bootstrap ingest; all candidates were locked (errno=35)."
  else
    echo "ERROR: search returned zero results after bootstrap ingest; check vault mount/store mismatch" >&2
    exit 1
  fi
fi

ask_payload=$(curl -sS http://127.0.0.1:18000/api/ask -H "Content-Type: application/json" -d '{"question":"warm content"}' || true)
ASK_JSON="$ask_payload" python - <<'PY'
import json, os, sys
raw = os.environ.get("ASK_JSON", "")
if not raw:
    raise SystemExit(0)
try:
    json.loads(raw)
except Exception:
    print("WARNING: /api/ask returned a non-JSON payload during bootstrap.", file=sys.stderr)
PY

alpha_bootstrap=${ALPHA_BOOTSTRAP:-0}
bootstrap_next="none"
index_doctor_status="skipped"
index_issue_count=0
if [ "$alpha_bootstrap" -eq 1 ]; then
  index_doctor_json=$(docker compose exec -T api python -m app.cli index doctor --json || true)
  index_doctor_status=$(INDEX_JSON="$index_doctor_json" python - <<'PY'
import json, os
raw = os.environ.get("INDEX_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
print(payload.get("status") or "unknown")
PY
)
  index_issue_count=$(INDEX_JSON="$index_doctor_json" python - <<'PY'
import json, os
raw = os.environ.get("INDEX_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
issues = payload.get("issues") or []
print(len(issues))
PY
)
  rebuild_safe=$(INDEX_JSON="$index_doctor_json" OBJECT_COUNT="$object_count" VECTOR_COUNT="$vector_count" python - <<'PY'
import json, os
raw = os.environ.get("INDEX_JSON", "")
try:
    payload = json.loads(raw)
except Exception:
    payload = {}
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
PY
)
  if [ "$rebuild_safe" -eq 1 ]; then
    docker compose exec -T api python -m app.cli index rebuild --backend pg --json || true
    bootstrap_next="re-run: python -m app.cli index doctor --json"
  elif [ "$index_doctor_status" != "ok" ]; then
    bootstrap_next="python -m app.cli index rebuild --backend pg"
  fi
fi

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
  note: /api/health ok=false can be expected when optional tools (e.g., ffmpeg) are missing; Stage0 ingest/search/ask can still work.
  next: curl -sS http://127.0.0.1:18000/search?q=test&k=3
SUMMARY

echo "Stop watcher: docker compose exec watcher sh -c 'touch /app/tmp/WATCHER_STOP'"
echo "URLs: http://127.0.0.1:18000  |  http://127.0.0.1:18000/api/status"
