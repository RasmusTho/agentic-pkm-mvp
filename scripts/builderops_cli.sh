#!/usr/bin/env bash
# scripts/builderops_cli.sh — BuilderOps CLI wrapper for automation worktrees.
#
# Resolves the repo-supported Python interpreter (.venv/bin/python3) and runs:
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
# worktrees usually do not have their own .venv.
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

_find_git_common_venv() {
    local common_dir
    common_dir="$(git -C "$APP_ROOT" rev-parse --git-common-dir 2>/dev/null)" || return 1
    if [ -n "$common_dir" ] && [ "${common_dir#/}" = "$common_dir" ]; then
        common_dir="$(cd "$APP_ROOT/$common_dir" && pwd)"
    fi

    local canonical_root
    canonical_root="$(dirname "$common_dir")"
    if [ -x "$canonical_root/.venv/bin/python3" ]; then
        echo "$canonical_root/.venv/bin/python3"
        return 0
    fi
    return 1
}

# Prefer the repo venv to guarantee click, pydantic, and all BuilderOps deps.
PYTHON="$(_find_venv "$APP_ROOT" 2>/dev/null || _find_git_common_venv 2>/dev/null)" || true
if [ -z "$PYTHON" ]; then
    echo "ERROR: BuilderOps CLI requires the repo virtualenv, but no usable .venv/bin/python3 was found." >&2
    echo "Run from the canonical checkout, or create the canonical repo venv first:" >&2
    echo "  cd /Users/rasmusthornberg/code/agentic-pkm-mvp && python3 -m venv .venv && .venv/bin/pip install -e ." >&2
    echo "Codex app worktrees should share that canonical checkout venv through git worktree metadata." >&2
    exit 1
fi

# Run from the app root (the directory containing app/) so that relative DB
# paths and module discovery resolve correctly.
cd "$APP_ROOT"
exec "$PYTHON" -m app.builderops "$@"
