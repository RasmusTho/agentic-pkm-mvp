#!/usr/bin/env bash
# await_pr_checks.sh — wait for a PR's CI checks (and optionally the Codex verdict) without
# draining the shared GitHub GraphQL budget.
#
# This repo runs many concurrent agents against ONE 5,000/hr GitHub API budget; GraphQL exhausts
# first. `gh pr checks` / `gh pr view --json mergeStateStatus` are GraphQL, and a tight poll loop
# starves every other agent. This script polls the REST check-runs and classic commit-status
# endpoints only, sleeps the bulk of CI up front, and backs off >=60s on the tail. The shared
# Python helper owns bounded backoff semantics and the single-query Codex verdict resolver.
# Contract: .codex/skills/_shared/CI_WAIT_CONTRACT.md
#
# Usage:
#   scripts/await_pr_checks.sh <PR> [--codex] [--repo owner/name] [--initial-wait S] [--interval S] [--timeout S] [--sha SHA]
#   scripts/await_pr_checks.sh --help
#
# --sha pins a commit for inspection and is NOT a merge gate (PR head-drift is not verified). Omit
# --sha for the merge-gating default: the head is auto-resolved and re-checked before success, the
# PR must not be mergeable_state=dirty, and the expected required check contexts must be PRESENT
# on the head before an all-green short list can count as success (#4605: a dirty PR schedules no
# pull_request workflows, yet CodeQL can still attach green head-ref check-runs).
#
# Exit codes:
#   0  CI check-runs + classic commit status all passed (with --codex, Codex also passed)
#   1  a required check failed
#   2  timed out before checks were confirmed complete
#   3  Codex verdict is blocking         (only with --codex)
#   4  Codex verdict unresolved — resolve per verification-and-closure before merge (only with --codex)
#   5  PR head moved during the wait — verified checks are stale; re-run (when SHA is auto-resolved)
#   6  PR is mergeable_state=dirty — pull_request workflows will not schedule; fix conflicts, re-run (merge-gating mode)
#   7  required check contexts absent from the head — absence is NOT success (merge-gating mode)
set -uo pipefail

INITIAL_WAIT=180     # sleep before first check (~ CI p50; the `not pg` gate is the long pole)
INTERVAL=90          # backoff between checks on the tail (floored to 60)
TIMEOUT=1800         # give up after this many seconds of total polling
CHECK_CODEX=0
PR=""
SHA=""
SHA_FROM_PR=0        # 1 when SHA is auto-resolved from the PR (enables the head-drift recheck)
REPO_FLAG=""

usage() { awk 'NR>1 && /^#/{sub(/^# ?/,""); print; next} NR>1{exit}' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --help|-h) usage ;;
    --codex) CHECK_CODEX=1; shift ;;
    --initial-wait) INITIAL_WAIT="$2"; shift 2 ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --sha) SHA="$2"; shift 2 ;;
    --repo) REPO_FLAG="$2"; shift 2 ;;
    -*) echo "unknown flag: $1" >&2; exit 64 ;;
    *) PR="$1"; shift ;;
  esac
done

[ -n "$PR" ] || { echo "error: PR number required (see --help)" >&2; exit 64; }
[ "$INTERVAL" -ge 60 ] 2>/dev/null || INTERVAL=60   # never drop below 60s on the shared bucket

command -v gh >/dev/null 2>&1 || { echo "error: gh is required" >&2; exit 64; }
command -v jq >/dev/null 2>&1 || { echo "error: jq is required" >&2; exit 64; }

