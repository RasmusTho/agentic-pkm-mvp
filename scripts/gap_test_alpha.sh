#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT_PATH="${VAULT_PATH:-$ROOT/vault}"
NOTE_REL="${1:-@Inbox/_gap_test.md}"
NOTE_PATH="$VAULT_PATH/$NOTE_REL"
OUTBOX_PATH="${OUTBOX_PATH:-/app/tmp/index-outbox.jsonl}"
WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-/app/tmp/watcher_heartbeat.json}"
WORKER_HEARTBEAT_PATH="${WORKER_HEARTBEAT_PATH:-/app/tmp/worker_heartbeat.json}"
WATCHER_CONTAINER="${WATCHER_CONTAINER:-workspace-watcher-1}"
WORKER_CONTAINER="${WORKER_CONTAINER:-workspace-worker-1}"
API_URL="${API_URL:-http://127.0.0.1:18000}"
REBUILD_INDEX_CMD="docker exec workspace-api-1 bash -lc 'cd /app && python -m app.cli index rebuild --backend pg'"

printf '[gap test] bash=%s\n' "$(bash --version | head -n 1)"
printf '[gap test] uname=%s\n' "$(uname -a)"

info() {
  printf '[gap test] %s\n' "$1"
}

worker_ingest_status() {
  docker exec "$WORKER_CONTAINER" bash -lc "cat '$WORKER_HEARTBEAT_PATH' 2>/dev/null || true" | python - <<'PY'
import json
import sys
raw = sys.stdin.read().strip()
if not raw:
    print("0 0")
    sys.exit(0)
try:
    data = json.loads(raw)
except Exception:
    print("0 0")
    sys.exit(0)
by_event = data.get("processed_by_event") or {}
last_map = data.get("last_processed") or {}
count = 0
if isinstance(by_event, dict):
    try:
        count = int(by_event.get("ingest.vault.changed") or 0)
    except Exception:
        count = 0
last_ts = 0.0
if isinstance(last_map, dict):
    try:
        last_ts = float(last_map.get("ingest.vault.changed") or 0.0)
    except Exception:
        last_ts = 0.0
print(f"{count} {last_ts}")
PY
}

wait_for_worker_ingest() {
  initial_count="$1"
  initial_ts="$2"
  max_attempts=15
  attempts=0
  while [ $attempts -lt $max_attempts ]; do
    read -r current_count current_ts <<EOT
$(worker_ingest_status)
EOT
    if [ "$current_count" -gt "$initial_count" ]; then
      return 0
    fi
    if python - "$initial_ts" "$current_ts" <<'PY'
import sys
try:
    initial = float(sys.argv[1])
    current = float(sys.argv[2])
except Exception:
    sys.exit(1)
if current > initial and current > 0:
    sys.exit(0)
sys.exit(1)
PY
    then
      return 0
    fi
    attempts=$((attempts + 1))
    sleep 2
  done
  return 1
}

read -r baseline_count baseline_ts <<EOT
$(worker_ingest_status)
EOT
info "worker ingest baseline: count=$baseline_count ts=$baseline_ts"

NONCE="$(python - <<'PY'
import secrets
print(secrets.token_hex(4))
PY)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MARKER="GAP_TEST_MARKER: $TIMESTAMP $NONCE"

mkdir -p "$(dirname "$NOTE_PATH")"
if ! grep -q '^# GAP Runtime Gap Test' "$NOTE_PATH" 2>/dev/null; then
  cat <<'TXT' >> "$NOTE_PATH"
# GAP Runtime Gap Test
TXT
fi
printf '%s\n' "$MARKER" >> "$NOTE_PATH"
info "wrote marker to $NOTE_PATH"
info "marker = $MARKER"

capture_tail() {
  docker exec "$WATCHER_CONTAINER" bash -lc "tail -n 40 '$OUTBOX_PATH' 2>/dev/null || true"
}

before_tail="$(capture_tail)"
sleep 3
after_tail="$(capture_tail)"
if ! printf '%s' "$after_tail" | grep -q 'ingest.vault.changed' && ! printf '%s' "$after_tail" | grep -qF "$NOTE_REL"; then
  printf 'FAIL: watcher outbox did not register ingest.vault.changed for the marker.\n' >&2
  docker exec "$WATCHER_CONTAINER" bash -lc "tail -n 40 '$OUTBOX_PATH' || true"
  docker exec "$WATCHER_CONTAINER" bash -lc "cat '$WATCHER_HEARTBEAT_PATH' || echo 'no heartbeat found'"
  exit 1
fi
info "outbox tail before:\n$before_tail"
info "outbox tail after:\n$after_tail"

