#!/usr/bin/env bash
set -euo pipefail

ISSUE_NUMBER=""
REPO=""
AGENT_ID=""
SESSION_ID=""
PREFLIGHT_ONLY=0
COORDINATION_MODE="auto"
FALLBACK_REASON=""
TASK_ID=""
TTL_MINUTES=90
PYTHON_BIN="${PYTHON:-python3}"
JSON_PYTHON_BIN="${JSON_PYTHON:-python3}"

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
    --agent)
      AGENT_ID="$2"
      shift 2
      ;;
    --session)
      SESSION_ID="$2"
      shift 2
      ;;
    --task-id)
      TASK_ID="$2"
      shift 2
      ;;
    --ttl-minutes)
      TTL_MINUTES="$2"
      shift 2
      ;;
    --preflight-only)
      PREFLIGHT_ONLY=1
      shift
      ;;
    --coordination-mode)
      COORDINATION_MODE="$2"
      shift 2
      ;;
    --fallback-reason)
      FALLBACK_REASON="$2"
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
if [[ "$COORDINATION_MODE" != "auto" && "$COORDINATION_MODE" != "dispatcher-backed" && "$COORDINATION_MODE" != "github-label-only-fallback" ]]; then
  echo "--coordination-mode must be auto, dispatcher-backed, or github-label-only-fallback" >&2
  exit 2
fi
if ! [[ "$TTL_MINUTES" =~ ^[1-9][0-9]*$ ]]; then
  echo "--ttl-minutes must be a positive integer" >&2
  exit 2
fi

EXPECTED_BRANCH="$(git branch --show-current)"
EXPECTED_WORKTREE="$(git rev-parse --show-toplevel)"
TASK_ID="${TASK_ID:-github-issue-$ISSUE_NUMBER}"

scripts/agent_workspace_preflight.sh \
  --expected-branch "$EXPECTED_BRANCH" \
  --expected-worktree "$EXPECTED_WORKTREE"

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  echo "pickup-preflight-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE claim_evidence=not-acquired"
  exit 0
fi

if [[ -z "$AGENT_ID" ]]; then
  echo "--agent is required for pickup" >&2
  exit 2
fi
if [[ -z "$SESSION_ID" ]]; then
  echo "--session is required for pickup" >&2
  exit 2
fi

if [[ -z "$REPO" ]]; then
  origin_url="$(git remote get-url origin)"
  REPO="$(printf '%s' "$origin_url" | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')"
