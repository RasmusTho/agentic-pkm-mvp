#!/usr/bin/env bash
# await_pr_checks.sh — wait for a PR's CI checks (and optionally the Codex verdict) without
# draining the shared GitHub GraphQL budget.
#
# This repo runs many concurrent agents against ONE 5,000/hr GitHub API budget; GraphQL exhausts
# first. `gh pr checks` / `gh pr view --json mergeStateStatus` are GraphQL, and a tight poll loop
# starves every other agent. This script polls REST check-runs only, sleeps the bulk of CI up front,
# and backs off >=60s on the tail. Contract: .codex/skills/_shared/CI_WAIT_CONTRACT.md
#
# Usage:
#   scripts/await_pr_checks.sh <PR> [--codex] [--initial-wait S] [--interval S] [--timeout S] [--sha SHA]
#   scripts/await_pr_checks.sh --help
#
# Exit codes: 0 all checks passed · 1 a check failed · 2 timeout · 3 Codex blocking (with --codex)
set -uo pipefail

INITIAL_WAIT=180     # sleep before first check (~ CI p50; the `not pg` gate is the long pole)
INTERVAL=90          # backoff between checks on the tail (floored to 60)
TIMEOUT=1800         # give up after this many seconds of total polling
CHECK_CODEX=0
PR=""
SHA=""

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage ;;
    --codex) CHECK_CODEX=1; shift ;;
    --initial-wait) INITIAL_WAIT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --sha) SHA="$2"; shift 2 ;;
    -*) echo "unknown flag: $1" >&2; exit 64 ;;
    *) PR="$1"; shift ;;
  esac
done

[ -n "$PR" ] || { echo "error: PR number required (see --help)" >&2; exit 64; }
[ "$INTERVAL" -ge 60 ] 2>/dev/null || INTERVAL=60   # never drop below 60s on the shared bucket

REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
[ -n "$REPO" ] || { echo "error: could not resolve repo from git remote 'origin'" >&2; exit 64; }

# Free, rate-limit-exempt preflight — informational only.
budget=$(gh api rate_limit --jq '"core=\(.resources.core.remaining) graphql=\(.resources.graphql.remaining)"' 2>/dev/null || echo "unknown")
echo "repo=$REPO pr=$PR budget: $budget (this script uses REST core only)"

if [ -z "$SHA" ]; then
  SHA=$(gh api "repos/$REPO/pulls/$PR" --jq '.head.sha' 2>/dev/null) || true
  [ -n "$SHA" ] || { echo "error: could not resolve head SHA for PR #$PR (REST)" >&2; exit 64; }
fi
echo "head=$SHA"

echo "waiting ${INITIAL_WAIT}s before first check (CI runs ~4-5 min; not polling through it)..."
sleep "$INITIAL_WAIT"

deadline=$(( $(date +%s) + TIMEOUT - INITIAL_WAIT ))
while :; do
  pending=$(gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" \
    --jq '[.check_runs[] | select(.status!="completed") | .name] | join(", ")' 2>/dev/null)
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "transient REST error (rc=$rc); backing off ${INTERVAL}s..."
  elif [ -z "$pending" ]; then
    break   # all check-runs completed
  else
    echo "still running: $pending"
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "TIMEOUT after ${TIMEOUT}s; checks still pending: ${pending:-unknown}" >&2
    exit 2
  fi
  sleep "$INTERVAL"
done

# All complete — classify conclusions (skipped/neutral are not failures).
failed=$(gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" \
  --jq '[.check_runs[] | select(.conclusion!=null and .conclusion!="success" and .conclusion!="skipped" and .conclusion!="neutral") | "\(.name): \(.conclusion)"] | join("; ")' 2>/dev/null)
if [ -n "$failed" ]; then
  echo "CHECKS FAILED: $failed" >&2
  exit 1
fi
echo "all required checks passed on $SHA"

if [ "$CHECK_CODEX" -eq 1 ]; then
  bot="chatgpt-codex-connector[bot]"
  reaction=$(gh api "repos/$REPO/issues/$PR/reactions" \
    --jq "[.[] | select(.user.login==\"$bot\") | .content] | join(\",\")" 2>/dev/null)
  review=$(gh api "repos/$REPO/pulls/$PR/reviews" \
    --jq "[.[] | select(.user.login==\"$bot\") | .state] | last // \"\"" 2>/dev/null)
  echo "codex: reactions=[${reaction:-none}] last_review=${review:-none}"
  case ",$reaction," in
    *",-1,"*|*",confused,"*) echo "CODEX BLOCKING: negative reaction" >&2; exit 3 ;;
  esac
  if [ "$review" = "CHANGES_REQUESTED" ]; then
    echo "CODEX BLOCKING: CHANGES_REQUESTED" >&2; exit 3
  fi
  case ",$reaction," in
    *",+1,"*|*",heart,"*|*",hooray,"*|*",rocket,"*|*",laugh,"*) echo "codex: pass (positive reaction)" ;;
    *) echo "codex: no verdict yet — resolve per verification-and-closure :: Reading the Codex verdict (do not hard-wait)" ;;
  esac
fi

exit 0
