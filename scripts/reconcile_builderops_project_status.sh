#!/usr/bin/env bash
# Low-frequency BuilderOps/GitHub Project reconciliation hook.
#
# This is deliberately outside dispatcher next/claim/heartbeat/complete. It may
# use GitHub Project/GraphQL-backed helpers because it is a manual/batched
# projection repair path, not an agent pickup hot path.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=lib/start_full_system_env.sh
source "scripts/lib/start_full_system_env.sh"

PYTHON_BIN="$(resolve_start_full_system_python_bin || true)"
if [ -z "${PYTHON_BIN:-}" ]; then
  echo "ERROR: repo Python unavailable for project reconciliation" >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  set -- --scan
fi

exec "$PYTHON_BIN" scripts/reconcile_project_status.py "$@"
