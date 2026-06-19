#!/usr/bin/env bash
# bootstrap_test_channel.sh — the ONE idempotent test-channel bring-up (#1997 F3).
#
# Single source of truth for a correct test channel. It is where the six
# 2026-06-14 symptoms die: vault init is run, INDEX_OUTBOX_PATH is shared and
# absolute, heartbeat paths are tmp-test/, the DSN is host-reachable
# (127.0.0.1:15434), TEST_VAULT_ROOT is absolute, and exactly one watcher runs
# (the container watcher; this script never launches a host watcher).
#
# A clean `promote-to-test` needs ZERO manual env exports because this script
# derives and verifies the whole channel env itself.
#
# Usage:
#   bash scripts/bootstrap_test_channel.sh                # config + Docker stack
#   bash scripts/bootstrap_test_channel.sh --config-only  # config layer only (CI)
#
# Idempotent: safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)}"

CONFIG_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --config-only) CONFIG_ONLY=1 ;;
    *) echo "ERROR: unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Vault root for this self-verifying harness. The product layer
# (derive_test_channel_env) is intentionally fail-loud with no synthetic default,
# so the harness supplies an explicit vault: the configured operator vault when
# present, otherwise a repo-local ephemeral scratch vault (gitignored). This keeps
# the zero-manual-env-exports property for CI without hardcoding a vault name in
# product code. The scratch vault is a throwaway CI/local fixture, never a real vault.
BOOTSTRAP_VAULT_ROOT="${VAULT_ROOT_TEST:-${TEST_VAULT_ROOT:-${VAULT_ROOT:-${ROOT}/vault-test}}}"

# ── [1/4] vault init + canonical env + fail-loud preflight ────────────────────
# `ops bootstrap-test-channel --print-env` runs `vault init`, derives the
# canonical (absolute, channel-correct, host-reachable) env, runs the F2
# preflight, and exits non-zero if the channel is inconsistent. We capture its
# KEY=VALUE output and export it — no manual env exports required anywhere.
echo "==> [1/4] vault init + canonical channel env + fail-loud preflight"
bootstrap_env=$("${PYTHON}" -m app.cli ops bootstrap-test-channel --vault-root "${BOOTSTRAP_VAULT_ROOT}" --print-env)
while IFS= read -r line; do
  [ -n "$line" ] || continue
  export "$line"
done <<EOF
${bootstrap_env}
EOF

# ── [2/4] seed UAT notes (idempotent) ─────────────────────────────────────────
echo "==> [2/4] seed UAT notes into the test vault (idempotent)"
PYTHON="${PYTHON}" bash scripts/init_test_vault.sh

# ── [3/4] re-affirm the channel preflight against the exported env ────────────
echo "==> [3/4] re-affirm channel-env preflight (host context)"
"${PYTHON}" -m app.cli ops channel-preflight --channel test --context host

if [ "$CONFIG_ONLY" -eq 1 ]; then
  echo "==> config-only: skipping Docker stack bring-up"
  echo "SUCCESS: test channel config is correct (zero manual env exports needed)"
  exit 0
fi

# ── [4/4] bring up the single-watcher test stack ──────────────────────────────
# Single watcher: the container watcher (WATCHER_AUTO_EXEC=1 in the derived env).
# This script never launches a host-side watcher, so there is no two-watcher
# race on tmp-test/ state (issue #1997 symptom 6). `make test-start-full` sets
# PKM_ENVIRONMENT=test, COMPOSE_FILE/PROJECT, and calls start_full_system.sh.
echo "==> [4/4] bring up the single-watcher test stack"
make test-down >/dev/null 2>&1 || true
make test-start-full VAULT_ROOT="${VAULT_ROOT}"

echo "SUCCESS: test channel is up and channel-correct (single bootstrap, zero manual env exports)"
