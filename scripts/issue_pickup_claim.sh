#!/usr/bin/env bash
set -euo pipefail

ISSUE_NUMBER=""
REPO=""
PREFLIGHT_ONLY=0
SKIP_PREFLIGHT=0
COORDINATION_MODE="auto"
PYTHON_BIN="${PYTHON:-python3}"

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
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=1
      shift
      ;;
    --coordination-mode)
      COORDINATION_MODE="$2"
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

detect_coordination_receipt() {
  if [[ "$COORDINATION_MODE" != "auto" ]]; then
    echo "$COORDINATION_MODE none"
    return 0
  fi

  local status_json
  if ! status_json="$("$PYTHON_BIN" -m app.dispatcher status --json 2>/dev/null)"; then
    echo "github-label-only-fallback dispatcher_status_failed"
    return 0
  fi

  DISPATCHER_STATUS_JSON="$status_json" "$PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ["DISPATCHER_STATUS_JSON"])
except (KeyError, json.JSONDecodeError):
    print("github-label-only-fallback dispatcher_status_unparseable")
    raise SystemExit(0)

mode = payload.get("coordination_mode")
if not isinstance(mode, str) or not mode:
    mode = "dispatcher-backed" if payload.get("db_exists") else "github-label-only-fallback"
reason = payload.get("fallback_reason")
if not isinstance(reason, str) or not reason:
    reason = "none"
print(f"{mode} {reason}")
PY
}

read -r RECEIPT_COORDINATION_MODE RECEIPT_FALLBACK_REASON < <(detect_coordination_receipt)

if [[ "$SKIP_PREFLIGHT" -ne 1 ]]; then
  scripts/agent_workspace_preflight.sh \
    --expected-branch "$EXPECTED_BRANCH" \
    --expected-worktree "$EXPECTED_WORKTREE"
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  echo "pickup-preflight-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON"
  exit 0
fi

if [[ -n "$REPO" ]]; then
  gh issue edit "$ISSUE_NUMBER" --repo "$REPO" --remove-label agent:ready
else
  gh issue edit "$ISSUE_NUMBER" --remove-label agent:ready
fi

echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON"