# Resolve the repo: --repo flag, then $GH_REPO, then the git 'origin' remote. (Avoid `gh repo view`,
# which is GraphQL — the bucket this script exists to spare.) A remote-less worktree can still take the
# blessed REST path via --repo/GH_REPO instead of falling back to a GraphQL-draining manual poll.
REPO="${REPO_FLAG:-${GH_REPO:-}}"
[ -n "$REPO" ] || REPO=$(git remote get-url origin 2>/dev/null | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
[ -n "$REPO" ] || { echo "error: could not resolve repo — pass --repo owner/name or set GH_REPO (no 'origin' remote found)" >&2; exit 64; }

# Free, rate-limit-exempt preflight — informational only.
budget=$(gh api rate_limit --jq '"core=\(.resources.core.remaining) graphql=\(.resources.graphql.remaining)"' 2>/dev/null || echo "unknown")
echo "repo=$REPO pr=$PR budget: $budget (this script uses REST core only)"

# Dirty-PR fail-closed gate (#4605, LearningSignal lrn_20260729154323_f134857a, PR #4354): a
# mergeable_state=dirty PR cannot compute refs/pull/<n>/merge, so the repo's pull_request
# workflows NEVER schedule for it — while CodeQL can still attach green check-runs from
# refs/pull/<n>/head. Waiting on such a head can only ever see unrelated green checks, so the
# wait must refuse up front instead of reporting a false green. Merge-gating mode only.
fail_if_dirty() {
  if [ "$1" = "dirty" ]; then
    echo "PR NOT MERGEABLE (mergeable_state=dirty): PR #$PR cannot compute its merge ref, so pull_request workflows will not schedule." >&2
    echo "Head-ref check-runs (e.g. CodeQL) are NOT the required CI suite — refusing to wait toward a false green (CI_WAIT_CONTRACT.md :: Rules)." >&2
    echo "Resolve the conflict (rebase onto the base branch, push) and re-run." >&2
    exit 6
  fi
}

BASE_REF=""
if [ -z "$SHA" ]; then
  pr_resp=$(gh api "repos/$REPO/pulls/$PR" 2>/dev/null) || true
  SHA=$(printf '%s' "$pr_resp" | jq -r '.head.sha // empty' 2>/dev/null)
  [ -n "$SHA" ] || { echo "error: could not resolve head SHA for PR #$PR (REST)" >&2; exit 64; }
  BASE_REF=$(printf '%s' "$pr_resp" | jq -r '.base.ref // empty' 2>/dev/null)
  SHA_FROM_PR=1
  # mergeable_state=unknown is a transient compute state and passes through; the
  # required-check presence gate below is the backstop while GitHub recomputes.
  fail_if_dirty "$(printf '%s' "$pr_resp" | jq -r '.mergeable_state // "unknown"' 2>/dev/null)"
fi
echo "head=$SHA"
if [ "$SHA_FROM_PR" -eq 0 ]; then
  # --sha pins a specific commit for inspection; it is deliberately NOT a merge gate, because the
  # PR head may differ from (or move away from) the pinned SHA, so a `--sha X && gh pr merge` would
  # merge an unverified head. The merge-gating mode is the default (auto-resolved head + drift
  # check + dirty-PR and required-check presence gates, which --sha mode deliberately skips).
  echo "note: --sha mode is diagnostic, NOT a merge gate (PR head-drift is not verified)." >&2
  echo "      For an autonomous merge gate, omit --sha so the head is resolved and re-checked." >&2
fi

# Required-check presence (#4605): success must mean "the required suite ran green", never "the
# few checks that happened to attach are green". Resolution order for the expected set
# (documented in CI_WAIT_CONTRACT.md :: Rules):
#   1. Live branch-protection contexts for the PR's base branch (REST; needs admin — best effort).
#   2. Documented fallback set per base branch from docs/development/GITHUB_GOVERNANCE_SETUP.md:
#      stable -> smoke, smoke-docker, pr-contract; otherwise (main default) -> Unit tests (not pg).
# This is the repo-required set, not "every optional check": absence of an arbitrary optional
# check never fails the wait. Merge-gating mode only; --sha diagnostic mode skips it.
REQUIRED_CHECKS=""
REQUIRED_SOURCE=""
if [ "$SHA_FROM_PR" -eq 1 ]; then
  base="${BASE_REF:-main}"
  prot=$(gh api "repos/$REPO/branches/$base/protection/required_status_checks" 2>/dev/null) || prot=""
  if [ -n "$prot" ]; then
    REQUIRED_CHECKS=$(printf '%s' "$prot" | jq -r '((.contexts // []) + [.checks // [] | .[].context]) | unique | .[]' 2>/dev/null)
  fi
  if [ -n "$REQUIRED_CHECKS" ]; then
    REQUIRED_SOURCE="branch-protection:$base"
  else
    if [ "$base" = "stable" ]; then
      REQUIRED_CHECKS=$(printf 'smoke\nsmoke-docker\npr-contract')
    else
      REQUIRED_CHECKS='Unit tests (not pg)'
    fi
    REQUIRED_SOURCE="documented-fallback:$base"
  fi
  echo "required checks ($REQUIRED_SOURCE): $(printf '%s\n' "$REQUIRED_CHECKS" | paste -sd ',' - | sed 's/,/, /g')"
fi

echo "waiting ${INITIAL_WAIT}s before first check (CI runs ~4-5 min; not polling through it)..."
sleep "$INITIAL_WAIT"

# Dedupe rule (see CI_WAIT_CONTRACT.md): GitHub keeps every check-run record for a head SHA, so a
# re-run after a body/config fix leaves BOTH the stale failed record and the newer successful one
# for the same check NAME on the same SHA. Classifying on the raw list fails closed on a check that
# has already gone green on its latest run (observed live on PR #2915 and #2924: `pr-contract`
# failure+success on one SHA). Before pending/conclusion classification, keep only the LATEST
# record per check-run `name` — ranked by `started_at` (fallback `id` on a tie/missing timestamp) —
# and classify off that deduped set only. A genuinely failed LATEST record still fails closed.
DEDUPE_LATEST_PER_NAME='
  [.check_runs[]]
  | group_by(.name)
  | map(sort_by([(.started_at // ""), .id]) | last)
'

# Fetch check-runs once per iteration into a single guarded response, then derive BOTH the
# pending set and the failed conclusions from the deduped (latest-per-name) set. Fail CLOSED: a
# fetch error, an unparseable body, or zero attached checks never falls through to success — it
# retries until the deadline, then times out (exit 2). The conclusion classification only runs on
# a response we trust.
deadline=$(( $(date +%s) + TIMEOUT - INITIAL_WAIT ))
failed=""
missing_required=""
while :; do
  missing_required=""
  resp=$(gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" 2>/dev/null)
  rc=$?
  count=$(printf '%s' "$resp" | jq -r '.check_runs | length' 2>/dev/null)
  if [ "$rc" -ne 0 ] || ! [ "${count:-x}" -ge 0 ] 2>/dev/null; then
    echo "transient REST/parse error (rc=$rc); backing off ${INTERVAL}s..."
  elif [ "$count" -eq 0 ]; then
    echo "no check-runs attached to $SHA yet; waiting..."
  else
    pending=$(printf '%s' "$resp" | jq -r "${DEDUPE_LATEST_PER_NAME} | [.[] | select(.status!=\"completed\") | .name] | join(\", \")")
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
        # Both surfaces resolved — derive failures from the SAME trusted responses (fail closed),
        # classifying off the latest record per check-run name only.
        failed=$(printf '%s' "$resp" | jq -r "${DEDUPE_LATEST_PER_NAME} | [.[] | select(.conclusion!=null and .conclusion!=\"success\" and .conclusion!=\"skipped\" and .conclusion!=\"neutral\") | \"\(.name): \(.conclusion)\"] | join(\"; \")")
        if [ "${stotal:-0}" -gt 0 ] && [ "$sstate" != "success" ]; then
          failed="${failed:+$failed; }classic commit status=$sstate"
        fi
        if [ -n "$failed" ]; then
          break
        fi
        # Required-check presence gate (#4605, merge-gating mode only): an all-green short list is
        # not success unless every expected required context is actually PRESENT on this head
        # (check-run names + classic status contexts). A required workflow can attach late, so
        # absence keeps waiting inside the budgeted backoff; it only becomes terminal (exit 7) at
        # the deadline — never a silent fall-through to success.
        if [ "$SHA_FROM_PR" -eq 1 ] && [ -n "$REQUIRED_CHECKS" ]; then
          present=$( { printf '%s' "$resp" | jq -r "${DEDUPE_LATEST_PER_NAME} | .[].name" 2>/dev/null; \
                       printf '%s' "$sresp" | jq -r '.statuses // [] | .[].context' 2>/dev/null; } )
          missing_required=$(printf '%s\n' "$REQUIRED_CHECKS" | while IFS= read -r req; do
            [ -n "$req" ] || continue
            printf '%s\n' "$present" | grep -Fxq -- "$req" || printf '%s\n' "$req"
          done)
          if [ -n "$missing_required" ]; then
            echo "required checks not attached to $SHA yet: $(printf '%s\n' "$missing_required" | paste -sd ',' - | sed 's/,/, /g'); waiting..."
          else
            break
          fi
        else
          break
        fi
      fi
    fi
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    if [ -n "$missing_required" ]; then
      echo "REQUIRED CHECKS MISSING on $SHA: $(printf '%s\n' "$missing_required" | paste -sd ',' - | sed 's/,/, /g') (expected set source: $REQUIRED_SOURCE)" >&2
      echo "Absence of a required check is NOT success — the attached checks may be head-ref-only (e.g. CodeQL on a PR whose pull_request workflows never scheduled)." >&2
      echo "Failing closed; see CI_WAIT_CONTRACT.md :: Rules (#4605)." >&2
      exit 7
    fi
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
  cur_resp=$(gh api "repos/$REPO/pulls/$PR" 2>/dev/null) || true
  cur=$(printf '%s' "$cur_resp" | jq -r '.head.sha // empty' 2>/dev/null)
  if [ -z "$cur" ]; then
    echo "ERROR: could not re-confirm PR head after the wait — failing closed" >&2; exit 2
  elif [ "$cur" != "$SHA" ]; then
    echo "PR HEAD MOVED during the wait: verified $SHA but head is now $cur — verified checks are stale; re-run" >&2
    exit 5
  fi
  # The base can advance mid-wait and turn the PR dirty; green head checks would then gate a PR
  # GitHub itself refuses to merge, so re-assert mergeability from the same re-fetch (#4605).
  fail_if_dirty "$(printf '%s' "$cur_resp" | jq -r '.mergeable_state // "unknown"' 2>/dev/null)"
fi
echo "all required checks passed on $SHA"

if [ "$CHECK_CODEX" -eq 1 ]; then
  # Resolve the verdict with one combined GraphQL query through the shared helper instead of
  # re-reading reactions, reviews, issue comments, and pull comments as separate calls.
  head_ts=$(gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" --jq '[.check_runs[].started_at | select(.!=null)] | min // ""' 2>/dev/null) || head_ts=""
  codex_args=(codex-verdict --repo "$REPO" --pr "$PR" --sha "$SHA")
  if [ -n "$head_ts" ]; then
    codex_args+=(--head-started-at "$head_ts")
  fi
  codex_stderr_file=$(mktemp)
  codex_json=$(python3 -m app.dispatcher.poll_backoff "${codex_args[@]}" 2>"$codex_stderr_file")
  codex_rc=$?
  codex_stderr=$(cat "$codex_stderr_file" 2>/dev/null); rm -f "$codex_stderr_file"
  if [ "$codex_rc" -eq 0 ]; then
    echo "codex: $codex_json"; exit 0
  elif [ "$codex_rc" -eq 3 ]; then
    echo "CODEX BLOCKING for $SHA: $codex_json" >&2; exit 3
  elif [ "$codex_rc" -eq 4 ]; then
    echo "codex: unresolved for $SHA: $codex_json" >&2
    echo "       do NOT auto-merge on this exit code (no hard-wait — the caller owns the ambiguous call)." >&2
    exit 4
  fi
  # Surface the helper's stderr so a GitHubKillSwitchActive skip is
  # distinguishable from a genuinely failed query (both fail closed).
  echo "codex: combined verdict query failed — failing closed" >&2
  if [ -n "$codex_stderr" ]; then
    printf '%s\n' "$codex_stderr" | sed 's/^/       /' >&2
  fi
  exit 2
fi

exit 0
