#!/usr/bin/env bash
set -euo pipefail

CWD="$(pwd)"
EXPECTED_BRANCH=""
EXPECTED_WORKTREE=""
BASE_BRANCH="main"
ALLOW_DIRTY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cwd)
      CWD="$2"
      shift 2
      ;;
    --expected-branch)
      EXPECTED_BRANCH="$2"
      shift 2
      ;;
    --expected-worktree)
      EXPECTED_WORKTREE="$2"
      shift 2
      ;;
    --base-branch)
      BASE_BRANCH="$2"
      shift 2
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
      shift
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$CWD"

ARGS=(--cwd "$CWD")
if [[ -n "$EXPECTED_BRANCH" ]]; then
  ARGS+=(--expected-branch "$EXPECTED_BRANCH")
fi
if [[ -n "$EXPECTED_WORKTREE" ]]; then
  ARGS+=(--expected-worktree "$EXPECTED_WORKTREE")
fi
if [[ -n "$BASE_BRANCH" ]]; then
  ARGS+=(--base-branch "$BASE_BRANCH")
fi
if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
  ARGS+=(--allow-dirty)
fi

# Parallel-agent safety: refuse to run in the shared root worktree by default
# (AGENTS.md :: Parallel-agent execution). Set PKM_ALLOW_SHARED_ROOT=1 for deliberate solo work in the root.
if [[ "${PKM_ALLOW_SHARED_ROOT:-0}" != "1" ]]; then
  ARGS+=(--require-dedicated-worktree)
fi

python3 scripts/git_hygiene_preflight.py "${ARGS[@]}"
