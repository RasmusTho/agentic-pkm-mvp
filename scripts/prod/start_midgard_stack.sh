#!/usr/bin/env bash
# Canonical prod stack startup guard for the Midgård vault.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
cd "$ROOT"

env_file=".env.prod.local"
if [ ! -f "$env_file" ]; then
  echo "ERROR: missing ${env_file}; prod startup requires the configured Midgård vault." >&2
  exit 2
fi

source "scripts/lib/load_env_defaults.sh"
load_env_defaults_file "$env_file"

if [ -z "${VAULT_ROOT:-}" ]; then
  echo "ERROR: ${env_file} must set VAULT_ROOT to the Midgård vault." >&2
  exit 2
fi

vault_base="$(basename "$VAULT_ROOT" | tr '[:upper:]' '[:lower:]')"
if ! printf '%s' "$vault_base" | grep -Eq 'midg(å|a)rd'; then
  echo "ERROR: prod VAULT_ROOT must resolve to Midgård/Midgard, got: $VAULT_ROOT" >&2
  exit 2
fi

if [ ! -d "$VAULT_ROOT" ]; then
  echo "ERROR: prod VAULT_ROOT is not a directory: $VAULT_ROOT" >&2
  exit 2
fi

export VAULT_ROOT
exec scripts/start_full_system.sh
