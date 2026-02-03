#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
VAULT_ROOT="${VAULT_ROOT:-$(pwd)/vault}"
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

resolve_inbox_dir() {
  if [ -n "${VAULT_INBOX_DIR_REL:-}" ]; then
    printf '%s\n' "${VAULT_INBOX_DIR_REL}"
    return
  fi

  python -m app.cli vault-layout-ensure --vault-root "$VAULT_ROOT" --json \
    | python - <<'PY'
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
print((payload.get("inbox_folder") or "").strip())
PY
}

inbox_dir_rel="$(resolve_inbox_dir)"
if [ -z "$inbox_dir_rel" ]; then
  echo "ERROR: could not resolve inbox folder; set VAULT_INBOX_DIR_REL or ensure vault.layout.md exists" >&2
  exit 1
fi

NOTE_REL="${NOTE_REL:-${inbox_dir_rel}/_gap_test.md}"
NOTE_PATH="${NOTE_PATH:-$VAULT_ROOT/$NOTE_REL}"

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
    if relative_path(entry) == note_rel:
        sys.exit(0)
sys.exit(1)
PY
  then
    panel_seen=1
    break
  fi
  sleep "$ASK_RETRY_SLEEP"
done

if [ "$panel_seen" -ne 1 ]; then
  echo "[gap test] panel.scan.requested not observed" >&2
  exit 2
fi

printf '[gap test] panel.scan.requested observed for %s\n' "$NOTE_REL"
