#!/usr/bin/env bash
set -euo pipefail

VAULT_PATH=${VAULT:-${1:-}}
OUTBOX_PATH=${OUTBOX:-tmp/index-outbox.live.jsonl}
STOP_FILE=${WATCHER_STOP_FILE:-tmp/WATCHER_STOP}

if [[ -z "$VAULT_PATH" ]]; then
  echo "Usage: VAULT=/path/to/vault scripts/run_live_watcher.sh" >&2
  echo "VAULT env (or first arg) is required to run the live watcher." >&2
  exit 1
fi

python -m app.cli settings validate

export POLICY_ENFORCE=1
export WATCHER_ENABLE=1
export WATCHER_VAULT_PATH="$VAULT_PATH"
export WATCHER_SCOPE_GLOB=${WATCHER_SCOPE_GLOB:-"@Inbox/**"}
export WATCHER_DEBOUNCE_MS=${WATCHER_DEBOUNCE_MS:-1500}
export WATCHER_RATE_LIMIT_PER_MIN=${WATCHER_RATE_LIMIT_PER_MIN:-30}
export WATCHER_BACKOFF_SECONDS=${WATCHER_BACKOFF_SECONDS:-10}
export WATCHER_STOP_FILE="$STOP_FILE"
export INDEX_OUTBOX_PATH="$OUTBOX_PATH"

cat <<INFO
watcher: starting with
  vault: $WATCHER_VAULT_PATH
  scope: $WATCHER_SCOPE_GLOB
  stop file: $STOP_FILE (touch to pause)
  outbox: $OUTBOX_PATH (tail -f to observe events)
INFO

python -m app.cli watcher run
