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
  echo "--- docker compose logs worker (tail=200) ---"
  docker compose logs --tail=200 worker || true
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
try:
    from app.db.dsn import resolve_dsn

    url = resolve_dsn(url)
except Exception:
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]

with connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select id, created_at, delivered_at, topic, payload::text from outbox "
            "where payload::text ilike %s order by created_at desc limit 10",
            (pattern,),
        )
        rows = cur.fetchall()
        for row_id, created_at, delivered_at, topic, payload in rows:
            payload_snip = str(payload)[:160]
            print(row_id, created_at, delivered_at, topic, payload_snip)
PY
}

fail() {
  local reason="$1"
  echo "ERROR: $reason" >&2
  print_diagnostics
  exit 1
}

query_outbox_total() {
  docker compose exec -T api python - <<'PY'
import os
from psycopg import connect

note = os.environ.get("SMOKE_NOTE_NAME", "")
pattern = f"%{note}%"
url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not url:
    print("0")
    raise SystemExit(0)
try:
    from app.db.dsn import resolve_dsn

    url = resolve_dsn(url)
except Exception:
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]

with connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select count(*) from outbox where payload::text ilike %s",
            (pattern,),
        )
        print(cur.fetchone()[0])
PY
}

query_latest_delivered() {
  docker compose exec -T api python - <<'PY'
import os
from psycopg import connect

note = os.environ.get("SMOKE_NOTE_NAME", "")
pattern = f"%{note}%"
url = os.environ.get("DATABASE_URL") or os.environ.get("DB_DSN")
if not url:
    print("0")
    raise SystemExit(0)
try:
    from app.db.dsn import resolve_dsn

    url = resolve_dsn(url)
except Exception:
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]

with connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "select delivered_at is not null from outbox where payload::text ilike %s order by created_at desc limit 1",
            (pattern,),
        )
        row = cur.fetchone()
        print("1" if row and row[0] else "0")
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

echo "--- watcher env ---"
docker compose exec -T watcher env | egrep 'WATCHER|VAULT|DATABASE_URL|DB_DSN|STORE_BACKEND' || true
echo "--- worker env ---"
docker compose exec -T worker env | egrep 'WATCHER|VAULT|DATABASE_URL|DB_DSN|STORE_BACKEND' || true
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

cat <<EOFNOTE > "$note_path"
---
title: Watcher Capture Smoke
tags: [watcher, smoke]
---

%% AI:Start %%
- action: summarize
%% AI:End %%

Generated at $(date -u +"%Y-%m-%dT%H:%M:%SZ"). This note exercises watcher scan, uuid healing, and DB outbox enqueue.
EOFNOTE

marker_line="SMOKE_MARKER: $(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "$marker_line" >> "$note_path"

relative_path="$inbox_dir/@Smoke/$note_name"
export SMOKE_NOTE_NAME="$note_name"

echo "Smoke note: $note_path"
echo "Relative path: $relative_path"

before_total=$(query_outbox_total)

echo "Running watcher ticks (max=30)"
if ! docker compose exec -T watcher python -m app.cli watcher run --max-ticks 30; then
  fail "watcher run failed"
fi

after_total="$before_total"
for _ in 1 2 3 4 5 6 7 8; do
  after_total=$(query_outbox_total)
  if [ "$after_total" -gt "$before_total" ]; then
    break
  fi
  sleep 1
done

if ! assert_uuid_written "$note_path"; then
  fail "uuid not written to smoke note"
fi

if [ "$after_total" -le "$before_total" ]; then
  fail "DB outbox did not enqueue a new event for $note_name (before_total=$before_total after_total=$after_total)"
fi

delivered="0"
for _ in 1 2 3 4 5; do
  delivered=$(query_latest_delivered)
  if [ "$delivered" = "1" ]; then
    break
  fi
  sleep 1
done

if [ "$delivered" != "1" ]; then
  fail "outbox row for $note_name was not marked delivered within 5s"
fi

echo "Watcher inbox smoke succeeded for $note_path"
