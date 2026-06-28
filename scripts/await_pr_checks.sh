#!/usr/bin/env bash
# await_pr_checks.sh — wait for a PR's CI checks (and optionally the Codex verdict) without
# draining the shared GitHub GraphQL budget.
#
# This repo runs many concurrent agents against ONE 5,000/hr GitHub API budget; GraphQL exhausts
# first. `gh pr checks` / `gh pr view --json mergeStateStatus` are GraphQL, and a tight poll loop
# starves every other agent. This script polls the REST check-runs and classic commit-status
# endpoints only, sleeps the bulk of CI up front, and backs off >=60s on the tail.
# Contract: .codex/skills/_shared/CI_WAIT_CONTRACT.md
#
# Usage:
#   scripts/await_pr_checks.sh <PR> [--codex] [--initial-wait S] [--interval S] [--timeout S] [--sha SHA]
#   scripts/await_pr_checks.sh --help
#
# Exit codes:
#   0  CI check-runs + classic commit status all passed (with --codex, Codex also gave a positive reaction)
#   1  a required check failed
#   2  timed out before checks were confirmed complete
#   3  Codex verdict is blocking         (only with --codex)
#   4  Codex verdict unresolved — resolve per verification-and-closure before merge (only with --codex)
#   5  PR head moved during the wait — verified checks are stale; re-run (when SHA is auto-resolved)
set -uo pipefail

INITIAL_WAIT=180     # sleep before first check (~ CI p50; the `not pg` gate is the long pole)
INTERVAL=90          # backoff between checks on the tail (floored to 60)
TIMEOUT=1800         # give up after this many seconds of total polling
CHECK_CODEX=0
PR=""
SHA=""
SHA_FROM_PR=0        # 1 when SHA is auto-resolved from the PR (enables the head-drift recheck)

usage() { awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0; }

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

command -v gh >/dev/null 2>&1 || { echo "error: gh is required" >&2; exit 64; }
command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 64; }

REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
[ -n "$REPO" ] || { echo "error: could not resolve repo from git remote 'origin'" >&2; exit 64; }

# Free, rate-limit-exempt preflight — informational only.
budget=$(gh api rate_limit --jq '"core=\(.resources.core.remaining) graphql=\(.resources.graphql.remaining)"' 2>/dev/null || echo "unknown")
echo "repo=$REPO pr=$PR budget: $budget (this script uses REST core only)"

if [ -z "$SHA" ]; then
  SHA=$(gh api "repos/$REPO/pulls/$PR" --jq '.head.sha' 2>/dev/null) || true
  [ -n "$SHA" ] || { echo "error: could not resolve head SHA for PR #$PR (REST)" >&2; exit 64; }
  SHA_FROM_PR=1
fi
echo "head=$SHA"

echo "waiting ${INITIAL_WAIT}s before first check (CI runs ~4-5 min; not polling through it)..."
sleep "$INITIAL_WAIT"

# Fetch check-runs once per iteration into a single guarded response, then derive BOTH the
# pending set and the failed conclusions from it. Fail CLOSED: a fetch error, an unparseable
# body, or zero attached checks never falls through to success — it retries until the deadline,
# then times out (exit 2). The conclusion classification only runs on a response we trust.
deadline=$(( $(date +%s) + TIMEOUT - INITIAL_WAIT ))
failed=""
while :; do
  resp=$(gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" 2>/dev/null)
  rc=$?
  count=$(printf '%s' "$resp" | jq -r '.check_runs | length' 2>/dev/null)
  if [ "$rc" -ne 0 ] || ! [ "${count:-x}" -ge 0 ] 2>/dev/null; then
    echo "transient REST/parse error (rc=$rc); backing off ${INTERVAL}s..."
  elif [ "$count" -eq 0 ]; then
    echo "no check-runs attached to $SHA yet; waiting..."
  else
    pending=$(printf '%s' "$resp" | jq -r '[.check_runs[] | select(.status!="completed") | .name] | join(", ")')
    if [ -n "$pending" ]; then
      echo "still running: $pending"
    else
      # Check-runs complete — also confirm the classic combined commit status. Branch protection on
      # stable-targeted PRs requires the classic status context (strict=true); check-runs alone would
      # green-light too early (see GITHUB_GOVERNANCE_SETUP.md and the contract's manual REST path).
      sresp=$(gh api "repos/$REPO/commits/$SHA/status" 2>/dev/null); src=$?
      sstate=$(printf '%s' "$sresp" | jq -r '.state // empty' 2>/dev/null)
      stotal=$(printf '%s' "$sresp" | jq -r '.total_count // 0' 2>/dev/null)
      if [ "$src" -ne 0 ] || [ -z "$sstate" ]; then
        echo "transient status fetch error (rc=$src); backing off ${INTERVAL}s..."
      elif [ "${stotal:-0}" -gt 0 ] && [ "$sstate" = "pending" ]; then
        echo "classic commit statuses still pending; waiting..."
      else
        # Both surfaces resolved — derive failures from the SAME trusted responses (fail closed).
        failed=$(printf '%s' "$resp" | jq -r '[.check_runs[] | select(.conclusion!=null and .conclusion!="success" and .conclusion!="skipped" and .conclusion!="neutral") | "\(.name): \(.conclusion)"] | join("; ")')
        if [ "${stotal:-0}" -gt 0 ] && [ "$sstate" != "success" ]; then
          failed="${failed:+$failed; }classic commit status=$sstate"
        fi
        break
      fi
    fi
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "TIMEOUT after ${TIMEOUT}s; checks not confirmed complete (last pending: ${pending:-unknown})" >&2
    exit 2
  fi
  sleep "$INTERVAL"
done

if [ -n "$failed" ]; then
  echo "CHECKS FAILED: $failed" >&2
  exit 1
fi

# Current-SHA truth: if we resolved SHA from the PR, the head must not have moved during the wait.
# Otherwise the green we just verified is for a stale commit, and an autonomous `&& gh pr merge`
# would merge the new, unverified head. (Skipped when --sha pins an explicit commit.)
if [ "$SHA_FROM_PR" -eq 1 ]; then
  cur=$(gh api "repos/$REPO/pulls/$PR" --jq '.head.sha' 2>/dev/null)
  if [ -z "$cur" ]; then
    echo "ERROR: could not re-confirm PR head after the wait — failing closed" >&2; exit 2
  elif [ "$cur" != "$SHA" ]; then
    echo "PR HEAD MOVED during the wait: verified $SHA but head is now $cur — verified checks are stale; re-run" >&2
    exit 5
  fi
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
    *",+1,"*|*",heart,"*|*",hooray,"*|*",rocket,"*|*",laugh,"*)
      echo "codex: pass (positive reaction)"; exit 0 ;;
    *)
      echo "codex: verdict UNRESOLVED — resolve per verification-and-closure :: Reading the Codex verdict;" >&2
      echo "       do NOT auto-merge on this exit code (no hard-wait — the caller owns the ambiguous call)." >&2
      exit 4 ;;
  esac
fi

exit 0
