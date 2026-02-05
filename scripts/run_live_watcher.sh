#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT="${VAULT:-${1:-${VAULT_ROOT:-}}}"

if [[ -z "$VAULT" ]]; then
  echo "VAULT_ROOT (or VAULT/arg) is required" >&2
  exit 2
fi

export POLICY_ENFORCE="${POLICY_ENFORCE:-1}"
export WATCHER_ENABLE="${WATCHER_ENABLE:-1}"
export WATCHER_VAULT_PATH="${WATCHER_VAULT_PATH:-$VAULT}"

export WATCHER_DEBOUNCE_MS="${WATCHER_DEBOUNCE_MS:-1500}"
export WATCHER_RATE_LIMIT_PER_MIN="${WATCHER_RATE_LIMIT_PER_MIN:-30}"
export WATCHER_BACKOFF_SECONDS="${WATCHER_BACKOFF_SECONDS:-10}"
export WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-$ROOT/tmp/watcher_heartbeat.json}"
export INDEX_OUTBOX_PATH="${INDEX_OUTBOX_PATH:-$ROOT/tmp/index-outbox.jsonl}"

mkdir -p "$ROOT/tmp"

echo "Vault: $WATCHER_VAULT_PATH"
echo "Scope: ${WATCHER_SCOPE_GLOB:-<default: *.md,**/*.md>}"
echo "Outbox: $INDEX_OUTBOX_PATH"
echo "Stop:   touch $ROOT/tmp/WATCHER_STOP"
echo

python -m app.cli settings validate
python -m app.cli watcher run
