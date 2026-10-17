#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}"
LOCK_PATH=/tmp/agentic-pkm-mvp-builderops-lock/deployment.lock
exec python3 "${ROOT}/scripts/builderops/deployment_lock.py" --lock-path "${LOCK_PATH}" \
  -- python3 -m app.ops.devui_component_promotion "$@"
