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

# The marker the preflight emits ONLY for a real channel-env violation. A bare
# non-zero exit (e.g. rc=127 command-not-found, or a Python import traceback)
# does NOT carry this marker, so asserting on it — not on bare non-zero — keeps a
# *crash* from masquerading as a *rejection* and hiding a vacuous gate
# (issue #1997 F1; PR #2001 review residuals).
PREFLIGHT_REJECT_MARKER="channel-env preflight"

# Run `ops channel-preflight` under a HERMETIC env so the caller's environment
# can never leak in and mask the injected fault (notably the "unset" cases). We
# clear the env with `env -i` and re-add only the minimum the interpreter needs
# (HOME/PATH for Python, PYTHONPATH so `-m app.cli` imports from the repo), then
# apply the per-case KEY=VALUE overrides. Captures stdout+stderr and exit code.
_run_preflight() {
  env -i \
    HOME="${HOME:-/root}" \
    PATH="${PATH}" \
    PYTHONPATH="${PYTHONPATH:-$ROOT}" \
    "$@" \
    "${PYTHON}" -m app.cli ops channel-preflight --channel test --context host 2>&1
}

# Baseline: a KNOWN-GOOD test env MUST be ACCEPTED (rc=0, PASS report). This
# proves the preflight actually runs to completion under the hermetic env — so a
# rejected case is a real rejection, not a crash/missing-command that just
# happens to be non-zero (PR #2001 review residual: distinguish crashes from
# rejections).
assert_baseline_accepted() {
  local out rc
  set +e
  out="$(_run_preflight \
    PKM_ENVIRONMENT=test VAULT_ROOT=/srv/vault-test VAULT_ROOT_TEST=/srv/vault-test \
    INDEX_OUTBOX_PATH=/srv/tmp-test/index-outbox.jsonl \
    DATABASE_URL='postgresql+psycopg://app:app@127.0.0.1:15434/app_test')"
  rc=$?
  set -e
  if [ "$rc" -ne 0 ] || ! printf '%s' "$out" | grep -q "PASS  ${PREFLIGHT_REJECT_MARKER}"; then
    echo "BASELINE FAILED: a known-good test env was NOT accepted (rc=${rc}). The" >&2
    echo "preflight is crashing rather than running — every 'rejection' below would" >&2
    echo "be meaningless. Output:" >&2
    printf '%s\n' "$out" >&2
    fail=1
  else
    echo "ok: baseline known-good test env accepted (gate runs, rc=0)"
  fi
}

# Assert that `ops channel-preflight` REJECTS a deliberately broken env *for the
# right reason*: it must exit exactly 1 (click ClickException) AND emit the
# channel-preflight FAIL report. A bare non-zero (127/traceback) is NOT accepted
# as a rejection. $1 is a human label; the rest are KEY=VALUE env overrides.
assert_rejected() {
  local label="$1"; shift
  local out rc
  set +e
  out="$(_run_preflight "$@")"
  rc=$?
  set -e
  if [ "$rc" -eq 0 ]; then
    echo "FAULT-INJECTION FAILED: gate ACCEPTED broken config — ${label}" >&2
    fail=1
  elif [ "$rc" -ne 1 ] || ! printf '%s' "$out" | grep -q "FAIL  ${PREFLIGHT_REJECT_MARKER}"; then
    echo "FAULT-INJECTION FAILED: gate did not REJECT — it CRASHED (rc=${rc}, no" >&2
    echo "channel-preflight violation report) — ${label}. A crash is not a" >&2
    echo "rejection; the gate may be vacuous. Output:" >&2
    printf '%s\n' "$out" >&2
    fail=1
  else
    echo "ok: gate rejected — ${label} (rc=${rc})"
  fi
}

# Baseline first: prove the gate ACCEPTS a correct config (so the rejections
# below are real rejections, not crashes that merely exit non-zero).
assert_baseline_accepted

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
