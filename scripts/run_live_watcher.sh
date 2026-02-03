#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VAULT="${VAULT:-${1:-${VAULT_ROOT:-}}}"

if [[ -z "$VAULT" ]]; then
  echo "VAULT_ROOT (or VAULT/arg) is required" >&2
  exit 2
fi

resolve_inbox_dir() {
  python -m app.cli vault-layout-ensure --vault-root "$VAULT" --json \
    | python - <<'PY'
import json, sys
try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}
print((payload.get("inbox_folder") or "").strip())
PY
}

export POLICY_ENFORCE="${POLICY_ENFORCE:-1}"
export WATCHER_ENABLE="${WATCHER_ENABLE:-1}"
export WATCHER_VAULT_PATH="${WATCHER_VAULT_PATH:-$VAULT}"

if [[ -z "${VAULT_INBOX_DIR_REL:-}" ]]; then
  VAULT_INBOX_DIR_REL="$(resolve_inbox_dir)"
  if [[ -z "$VAULT_INBOX_DIR_REL" ]]; then
    echo "ERROR: could not resolve inbox folder; set VAULT_INBOX_DIR_REL or ensure vault.layout.md exists" >&2
    exit 1
  fi
  export VAULT_INBOX_DIR_REL
fi

if [[ -z "${WATCHER_SCOPE_GLOB:-}" ]]; then
  export WATCHER_SCOPE_GLOB="${VAULT_INBOX_DIR_REL}/**"
fi

export WATCHER_DEBOUNCE_MS="${WATCHER_DEBOUNCE_MS:-1500}"
export WATCHER_RATE_LIMIT_PER_MIN="${WATCHER_RATE_LIMIT_PER_MIN:-30}"
export WATCHER_BACKOFF_SECONDS="${WATCHER_BACKOFF_SECONDS:-10}"
export WATCHER_HEARTBEAT_PATH="${WATCHER_HEARTBEAT_PATH:-$ROOT/tmp/watcher_heartbeat.json}"
export INDEX_OUTBOX_PATH="${INDEX_OUTBOX_PATH:-$ROOT/tmp/index-outbox.jsonl}"

mkdir -p "$ROOT/tmp"

echo "Vault: $WATCHER_VAULT_PATH"
echo "Scope: $WATCHER_SCOPE_GLOB"
echo "Outbox: $INDEX_OUTBOX_PATH"
echo "Stop:   touch $ROOT/tmp/WATCHER_STOP"
echo

python -m app.cli settings validate
python -m app.cli watcher run
