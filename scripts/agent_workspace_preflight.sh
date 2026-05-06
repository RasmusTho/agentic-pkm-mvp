#!/usr/bin/env bash
set -euo pipefail

CWD="$(pwd)"
EXPECTED_BRANCH=""
EXPECTED_WORKTREE=""

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

python3 scripts/git_hygiene_preflight.py "${ARGS[@]}"
