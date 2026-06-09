#!/usr/bin/env bash
# scripts/builderops_cli.sh — BuilderOps CLI wrapper for automation worktrees.
#
# Resolves the repo-supported Python interpreter (.venv/bin/python3 when
# available, otherwise python3) and runs:
#
#   python3 -m app.builderops builderops <args...>
#
# Usage from any automation worktree (cwd is the repo root or any worktree):
#
#   scripts/builderops_cli.sh builderops list --type LearningSignal --json
#   scripts/builderops_cli.sh builderops create-learning-signal \
#     --summary "..." --content "..." --signal-type workflow \
#     --source-ref github_issue:#1234 --json
#   scripts/builderops_cli.sh builderops append-receipt ...
#
# The ``builderops`` subcommand name must be the first argument so that the
# invocation mirrors ``python3 -m app.cli builderops ...``.
#
# Environment:
#   BUILDEROPS_DB_PATH   — override the SQLite DB path (optional)
#   BUILDEROPS_STATE_DIR — override the state directory (optional)

set -euo pipefail

# Resolve the directory that contains the app/ package.
# When invoked from a git worktree the script lives under:
#   <worktree-root>/scripts/builderops_cli.sh
# so the directory containing app/ is the worktree root (one level up).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Locate the repo venv.  The .venv is created in the main repo checkout; git
# worktrees that live under .claude/worktrees/ do not have their own .venv.
# Walk upward from APP_ROOT until we find a directory containing .venv/.
_find_venv() {
    local dir="$1"
    while [ "$dir" != "/" ]; do
        if [ -x "$dir/.venv/bin/python3" ]; then
            echo "$dir/.venv/bin/python3"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    return 1
}

# Prefer the repo venv to guarantee click, pydantic, and all BuilderOps deps.
PYTHON="$(_find_venv "$APP_ROOT" 2>/dev/null)" || true
if [ -z "$PYTHON" ]; then
    PYTHON="$(command -v python3 2>/dev/null)" || true
fi
if [ -z "$PYTHON" ]; then
    echo "ERROR: no usable python3 found." >&2
    echo "Set up the repo venv first:  python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    exit 1
fi

# Run from the app root (the directory containing app/) so that relative DB
# paths and module discovery resolve correctly.
cd "$APP_ROOT"
exec "$PYTHON" -m app.builderops "$@"
