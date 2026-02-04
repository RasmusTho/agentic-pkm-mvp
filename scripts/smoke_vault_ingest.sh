#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "ERROR: VAULT_ROOT is required" >&2
  exit 1
fi

vault_root="${VAULT_ROOT}"
if [ ! -d "$vault_root" ]; then
  echo "ERROR: Vault root not found: $vault_root" >&2
  exit 1
fi

resolve_inbox_dir() {
  if [ -n "${VAULT_INBOX_DIR_REL:-}" ]; then
    printf '%s\n' "${VAULT_INBOX_DIR_REL}"
    return
  fi

  python -m app.cli vault-layout-ensure --vault-root "$vault_root" --json \
    | python - <<'PY'
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
print((payload.get("inbox_folder") or "").strip())
PY
}

inbox_rel="$(resolve_inbox_dir)"
if [ -z "$inbox_rel" ]; then
  echo "ERROR: could not resolve inbox folder; set VAULT_INBOX_DIR_REL or ensure vault.layout.md exists" >&2
  exit 1
fi

inbox_path="$vault_root/$inbox_rel"
if [ ! -d "$inbox_path" ]; then
  echo "ERROR: inbox folder not found: $inbox_path" >&2
  exit 1
fi

smoke_dir="$inbox_path/@Smoke"
mkdir -p "$smoke_dir"

note_uuid=$(python - <<'PY'
from __future__ import annotations
import uuid
print(uuid.uuid4())
PY
)

note_name="smoke-$(date +%s)-${note_uuid}.md"
note_path="$smoke_dir/$note_name"
container_note_path="/app/vault/$inbox_rel/@Smoke/$note_name"

cat > "$note_path" <<NOTE
---
uuid: $note_uuid
---
# smoke
This note verifies the vault ingest pipeline.
NOTE

pipe_output=""
set +e
pipe_output=$(docker compose exec -T api python -m app.cli pipe "$container_note_path" --json 2>&1)
pipe_status=$?
set -e
if [ "$pipe_status" -ne 0 ]; then
  echo "ERROR: pipe failed" >&2
  echo "$pipe_output" >&2
  docker compose logs --tail=100 api || true
  exit 1
fi

object_id=$(PIPE_JSON="$pipe_output" python - <<'PY'
from __future__ import annotations
import json, os, sys
raw = os.environ.get("PIPE_JSON", "")
try:
    data = json.loads(raw)
except Exception as exc:
    print(f"ERROR: failed to parse pipe JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)
print(data["normalize"]["object_id"])
PY
)

query_row() {
  docker compose exec -T db sh -lc "psql -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\" -At -c \"$1\""
}

outbox_query="select id from outbox where topic = 'ingest.object.created' and payload->>'object_id' = '$object_id' order by created_at desc limit 1;"
outbox_id=$(query_row "$outbox_query")
if [ -z "$outbox_id" ]; then
  echo "ERROR: DB outbox row not found for object_id=$object_id" >&2
  docker compose logs --tail=200 db || true
  exit 1
fi

delivered_query="select coalesce(delivered_at::text, '') from outbox where id = '$outbox_id';"
delivered_at=""
start=$SECONDS
while [ $((SECONDS - start)) -lt 30 ]; do
  delivered_at=$(query_row "$delivered_query")
  if [ -n "$delivered_at" ]; then
    break
  fi
  sleep 1
done

if [ -z "$delivered_at" ]; then
  echo "ERROR: worker did not process outbox event for object_id=$object_id" >&2
  docker compose logs --tail=200 worker || true
  docker compose logs --tail=200 db || true
  exit 1
fi

printf "Vault smoke note: %s\nObject id: %s\nOutbox id: %s\nDelivered: %s\n" "$note_path" "$object_id" "$outbox_id" "$delivered_at"
