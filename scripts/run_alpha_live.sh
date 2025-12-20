#!/usr/bin/env bash
set -euo pipefail

VAULT_DEFAULT="/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/PKM - Alpha"
VAULT="${VAULT:-${1:-$VAULT_DEFAULT}}"

export POLICY_ENFORCE="${POLICY_ENFORCE:-1}"
export WATCHER_ENABLE="${WATCHER_ENABLE:-1}"
export WATCHER_VAULT_PATH="${WATCHER_VAULT_PATH:-$VAULT}"

export WATCHER_SCOPE_GLOB="${WATCHER_SCOPE_GLOB:-@Inbox/**}"
export WATCHER_DEBOUNCE_MS="${WATCHER_DEBOUNCE_MS:-1500}"
export WATCHER_RATE_LIMIT_PER_MIN="${WATCHER_RATE_LIMIT_PER_MIN:-30}"
export WATCHER_BACKOFF_SECONDS="${WATCHER_BACKOFF_SECONDS:-10}"

export STORE_BACKEND="${STORE_BACKEND:-memory}"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD="${PYTEST_DISABLE_PLUGIN_AUTOLOAD:-1}"

mkdir -p tmp

echo "Vault: $WATCHER_VAULT_PATH"
echo "Scope: $WATCHER_SCOPE_GLOB"
echo "Policy: POLICY_ENFORCE=$POLICY_ENFORCE"
echo "Stop:   touch tmp/WATCHER_STOP   (resume: rm tmp/WATCHER_STOP)"
echo

python -m app.cli settings validate
python -m app.cli watcher run
