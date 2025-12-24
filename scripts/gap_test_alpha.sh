#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18000}"
OUTBOX_PATH="${OUTBOX_PATH:-/app/tmp/index-outbox.jsonl}"
WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-/app/tmp/watcher_heartbeat.json}"
WORKER_HEARTBEAT_PATH="${WORKER_HEARTBEAT_PATH:-/app/tmp/worker_heartbeat.json}"

WATCHER_CONTAINER="${WATCHER_CONTAINER:-workspace-watcher-1}"
WORKER_CONTAINER="${WORKER_CONTAINER:-workspace-worker-1}"

VAULT_ROOT="${VAULT_ROOT:-$(pwd)/vault}"
NOTE_REL="${NOTE_REL:-@Inbox/_gap_test.md}"
NOTE_PATH="${NOTE_PATH:-$VAULT_ROOT/$NOTE_REL}"

TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-60}"
ASK_RETRIES="${ASK_RETRIES:-6}"
ASK_RETRY_SLEEP="${ASK_RETRY_SLEEP:-1}"

printf '[gap test] bash=%s\n' "$(bash --version | head -n 1 || true)"
printf '[gap test] uname=%s\n' "$(uname -a || true)"
echo "[gap test] API_BASE_URL=$API_BASE_URL"
echo "[gap test] OUTBOX_PATH=$OUTBOX_PATH"
echo "[gap test] NOTE_REL=$NOTE_REL"
echo "[gap test] NOTE_PATH=$NOTE_PATH"

note_dir="$(dirname "$NOTE_PATH")"
mkdir -p "$note_dir"

nonce="$(python -c 'import secrets; print(secrets.token_hex(4))')"
marker="GAP_TEST_MARKER: $(date -u +%Y%m%dT%H%M%SZ) $nonce"

cat > "$NOTE_PATH" <<NOTE
---
uuid: "SET-BY-SYSTEM"
title: "Gap Test"
review_state: "processed"
origin: "local"
trust: "own"
source_ref: "vault://$NOTE_REL"
---

$marker

This note is used by scripts/gap_test_alpha.sh to validate:
- watcher sees vault change
- worker ingests change and emits pipeline/index events
- /api/ask can retrieve the note with sources
NOTE

echo "[gap test] wrote marker to $NOTE_PATH"
echo "[gap test] marker = $marker"

echo "[gap test] outbox tail before:"
curl -sS "$API_BASE_URL/api/events/tail?path=$OUTBOX_PATH&n=30" || true
echo

deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))

echo "[gap test] waiting for watcher to emit panel.scan.requested for $NOTE_REL ..."
found_scan=0
while [ "$(date +%s)" -lt "$deadline" ]; do
  tail_payload="$(curl -sS "$API_BASE_URL/api/events/tail?path=$OUTBOX_PATH&n=200" || true)"
  if printf '%s' "$tail_payload" | grep -q '"event"[[:space:]]*:[[:space:]]*"panel.scan.requested"' \
     && printf '%s' "$tail_payload" | grep -qF "$NOTE_REL"; then
    found_scan=1
    break
  fi
  sleep 0.5
done

if [ "$found_scan" -ne 1 ]; then
  echo "[gap test] did not observe panel.scan.requested within timeout"
  echo "[gap test] diagnostics: outbox tail after:"
  curl -sS "$API_BASE_URL/api/events/tail?path=$OUTBOX_PATH&n=120" || true
  echo
  echo "[gap test] watcher heartbeat:"
  docker exec "$WATCHER_CONTAINER" bash -lc "cat '$WATCHER_HEARTBEAT_PATH' 2>/dev/null || true" || true
  echo
  docker logs --tail 200 "$WATCHER_CONTAINER" || true
  exit 1
fi

echo "[gap test] worker stat:"
docker exec "$WORKER_CONTAINER" bash -lc "stat -f '%z %m %N' '$OUTBOX_PATH' || stat '$OUTBOX_PATH' || true" || true

echo "[gap test] worker logs (tail 120):"
docker logs --tail 120 "$WORKER_CONTAINER" || true

echo "[gap test] api health payload:"
curl -sS "$API_BASE_URL/api/health" || true
echo

echo "[gap test] api status payload:"
curl -sS "$API_BASE_URL/api/status" || true
echo

question='Return exactly the line that starts with "GAP_TEST_MARKER:" from the latest gap test note. Reply with only that line.'
ask_has_sources=0
ask_answer=""
ask_sources_len=0
ask_response=""

