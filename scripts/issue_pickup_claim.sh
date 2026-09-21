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

# The default task id is derived from the single Python source
# (app/dispatcher/sync_github.py::github_issue_task_id), so this wrapper can
# never drift from the id `dispatcher pull` assigns (INV-DG-2). python3 is
# already a hard dependency of every wrapper path via JSON parsing.
if [[ -z "$TASK_ID" ]]; then
  script_repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  if ! TASK_ID="$(
    TASK_ID_REPO="$REPO" \
    TASK_ID_ISSUE="$ISSUE_NUMBER" \
    TASK_ID_REPO_ROOT="$script_repo_root" \
    "$JSON_PYTHON_BIN" - <<'PY'
import os
import sys

sys.path.insert(0, os.environ["TASK_ID_REPO_ROOT"])

from app.dispatcher.sync_github import github_issue_task_id

print(github_issue_task_id(os.environ["TASK_ID_REPO"], int(os.environ["TASK_ID_ISSUE"])))
PY
  )"; then
    echo "could not derive task_id via app.dispatcher.sync_github.github_issue_task_id; pass --task-id explicitly" >&2
    exit 2
  fi
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
    print("dispatcher-status-unavailable false dispatcher_status_unparseable")
    raise SystemExit(0)

if not isinstance(payload, dict) or payload.get("ok") is not True:
    print("dispatcher-status-unavailable false dispatcher_status_invalid")
    raise SystemExit(0)

db_exists = payload.get("db_exists")
reported_mode = payload.get("coordination_mode")
if db_exists is True:
    if reported_mode == "dispatcher-backed":
        mode = "dispatcher-backed"
    else:
        mode = "dispatcher-state-unavailable"
elif db_exists is False:
    if reported_mode == "github-label-only-fallback":
        mode = "github-label-only-fallback"
    else:
        mode = "dispatcher-status-inconsistent"
else:
    mode = "dispatcher-status-unavailable"

reason = payload.get("fallback_reason")
if not isinstance(reason, str) or not reason:
    reason = "none" if mode == "dispatcher-backed" else "dispatcher_unavailable"
print(f"{mode} {reason}")
PY
}

read -r DETECTED_MODE DETECTED_REASON < <(detect_coordination_receipt)
if [[ "$DETECTED_MODE" == "dispatcher-status-unavailable" || \
      "$DETECTED_MODE" == "dispatcher-state-unavailable" || \
      "$DETECTED_MODE" == "dispatcher-status-inconsistent" ]]; then
  echo "pickup refused: dispatcher status is malformed or inconsistent; fallback authority is unavailable" >&2
  exit 1
fi
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
  if [[ "$DETECTED_MODE" == "dispatcher-backed" ]]; then
    echo "GitHub-label-only fallback refused while dispatcher-backed coordination is available" >&2
    exit 1
  fi
  RECEIPT_COORDINATION_MODE="github-label-only-fallback"
  RECEIPT_FALLBACK_REASON="${FALLBACK_REASON:-$DETECTED_REASON}"
  if [[ -z "$RECEIPT_FALLBACK_REASON" || "$RECEIPT_FALLBACK_REASON" == "none" ]]; then
    echo "--fallback-reason is required for explicit label-only fallback" >&2
    exit 2
  fi
fi

replace_ready_label_with_in_progress() {
  # GitHub's per-label DELETE would leave a successful claim with no active
  # agent-state label. Read the current labels, then use the collection PUT
  # endpoint for one atomic replacement that keeps every non-agent label.
  local labels_json label_payload
  if ! labels_json="$(gh api --method GET "repos/$REPO/issues/$ISSUE_NUMBER/labels")"; then
    return 1
  fi
  if ! label_payload="$(
    GITHUB_LABELS_JSON="$labels_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    labels = json.loads(os.environ["GITHUB_LABELS_JSON"])
except (KeyError, json.JSONDecodeError) as exc:
    raise SystemExit(f"GitHub label read is not valid JSON: {exc}")

if not isinstance(labels, list):
    raise SystemExit("GitHub label read did not return a list")

names = []
for label in labels:
    name = label.get("name") if isinstance(label, dict) else label
    if not isinstance(name, str) or not name:
        raise SystemExit("GitHub label read contained an invalid label")
    if name.startswith("agent:"):
        continue
    if name not in names:
        names.append(name)

if "agent:ready" not in {
    label.get("name") if isinstance(label, dict) else label for label in labels
}:
    raise SystemExit("GitHub label read no longer contains agent:ready")

names.append("agent:in-progress")

print(json.dumps({"labels": names}))
PY
  )"; then
    return 1
  fi

  if gh api --method PUT \
    "repos/$REPO/issues/$ISSUE_NUMBER/labels" \
    --input - <<<"$label_payload" >/dev/null; then
    return 0
  fi

  # A nonzero transport result is ambiguous: GitHub may have applied the PUT
  # before the response was lost. Read back the label set before releasing a
  # dispatcher lease or reporting a label-only outcome.
  local readback_json
  if ! readback_json="$(gh api --method GET "repos/$REPO/issues/$ISSUE_NUMBER/labels")"; then
    return 2
  fi
  local readback_status=0
  if GITHUB_LABELS_JSON="$readback_json" \
    EXPECTED_LABEL_PAYLOAD_JSON="$label_payload" \
    ORIGINAL_LABELS_JSON="$labels_json" \
    "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

