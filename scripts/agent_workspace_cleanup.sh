#!/usr/bin/env bash
set -euo pipefail

# Safe cleanup helper for multi-agent worktree workflows.
# Default: report-only. Use --apply to execute safe cleanup actions.

MODE="report"
STALE_DAYS=14
CWD="$(pwd)"
PR_STATE_FILE=""

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
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$CWD"

if [[ "$MODE" == "report" ]]; then
  ARGS=(--cwd "$CWD" --stale-after-days "$STALE_DAYS" --mode report)
  if [[ -n "$PR_STATE_FILE" ]]; then
    ARGS+=(--pr-state-file "$PR_STATE_FILE")
  fi
  python3 scripts/git_hygiene_janitor.py "${ARGS[@]}"
  exit 0
fi

if [[ -z "$PR_STATE_FILE" ]]; then
  echo "Refusing cleanup: --apply requires --pr-state-file." >&2
  exit 1
fi

python3 scripts/git_hygiene_janitor.py \
  --cwd "$CWD" \
  --stale-after-days "$STALE_DAYS" \
  --mode apply \
  --pr-state-file "$PR_STATE_FILE"
