State: Accepted target-state decision, owner-directed 2026-10-18. Enactment is tracked by the parent Issue named below; until each slice lands, the current mechanics in the owner documents still apply.
Doc role: Decision record (ADR)
Authority: Sets the delivery flow from merge to production. Supersedes ADR-0040 §1–§2 once its prod-promotion slice is enacted; until then prod keeps tracking `main` under ADR-0040. Deployment mechanics stay owned by `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`, promotion authority by `docs/RELEASE_CHANNELS/README.md`, and test gates by `docs/TESTING.md`.
Owner: Builder System / CES boundary (delivery pipeline) with Release Channels
Temporal class: Durable architecture decision; supersede through a later ADR.
Source of truth: This ADR. Shipped behavior remains owned by the documents named above and by runtime receipts.

# ADR-0068: Continuous dev delivery — merge on risk, then dev → test → prod

**Date:** 2026-10-18
**Status:** Accepted target state (owner-directed)

## Context

The owner stated the intended flow on 2026-10-18:

> The idea of test on dev and later on test is not meant to delay merge to main. We merge on risk
> and then we create a bug if we find a problem. If no problem is found we move to test for UAT and
> then merge to prod. [...] Then we have main → dev → test → prod, but main and dev should only
> differ based on technical need. [...] There needs to be a robust mechanism that can handle a high
> throughput of PRs to dev. We can't stop development for a deploy problem.

The post-merge controller (`scripts/postmerge_dev_test.py`) already deploys one immutable image per
admitted `main` build to `dev` and then `test`, and a failed candidate does not veto later ones
(`docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md`). Three gaps let a deploy problem stop development
anyway:

- The only way to hold the pipeline was to unload the controller. On 2026-10-16 it was unloaded to
  protect an investigation (#3347), and nothing reached `dev` for two days.
- Nothing reported that the controller was absent, so the stop was silent.
- A dev failure produced a red receipt but no routed bug, so the remedy was a manual pause instead of
  a fix merged to `main`.

## Decision

### D1 — Merge on risk

A PR merges on its required PR checks only. No post-merge stage (dev deploy, heavy tests, nightly,
UAT) ever gates or reverts a merge. Problems found after merge become bug Issues and are fixed by
later PRs.

### D2 — `dev` follows `main`, latest wins

The controller deploys the newest admitted `main` build. Commits that land while a deploy runs
are batched into the next candidate rather than queued one by one. A candidate never waits behind an
older failed one. High PR throughput therefore costs dev deploys only at the rate the controller
can complete them.

### D3 — A failure files a bug; it never pauses the pipeline

A red `dev` or `test` candidate opens or updates one rolling bug Issue per channel. The bug names the
candidate SHA, the commit range since the channel's last good candidate, the failing gate, and the run
or receipt. The next candidate then proceeds as normal. The default recovery is **roll-forward**: the
fix merges to `main` and reaches `dev` as a later candidate. The controller may redeploy the last good
image automatically only when the failed candidate applied no forward-only migration. The existing
rule that automation never rolls back a database stays.

### D4 — Git refs record channel state

- `main` — merged work.
- `dev` — the last candidate with a green dev verdict, advanced by the controller. `main` and `dev`
  differ only by technical need. A deliberate hold pins `dev` with a linked Issue and is visible as
  such; it never stops merges.
- `test` — the last candidate promoted to `test` for UAT, advanced automatically after a green dev
  verdict.
- `stable` — production. It advances only from a candidate that passed `test` UAT, through the
  human-approved promotion path. This restores the gated `stable` ref of `docs/RELEASE_CHANNELS/README.md`
  and replaces ADR-0040's `main`-tracking prod once enacted.

A green dev verdict means the existing dev gates (health/version, fleet/UI smoke, isolated PG
profile) plus the deferred heavy tests (`docs/development/TEST_STRATEGY_HOT_PATH.md :: Post-merge heavy tests`) run on `dev`
after its deploy.

### D5 — Pause only the machinery, and never silently

A deploy-machinery kill switch exists for the case "the deployer itself is unsafe", not "this
candidate is broken". Engaging it requires a linked Issue and an expiry. Unloading or stopping the
controller is not a supported pause mechanism. An absent, stopped, or paused controller is itself an
alert.

### D6 — Liveness is GitHub-visible

A GitHub check turns red when `main` has a newer admitted build than the last dev verdict for longer
than a bounded grace period, or when the controller reports no heartbeat. A stopped pipeline is
therefore loud within hours, not discovered days later.

### D7 — The controller runs from pinned tooling

The controller runs from its own reviewed, pinned tooling environment, separate from candidate code,
so a bad candidate cannot crash the deployer (for example the 2026-10 controller log ending in
`ModuleNotFoundError: No module named 'app'`).

## Constraints honored

- PR workflows still receive no deployment credentials (`docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md`).
- Production keeps its target-bound forward-only migration acknowledgement and its human approval.
- No automated database rollback.
- `Unit tests (not pg)` remains the only required PR check.

## Consequences

- Development never waits on dev, test, or a deploy investigation. The cost is that a red candidate
  can sit on `dev` until a fix merges. D3's last-good redeploy narrows that window only where it is safe.
- With batching, one bug can cover several merged PRs. The commit range in the bug is the first
  triage tool; automatic bisection is a later option.
- Every agent works under D1 and D3. Agents do not pause the controller to protect their own work;
  they file or update the channel bug, or engage the D5 kill switch with an Issue and an expiry.

## Enactment

Tracked by the parent Issue linked from `docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md :: Continuous dev delivery target (ADR-0068)`.
The slices are: the liveness check (D6), automatic channel bug filing (D3), the `dev`/`test` refs and
their advancement (D4), the kill switch replacing unload-as-pause (D5), pinned controller tooling (D7),
the safe last-good redeploy (D3), heavy tests on `dev` (D4), and prod promotion from `test` to
`stable` (D4, superseding ADR-0040 §1–§2).

## References

- ADR-0040 (prod promotion ref `main` interim)
- `docs/plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: CI deployment automation posture`
- `docs/RELEASE_CHANNELS/README.md :: Promotion model`
- `docs/development/TEST_STRATEGY_HOT_PATH.md :: Post-merge heavy tests`
- #6154, #6158, #6170, #3347
