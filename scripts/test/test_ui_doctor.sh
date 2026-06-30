#!/usr/bin/env bash
# Read-only test/Bifröst Companion UI doctor (Issue #1359).
#
# Diagnoses common test-channel startup failure modes without starting services
# or mutating runtime/vault state: Docker/Colima availability, test vault
# resolution (Bifröst), runtime API health on 18002, container vault mount, UI
# port 8112 occupancy, UI reachability, optional target note, and Tailscale IP.
# Reports channel identity (PKM_ENVIRONMENT=test, pkm-test, app_test) so test is
# clearly distinguished from dev/prod.
#
# Channel-isolation preflight (Issue #1627): before any other check, validates
# that docker-compose.test.yml's effective env bindings (PKM_ENVIRONMENT,
# DATABASE_URL, DB_DSN) all resolve to the test channel. Fail-closes with a
# clear error if the overlay has drifted to prod bindings.
#
# Usage:
#   make test-ui-doctor
#   scripts/test/test_ui_doctor.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# ── channel-isolation preflight (Issue #1627) ────────────────────────────────
# Runs before any network or Docker check so a drifted compose is caught first.
_run_channel_isolation_preflight() {
  local python_bin overlay_path
  overlay_path="${REPO_ROOT}/docker-compose.test.yml"
  if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
    python_bin="${REPO_ROOT}/.venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    python_bin="$(command -v python3)"
  else
    echo "  [warn] channel-isolation preflight: no Python found, skipping"
    return 0
  fi

  local output exit_code
  output="$( \
    cd "${REPO_ROOT}" && \
    "${python_bin}" -m app.release_channels.channel_isolation_preflight \
      "${overlay_path}" test 2>&1 \
  )" && exit_code=0 || exit_code=$?

  if [ "${exit_code}" -eq 0 ]; then
    echo "  [ok]   channel-isolation preflight: test bindings verified"
  else
    echo "  [FAIL] channel-isolation preflight: compose/env binding mismatch"
    echo ""
    printf '%s\n' "${output}" | sed 's/^/         /'
    echo ""
    echo "  Action: correct docker-compose.test.yml before starting the test stack."
    echo "  This preflight is read-only — it will not modify operator files."
    return 1
  fi
}

# shellcheck source=../lib/companion_ui_startup.sh
source "${SCRIPT_DIR}/../lib/companion_ui_startup.sh"

CUI_CHANNEL="test"
CUI_EXPECTED_VAULT_PATTERN="bifr(ö|o)st"
CUI_EXPECTED_VAULT_LABEL="Bifröst/Bifrost"
CUI_API_PORT="18002"
CUI_UI_PORT="8112"
CUI_COMPOSE_FILES="docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.test.yml"
CUI_COMPOSE_PROJECT="pkm-test"
CUI_SERVE_MODULE="companion_ui.workspace.serve_dev_page"
CUI_DB_LABEL="app_test"
export CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
  CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE CUI_DB_LABEL

# Run channel-isolation preflight first; abort if it fails.
_run_channel_isolation_preflight || exit 1

cui_run_doctor
