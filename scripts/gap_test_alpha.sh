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

info() {
  printf '[gap test] %s\n' "$1"
}

info "wrote marker to $NOTE_PATH"
info "marker = $MARKER"

capture_tail() {
  docker exec "$WATCHER_CONTAINER" bash -lc "tail -n 20 '$OUTBOX_PATH' 2>/dev/null || true"
}

before_tail="$(capture_tail)"
sleep 3
after_tail="$(capture_tail)"
if ! printf '%s' "$after_tail" | grep -q 'watcher\.' && ! printf '%s' "$after_tail" | grep -qF "$NOTE_REL"; then
  printf 'FAIL: watcher outbox did not show change.\n' >&2
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

ask_question="GAP_TEST_MARKER $NONCE"
ask_payload="{\"question\":\"${ask_question}\"}"
ask_response="$(curl --retry 20 --retry-connrefused --retry-delay 1 -sS -X POST "$API_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload")"
info "ask response:\n$ask_response"
mapfile -t ask_lines < <(printf '%s' "$ask_response" | python - <<'PY'
import json, sys
try:
    data = json.load(sys.stdin)
except json.JSONDecodeError as exc:
    sys.stderr.write(f'failed to parse ask response: {exc}\n')
    sys.exit(2)
sources = data.get('sources') or []
print(len(sources))
if not sources:
    sys.exit(3)
print(json.dumps(sources[0], ensure_ascii=False))
PY)
ask_count="${ask_lines[0]:-0}"
ask_source=""
if [ "${#ask_lines[@]}" -gt 1 ]; then
  ask_source="${ask_lines[1]}"
fi
if [ "$ask_count" -lt 1 ]; then
  need_index_rebuild=true
fi

if [ "$need_index_rebuild" = true ]; then
  info "triggering index rebuild"
  docker exec workspace-api-1 bash -lc 'cd /app && python -m app.cli index rebuild --backend pg'
fi

info "ask sources count: $ask_count"
if [ -n "$ask_source" ]; then
  info "first ask source: $ask_source"
fi

info "GAP runtime gap test completed successfully"
