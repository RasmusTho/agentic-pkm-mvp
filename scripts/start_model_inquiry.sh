#!/usr/bin/env bash
# Worktree-safe desktop-skill entrypoint for the Python model inquiry launcher.
# Set BUILDEROPS_PYTHON to an executable interpreter path to override the
# repo-.venv discovery below (e.g. for CI/tests with no checked-out venv).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/resolve_repo_python.sh"

PYTHON="$(builderops_resolve_python "$APP_ROOT")" || true
if [ -z "$PYTHON" ]; then
    echo "ERROR: Model inquiry launch requires the repo virtualenv, but no usable .venv/bin/python3 was found." >&2
    echo "Create the canonical checkout venv before launching the desktop skill." >&2
    exit 1
fi

cd "$APP_ROOT"
export BUILDEROPS_PYTHON="$PYTHON"
exec "$PYTHON" -m app.ops.host_secret_bootstrap \
    --channel dev \
    --consumer builderops-model-inquiry \
    -- \
    "$PYTHON" "$SCRIPT_DIR/start_model_inquiry.py" "$@"
