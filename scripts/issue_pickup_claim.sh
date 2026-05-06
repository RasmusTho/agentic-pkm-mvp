#!/usr/bin/env bash
set -euo pipefail

ISSUE_NUMBER=""
REPO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issue)
      ISSUE_NUMBER="$2"
      shift 2
      ;;
    --repo)
      REPO="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ISSUE_NUMBER" ]]; then
  echo "--issue is required" >&2
  exit 2
fi

EXPECTED_BRANCH="$(git branch --show-current)"
EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"

scripts/agent_workspace_preflight.sh \
  --expected-branch "$EXPECTED_BRANCH" \
  --expected-worktree "$EXPECTED_WORKTREE"

if [[ -n "$REPO" ]]; then
  gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --remove-label agent:ready
else
  gh issue edit "$ISSUE_NUMBER" --remove-label agent:ready
fi

echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE"
