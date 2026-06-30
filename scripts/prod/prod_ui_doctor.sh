#!/usr/bin/env bash
# Read-only prod/Midgård Companion UI doctor with production guardrails
# (Issue #1360).
#
# Diagnoses prod-channel startup failure modes without starting services or
# mutating runtime/vault state: Docker/Colima availability, prod vault
# resolution (Midgård), runtime API health on 18000, container vault mount, UI
# port 8113 occupancy, UI reachability, optional target note, Tailscale IP, and
# a prod-specific check for unexpectedly-enabled automation/write flags.
#
# Usage:
#   make prod-ui-doctor
#   scripts/prod/prod_ui_doctor.sh
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
export CUI_CHANNEL CUI_EXPECTED_VAULT_PATTERN CUI_EXPECTED_VAULT_LABEL \
  CUI_API_PORT CUI_UI_PORT CUI_COMPOSE_FILES CUI_COMPOSE_PROJECT CUI_SERVE_MODULE CUI_DB_LABEL

# Prod-specific read-only check: surface automation/write-capable flags so the
# operator can see whether a prod start would run mutation-capable services.
cui_extra_doctor() {
  local rc=0
  if [ "${PROD_UI_ENABLE_AUTOMATION:-0}" = "1" ] || [ "${WATCHER_AUTO_EXEC:-}" = "1" ]; then
    echo "  [warn] automation/write-capable flags are ENABLED in this environment"
    echo "         (PROD_UI_ENABLE_AUTOMATION=${PROD_UI_ENABLE_AUTOMATION:-unset}, WATCHER_AUTO_EXEC=${WATCHER_AUTO_EXEC:-unset})."
    echo "         A prod start here would run mutation-capable services. Confirm this is intended."
    rc=1
  else
    echo "  [ok]   no unexpected automation/write flags enabled (safe verification posture)"
  fi
  return "${rc}"
}

cui_run_doctor
