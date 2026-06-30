#!/usr/bin/env bash
# Canonical prod/Midgård Companion UI startup with production guardrails
# (Issue #1360).
#
# Starts/verifies the prod runtime API + Companion UI production page against
# the Midgård vault, using the same shared pattern as dev (#1358) and test
# (#1359) but with stricter production safety:
#
#   - refuses to start unless the resolved vault is Midgård/Midgard;
#   - DEFAULTS to a safe verification posture — watchers/workers are NOT
#     auto-started (WATCHER_AUTO_EXEC=0);
#   - write-capable / automation-capable startup requires EXPLICIT operator
#     acknowledgement via PROD_UI_ENABLE_AUTOMATION=1;
#   - clearly reports prod channel identity and the active posture.
#
# This command does not change promotion/rollback semantics or the stable
# release pointer. See docs/RELEASE_CHANNELS/README.md for promotion/rollback.
#
# Usage:
#   make prod-ui                              # safe verification posture
#   PROD_UI_ENABLE_AUTOMATION=1 make prod-ui   # explicit write/automation-capable
#   scripts/prod/start_midgard_ui.sh
#
# Optional environment:
#   CUI_BIND_LAN=1                 bind the UI to 0.0.0.0 for LAN/Tailscale UAT
#   CUI_TARGET_NOTE=<rel-path>     verify a note path via /api/companion/workspace
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
# shellcheck source=../lib/companion_ui_startup.sh
source "${SCRIPT_DIR}/../lib/companion_ui_startup.sh"

CUI_CHANNEL="prod"
CUI_EXPECTED_VAULT_PATTERN="midg(å|a)rd"
CUI_EXPECTED_VAULT_LABEL="Midgård/Midgard"
CUI_API_PORT="18000"
CUI_UI_PORT="8113"
CUI_COMPOSE_FILES="docker-compose.yaml:docker-compose.app-bind.yml:docker-compose.prod.yml"
CUI_COMPOSE_PROJECT="pkm-prod"
CUI_SERVE_MODULE="companion_ui.workspace.serve_production_page"
CUI_DB_LABEL="app"

# Production guardrail: safest posture by default. Automation/write-capable
# services (watcher auto-exec) are started ONLY on explicit acknowledgement.
if [ "${PROD_UI_ENABLE_AUTOMATION:-0}" = "1" ]; then
  CUI_WATCHER_AUTO_EXEC="1"
  echo "[companion-ui:prod] *** WRITE/AUTOMATION-CAPABLE MODE ENABLED ***"
  echo "[companion-ui:prod] operator acknowledged via PROD_UI_ENABLE_AUTOMATION=1; watcher auto-exec ON."
else
  CUI_WATCHER_AUTO_EXEC="0"
  echo "[companion-ui:prod] SAFE VERIFICATION POSTURE: watchers/workers NOT auto-started (watcher auto-exec OFF)."
  echo "[companion-ui:prod] to enable write/automation-capable services, re-run with PROD_UI_ENABLE_AUTOMATION=1."
fi

export CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
  CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE \
  CUI_DB_LABEL CUI_WATCHER_AUTO_EXEC

cui_run_start
