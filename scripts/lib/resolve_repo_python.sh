#!/usr/bin/env bash
# Shared repo-virtualenv resolution for worktree-safe BuilderOps entrypoints.

builderops_find_venv() {
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

builderops_find_git_common_venv() {
    local app_root="$1"
    local common_dir
    common_dir="$(git -C "$app_root" rev-parse --git-common-dir 2>/dev/null)" || return 1
    if [ -n "$common_dir" ] && [ "${common_dir#/}" = "$common_dir" ]; then
        common_dir="$(cd "$app_root/$common_dir" && pwd)"
    fi

    local canonical_root
    canonical_root="$(dirname "$common_dir")"
    if [ -x "$canonical_root/.venv/bin/python3" ]; then
        echo "$canonical_root/.venv/bin/python3"
        return 0
    fi
    return 1
}

# BUILDEROPS_PYTHON: explicit interpreter override, honored first. Must be an
# executable path (e.g. set by CI/tests to `sys.executable`). Never inferred —
# if set but not executable, resolution fails loud rather than falling back to
# venv discovery. Desktop use is unaffected: the fail-loud no-venv path below
# only runs when this override is unset.
builderops_resolve_python() {
    local app_root="$1"
    if [ -n "${BUILDEROPS_PYTHON:-}" ]; then
        if [ -f "$BUILDEROPS_PYTHON" ] && [ -x "$BUILDEROPS_PYTHON" ]; then
            echo "$BUILDEROPS_PYTHON"
            return 0
        fi
        echo "BUILDEROPS_PYTHON is set to '$BUILDEROPS_PYTHON' but is not an executable file." >&2
        return 1
    fi
    builderops_find_venv "$app_root" 2>/dev/null \
        || builderops_find_git_common_venv "$app_root" 2>/dev/null
}
