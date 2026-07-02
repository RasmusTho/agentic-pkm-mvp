State: Shared skill contract. Canonical procedure for waiting on CI checks (and the optional `--codex` verdict path, inactive as the default gate).

# CI Wait Contract

Single source for **how** to wait on PR checks — and, for opt-in `--codex` callers, the inactive Codex review verdict — without draining the
shared GitHub API budget. Skills that wait before handoff or merge (`verification-and-closure`,
`pr-integration`, `deliver-issue-set`) reference this contract by name instead of carrying inline
poll loops. The shared helper is `app.dispatcher.poll_backoff`; it owns interval + cap +
exponential backoff semantics, honors `Retry-After` and `x-ratelimit-reset`, and resolves Codex
evidence with one combined query where possible. This contract is the *how*; the *when/whether to
merge* stays in those skills. Governs `AGENTS.md :: Parallel-agent execution` (shared-budget
awareness) at the command level.

## Why this exists

Many agents run against this repo at once and share **one 5,000/hr GitHub API budget**. GraphQL has
its own sub-bucket that **exhausts first**. `gh pr checks`, `gh pr view --json mergeStateStatus`, and
`gh pr view/list` are **GraphQL**. A tight poll loop (e.g. every 30s while a ~4 min test gate runs)
drains GraphQL to zero and stalls every other agent's reads — a recurring, system-wide failure (hit
2026-06-28 on PR #2596). The wait itself is unavoidable; the *drain* is not.

## Rules

1. **Never tight-poll, and never poll GraphQL for check state.** Use REST (`gh api`) only.
2. **Wait the bulk first, then check.** CI on this repo runs ~4–5 min wall-clock (the `not pg` test
   gate is the long pole). Sleep most of that *before* the first check instead of polling through it.
3. **Back off ≥ 60–120s** between checks on the tail. One PR's wait must not starve the shared bucket.
4. **Preflight the free endpoint.** `gh api rate_limit` is **exempt** (does not count) — read it before
   assuming exhaustion, and compare `.graphql.remaining` vs `.core.remaining`.
5. **`verification-and-closure`'s default merge gate is now a local `code-review` subagent run, not
   Codex** (see `verification-and-closure` :: *Running the local review gate*) — CI wait no longer
   needs `--codex` by default. `--codex` remains available below for callers that still want the
   Codex verdict resolved; if used, Codex is variable and may stall — never hard-wait on it, and
   resolve it on the same cadence as CI with the stall escape hatch (see `verification-and-closure` ::
   *Reading the Codex verdict*, inactive as the default gate but kept for `--codex` callers).
6. **Use the shared helper, preferably through the blessed script.** Do not hand-roll CI or Codex
   wait loops; `scripts/await_pr_checks.sh` delegates shared backoff/verdict behavior to
   `app.dispatcher.poll_backoff`.

## Blessed path

```bash
scripts/await_pr_checks.sh <PR>            # wait for required check-runs, REST-only, calibrated backoff
scripts/await_pr_checks.sh <PR> --codex    # also resolve the Codex verdict with one combined query
scripts/await_pr_checks.sh --help          # flags: --initial-wait, --interval, --timeout, --sha
```

`--sha` pins a commit for inspection and is **not** a merge gate (PR head-drift is not verified); omit
it for the merge-gating default, where the head is auto-resolved and re-checked before success.

It auto-detects the repo from the git remote, resolves the PR head SHA via REST, sleeps `--initial-wait`
(default 180s) before the first check, then polls the REST **check-runs and classic commit-status**
endpoints every `--interval` (default 90s, floor 60s) until all complete or `--timeout` (default 1800s),
failing **closed** on any fetch error (an unverifiable state never reports success). Exit codes:

- `0` — CI passed (with `--codex`, Codex also passed)
- `1` — a required check failed
- `2` — timed out before checks were confirmed complete
- `3` — Codex verdict is blocking (only with `--codex`)
- `4` — Codex verdict unresolved (only with `--codex`) — resolve before merge
- `5` — the PR head moved during the wait (when SHA is auto-resolved) — verified checks are stale; re-run

The CI wait never issues a GraphQL check-state call. For an autonomous `&& gh pr merge`, run
`scripts/await_pr_checks.sh <PR>` (no `--codex`) and require exit `0`, then run the local review gate
per `verification-and-closure` :: *Running the local review gate* before merging. `--codex` is
retained for callers that still want it: with `--codex`, exit `4` means stop and resolve the Codex
verdict yourself per `verification-and-closure` :: *Reading the Codex verdict* (inactive as the
default gate, do not hard-wait, and do not auto-merge on an unresolved verdict). The
`--codex` verdict is resolved by `python3 -m app.dispatcher.poll_backoff codex-verdict`, which queries
reactions, reviews, pull comments, and issue comments in one combined GraphQL request where GitHub
supports it. Findings / changes-requested are matched to the exact SHA where commit-specific evidence
is available.
`verification-and-closure` remains the merge authority for genuinely ambiguous calls; the script gates
the *wait* and reports a head-pinned verdict — it does not replace the skill's judgment.

## Manual REST commands (when the script is unavailable)

```bash
REPO=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
SHA=$(gh api "repos/$REPO/pulls/$PR" --jq '.head.sha')          # REST: PR head SHA

# Incomplete check-runs on the head SHA (empty output = all complete):
gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" \
  --jq '.check_runs[] | select(.status!="completed") | .name'

# Combined commit status (success / pending / failure):
gh api "repos/$REPO/commits/$SHA/status" --jq '.state'

# Any failed/cancelled/timed-out check-runs:
gh api "repos/$REPO/commits/$SHA/check-runs?per_page=100" \
  --jq '.check_runs[] | select(.conclusion!=null and .conclusion!="success" and .conclusion!="skipped" and .conclusion!="neutral") | "\(.name): \(.conclusion)"'

# Mergeability (REST, not GraphQL):
gh api "repos/$REPO/pulls/$PR" --jq '.mergeable, .mergeable_state'

# Codex verdict — primary signal can be an emoji reaction or a review.
# Use the helper so the verdict surfaces are collapsed into one query where possible.
python3 -m app.dispatcher.poll_backoff codex-verdict --repo "$REPO" --pr "$PR" --sha "$SHA"
```

Sleep between iterations with `sleep 90` (or longer); do not drop below 60s.

## When GraphQL is already at 0

REST core almost always still has quota, so check-run waiting and most mutations proceed unaffected.
Only fall back to a scheduled wake-up until the `rate_limit` reset epoch if **REST core** is also at 0.
See `reference_gh_rate_limit_routing` for the full read/write/merge REST routing table.
