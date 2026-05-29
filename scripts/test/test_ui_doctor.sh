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
# Usage:
#   make test-ui-doctor
#   scripts/test/test_ui_doctor.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=../lib/companion_ui_startup.sh
source "${SCRIPT_DIR}/../lib/companion_ui_startup.sh"

CUI_CHANNEL="test"
CUI_EXPECTED_VAULT_PATTERN="bifr(ö|o)st"
CUI_EXPECTED_VAULT_LABEL="Bifröst/Bifrost"
CUI_API_PORT="18002"
CUI_UI_PORT="8112"
CUI_COMPOSE_FILES="docker-compose.yaml:docker-compose.test.yml"
CUI_COMPOSE_PROJECT="pkm-test"
CUI_SERVE_MODULE="companion_ui.workspace.serve_dev_page"
CUI_DB_LABEL="app_test"
export CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
  CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE CUI_DB_LABEL

cui_run_doctor