def label_names(value):
    if not isinstance(value, list):
        raise ValueError("label payload is not a list")
    names = []
    for label in value:
        name = label.get("name") if isinstance(label, dict) else label
        if not isinstance(name, str) or not name:
            raise ValueError("label payload contains an invalid name")
        names.append(name)
    return set(names)

try:
    actual = label_names(json.loads(os.environ["GITHUB_LABELS_JSON"]))
    expected_payload = json.loads(os.environ["EXPECTED_LABEL_PAYLOAD_JSON"])
    if not isinstance(expected_payload, dict):
        raise ValueError("expected label payload is not an object")
    expected = label_names(expected_payload.get("labels"))
    original = label_names(json.loads(os.environ["ORIGINAL_LABELS_JSON"]))
except (KeyError, json.JSONDecodeError, TypeError, ValueError):
    raise SystemExit(2)
if actual == expected:
    raise SystemExit(0)
if actual == original:
    raise SystemExit(1)
raise SystemExit(2)
PY
  then
    return 0
  else
    readback_status=$?
    return "$readback_status"
  fi
}

verify_current_ready_issue() {
  local issue_json
  if ! issue_json="$(gh api "repos/$REPO/issues/$ISSUE_NUMBER")"; then
    return 1
  fi
  GITHUB_ISSUE_JSON="$issue_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os
import sys

try:
    issue = json.loads(os.environ["GITHUB_ISSUE_JSON"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit("GitHub issue read is not valid JSON")

if not isinstance(issue, dict):
    raise SystemExit("GitHub issue read did not return an object")
try:
    expected_number = int(os.environ["ISSUE_NUMBER"])
except (KeyError, ValueError):
    raise SystemExit("requested issue number is invalid")
actual_number = issue.get("number")
if (
    isinstance(actual_number, bool)
    or not isinstance(actual_number, int)
    or actual_number != expected_number
):
    raise SystemExit("GitHub issue read returned a different issue number")
if str(issue.get("state", "")).lower() != "open":
    raise SystemExit("GitHub issue is not open")
labels = issue.get("labels")
if not isinstance(labels, list):
    raise SystemExit("GitHub issue read did not include a labels list")
names = []
for label in labels:
    name = label.get("name") if isinstance(label, dict) else label
    if not isinstance(name, str):
        raise SystemExit("GitHub issue read contained an invalid label")
    names.append(name)
if "agent:ready" not in names:
    raise SystemExit("fresh GitHub issue read no longer contains agent:ready")
agent_state_labels = {name for name in names if name.startswith("agent:")}
if agent_state_labels != {"agent:ready"}:
    raise SystemExit("fresh GitHub issue read contains conflicting agent-state labels")
body = issue.get("body")
if not isinstance(body, str):
    body = ""
repository_root = os.environ.get("ISSUE_READINESS_REPO_ROOT")
if not isinstance(repository_root, str) or not repository_root:
    raise SystemExit("issue readiness validator path is unavailable")
sys.path.insert(0, repository_root)
from scripts.validate_issue_readiness import classify_issue_body

report = classify_issue_body(body, issue_number=expected_number, labels=names)
if report.readiness_classification != "ready_candidate":
    raise SystemExit(
        "fresh GitHub issue failed strict readiness validation: "
        + report.readiness_classification
    )
PY
}

release_dispatcher_claim() {
  local release_json
  if ! release_json="$(
    "$PYTHON_BIN" -m app.dispatcher release "$TASK_ID" --agent "$AGENT_ID" --json 2>/dev/null
  )"; then
    return 1
  fi

  DISPATCHER_RELEASE_JSON="$release_json" \
  EXPECTED_TASK_ID="$TASK_ID" \
  "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ["DISPATCHER_RELEASE_JSON"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit(1)

task = payload.get("task")
if payload.get("ok") is not True or not isinstance(task, dict):
    raise SystemExit(1)
if task.get("task_id") != os.environ["EXPECTED_TASK_ID"]:
    raise SystemExit(1)
if task.get("claimed_by") is not None or task.get("lease_id") is not None:
    raise SystemExit(1)
PY
}

if [[ "$RECEIPT_COORDINATION_MODE" == "dispatcher-backed" ]]; then
  pickup_refresh_json=""
  if ! pickup_refresh_json="$(
    "$PYTHON_BIN" -m app.dispatcher pickup-refresh "$TASK_ID" --repo "$REPO" --json
  )"; then
    pickup_reason="$(
      PICKUP_REFRESH_JSON="$pickup_refresh_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ.get("PICKUP_REFRESH_JSON", ""))
