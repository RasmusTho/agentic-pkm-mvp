#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT_PATH="${VAULT_PATH:-$ROOT/vault}"
NOTE_REL="${1:-@Inbox/_gap_test.md}"
NOTE_PATH="$VAULT_PATH/$NOTE_REL"
OUTBOX_PATH="${OUTBOX_PATH:-/app/tmp/index-outbox.jsonl}"
WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-/app/tmp/watcher_heartbeat.json}"
WATCHER_CONTAINER="${WATCHER_CONTAINER:-workspace-watcher-1}"
WORKER_CONTAINER="${WORKER_CONTAINER:-workspace-worker-1}"
API_URL="${API_URL:-http://127.0.0.1:18000}"
REBUILD_INDEX_CMD="docker exec workspace-api-1 bash -lc 'cd /app && python -m app.cli index rebuild --backend pg'"

NONCE="$(python - <<'PY'
import secrets
print(secrets.token_hex(4))
PY)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MARKER="GAP_TEST_MARKER: $TIMESTAMP $NONCE"

info() {
  printf '[gap test] %s\n' "$1"
}

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
  docker exec "$WATCHER_CONTAINER" bash -lc "tail -n 20 '$OUTBOX_PATH' 2>/dev/null || true"
}

before_tail="$(capture_tail)"
sleep 3
after_tail="$(capture_tail)"
if ! printf '%s' "$after_tail" | grep -q 'watcher\.' && ! printf '%s' "$after_tail" | grep -qF "$NOTE_REL"; then
  printf 'FAIL: watcher outbox did not register the marker.\n' >&2
  docker exec "$WATCHER_CONTAINER" bash -lc "tail -n 20 '$OUTBOX_PATH' || true"
  docker exec "$WATCHER_CONTAINER" bash -lc "cat '$WATCHER_HEARTBEAT_PATH' || echo 'no heartbeat found'"
  exit 1
fi
info "outbox tail before:\n$before_tail"
info "outbox tail after:\n$after_tail"

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

if [ "$need_index_rebuild" = true ]; then
  info "triggering index rebuild"
  $REBUILD_INDEX_CMD
fi

ask_question="GAP_TEST_MARKER $NONCE"
ask_payload="{\"question\":\"${ask_question}\"}"

attempts=0
max_attempts=6
ask_count=0
matched=0
ask_source=""
reason=""
while [ $attempts -lt $max_attempts ]; do
  info "ask attempt $((attempts + 1))"
  ask_response="$(curl --retry 20 --retry-connrefused --retry-delay 1 -sS -X POST "$API_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload")"
  info "ask response:\n$ask_response"
  parse=$(printf '%s' "$ask_response" | python - <<'PY'
import json, sys
needle = sys.argv[1]
marker = sys.argv[2]
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError as exc:
    sys.stderr.write(f'ask response decode failed: {exc}\n')
    sys.exit(1)
sources = data.get('sources') or []
if not sources:
    print(0)
    print(0)
    print('')
    sys.exit(3)
found = 0
best = ''
for src in sources:
    text = json.dumps(src, ensure_ascii=False)
    if not best:
        best = text
    if needle in text or marker in text:
        found = 1
        best = text
        break
print(len(sources))
print(found)
print(best.replace('\n', ' ').replace('\r', ' '))
if not found:
    sys.exit(4)
PY "$NOTE_REL" "GAP_TEST_MARKER"
  parse_exit=$?
  IFS=$'\n'
  read -r ask_count matched ask_source <<< "$parse"
  ask_count=${ask_count:-0}
  matched=${matched:-0}
  if [ $parse_exit -eq 0 ] && [ "$matched" -eq 1 ]; then
    info "ask returned $ask_count sources and matched the test marker"
    break
  fi
  if [ $parse_exit -eq 3 ]; then
    reason="ask returned no sources"
  elif [ $parse_exit -eq 4 ]; then
    reason="ask returned sources but none referenced the gap marker"
  else
    reason="ask response parsing error"
  fi
  attempts=$((attempts + 1))
  if [ $attempts -lt $max_attempts ]; then
    sleep 5
  fi
done

if [ "$matched" -ne 1 ]; then
  info "final ask count: $ask_count"
  info "final ask source detail: $ask_source"
  printf 'FAIL: /api/ask did not return a source linked to %s (%s)\n' "$NOTE_REL" "$reason" >&2
  printf 'api health payload:\n%s\n' "$health_payload"
  printf 'api status payload:\n%s\n' "$status_payload"
  docker exec "$WATCHER_CONTAINER" bash -lc "grep -nF '$MARKER' '$OUTBOX_PATH' || true"
  docker exec "$WORKER_CONTAINER" bash -lc "grep -nF '$MARKER' '$OUTBOX_PATH' || true"
  docker logs --tail 200 "$WORKER_CONTAINER" || true
  docker logs --tail 200 "$WATCHER_CONTAINER" || true
  printf 'ask response final:\n%s\n' "$ask_response"
  exit 2
fi

info "ask sources count: $ask_count"
if [ -n "$ask_source" ]; then
  info "first matching ask source: $ask_source"
fi

info "GAP runtime gap test completed successfully"
