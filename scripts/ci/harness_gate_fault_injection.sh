#!/usr/bin/env bash
# harness_gate_fault_injection.sh — prove the harness gate is NOT vacuous.
#
# A self-verifying harness is only meaningful if a *broken* harness makes the
# gate go red. This script deliberately injects each of the 2026-06-14 misconfig
# faults and asserts the channel preflight REJECTS it. If the preflight ever
# accepts a broken channel config, the gate is vacuous and this script fails —
# which is the signal that the gate has rotted (issue #1997 F1).
#
# Exit 0 = every injected fault was correctly rejected (gate is real).
# Exit 1 = a fault slipped through (gate is vacuous) OR the harness is missing.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-python}"

fail=0

# Assert that `ops channel-preflight` exits NON-zero for a deliberately broken
# env. $1 is a human label; the remaining args are KEY=VALUE env overrides.
assert_rejected() {
  local label="$1"; shift
  local rc
  set +e
  env "$@" "${PYTHON}" -m app.cli ops channel-preflight --channel test --context host >/dev/null 2>&1
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    echo "FAULT-INJECTION FAILED: gate ACCEPTED broken config — ${label}" >&2
    fail=1
  else
    echo "ok: gate rejected — ${label} (rc=${rc})"
  fi
}

# Symptom 4 — in-container DSN reached from the host + prod DB name.
assert_rejected "in-container db:5432 / prod DB name" \
  PKM_ENVIRONMENT=test VAULT_ROOT=/srv/vault-test VAULT_ROOT_TEST=/srv/vault-test \
  INDEX_OUTBOX_PATH=/srv/tmp-test/index-outbox.jsonl \
  DATABASE_URL='postgresql+psycopg://app:app@db:5432/app'

# Symptom 2 — INDEX_OUTBOX_PATH left ambient (unset → CWD-relative).
assert_rejected "ambient INDEX_OUTBOX_PATH (unset)" \
  PKM_ENVIRONMENT=test VAULT_ROOT=/srv/vault-test VAULT_ROOT_TEST=/srv/vault-test \
  DATABASE_URL='postgresql+psycopg://app:app@127.0.0.1:15434/app_test'

# Symptom 5 — relative TEST_VAULT_ROOT (CWD-relative).
assert_rejected "relative VAULT_ROOT" \
  PKM_ENVIRONMENT=test VAULT_ROOT=vault-test VAULT_ROOT_TEST=vault-test \
  INDEX_OUTBOX_PATH=/srv/tmp-test/index-outbox.jsonl \
  DATABASE_URL='postgresql+psycopg://app:app@127.0.0.1:15434/app_test'

# Symptom 3 — heartbeat in tmp/ instead of tmp-test/.
assert_rejected "heartbeat in tmp/ not tmp-test/" \
  PKM_ENVIRONMENT=test VAULT_ROOT=/srv/vault-test VAULT_ROOT_TEST=/srv/vault-test \
  INDEX_OUTBOX_PATH=/srv/tmp-test/index-outbox.jsonl \
  WORKER_HEARTBEAT_PATH=/srv/tmp/worker_heartbeat.json \
  DATABASE_URL='postgresql+psycopg://app:app@127.0.0.1:15434/app_test'

# Wrong channel entirely — must never bootstrap the operator/prod channel.
assert_rejected "prod channel refused by the test harness" \
  PKM_ENVIRONMENT=prod

if [ "$fail" -ne 0 ]; then
  echo "" >&2
  echo "GATE IS VACUOUS: at least one broken config was accepted. The harness" >&2
  echo "self-verification has rotted (issue #1997 F1)." >&2
  exit 1
fi

echo ""
echo "PASS: the harness gate rejected every injected fault — the gate is real."
