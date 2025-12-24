#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"

OUTBOX_PATH="${OUTBOX_PATH:-/app/tmp/index-outbox.jsonl}"
WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-/app/tmp/watcher_heartbeat.json}"
WORKER_HEARTBEAT_PATH="${WORKER_HEARTBEAT_PATH:-/app/tmp/worker_heartbeat.json}"

WATCHER_CONTAINER="${WATCHER_CONTAINER:-workspace-watcher-1}"
WORKER_CONTAINER="${WORKER_CONTAINER:-workspace-worker-1}"

NOTE_REL="${NOTE_REL:-@Inbox/_gap_test.md}"
VAULT_ROOT="${VAULT_ROOT:-$(pwd)/vault}"
NOTE_PATH="${NOTE_PATH:-$VAULT_ROOT/$NOTE_REL}"

TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
ASK_RETRIES="${ASK_RETRIES:-6}"
ASK_RETRY_SLEEP="${ASK_RETRY_SLEEP:-1}"

JSON_TOOL_PYTHON="python3"
if ! command -v "$JSON_TOOL_PYTHON" >/dev/null 2>&1; then
  JSON_TOOL_PYTHON="python"
fi

pretty_json() { "$JSON_TOOL_PYTHON" -m json.tool; }

has_docker=0
if command -v docker >/dev/null 2>&1; then
  has_docker=1
fi

printf '[gap test] bash=%s\n' "$(bash --version | head -n 1 || true)"
printf '[gap test] uname=%s\n' "$(uname -a || true)"
echo "[gap test] API_BASE_URL=$API_BASE_URL"
echo "[gap test] OUTBOX_PATH=$OUTBOX_PATH"
echo "[gap test] NOTE_REL=$NOTE_REL"
echo "[gap test] NOTE_PATH=$NOTE_PATH"

note_dir="$(dirname "$NOTE_PATH")"
mkdir -p "$note_dir"

uuid="$("$JSON_TOOL_PYTHON" - <<'PY'
import uuid
print(uuid.uuid4())
PY
)"
marker="GAP_TEST_MARKER: $(date -u +%Y%m%dT%H%M%SZ) $uuid"

cat > "$NOTE_PATH" <<NOTE
---
uuid: [[${uuid}]]
title: _gap_test
review_state: inbox
---
$marker
NOTE

echo "[gap test] wrote marker to $NOTE_PATH"
echo "[gap test] marker = $marker"

tail_topic() { curl -sS "$API_BASE_URL/api/events/tail?topic=$1&limit=$2" 2>/dev/null || true; }
tail_path()  { curl -sS "$API_BASE_URL/api/events/tail?path=$1&n=$2" 2>/dev/null || true; }

seen_scan_event() {
  NOTE_REL_ENV="$NOTE_REL" TAIL_JSON="$1" "$JSON_TOOL_PYTHON" - <<'PY'
import json, os, sys
note_rel = os.environ.get("NOTE_REL_ENV","")
raw = os.environ.get("TAIL_JSON","") or ""
if not raw.strip():
  sys.exit(1)
try:
  data = json.loads(raw)
except Exception:
  sys.exit(1)

def walk(x):
  if isinstance(x, dict):
    yield x
    for v in x.values():
      for y in walk(v):
        yield y
  elif isinstance(x, list):
    for i in x:
      for y in walk(i):
        yield y

def relpath(entry):
  if not isinstance(entry, dict):
    return ""
  payload = entry.get("payload")
  if isinstance(payload, dict):
    return payload.get("relative_path") or payload.get("path") or ""
  return entry.get("relative_path") or entry.get("path") or ""

for entry in walk(data):
  if not isinstance(entry, dict):
    continue
  ev = entry.get("event") or entry.get("name") or ""
  rp = relpath(entry)
  if ev == "panel.scan.requested" and rp == note_rel:
    sys.exit(0)

sys.exit(1)
PY
}