fi
if [[ "$REPO" != */* ]]; then
  echo "could not resolve GitHub owner/repo; pass --repo OWNER/REPO" >&2
  exit 2
fi

detect_coordination_receipt() {
  local status_json
  if ! status_json="$("$PYTHON_BIN" -m app.dispatcher status --json 2>/dev/null)"; then
    echo "github-label-only-fallback dispatcher_status_failed"
    return 0
  fi

  DISPATCHER_STATUS_JSON="$status_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ["DISPATCHER_STATUS_JSON"])
except (KeyError, json.JSONDecodeError):
    print("github-label-only-fallback dispatcher_status_unparseable")
    raise SystemExit(0)

mode = payload.get("coordination_mode")
if mode != "dispatcher-backed":
    mode = "github-label-only-fallback"
reason = payload.get("fallback_reason")
if not isinstance(reason, str) or not reason:
    reason = "none" if mode == "dispatcher-backed" else "dispatcher_unavailable"
print(f"{mode} {reason}")
PY
}

read -r DETECTED_MODE DETECTED_REASON < <(detect_coordination_receipt)
if [[ "$COORDINATION_MODE" == "auto" ]]; then
  RECEIPT_COORDINATION_MODE="$DETECTED_MODE"
  RECEIPT_FALLBACK_REASON="$DETECTED_REASON"
elif [[ "$COORDINATION_MODE" == "dispatcher-backed" ]]; then
  if [[ "$DETECTED_MODE" != "dispatcher-backed" ]]; then
    echo "dispatcher-backed pickup requested but dispatcher is unavailable: $DETECTED_REASON" >&2
    exit 1
  fi
  RECEIPT_COORDINATION_MODE="dispatcher-backed"
  RECEIPT_FALLBACK_REASON="none"
else
  RECEIPT_COORDINATION_MODE="github-label-only-fallback"
  RECEIPT_FALLBACK_REASON="${FALLBACK_REASON:-$DETECTED_REASON}"
  if [[ -z "$RECEIPT_FALLBACK_REASON" || "$RECEIPT_FALLBACK_REASON" == "none" ]]; then
    echo "--fallback-reason is required for explicit label-only fallback" >&2
    exit 2
  fi
fi

remove_ready_label() {
  gh api --method DELETE \
    "repos/$REPO/issues/$ISSUE_NUMBER/labels/agent%3Aready" >/dev/null
}

if [[ "$RECEIPT_COORDINATION_MODE" == "dispatcher-backed" ]]; then
  claim_json=""
  if ! claim_json="$("$PYTHON_BIN" -m app.dispatcher claim "$TASK_ID" --agent "$AGENT_ID" --ttl-minutes "$TTL_MINUTES" --json)"; then
    echo "dispatcher claim failed for expected task $TASK_ID; agent:ready was not removed" >&2
    exit 1
  fi

  validation=""
  if ! validation="$(
    DISPATCHER_CLAIM_JSON="$claim_json" \
    EXPECTED_TASK_ID="$TASK_ID" \
    EXPECTED_ISSUE_NUMBER="$ISSUE_NUMBER" \
    EXPECTED_AGENT_ID="$AGENT_ID" \
    "$JSON_PYTHON_BIN" - <<'PY'
import json
import os
from datetime import datetime, timezone

try:
    payload = json.loads(os.environ["DISPATCHER_CLAIM_JSON"])
except (KeyError, json.JSONDecodeError) as exc:
    raise SystemExit(f"dispatcher claim receipt is not valid JSON: {exc}")

task = payload.get("task")
lease = payload.get("lease")
if payload.get("ok") is not True or not isinstance(task, dict) or not isinstance(lease, dict):
    raise SystemExit("dispatcher claim receipt is missing task or lease evidence")

expected_task = os.environ["EXPECTED_TASK_ID"]
expected_issue = int(os.environ["EXPECTED_ISSUE_NUMBER"])
expected_agent = os.environ["EXPECTED_AGENT_ID"]
lease_id = lease.get("lease_id")
expires_at = lease.get("expires_at")
try:
    expiry_is_future = (
        isinstance(expires_at, str)
        and datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        > datetime.now(timezone.utc)
    )
except ValueError:
    expiry_is_future = False
checks = {
    "task id": task.get("task_id") == expected_task,
    "issue number": task.get("issue_number") == expected_issue,
    "task status": task.get("status") in {"claimed", "in_progress"},
    "task owner": task.get("claimed_by") == expected_agent,
    "task lease": isinstance(task.get("lease_id"), str) and task.get("lease_id") == lease_id,
    "lease id": isinstance(lease_id, str) and bool(lease_id),
    "lease resource": lease.get("resource") == f"issue:{expected_issue}",
    "lease holder": lease.get("holder") == expected_agent,
    "lease expiry": expiry_is_future,
    "lease active": lease.get("released_at") is None,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("dispatcher claim verification failed: " + ", ".join(failed))
print(f"{lease_id} {expected_agent}")
PY
  )"; then
    "$PYTHON_BIN" -m app.dispatcher release "$TASK_ID" --agent "$AGENT_ID" --json >/dev/null 2>&1 || true
    echo "dispatcher availability is not an acquired claim; agent:ready was not removed" >&2
    exit 1
  fi

  read -r RECEIPT_LEASE_ID RECEIPT_HOLDER <<< "$validation"
  if ! remove_ready_label; then
    "$PYTHON_BIN" -m app.dispatcher release "$TASK_ID" --agent "$AGENT_ID" --json >/dev/null 2>&1 || true
    echo "GitHub label removal failed; released verified dispatcher lease $RECEIPT_LEASE_ID" >&2
    exit 1
  fi

  echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON task_id=$TASK_ID lease_id=$RECEIPT_LEASE_ID holder=$RECEIPT_HOLDER evidence=verified-dispatcher-lease"
  exit 0
fi

claimant_receipt="Pickup intent receipt: agent=$AGENT_ID session=$SESSION_ID branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON issue=$ISSUE_NUMBER"
comment_json="$(
  gh api --method POST \
    "repos/$REPO/issues/$ISSUE_NUMBER/comments" \
    -f "body=$claimant_receipt"
)"
comment_id="$(
  GITHUB_COMMENT_JSON="$comment_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ["GITHUB_COMMENT_JSON"])
except (KeyError, json.JSONDecodeError) as exc:
    raise SystemExit(f"GitHub claimant receipt is not valid JSON: {exc}")
comment_id = payload.get("id")
if not isinstance(comment_id, int):
    raise SystemExit("GitHub claimant receipt did not return a comment id")
print(comment_id)
PY
)"

if ! remove_ready_label; then
  echo "GitHub label removal failed after claimant intent receipt comment=$comment_id" >&2
  exit 1
fi

echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON agent=$AGENT_ID session=$SESSION_ID evidence=github-comment:$comment_id"
