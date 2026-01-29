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

print_diagnostics() {
  echo "--- docker compose ps ---"
  docker compose ps || true
  echo "--- docker compose logs watcher (tail=200) ---"
  docker compose logs --tail=200 watcher || true
  echo "--- docker compose logs api (tail=200) ---"
  docker compose logs --tail=200 api || true
  echo "--- outbox rows matching note ---"
  docker compose exec -T api python - <<'PY'
import os
from psycopg import connect

note = os.environ.get("SMOKE_NOTE_NAME", "")
pattern = f"%{note}%"
url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not url:
    print("DATABASE_URL/DB_DSN missing in container")
    raise SystemExit(1)

with connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select created_at, delivered_at, topic, payload::text from outbox "
            "where payload::text ilike %s order by created_at desc limit 10",
            (pattern,),
        )
        rows = cur.fetchall()
        for created_at, delivered_at, topic, payload in rows:
            payload_snip = str(payload)[:120]
            print(created_at, delivered_at, topic, payload_snip)
PY
}

fail() {
  local reason="$1"
  echo "ERROR: $reason" >&2
  print_diagnostics
  exit 1
}

query_outbox_count() {
  docker compose exec -T api python - <<'PY'
import os
from psycopg import connect

note = os.environ.get("SMOKE_NOTE_NAME", "")
pattern = f"%{note}%"
url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not url:
    print("0")
    raise SystemExit(0)

with connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from outbox where delivered_at is null and payload::text ilike %s",
            (pattern,),
        )
        count = cur.fetchone()[0]
        print(count)
PY
}

assert_uuid_written() {
  python - <<'PY'
import sys
from pathlib import Path
from scripts.yaml_roundtrip import load_frontmatter

path = Path(sys.argv[1])
raw = path.read_text(encoding="utf-8")
frontmatter, _ = load_frontmatter(raw)
value = ""
if isinstance(frontmatter, dict):
    value = str(frontmatter.get("uuid") or "").strip()
if not value:
    raise SystemExit(2)
PY
  "$1"
}

echo "Ensuring vault layout for: $VAULT_ROOT"
layout_json=$(python -m app.cli vault-layout-ensure --vault-root "$VAULT_ROOT" --json)

inbox_dir=$(python - <<'PY'
import json
import sys

try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
print(payload.get("inbox_folder") or "")
PY
<<<"$layout_json")

if [ -z "$inbox_dir" ]; then
  fail "inbox_folder missing from layout output"
fi

inbox_base="$VAULT_ROOT/$inbox_dir"
if [ ! -d "$inbox_base" ]; then
  fail "inbox directory missing: $inbox_base"
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

%% AI:Start %%
- action: summarize
%% AI:End %%

Generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ"). This note exercises watcher inbox scan, uuid healing, and DB outbox enqueue.
EOF

relative_path="$inbox_dir/@Smoke/$note_name"
export SMOKE_NOTE_NAME="$note_name"

echo "Smoke note: $note_path"
echo "Relative path: $relative_path"

before_count=$(query_outbox_count)

if ! docker compose exec -T watcher env WATCHER_AUTO_EXEC=1 python -m app.cli watcher run --max-ticks 30; then
  fail "watcher run failed"
fi

after_count="$before_count"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  after_count=$(query_outbox_count)
  if [ "$after_count" -gt "$before_count" ]; then
    break
  fi
  sleep 1
done

if ! assert_uuid_written "$note_path"; then
  fail "uuid not written to smoke note"
fi

if [ "$after_count" -le "$before_count" ]; then
  fail "DB outbox did not enqueue new event for $note_name (before=$before_count after=$after_count)"
fi

echo "Watcher inbox smoke succeeded for $note_path"
