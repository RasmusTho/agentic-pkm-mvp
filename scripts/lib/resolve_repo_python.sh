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

builderops_resolve_python() {
    local app_root="$1"
    builderops_find_venv "$app_root" 2>/dev/null \
        || builderops_find_git_common_venv "$app_root" 2>/dev/null
}
