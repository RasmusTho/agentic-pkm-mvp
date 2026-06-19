#!/usr/bin/env bash
# Bootstrap dev-time BuilderOps coordination without making GitHub availability
# a hard dependency for runtime startup.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=lib/start_full_system_env.sh
source "scripts/lib/start_full_system_env.sh"

PYTHON_BIN="$(resolve_start_full_system_python_bin || true)"
if [ -z "${PYTHON_BIN:-}" ]; then
  echo "BuilderOps bootstrap: degraded (repo Python unavailable)" >&2
  exit 0
fi

exec "$PYTHON_BIN" -m app.ops.builderops_startup --root "$ROOT" "$@"
