#!/usr/bin/env bash
# Canonical test/Bifröst Companion UI startup (Issue #1359).
#
# Starts the test runtime API + Companion UI against the Bifröst vault in one
# operator command, using the same shared pattern as dev/Niflheim (#1358) while
# preserving test-channel separation (PKM_ENVIRONMENT=test, app_test DB,
# pkm-test compose project, API 18002, UI 8112).
#
# Usage:
#   make test-ui
#   scripts/test/start_bifrost_ui.sh
#
# Optional environment:
#   CUI_BIND_LAN=1                 bind the UI to 0.0.0.0 for LAN/Tailscale UAT
#   CUI_TARGET_NOTE=<rel-path>     verify a note path via /api/companion/workspace
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
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

cui_run_start
