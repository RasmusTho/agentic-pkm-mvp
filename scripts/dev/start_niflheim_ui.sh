#!/usr/bin/env bash
# Canonical dev/Niflheim Companion UI startup (Issue #1358).
#
# Starts the dev runtime API + Companion UI dev page against the Niflheim vault
# in one operator command. Refuses to start against the wrong vault, verifies
# runtime health and the container vault mount, handles a stale UI listener on
# port 8111 safely, and prints the final UAT URLs and log paths.
#
# Usage:
#   make dev-ui
#   scripts/dev/start_niflheim_ui.sh
#
# Optional environment:
#   CUI_BIND_LAN=1                 bind the UI to 0.0.0.0 for LAN/Tailscale UAT
#   CUI_TARGET_NOTE=<rel-path>     verify a note path via /api/companion/workspace
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

cui_run_start
