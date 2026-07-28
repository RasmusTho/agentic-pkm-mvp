#!/usr/bin/env bash
set -euo pipefail

# Keep the local worktree projection coupled to the dispatcher lease.
# Dispatcher failures are fail-closed: do not renew or remove local state.

COMMAND=""
TASK_ID=""
AGENT_ID=""
WORKTREE="$(pwd)"
COORDINATION_MODE="dispatcher-backed"
PYTHON_BIN="${PYTHON:-python3}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    heartbeat|complete|release)
      COMMAND="$1"
      shift
      ;;
    --task-id)
      TASK_ID="$2"
      shift 2
      ;;
    --agent)
      AGENT_ID="$2"
      shift 2
      ;;
    --worktree)
      WORKTREE="$2"
      shift 2
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

if [[ -z "$COMMAND" || -z "$TASK_ID" || -z "$AGENT_ID" ]]; then
  echo "Usage: $0 {heartbeat|complete|release} --task-id <id> --agent <id> [--worktree <path>] [--coordination-mode dispatcher-backed|github-label-only-fallback]" >&2
  exit 2
fi

WORKTREE="$(cd "$WORKTREE" && pwd -P)"

if [[ "$COORDINATION_MODE" == "dispatcher-backed" ]]; then
  if [[ "$COMMAND" == "heartbeat" ]]; then
    lease_json="$($PYTHON_BIN -m app.dispatcher heartbeat "$TASK_ID" --agent "$AGENT_ID" --json)"
    read -r lease_id expires_at < <(
      LEASE_JSON="$lease_json" "$PYTHON_BIN" - <<'PY'
import json
import os

payload = json.loads(os.environ["LEASE_JSON"])
lease = payload.get("lease")
if payload.get("ok") is not True or not isinstance(lease, dict):
    raise SystemExit("dispatcher heartbeat did not return lease evidence")
lease_id = lease.get("lease_id")
expires_at = lease.get("expires_at")
if not isinstance(lease_id, str) or not isinstance(expires_at, str):
    raise SystemExit("dispatcher heartbeat lease evidence is incomplete")
print(lease_id, expires_at)
PY
    )
    "$PYTHON_BIN" scripts/agent_worktree.py --cwd "$WORKTREE" heartbeat \
      --path "$WORKTREE" --lease-id "$lease_id" --expires-at "$expires_at"
    exit 0
  fi

  "$PYTHON_BIN" -m app.dispatcher "$COMMAND" "$TASK_ID" --agent "$AGENT_ID" --json >/dev/null
elif [[ "$COMMAND" == "heartbeat" ]]; then
  "$PYTHON_BIN" scripts/agent_worktree.py --cwd "$WORKTREE" heartbeat --path "$WORKTREE"
  exit 0
fi

"$PYTHON_BIN" scripts/agent_worktree.py --cwd "$WORKTREE" release --path "$WORKTREE"
