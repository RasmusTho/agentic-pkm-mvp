#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "ERROR: VAULT_ROOT must be set to locate the vault." >&2
  exit 1
fi

if [ ! -d "$VAULT_ROOT" ]; then
  echo "ERROR: VAULT_ROOT does not point to a directory: $VAULT_ROOT" >&2
  exit 1
fi

echo "Ensuring vault layout for: $VAULT_ROOT"
layout_json=$(python -m app.cli vault-layout-ensure --vault-root "$VAULT_ROOT" --json)

inbox_dir=$(python - <<'PY'
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
print(payload.get("inbox_folder") or "")
PY
<<<"$layout_json")

if [ -z "$inbox_dir" ]; then
  echo "ERROR: inbox_folder missing from layout output" >&2
  exit 1
fi

inbox_base="$VAULT_ROOT/$inbox_dir"
if [ ! -d "$inbox_base" ]; then
  echo "ERROR: inbox directory missing: $inbox_base" >&2
  exit 1
fi

smoke_dir="$inbox_base/@Smoke"
mkdir -p "$smoke_dir"

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
note_name="watcher-smoke-$timestamp.md"
note_path="$smoke_dir/$note_name"

cat <<EOF > "$note_path"
---
title: Watcher Inbox Smoke
tags: [watcher, smoke]
---

Generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ"). This note is used to exercise the watcher inbox scan.
EOF

relative_path=$(python - <<'PY'
import pathlib, sys
inbox = pathlib.Path(sys.argv[1])
note = pathlib.Path(sys.argv[2])
print(str(inbox / note))
PY
  "$inbox_dir" "$note_name")

index_outbox="${INDEX_OUTBOX_PATH:-tmp/index-outbox.jsonl}"
touch "$index_outbox"

echo "Waiting for watcher to emit panel.scan.requested for $relative_path"
found=0
deadline=$((SECONDS + 45))
while [ $SECONDS -lt $deadline ]; do
  if python - <<'PY'
import json, pathlib, os, sys
target = os.environ["TARGET_REL"]
path = pathlib.Path(os.environ["INDEX_OUTBOX_PATH"])
if not path.exists():
    sys.exit(1)
with path.open("r", encoding="utf-8") as fh:
    for line in fh:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = obj.get("payload") or {}
        if obj.get("event") == "panel.scan.requested" and payload.get("relative_path") == target:
            sys.exit(0)
sys.exit(1)
PY
    TARGET_REL="$relative_path" INDEX_OUTBOX_PATH="$index_outbox"
  then
    found=1
    break
  fi
  sleep 1
done

if [ "$found" -ne 1 ]; then
  echo "ERROR: Did not observe panel.scan.requested for $relative_path after 45s" >&2
  exit 1
fi

tick_log_default="/app/tmp/watcher_tick.jsonl"
tick_log_env="${WATCHER_TICK_LOG_PATH:-}"
tick_log_path="${tick_log_env:-$(cat tmp/latest_watcher_tick_log 2>/dev/null || echo "$tick_log_default")}"
host_tick_log="$tick_log_path"
if [[ "$host_tick_log" == /app/* ]]; then
  host_tick_log=".${host_tick_log#/app}"
fi

if [ ! -f "$host_tick_log" ]; then
  echo "ERROR: watcher tick log missing at $host_tick_log" >&2
  exit 1
fi

echo "Watcher tick log ($host_tick_log) tail:"
tail -n 10 "$host_tick_log"

scanned_files=$(python - <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
if not lines:
    print(0)
    sys.exit(0)
payload = json.loads(lines[-1])
print(int(payload.get("scanned_files") or 0))
PY
  "$host_tick_log")

printf "Last tick scanned_files=%s bytes\n" "$scanned_files"
if [ "$scanned_files" -ge 5000 ]; then
  echo "ERROR: scanned_files ($scanned_files) is too large" >&2
  exit 1
fi

echo "Watcher inbox smoke succeeded for $note_path"