except json.JSONDecodeError:
    payload = {}
reason = payload.get("reason") or payload.get("error")
if not isinstance(reason, str) or not reason:
    reason = "refresh_failed"
print(reason)
PY
    )"
    echo "dispatcher pickup refresh refused reason=$pickup_reason; agent:ready was not removed" >&2
    exit 1
  else
    if ! PICKUP_REFRESH_JSON="$pickup_refresh_json" "$JSON_PYTHON_BIN" - <<'PY'
import json
import os

try:
    payload = json.loads(os.environ["PICKUP_REFRESH_JSON"])
except (KeyError, json.JSONDecodeError):
    raise SystemExit("pickup refresh response is not valid JSON")
if payload.get("ok") is not True or payload.get("ready") is not True:
    raise SystemExit("pickup refresh did not prove the task ready")
PY
    then
      echo "dispatcher pickup refresh evidence was invalid; agent:ready was not removed" >&2
      exit 1
    fi
  fi

fi

if [[ "$RECEIPT_COORDINATION_MODE" == "dispatcher-backed" ]]; then
  claim_json=""
  if ! claim_json="$("$PYTHON_BIN" -m app.dispatcher claim "$TASK_ID" --agent "$AGENT_ID" --ttl-minutes "$TTL_MINUTES" --json)"; then
    # Provider-wide partial-sync metadata cannot prove why this exact task is
    # absent: the kill switch still runs the essential agent:ready scan. Keep
    # the dispatcher claim failure opaque and leave the label untouched rather
    # than advertising a lease-bypassing fallback without task-specific proof.
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
    if release_dispatcher_claim; then
      echo "claim-verification-failed cleanup=released task_id=$TASK_ID lease_id=unverified holder=$AGENT_ID evidence=verified-dispatcher-release" >&2
    else
      echo "claim-verification-failed cleanup-failed task_id=$TASK_ID lease_id=unverified holder=$AGENT_ID evidence=cleanup-failed" >&2
    fi
    echo "dispatcher availability is not an acquired claim; agent:ready was not removed" >&2
    exit 1
  fi

  read -r RECEIPT_LEASE_ID RECEIPT_HOLDER <<< "$validation"
  label_transition_status=0
  if replace_ready_label_with_in_progress; then
    label_transition_status=0
  else
    label_transition_status=$?
  fi
  if [[ "$label_transition_status" -eq 2 ]]; then
    echo "label-transition-unknown cleanup=lease-retained task_id=$TASK_ID lease_id=$RECEIPT_LEASE_ID holder=$RECEIPT_HOLDER evidence=label-readback-unknown" >&2
    exit 1
  fi
  if [[ "$label_transition_status" -eq 1 ]]; then
    if release_dispatcher_claim; then
      echo "label-transition-failed cleanup=released task_id=$TASK_ID lease_id=$RECEIPT_LEASE_ID holder=$RECEIPT_HOLDER evidence=verified-dispatcher-release" >&2
    else
      echo "label-transition-failed cleanup-failed task_id=$TASK_ID lease_id=$RECEIPT_LEASE_ID holder=$RECEIPT_HOLDER evidence=cleanup-failed" >&2
    fi
    exit 1
  fi

  echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON task_id=$TASK_ID lease_id=$RECEIPT_LEASE_ID holder=$RECEIPT_HOLDER evidence=verified-dispatcher-lease"
  exit 0
fi

claimant_receipt="Pickup intent receipt: agent=$AGENT_ID session=$SESSION_ID branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON issue=$ISSUE_NUMBER"
if ! ISSUE_READINESS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)" \
  ISSUE_NUMBER="$ISSUE_NUMBER" verify_current_ready_issue; then
  echo "GitHub-label-only pickup refused; exact issue is not freshly open and strictly ready; agent:ready was not removed" >&2
  exit 1
fi
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

label_transition_status=0
if replace_ready_label_with_in_progress; then
  label_transition_status=0
else
  label_transition_status=$?
fi
if [[ "$label_transition_status" -eq 2 ]]; then
  echo "GitHub label transition outcome unknown after claimant intent receipt comment=$comment_id; no dispatcher lease exists" >&2
  exit 1
fi
if [[ "$label_transition_status" -eq 1 ]]; then
  echo "GitHub label transition failed after claimant intent receipt comment=$comment_id" >&2
  exit 1
fi

echo "pickup-claim-complete issue=$ISSUE_NUMBER branch=$EXPECTED_BRANCH worktree=$EXPECTED_WORKTREE coordination_mode=$RECEIPT_COORDINATION_MODE fallback_reason=$RECEIPT_FALLBACK_REASON agent=$AGENT_ID session=$SESSION_ID evidence=github-comment:$comment_id"
