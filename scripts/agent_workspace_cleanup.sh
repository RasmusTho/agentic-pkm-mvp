#!/usr/bin/env bash
set -euo pipefail

# Safe cleanup helper for multi-agent worktree workflows.
# Default: report-only. Use --apply to execute safe cleanup actions.

MODE="report"
STALE_DAYS=14
CWD="$(pwd)"

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
    *)
      echo "Unknown arg: $1" >&2
      exit 2
      ;;
  esac
done

cd "$CWD"

if [[ "$MODE" == "report" ]]; then
  python3 scripts/git_hygiene_janitor.py --cwd "$CWD" --stale-after-days "$STALE_DAYS"
  exit 0
fi

# Apply mode: require clean tree in the current checkout.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing cleanup: current worktree is dirty." >&2
  exit 1
fi

CURRENT_BRANCH="$(git branch --show-current)"
CURRENT_TOP="$(git rev-parse --show-toplevel)"

# 1) Prune stale worktree metadata.
git worktree prune

# 2) Remove only codex-owned local worktrees whose branch is already merged to origin/main.
#    Never remove current worktree.
while IFS= read -r wt; do
  [[ -z "$wt" ]] && continue
  WT_PATH="$(awk '{print $1}' <<<"$wt")"
  WT_BRANCH="$(awk '{print $2}' <<<"$wt")"
  [[ "$WT_PATH" == "$CURRENT_TOP" ]] && continue
  [[ "$WT_BRANCH" == "$CURRENT_BRANCH" ]] && continue
  [[ "$WT_BRANCH" != codex/* ]] && continue

  if git show-ref --verify --quiet "refs/heads/$WT_BRANCH"; then
    if git merge-base --is-ancestor "$WT_BRANCH" origin/main; then
      if [[ -n "$(git -C "$WT_PATH" status --porcelain 2>/dev/null || true)" ]]; then
        echo "Skipping dirty worktree: $WT_PATH ($WT_BRANCH)"
        continue
      fi
      git worktree remove "$WT_PATH" || true
      git branch -d "$WT_BRANCH" || true
    fi
  fi
done < <(git worktree list --porcelain | awk '
  /^worktree / {path=$2}
  /^branch / {sub("refs/heads/", "", $2); print path " " $2}
')

# 3) Delete merged local codex/ branches not checked out anywhere.
while IFS= read -r branch; do
  [[ -z "$branch" ]] && continue
  [[ "$branch" == "$CURRENT_BRANCH" ]] && continue
  if git merge-base --is-ancestor "$branch" origin/main; then
    git branch -d "$branch" || true
  fi
done < <(git for-each-ref --format='%(refname:short)' refs/heads/codex/)

# 4) Drop old stash entries created for integration drift isolation.
#    Only drops entries older than STALE_DAYS containing preserve-local-drift.
CUTOFF_EPOCH="$(( $(date +%s) - STALE_DAYS*24*60*60 ))"
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  REF="$(cut -d: -f1 <<<"$line")"
  EPOCH="$(grep -Eo '[0-9]{10}' <<<"$line" | head -n1 || true)"
  if [[ -n "$EPOCH" && "$EPOCH" -lt "$CUTOFF_EPOCH" ]]; then
    if grep -q "preserve-local-drift" <<<"$line"; then
      git stash drop "$REF" || true
    fi
  fi
done < <(git stash list --date=unix)

echo "Cleanup apply complete."
