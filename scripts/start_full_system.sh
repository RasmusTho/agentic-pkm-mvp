#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

runtime_env=""
vault_host_path="${VAULT_ROOT:-./vault}"
if [ -n "${VAULT_ROOT:-}" ]; then
  bash scripts/export_runtime_env.sh
  runtime_env="--env-file tmp/runtime.env"
fi

echo "Vault host path: $vault_host_path -> /app/vault"

if [ -n "$runtime_env" ]; then
  docker compose $runtime_env up -d db api worker
else
  docker compose up -d db api worker
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

if ! docker compose exec -T api sh -c '[ -d /app/vault ]' >/dev/null 2>&1; then
  echo "ERROR: /app/vault mount is missing inside the api container" >&2
  exit 1
fi

# Ensure vault layout contract before counting notes or ingest
docker compose exec -T api python -m app.cli vault-layout-ensure --vault-root /app/vault

vault_note_count=$(docker compose exec -T api sh -c 'find /app/vault -name "*.md" | wc -l' | tr -d '[:space:]')
vault_note_count=${vault_note_count:-0}
if [ "$vault_note_count" -le 0 ]; then
  echo "ERROR: /app/vault contains no markdown files for the watcher scope" >&2
  exit 1
fi

store_stats_json=$(docker compose exec -T api python -m app.cli store stats --json)
extract_stat() {
  local key="$1"
  STAT_KEY="$key" STORE_STATS_JSON="$store_stats_json" python - <<'PY'
import json, os
print(json.loads(os.environ['STORE_STATS_JSON']).get(os.environ['STAT_KEY']) or 0)
PY
}
objects_before=$(extract_stat objects)
vectors_before=$(extract_stat vectors)

ingest_run="no"
max_notes=${BOOTSTRAP_INGEST_MAX_NOTES:-500}
object_count="$objects_before"
vector_count="$vectors_before"
if [ "$objects_before" -le 0 ]; then
  ingest_run="yes"
  docker compose exec -T api env STORE_BACKEND=pg DATABASE_URL=postgresql://app:app@db:5432/app python -m app.cli vault-alpha-ingest --vault-root /app/vault --max-notes "$max_notes" --force
  store_stats_json=$(docker compose exec -T api python -m app.cli store stats --json)
  objects_after=$(extract_stat objects)
  vectors_after=$(extract_stat vectors)
  object_count="$objects_after"
  vector_count="$vectors_after"
fi

search_payload=$(curl -sS "http://127.0.0.1:18000/search?q=test&k=3")
search_results=$(SEARCH_JSON="$search_payload" python - <<'PY'
import json, os
payload = json.loads(os.environ['SEARCH_JSON'])
print(len(payload.get('results') or []))
PY
)
if [ "$ingest_run" = "yes" ] && [ "$search_results" -eq 0 ]; then
  echo "ERROR: search returned zero results after bootstrap ingest; check vault mount/store mismatch" >&2
  exit 1
fi

ask_payload=$(curl -sS http://127.0.0.1:18000/api/ask -H "Content-Type: application/json" -d '{"question":"warm content"}')
ASK_JSON="$ask_payload" python - <<'PY'
import json, os
json.loads(os.environ['ASK_JSON'])
PY

cat <<SUMMARY
SUMMARY:
  healthz OK
  readyz: $readiness_state
  api health ok: $api_health_ok
  api health failed: $api_health_failed
  vault notes: $vault_note_count
  store objects: $object_count
  vector entries: $vector_count
  ingest run: $ingest_run
  search results: $search_results
  note: /api/health ok=false can be expected when optional tools (e.g., ffmpeg) are missing; Stage0 ingest/search/ask can still work.
  next: curl -sS http://127.0.0.1:18000/search?q=test&k=3
SUMMARY
