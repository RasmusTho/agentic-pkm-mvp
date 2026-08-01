#!/usr/bin/env bash
set -euo pipefail

# Safe cleanup helper for multi-agent worktree workflows.
# Default: report-only. Use --apply to execute safe cleanup actions.

MODE="report"
STALE_DAYS=14
CWD="$(pwd)"
PR_STATE_FILE=""
LEASE_FILE=""
TARGET_WORKTREE=""
TARGET_GENERATION=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      MODE="apply"
      shift
      ;;
    --report)
      MODE="report"
      shift
      ;;
    --stale-days)
      STALE_DAYS="$2"
      shift 2
      ;;
    --cwd)
      CWD="$2"
      shift 2
      ;;
    --pr-state-file)
      PR_STATE_FILE="$2"
      shift 2
      ;;
    --lease-file)
      LEASE_FILE="$2"
      shift 2
      ;;
    --target-worktree)
      TARGET_WORKTREE="$2"
      shift 2
      ;;
    --target-generation)
      TARGET_GENERATION="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$CWD"

if [[ "$MODE" == "report" ]]; then
  if [[ -n "$TARGET_WORKTREE" || -n "$TARGET_GENERATION" ]]; then
    echo "Target selectors are only valid with --apply." >&2
    exit 2
  fi
  ARGS=(--cwd "$CWD")
  if [[ -n "$LEASE_FILE" ]]; then
    ARGS+=(--lease-file "$LEASE_FILE")
  fi
  ARGS+=(janitor --stale-after-days "$STALE_DAYS" --mode report)
  if [[ -n "$PR_STATE_FILE" ]]; then
    ARGS+=(--pr-state-file "$PR_STATE_FILE")
  fi
  python3 scripts/agent_worktree.py "${ARGS[@]}"
  exit 0
fi

if [[ -z "$PR_STATE_FILE" || -z "$LEASE_FILE" ]]; then
  echo "Refusing cleanup: --apply requires --pr-state-file and --lease-file." >&2
  exit 1
fi
if [[ -n "$TARGET_WORKTREE" || -n "$TARGET_GENERATION" ]]; then
  if [[ -z "$TARGET_WORKTREE" || -z "$TARGET_GENERATION" ]]; then
    echo "Refusing cleanup: target cleanup requires --target-worktree and --target-generation." >&2
    exit 1
  fi
fi

ARGS=(
  --cwd "$CWD" \
  --lease-file "$LEASE_FILE" \
  janitor \
  --stale-after-days "$STALE_DAYS" \
  --mode apply \
  --pr-state-file "$PR_STATE_FILE"
)
if [[ -n "$TARGET_WORKTREE" ]]; then
  ARGS+=(--target-worktree "$TARGET_WORKTREE" --target-generation "$TARGET_GENERATION")
fi
python3 scripts/agent_worktree.py "${ARGS[@]}"
