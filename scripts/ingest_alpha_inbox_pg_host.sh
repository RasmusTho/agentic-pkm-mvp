#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VAULT_PATH="${VAULT_ROOT:-}"
DB_URL="postgresql://app:app@127.0.0.1:15432/app"
export STORE_BACKEND=pg
export DATABASE_URL="$DB_URL"
export DB_DSN="$DB_URL"
export INDEX_OUTBOX_PATH="${INDEX_OUTBOX_PATH:-$ROOT/tmp/index-outbox.jsonl}"
export WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-$ROOT/tmp/watcher_heartbeat.json}"

if [[ -z "$VAULT_PATH" ]]; then
  echo "VAULT_ROOT is required for host ingest" >&2
  exit 2
fi

if [[ ! -d "$VAULT_PATH" ]]; then
  echo "Vault path not found: $VAULT_PATH" >&2
  exit 3
fi

echo "Host ingest -> PG store using vault: $VAULT_PATH"
python -m app.cli vault-alpha-ingest --vault-root "$VAULT_PATH" --max-notes 200 --include-test-note --force

echo "Host index rebuild -> PG store"
python -m app.cli index rebuild --backend pg --strict

echo "Host PG ingest complete. Verify via scripts/run_alpha_stack.sh and the API status endpoints."