info "waiting for worker to process ingest.vault.changed"
if ! wait_for_worker_ingest "$baseline_count" "$baseline_ts"; then
  printf 'FAIL: worker did not process ingest.vault.changed within timeout.\n' >&2
  docker exec "$WORKER_CONTAINER" bash -lc "cat '$WORKER_HEARTBEAT_PATH' || echo 'no worker heartbeat'"
  docker logs --tail 200 "$WORKER_CONTAINER" || true
  docker logs --tail 200 "$WATCHER_CONTAINER" || true
  exit 1
fi

stat_snapshot() {
  docker exec "$WORKER_CONTAINER" bash -lc "stat -c '%s %Y %n' '$OUTBOX_PATH' 2>/dev/null || echo 'missing $OUTBOX_PATH'"
}

worker_before="$(stat_snapshot)"
sleep 3
worker_after="$(stat_snapshot)"
info "worker stat before: $worker_before"
info "worker stat after: $worker_after"
info "worker logs (tail 120):"
docker logs --tail 120 "$WORKER_CONTAINER" || true

health_payload="$(curl --retry 20 --retry-connrefused --retry-delay 1 -sS "$API_URL/api/health")"
status_payload="$(curl --retry 20 --retry-connrefused --retry-delay 1 -sS "$API_URL/api/status")"
info "api health payload:\n$health_payload"
info "api status payload:\n$status_payload"

need_index_rebuild=false
if printf '%s' "$status_payload" | grep -q 'vector_index_meta' && printf '%s' "$status_payload" | grep -q 'null'; then
  need_index_rebuild=true
fi

ask_question="GAP_TEST_MARKER $NONCE"
ask_payload="{\"question\":\"${ask_question}\"}"

attempts=0
max_attempts=6
ask_ok=0
ask_summary=""
while [ $attempts -lt $max_attempts ]; do
  info "ask attempt $((attempts + 1))"
  ask_response="$(curl --retry 20 --retry-connrefused --retry-delay 1 -sS -X POST "$API_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload" || true)"
  summary=$(NOTE_REL_ENV="$NOTE_REL" MARKER_ENV="$MARKER" python - <<'PY'
import json, os, sys, textwrap
note_rel = os.environ.get("NOTE_REL_ENV", "")
marker = os.environ.get("MARKER_ENV", "")
raw = sys.stdin.read()
try:
    data = json.loads(raw)
except Exception as exc:
    print(f"parse_error: {exc}")
    sys.exit(3)
sources = data.get("sources") or []
answer = data.get("answer") or ""
first = sources[0] if sources else {}
first_text = json.dumps(first, ensure_ascii=False) if first else ""
matched = any((note_rel in json.dumps(src, ensure_ascii=False)) or (marker in json.dumps(src, ensure_ascii=False)) for src in sources)
print(len(sources))
print(1 if matched else 0)
print(textwrap.shorten(answer, width=120, placeholder="…"))
print(first_text)
if matched:
    sys.exit(0)
if sources:
    sys.exit(4)
sys.exit(5)
PY <<<"$ask_response")
  count=$(printf '%s\n' "$summary" | sed -n '1p')
  matched=$(printf '%s\n' "$summary" | sed -n '2p')
  answer_snip=$(printf '%s\n' "$summary" | sed -n '3p')
  first_source=$(printf '%s\n' "$summary" | sed -n '4p')
  ask_summary="sources=$count matched=$matched answer=$answer_snip first_source=$first_source"
  if [ "$matched" = "1" ]; then
    ask_ok=1
    break
  fi
  attempts=$((attempts + 1))
  sleep 5
done

if [ $ask_ok -ne 1 ]; then
  info "ask validation failed"
  info "ask summary:\n$ask_summary"
  printf 'api health payload:\n%s\n' "$health_payload"
  printf 'api status payload:\n%s\n' "$status_payload"
  docker exec "$WATCHER_CONTAINER" bash -lc "grep -nF '$MARKER' '$OUTBOX_PATH' || true"
  docker exec "$WORKER_CONTAINER" bash -lc "grep -nF '$MARKER' '$OUTBOX_PATH' || true"
  docker exec "$WORKER_CONTAINER" bash -lc "cat '$WORKER_HEARTBEAT_PATH' || echo 'no worker heartbeat'"
  docker logs --tail 200 "$WORKER_CONTAINER" || true
  docker logs --tail 200 "$WATCHER_CONTAINER" || true
  printf 'ask response final:\n%s\n' "$ask_response"
  if [ "$need_index_rebuild" = true ]; then
    info "triggering index rebuild"
    $REBUILD_INDEX_CMD || true
  fi
  exit 2
fi

info "ask summary:\n$ask_summary"
info "GAP runtime gap test completed successfully"