diagnostics() {
  echo "[gap test] diagnostics: /api/status"
  curl -sS "$API_BASE_URL/api/status" | pretty_json || true
  echo "[gap test] diagnostics: /api/health"
  curl -sS "$API_BASE_URL/api/health" | pretty_json || true

  echo "[gap test] diagnostics: events tail (topic panel.scan.requested)"
  tail_topic "panel.scan.requested" 50 | pretty_json || true
  echo "[gap test] diagnostics: events tail (topic index.object.embedded)"
  tail_topic "index.object.embedded" 50 | pretty_json || true

  echo "[gap test] diagnostics: events tail (path outbox)"
  tail_path "$OUTBOX_PATH" 120 | pretty_json || true

  if [ "$has_docker" -eq 1 ]; then
    echo "[gap test] diagnostics: watcher heartbeat"
    docker exec "$WATCHER_CONTAINER" bash -lc "cat '$WATCHER_HEARTBEAT_PATH' 2>/dev/null || true" || true
    echo "[gap test] diagnostics: worker heartbeat"
    docker exec "$WORKER_CONTAINER" bash -lc "cat '$WORKER_HEARTBEAT_PATH' 2>/dev/null || true" || true
    echo "[gap test] diagnostics: watcher logs (tail 200)"
    docker logs --tail 200 "$WATCHER_CONTAINER" || true
    echo "[gap test] diagnostics: worker logs (tail 200)"
    docker logs --tail 200 "$WORKER_CONTAINER" || true
  fi
}

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
panel_seen=0

echo "[gap test] waiting for watcher to emit panel.scan.requested for $NOTE_REL ..."

while [ "$(date +%s)" -lt "$deadline" ]; do
  payload="$(tail_topic "panel.scan.requested" 50)"
  if seen_scan_event "$payload"; then
    panel_seen=1
    break
  fi

  payload2="$(tail_path "$OUTBOX_PATH" 200)"
  if seen_scan_event "$payload2"; then
    panel_seen=1
    break
  fi

  sleep 1
done

if [ "$panel_seen" -ne 1 ]; then
  echo "[gap test] panel.scan.requested timeout"
  diagnostics
  exit 1
fi

question='Return exactly the line that starts with "GAP_TEST_MARKER:" from the latest gap test note. Reply with only that line.'
ask_response=""
note_ok=0
marker_ok=0
sources_len=0

for i in $(seq 1 "$ASK_RETRIES"); do
  ask_payload="$("$JSON_TOOL_PYTHON" - <<PY
import json
print(json.dumps({"question": ${question@Q}}))
PY
)"
  ask_response="$(curl -sS "$API_BASE_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload" || true)"

  parsed="$(NOTE_REL_ENV="$NOTE_REL" MARKER_ENV="$marker" ASK_RESPONSE_JSON="$ask_response" "$JSON_TOOL_PYTHON" - <<'PY'
import json, os, sys
raw = os.environ.get("ASK_RESPONSE_JSON","") or ""
try:
  data = json.loads(raw) if raw.strip() else {}
except Exception:
  data = {}

sources = data.get("sources") or []
answer = (data.get("answer") or "").replace("\n"," ").strip()

note_rel = os.environ.get("NOTE_REL_ENV","")
marker = os.environ.get("MARKER_ENV","")

note_ok = 0
for s in sources:
  if isinstance(s, dict):
    p = s.get("relative_path") or s.get("path") or ""
  else:
    p = str(s)
  if note_rel and note_rel in str(p):
    note_ok = 1

marker_ok = 1 if (marker and marker in answer) else 0

print(f"note_ok={note_ok}")
print(f"marker_ok={marker_ok}")
print(f"sources_len={len(sources)}")
print("answer=" + answer)
PY
  )"

  note_ok="$(printf '%s\n' "$parsed" | sed -n 's/^note_ok=//p' | tail -n 1)"
  marker_ok="$(printf '%s\n' "$parsed" | sed -n 's/^marker_ok=//p' | tail -n 1)"
  sources_len="$(printf '%s\n' "$parsed" | sed -n 's/^sources_len=//p' | tail -n 1)"

  if [ "${note_ok:-0}" = "1" ] && [ "${marker_ok:-0}" = "1" ]; then
    break
  fi

  sleep "$ASK_RETRY_SLEEP"
done

echo "[gap test] /api/ask response:"
echo "$ask_response"
echo "[gap test] note_ok=$note_ok marker_ok=$marker_ok sources_len=$sources_len"

if [ "${note_ok:-0}" != "1" ] || [ "${marker_ok:-0}" != "1" ]; then
  echo "[gap test] /api/ask validation failed"
  diagnostics
  exit 2
fi

printf '[gap test] success: sources=%s\n' "${sources_len:-0}"
exit 0