for i in $(seq 1 "$ASK_RETRIES"); do
  ask_payload="$(ASK_QUESTION="$question" python - <<'PY'
import json, os
print(json.dumps({"question": os.environ.get("ASK_QUESTION", "")}))
PY
  )"
  ask_response="$(curl -sS "$API_BASE_URL/api/ask" -H 'Content-Type: application/json' -d "$ask_payload" || true)"

  parsed="$(printf '%s' "$ask_response" | NOTE_REL_ENV="$NOTE_REL" NONCE_ENV="$nonce" python - <<'PY'
import json, os, sys

note_rel = os.environ.get("NOTE_REL_ENV", "")
nonce = os.environ.get("NONCE_ENV", "")
raw = sys.stdin.read().strip()

data = {}
if raw:
  try:
    data = json.loads(raw)
  except Exception:
    data = {}

sources = data.get("sources") or []
answer = (data.get("answer") or "").replace("\n", " ").strip()

has_sources = 1 if len(sources) > 0 else 0
marker_ok = 1 if (nonce and nonce in answer) else 0
note_ok = 0
for s in sources:
  if isinstance(s, dict):
    path = s.get("relative_path") or s.get("path") or ""
    if note_rel and note_rel in str(path):
      note_ok = 1
  elif note_rel and note_rel in str(s):
    note_ok = 1

print(f"has_sources={has_sources}")
print(f"sources_len={len(sources)}")
print(f"marker_ok={marker_ok}")
print(f"note_ok={note_ok}")
print("answer=" + answer)
PY
  )"

  ask_has_sources="$(printf '%s\n' "$parsed" | sed -n 's/^has_sources=//p' | tail -n 1)"
  ask_sources_len="$(printf '%s\n' "$parsed" | sed -n 's/^sources_len=//p' | tail -n 1)"
  marker_ok="$(printf '%s\n' "$parsed" | sed -n 's/^marker_ok=//p' | tail -n 1)"
  note_ok="$(printf '%s\n' "$parsed" | sed -n 's/^note_ok=//p' | tail -n 1)"
  ask_answer="$(printf '%s\n' "$parsed" | sed -n 's/^answer=//p' | tail -n 1)"

  if [ "${ask_has_sources:-0}" = "1" ] && [ "${marker_ok:-0}" = "1" ] && [ "${note_ok:-0}" = "1" ]; then
    break
  fi

  sleep "$ASK_RETRY_SLEEP"
done

echo "[gap test] ask response:"
echo "$ask_response"
echo

if [ "${ask_has_sources:-0}" != "1" ] || [ "${marker_ok:-0}" != "1" ] || [ "${note_ok:-0}" != "1" ]; then
  echo "[gap test] /api/ask validation failed: has_sources=${ask_has_sources:-0} marker_ok=${marker_ok:-0} note_ok=${note_ok:-0} (sources_len=${ask_sources_len:-0})"
  echo "[gap test] diagnostics:"
  echo "[gap test] outbox tail after:"
  curl -sS "$API_BASE_URL/api/events/tail?path=$OUTBOX_PATH&n=120" || true
  echo

  echo "[gap test] grep marker in outbox (watcher container):"
  docker exec "$WATCHER_CONTAINER" bash -lc "grep -nF '$marker' '$OUTBOX_PATH' || true" || true
  echo

  echo "[gap test] grep marker in outbox (worker container):"
  docker exec "$WORKER_CONTAINER" bash -lc "grep -nF '$marker' '$OUTBOX_PATH' || true" || true
  echo

  echo "[gap test] watcher heartbeat:"
  docker exec "$WATCHER_CONTAINER" bash -lc "cat '$WATCHER_HEARTBEAT_PATH' 2>/dev/null || true" || true
  echo

  echo "[gap test] worker heartbeat:"
  docker exec "$WORKER_CONTAINER" bash -lc "cat '$WORKER_HEARTBEAT_PATH' 2>/dev/null || true" || true
  echo

  docker logs --tail 200 "$WORKER_CONTAINER" || true
  docker logs --tail 200 "$WATCHER_CONTAINER" || true
  exit 2
fi

echo "[gap test] OK: /api/ask returned sources and marker (sources_len=${ask_sources_len:-0})"
echo "[gap test] answer: $ask_answer"
exit 0
