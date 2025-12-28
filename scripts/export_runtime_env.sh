#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "VAULT_ROOT is required to export runtime env" >&2
  exit 2
fi

settings_path="$VAULT_ROOT/_system/settings/system-settings.yaml"
if [ ! -f "$settings_path" ]; then
  echo "System settings not found at: $settings_path" >&2
  exit 3
fi

mkdir -p tmp
printf "%s\n" "VAULT_ROOT=$VAULT_ROOT" > tmp/runtime.env
