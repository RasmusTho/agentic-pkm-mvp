#!/usr/bin/env bash
# Read-only dev/Niflheim Companion UI doctor (Issue #1358).
#
# Diagnoses common dev startup failure modes without starting services or
# mutating runtime/vault state: Docker/Colima availability, dev vault
# resolution (Niflheim), runtime API health, container vault mount, UI port
# occupancy, UI reachability, optional target note, and Tailscale IP.
#
# Usage:
#   make dev-ui-doctor
#   scripts/dev/dev_ui_doctor.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=../lib/companion_ui_startup.sh
source "${SCRIPT_DIR}/../lib/companion_ui_startup.sh"

CUI_CHANNEL="dev"
CUI_EXPECTED_VAULT_PATTERN="nife?lheim"
CUI_EXPECTED_VAULT_LABEL="Niflheim/Nifelheim"
CUI_API_PORT="18001"
CUI_UI_PORT="8111"
CUI_COMPOSE_FILES="docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.dev.yml"
CUI_COMPOSE_PROJECT="pkm-dev"
CUI_SERVE_MODULE="companion_ui.workspace.serve_dev_page"
export CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
  CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE

cui_run_doctor
