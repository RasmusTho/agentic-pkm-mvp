#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
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

pretty_json() {
  "$JSON_TOOL_PYTHON" -m json.tool
}

note_dir="$(dirname "$NOTE_PATH")"
mkdir -p "$note_dir"

uuid="$(python - <<'PY'
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

printf '[gap test] marker note written: %s\n' "$NOTE_PATH"
printf '[gap test] marker line: %s\n' "$marker"

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
panel_seen=0

while [ "$(date +%s)" -lt "$deadline" ]; do
  panel_payload="$(curl -sS "$API_BASE_URL/api/events/tail?topic=panel.scan.requested&limit=50" || true)"
  if NOTE_REL_ENV="$NOTE_REL" PANEL_PAYLOAD_JSON="$panel_payload" python - <<'PY'
import json, os, sys
raw = os.environ.get('PANEL_PAYLOAD_JSON', '')
if not raw:
    sys.exit(1)
try:
    data = json.loads(raw)
except Exception:
    sys.exit(1)

def collect(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from collect(value)
    elif isinstance(node, list):
        for item in node:
            yield from collect(item)

def relative_path(entry):
    if not isinstance(entry, dict):
        return ''
    payload = entry.get('payload') or {}
    if isinstance(payload, dict):
        rel = payload.get('relative_path') or payload.get('path') or ''
    else:
        rel = ''
    rel = rel or entry.get('relative_path') or entry.get('path') or ''
    return rel
note_rel = os.environ.get('NOTE_REL_ENV', '')
for entry in collect(data):
    if not isinstance(entry, dict):
        continue
    event = entry.get('event') or entry.get('name') or ''
    rel = relative_path(entry)
    if event == 'panel.scan.requested' and rel == note_rel:
        sys.exit(0)
sys.exit(1)
PY
  then
    panel_seen=1
    break
  fi
  sleep 1
done

if [ "$panel_seen" -ne 1 ]; then
  echo '[gap test] panel.scan.requested timeout'
  echo '[gap test] diagnostics: /api/status'
  curl -sS "$API_BASE_URL/api/status" | pretty_json || true
  echo '[gap test] diagnostics: /api/health'
  curl -sS "$API_BASE_URL/api/health" | pretty_json || true
  echo '[gap test] diagnostics: panel.scan.requested events tail'
  curl -sS "$API_BASE_URL/api/events/tail?topic=panel.scan.requested&limit=50" | pretty_json || true
  echo '[gap test] diagnostics: index.object.embedded events tail'
  curl -sS "$API_BASE_URL/api/events/tail?topic=index.object.embedded&limit=50" | pretty_json || true
  exit 1
fi

ask_response=""
parse_ok=0
note_present=0
marker_ok=0
sources_len=0

for i in $(seq 1 "$ASK_RETRIES"); do
  ask_payload="$(python - <<'PY'
import json
print(json.dumps({"question": "What is the GAP_TEST_MARKER line from the latest gap test note?"}))
PY
  )"
  ask_response="$(curl -sS "$API_BASE_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload" || true)"
  parsed="$(NOTE_REL_ENV="$NOTE_REL" MARKER_ENV="$marker" ASK_RESPONSE_JSON="$ask_response" python - <<'PY'
import json, os, sys
raw = os.environ.get('ASK_RESPONSE_JSON', '')
if not raw:
    print('parse_ok=0')
    sys.exit(0)
try:
    data = json.loads(raw)
except Exception:
    print('parse_ok=0')
    sys.exit(0)
answer = (data.get('answer') or '').replace('\n', ' ').strip()
sources = data.get('sources') or []
note_rel = os.environ.get('NOTE_REL_ENV', '')
marker = os.environ.get('MARKER_ENV', '')
note_ok = 0
for entry in sources:
    if isinstance(entry, dict):
        path_val = entry.get('relative_path') or entry.get('path') or ''
    else:
        path_val = str(entry)
    if note_rel and note_rel in path_val:
        note_ok = 1
marker_ok = 1 if marker and marker in answer else 0
print(f'parse_ok=1')
print(f'note_ok={note_ok}')
print(f'marker_ok={marker_ok}')
print(f'sources_len={len(sources)}')
print(f'answer={answer}')
PY
  )"
  parse_ok="$(printf '%s\n' "$parsed" | sed -n 's/^parse_ok=//p' | tail -n 1)"
  note_present="$(printf '%s\n' "$parsed" | sed -n 's/^note_ok=//p' | tail -n 1)"
  marker_ok="$(printf '%s\n' "$parsed" | sed -n 's/^marker_ok=//p' | tail -n 1)"
  sources_len="$(printf '%s\n' "$parsed" | sed -n 's/^sources_len=//p' | tail -n 1)"
  if [ "${parse_ok:-0}" != "1" ]; then
    echo '[gap test] /api/ask response could not be parsed'
    break
  fi
  if [ "${note_present:-0}" = "1" ] && [ "${marker_ok:-0}" = "1" ]; then
    break
  fi
  sleep "$ASK_RETRY_SLEEP"
done

echo '[gap test] /api/ask response:'
echo "$ask_response"

echo '[gap test] note_present' "$note_present" '[marker_ok]' "$marker_ok" '[sources_len]' "$sources_len"

echo '[gap test] api status payload:'
curl -sS "$API_BASE_URL/api/status" | pretty_json || true

echo '[gap test] api health payload:'
curl -sS "$API_BASE_URL/api/health" | pretty_json || true

echo '[gap test] events tail (panel.scan.requested):'
curl -sS "$API_BASE_URL/api/events/tail?topic=panel.scan.requested&limit=50" | pretty_json || true

echo '[gap test] events tail (index.object.embedded):'
curl -sS "$API_BASE_URL/api/events/tail?topic=index.object.embedded&limit=50" | pretty_json || true

if [ "${parse_ok:-0}" != "1" ]; then
  exit 1
fi
if [ "${note_present:-0}" != "1" ]; then
  echo '[gap test] /api/ask did not report the marker note as a source'
  exit 2
fi
if [ "${marker_ok:-0}" != "1" ]; then
  echo '[gap test] /api/ask did not echo the marker line in the answer'
  exit 2
fi

printf '[gap test] success: sources=%s\n' "${sources_len:-0}"
exit 0
