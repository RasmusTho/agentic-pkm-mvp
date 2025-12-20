#!/usr/bin/env bash
set -euo pipefail

VAULT_PATH=${1:-tmp/vault_smoke}
OUTBOX_PATH=${2:-tmp/index-outbox.smoke.jsonl}

python -m app.cli settings validate
POLICY_ENFORCE=1 STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 INDEX_OUTBOX_PATH="$OUTBOX_PATH" \
  python -m app.cli smoke reality --vault "$VAULT_PATH" --outbox "$OUTBOX_PATH"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory POLICY_ENFORCE=1 \
  python scripts/verify_reality_smoke.py --vault "$VAULT_PATH" --outbox "$OUTBOX_PATH"
