#!/usr/bin/env bash
# init_test_vault.sh — Initialize vault-test/ with required structure and UAT notes.
# Idempotent: running twice produces identical vault structure.
# Usage: bash scripts/init_test_vault.sh
#        make test-vault-init
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Seed the operator-configured test vault, honoring the same precedence as the
# bootstrap harness and derive_test_channel_env (per-channel override first), and
# falling back to the repo-local ephemeral scratch vault only when nothing is
# configured. This must match the root the bootstrap exports and that
# `uat-run-vault-test --vault-root` later reads, or the seed folder goes missing.
VAULT_TEST="${VAULT_ROOT_TEST:-${TEST_VAULT_ROOT:-${VAULT_ROOT:-vault-test}}}"
SYSTEM_CONFIG="${VAULT_TEST}/System/Config"
TEST_DIR="${VAULT_TEST}/Test"
PYTHON="${PYTHON:-$(if [ -x .venv/bin/python ]; then printf '%s' .venv/bin/python; elif command -v python3.12 >/dev/null 2>&1; then command -v python3.12; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)}"

# ── Directory structure ───────────────────────────────────────────────────────

echo "==> Creating ${VAULT_TEST}/ directory structure"
mkdir -p "${SYSTEM_CONFIG}"
mkdir -p "${TEST_DIR}"

# ── System/Config files ───────────────────────────────────────────────────────

WIRING_SRC="docs/settings/panel-action-wiring.yaml"
WIRING_DST="${SYSTEM_CONFIG}/panel-action-wiring.yaml"

if [ ! -f "${WIRING_SRC}" ]; then
  echo "ERROR: required source file not found: ${WIRING_SRC}" >&2
  exit 1
fi

echo "==> Copying panel-action-wiring.yaml to ${SYSTEM_CONFIG}/"
cp "${WIRING_SRC}" "${WIRING_DST}"

# ── Vault-settings init (issue #1991 invariant) ───────────────────────────────
# Vault init became a hard runtime precondition (#1991): a vault missing the
# vault-settings files validates as `uninitialized` and the watcher fail-exits.
# init_test_vault.sh is a producer of the test vault, so it must run vault init
# (issue #1997 symptom 1 / F4 invariant→producers rule). Idempotent: existing
# settings files are kept. --no-remember so the operator's last-active vault
# pointer is never rewritten.

echo "==> Initializing vault settings (idempotent, #1991 invariant)"
"${PYTHON}" -m app.cli vault init --path "${VAULT_TEST}" --machine-role primary --no-remember

# ── UAT notes ─────────────────────────────────────────────────────────────────

echo "==> Seeding UAT notes into ${TEST_DIR}/"
VAULT_ROOT="${VAULT_TEST}" "${PYTHON}" -m app.cli uat-seed-vault-test \
  --vault-root "${VAULT_TEST}" \
  --overwrite

# ── Verify structure ──────────────────────────────────────────────────────────

echo "==> Verifying ${VAULT_TEST}/ structure"

errors=0

required_dirs=(
  "${VAULT_TEST}/System/Config"
  "${VAULT_TEST}/Test"
)

required_files=(
  "${SYSTEM_CONFIG}/panel-action-wiring.yaml"
)

for d in "${required_dirs[@]}"; do
  if [ ! -d "$d" ]; then
    echo "ERROR: expected directory missing: $d" >&2
    errors=$((errors + 1))
  fi
done

for f in "${required_files[@]}"; do
  if [ ! -f "$f" ]; then
    echo "ERROR: expected file missing: $f" >&2
    errors=$((errors + 1))
  fi
done

# At least one UAT note should have been seeded
uat_count=$(find "${TEST_DIR}" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
if [ "${uat_count}" -eq 0 ]; then
  echo "ERROR: no UAT notes found under ${TEST_DIR}/" >&2
  errors=$((errors + 1))
fi

if [ "${errors}" -gt 0 ]; then
  echo "FAIL: ${VAULT_TEST}/ structure incomplete (${errors} error(s))" >&2
  exit 1
fi

cat <<SUMMARY
SUCCESS: ${VAULT_TEST}/ initialized
  System/Config/panel-action-wiring.yaml  ✓
  Test/                                    ✓ (${uat_count} UAT note(s))
  Idempotent: run again to verify no drift
SUMMARY
