#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CWD="$(pwd)"
EXPECTED_BRANCH=""
EXPECTED_WORKTREE=""
BASE_BRANCH="main"
ALLOW_DIRTY=0
INTEGRATION_MERGE_TARGET=""
INTEGRATION_STEP=""
LEGACY_6560_STEP=""
LEGACY_6560_AGENT=""
LEGACY_6560_SESSION=""
LEGACY_6560_HEAD=""
LEGACY_6560_INDEX=""

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
    --integration-merge-target)
      INTEGRATION_MERGE_TARGET="$2"
      shift 2
      ;;
    --integration-step)
      INTEGRATION_STEP="$2"
      shift 2
      ;;
    --legacy-6560-first-commit)
      LEGACY_6560_STEP="$2"
      shift 2
      ;;
    --legacy-6560-agent)
      LEGACY_6560_AGENT="$2"
      shift 2
      ;;
    --legacy-6560-session)
      LEGACY_6560_SESSION="$2"
      shift 2
      ;;
    --legacy-6560-head)
      LEGACY_6560_HEAD="$2"
      shift 2
      ;;
    --legacy-6560-index)
      LEGACY_6560_INDEX="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$CWD"

if [[ -n "$LEGACY_6560_STEP" || -n "$LEGACY_6560_AGENT" || -n "$LEGACY_6560_SESSION" || -n "$LEGACY_6560_HEAD" || -n "$LEGACY_6560_INDEX" ]]; then
  if [[ ( "$LEGACY_6560_STEP" != "stage" && "$LEGACY_6560_STEP" != "commit" ) || -z "$EXPECTED_BRANCH" || -z "$EXPECTED_WORKTREE" || "$ALLOW_DIRTY" -ne 1 || "$BASE_BRANCH" != "main" || -n "$INTEGRATION_MERGE_TARGET" || -n "$INTEGRATION_STEP" || -z "$LEGACY_6560_AGENT" || -z "$LEGACY_6560_SESSION" || -z "$LEGACY_6560_HEAD" || ( "$LEGACY_6560_STEP" == "stage" && -n "$LEGACY_6560_INDEX" ) || ( "$LEGACY_6560_STEP" == "commit" && -z "$LEGACY_6560_INDEX" ) ]]; then
    echo "#6560 first-commit preflight inputs are incomplete or incompatible" >&2
    exit 1
  fi
  LEGACY_ARGS=(--worktree "$(pwd -P)" --agent "$LEGACY_6560_AGENT" --session "$LEGACY_6560_SESSION"
    --head "$LEGACY_6560_HEAD" --expected-remote-head "$LEGACY_6560_HEAD" --effect "first-commit-$LEGACY_6560_STEP")
  if [[ "$LEGACY_6560_STEP" == "commit" ]]; then
    LEGACY_ARGS+=(--first-commit-index "$LEGACY_6560_INDEX")
  fi
  python3 -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from app.builderops import legacy_git_config as c; c.check_host_config(); c.check(cwd=Path(sys.argv[2]), worktree=Path(sys.argv[2]))' "$SCRIPT_DIR/.." "$(pwd -P)"
fi

ARGS=(--cwd "$CWD")
if [[ -n "$EXPECTED_BRANCH" ]]; then
  ARGS+=(--expected-branch "$EXPECTED_BRANCH")
fi
if [[ -n "$EXPECTED_WORKTREE" ]]; then
  ARGS+=(--expected-worktree "$EXPECTED_WORKTREE")
fi
if [[ -n "$BASE_BRANCH" && -z "$LEGACY_6560_STEP" ]]; then
  ARGS+=(--base-branch "$BASE_BRANCH")
fi
if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
  ARGS+=(--allow-dirty)
fi
if [[ -n "$INTEGRATION_MERGE_TARGET" ]]; then
  ARGS+=(--integration-merge-target "$INTEGRATION_MERGE_TARGET")
fi
if [[ -n "$INTEGRATION_STEP" ]]; then
  ARGS+=(--integration-step "$INTEGRATION_STEP")
fi

# Parallel-agent safety: refuse to run in the shared root worktree by default
# (AGENTS.md :: Parallel-agent execution). Set PKM_ALLOW_SHARED_ROOT=1 for deliberate solo work in the root.
if [[ "${PKM_ALLOW_SHARED_ROOT:-0}" != "1" || -n "$INTEGRATION_MERGE_TARGET" || -n "$INTEGRATION_STEP" || -n "$LEGACY_6560_STEP" ]]; then
  ARGS+=(--require-dedicated-worktree)
fi

if [[ -n "$LEGACY_6560_STEP" ]]; then
  # Git's otherwise read-only status probe may refresh index stat data.  This
  # path binds the original complete index bytes in the authenticated pin.
  GIT_OPTIONAL_LOCKS=0 python3 "$SCRIPT_DIR/git_hygiene_preflight.py" "${ARGS[@]}"
  python3 "$SCRIPT_DIR/legacy_6560_publication_gate.py" "${LEGACY_ARGS[@]}"
else
  python3 "$SCRIPT_DIR/git_hygiene_preflight.py" "${ARGS[@]}"
fi
