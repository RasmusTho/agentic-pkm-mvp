---
name: verification-and-closure
description: "Verify delivered slice work against its governing contract, merge the PR when satisfied, and close the loop truthfully."
---

# Verification and Closure

You are the delivery verification and feedback-loop agent for repo-first, docs-as-code work.

Use [`docs/development/PR_HOT_PATH.md`](../../../docs/development/PR_HOT_PATH.md) for the default PR delivery shape.
Use [`docs/development/PR_ESCALATION_PATHS.md`](../../../docs/development/PR_ESCALATION_PATHS.md) only when the PR hot path says an escalation trigger applies.
Use [`docs/development/PARENT_ISSUE_CLOSURE.md`](../../../docs/development/PARENT_ISSUE_CLOSURE.md) only when parent closure is relevant, especially for the final child slice or an explicit closure task.

⚠️ **CRITICAL: All lifecycle state changes (labels, Project Status, Issue closure, PR merge) must be executed using explicit commands and verified. Do not describe these changes.**
Test/check failures must be classified, not dismissed as merely "out of scope" when they are actually blocking.

## Your Job

- verify the implementation against the governing slice or feature contract
- validate tests, docs, and writeback quality
- ensure shipped truth moved to the right owner docs
- ensure roadmap or plan wording no longer falsely reads as pending
- detect false backlog or project states
- honor automation-driven `Done` projection first, and only fallback-set `Done` when needed
- merge the PR when the delivery contract is satisfied
- close exactly the PR's authenticated closing issues and set their Project Status to `Done`; keep
  a governing parent open when it is not itself named by a closing keyword
- release the dispatcher lease if one was claimed
- unblock dependent issues when the delivered work truly satisfies them

## Inputs to Inspect

- governing GitHub Issue
- the exact `closing_issues` and cumulative `supporting_issues` authority from a v2 dispatched context;
  on a manual run, derive the same sets from the live exact-head PR body
- parent feature issue when the governing issue is a child slice
- linked PR
- related closed PRs
- changed files
- `Source Anchors`
- owner docs
- `docs/architecture/SBS_OPERATING_MODEL.md` when the work has Product/Runtime SBS impact, Builder
  System impact, or a boundary between the two
- roadmap / status / plan docs
- CI results
- merge state if already merged
- current `origin/main` / target-base reachability for any resumed, chained, or review-repair work

## Pre-API startup failure classification

When a validation attempt fails before the API starts accepting requests (for example, before the
service listens, reports ready, or can answer its first API health check), classify the failure first
as **channel-bootstrap/configuration work**, not as a verified feature failure. Preserve a concrete,
redacted startup classification and determine whether the failure is in deploy environment
selection, Compose wiring, mounts, channel binding, or another bootstrap prerequisite. Evidence in
Issues, PRs, BuilderOps, and receipts may name variables and boolean/path-class results only; never
include raw paths, vault names, environment values, DSNs, secrets, or raw startup/Compose output.

- Do not mark the feature acceptance criterion failed, delivered, or impossible solely from a
  pre-API startup failure. Its feature proof is still unverified.
- If the startup evidence implicates the changed feature path after bootstrap/configuration is known
  good, reclassify it as a feature failure and repair it through the governing Issue.
- If a small, source-authorized bootstrap/configuration remediation exists, route it through
  `deliver-issue-set :: No-progress final gate`: create or repair a strict Issue with `Verify:`
  targets, claim or continue that next pickup, and resume delivery. Do not end with a blocker report.
- For a vault-binding remediation, require `owner-decision-brief :: Local vault-binding preflight`
  before creating, repairing, claiming, or continuing the Issue, even when no owner ask follows.
- Escalate only when the bootstrap evidence establishes a genuine human-authority need; otherwise use
  the existing issue-maintenance and delivery paths. This classification does not authorize deploy,
  image, pin, or runtime changes by itself.

## Validation Rules

- Compare code and docs to the governing issue's `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, and `Suggested Validation`
- Verify the PR's Product/Runtime System vs Builder System vs boundary classification. Product work
  must satisfy the SBS impact and owner-doc path; Builder work must route through the Builder System
  boundary/artifact map; boundary work must name and satisfy both sides.
- Run the exact `Suggested Validation` commands where possible
- Add focused extra checks if the touched surface obviously needs them
- For every AC, resolve the declared `Verify:` target on the current PR head SHA
- If a behavioral `Verify:` test is missing, skipped, xfailed, or excluded from the CI suite that ran, do not treat the AC as satisfied
- If a non-behavioral `Verify:` target is absent, do not merge until the writeback exists
- If any AC lacks a `Verify:` marker, route through issue maintenance before proceeding
- Verify owner-doc writeback if shipped behavior or contracts changed and acceptance is complete
- Verify Builder System work did not claim runtime/user memory or Product MEM/HKA authority unless a
  Product System authority path is present in the issue/PR evidence.
- Verify roadmap or plan wording was cleaned up if the item is now delivered
- Verify no duplicate `planned` and `shipped` statements remain active at once
- Verify the BuilderOps routing outcome per tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`):
  Tier 2+ PR bodies must carry the routing outcome; on Tier 1 (docs/governance lane) PRs a missing
  `## BuilderOps Routing` section means `none` and does not block merge. At every tier, unresolved
  learning, docs freshness, roadmap execution, promotion, projection, or receipt material must be
  represented by a BuilderOps record, a bounded GitHub Issue, or an explicit `none` reason
- Verify project lifecycle state still makes sense
- Verify closed terminal PR cards do not remain blank in the Project
- For terminal projection planning, a caller may generate the local dry-run plan
  `python3 -m app.builderops builderops epic-run-state lifecycle-plan --transition done --issue-file <file> --pr-file <file> --json`.
  The plan is advisory data only: it names required reads, proposed label/Project/PR writes, and
  verification reads, while performing no GitHub, Project, dispatcher, run-state, or agent-spawn
  mutation. Live merge, issue closure, label removal, and Project `Done` correction remain owned by
  this skill's explicit commands and verification steps.
- Verify review-feedback repairs are present on the target base branch before treating them as closed; a side branch or intermediate PR is not enough unless the fixing commit is reachable from the final merge target. [base-branch-truth]
- Run GitHub GraphQL `reviewThreads` closure checks only when a review-thread closure trigger is present: a review-fix or direct-repair PR, a PR body or source anchor that names prior review feedback, a terminal issue/PR closure audit, or known unresolved review feedback. Preserve the lightweight hot path for ordinary PRs with no trigger. [review-thread-closure]
- When a review-thread closure trigger applies, reply on and resolve or explicitly disposition the
  original review thread before final closure: P0/P1 repairs name the fixing PR or merge commit, P2
  deferrals name their durable defect Issue, and P3 observations may be closed as informational.
  [review-thread-closure]
- On resume or recovery, re-check branch, `origin/main`, relevant merged PRs, and expected implementation files before continuing publication, reimplementation, or closure. [post-resume-current-state-gate]
- If the work is a slice under a larger feature, keep post-merge validation evidence on the parent issue
- If post-merge validation advanced but acceptance is still pending, record the new evidence on the parent issue body or comments
- If work is incomplete, do not close the loop falsely; create a bounded follow-up Issue instead
- Treat governing identity and closure identity as separate authority. Re-read the exact-head PR
  body immediately before merge and again after merge; require it to reproduce the dispatched
  `governing_issue`, `closing_issues`, and `supporting_issues`. Close only `closing_issues`. When the
  governing issue is absent from `closing_issues`, leave it open, append the child-delivery and
  parent-validation evidence there, and evaluate parent closure only through
  `docs/development/PARENT_ISSUE_CLOSURE.md`. `supporting_issues` preserves the non-governing
  evidence set, but only its `closing_issues` subset grants closure; `Refs` never do.

## Direct Repair PRs

- For issue-backed PRs, close the exact closing issues and update the governing issue; these are the
  same lifecycle mutation only when the governing identity is itself in `closing_issues`.
- For direct repair PRs, verify the `Direct Repair` block instead of issue ACs.
- Do not create an Issue after the fact solely for a bounded direct repair.

## Verification Modes

- Issue-backed PR:
  - verify the governing issue-set contract and every closing issue's ACs
  - close/project `Done` for exact closing issues after merge; update an unclosed governing parent
    with validation evidence without projecting it `Done`
- Direct repair PR:
  - verify the `Direct Repair` block and `Validation`
  - do not require issue ACs
  - do not close or mutate a governing Issue
  - write a direct repair delivery receipt instead

## Merge Rules

Verification owns the merge decision.

For autonomous delivery, run the full gate chain unattended per `AGENTS.md :: Agency default`: wait for required checks and repo-standard checks that cover the PR to go green, classify any red check before merge, and resolve the local review gate — do not ask the owner to babysit. The prerequisites below are never waived (an unprotected branch or non-required GitHub check does not relax them); only the human watching is removed.

Wait **how** matters for CI: follow `_shared/CI_WAIT_CONTRACT.md` — use the shared `app.dispatcher.poll_backoff` helper through `scripts/await_pr_checks.sh <PR>` (no `--codex`; the review gate now runs locally per `Running the local review gate` below, not through the shared verdict poller), REST check-runs only, interval + cap + exponential backoff, honor `Retry-After` and x-ratelimit-reset headers, sleep the bulk of CI up front, and back off ≥60–120s. Never tight-poll `gh pr checks` or `gh pr view --json mergeStateStatus`; they are GraphQL and drain the budget shared by every concurrent agent.

Prerequisites for merge:

- current SHA truth is intact
- required checks and repo-standard checks that cover the changed surface are green on the current head SHA
- any red check that covers the changed surface is a hard stop until fixed, rerun green, or explicitly classified as unrelated by evidence; this includes `Unit tests (not pg)` even when branch protection does not require it
- no unresolved P0/P1 blocking review comments remain
- the local review gate is resolved (see `Running the local review gate` below, including
  `Severity routing` and `Re-triggering after a fix`) — P0/P1 findings must be fixed and
  re-verified, every P2 must carry its durable deferred-defect reference and review-thread
  disposition, and P3 observations may remain informational; a fix alone, without the required
  re-verification, does not satisfy a P0/P1 prerequisite
- when a review-thread closure trigger applies, no addressed review thread remains unresolved or
  lacks the required reply: a fixing PR/merge commit for P0/P1, or the deferred-defect Issue for P2
- no scope drift remains
- the PR fits one of the two verification modes above
- if issue-backed, every exact closing issue's acceptance criteria and `Verify:` targets are
  satisfied on the current head SHA
- when a distinct governing parent is not named for closure, validate it as the issue-set contract:
  batch authorization, child/scope map, shared constraints, source anchors, validation path, and
  exact governing/closing/supporting identities must agree; unfinished feature-level ACs on that
  open parent do not block delivery of fully verified closing children, and the parent is neither
  projected `Done` nor closed merely because the PR merges
- if direct repair, the `Direct Repair` block and `Validation` are satisfied on the current head SHA
- if the direct repair expands beyond bounded scope, stop and require, create, or link an issue before merge

### Running the local review gate 🤖

The PR review gate runs locally via the built-in `/code-review` skill instead of waiting on an
external GitHub-native reviewer bot. Run it once the PR's required and relevant repo-standard checks are green (per
`_shared/CI_WAIT_CONTRACT.md`, without `--codex`) and before merge:

- This section is an explicit repo-local authorization for any delivery or closure agent to spawn the
  `/code-review` review agent when it is resolving the mandatory local review gate for a PR. The
  agent does not need separate owner confirmation for this gate, because the reviewer is required by
  the closure contract. This authorization is narrow: it covers the independent review gate only, not
  arbitrary delegation, implementation workers, exploratory subagents, or recursive fan-out.
- Invoke `/code-review` (the code-reviewer subagent) against the PR's diff, with `--comment` so
  findings post as inline PR comments — this keeps the review visible on the PR itself, matching the
  old externally-visible verdict.
- Effort level follows `AGENTS.md :: Total Cost of Development` — default to `medium`/`high` per the
  PR's risk; escalate to `high`-`max` for security/data/migration/auth/concurrency/external-API
  surfaces per the TCD model+reasoning policy.
- Run the reviewer as a fresh subagent with no memory of the implementation reasoning, so it verifies
  independently rather than rubber-stamping its own prior work.

Resolve the verdict:

- **Pass** — the run reports no findings, or it has no unresolved P0/P1 finding and every P2/P3
  finding has been dispositioned per `Severity routing` below.
- **Blocking** — at least one P0/P1 finding remains unresolved. Only P0/P1 findings block merge or
  enter repair and re-review.
- Record the run's outcome (clean / findings-fixed / nonblocking-findings-dispositioned) in the
  delivery receipt so the gate is auditable after merge.
- Do not block indefinitely on a stalled or failed review run: if the reviewer subagent cannot complete
  (tool failure, timeout, repeated crash), classify the stop under
  `AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Escalation classifier`, use bounded backoff or a
  `blocked_technical` receipt, and preserve the merge block. A technical outage never creates a
  CI/review/merge waiver. Route through `owner-decision-brief` only when the classifier finds an
  explicit authority category; that decision does not relax the gate.

#### Severity routing

Every review finding must be assigned exactly one severity before merge routing. Severity controls
the disposition; there is no valid `blocking P2` category.

- **P0** — critical correctness or safety failure with immediate, severe impact. It blocks merge and
  enters the repair/re-review loop.
- **P1** — material correctness, contract, or safety failure. It blocks merge and enters the
  repair/re-review loop.
- **P2** — a real defect whose risk is accepted for this PR and deferred to bounded follow-up. Leave
  the PR code unchanged for that finding, invoke the existing
  `.codex/skills/bug-to-issue/SKILL.md` intake path to create or update durable defect evidence,
  mark the finding `deferred` in the review receipt, and reply on the original review finding/thread
  with the Issue reference. Once that reference is live, the finding is non-blocking and allows
  merge for that finding without another review round.
- **P3** — informational advice, style guidance, or a non-defect suggestion. Record it when useful;
  it does not block merge, require defect intake, or trigger another review round.

The following protected findings must be P0 or P1, never P2: data loss or corruption; source,
vault, or authority-integrity violations; secrets, authentication, or authorization failures;
migration durability failures; concurrency or multi-writer safety failures; irreversible or
external side effects without the required authority; false-green CI, receipts, merge, or closure
evidence; and any failed governing acceptance criterion, `Verify:` target, contract, or closure
gate. When the evidence is insufficient to distinguish a protected failure from a true P2, the
review is inconclusive and the merge block remains while evidence is recovered.

P2/P3 findings never consume repair attempts, trigger mechanism convergence, or count toward the
low-convergence circuit breaker. A reviewer remains independent, current-SHA CI remains mandatory,
and issue acceptance/`Verify:`, authority, verified-merge, and closure gates remain fail-closed
regardless of finding severity.

The imported `pr-integration` skill's legacy `cheap fix` shorthand is not an independent review
severity or an exception to this routing. Per its required `PR_HOT_PATH.md` classification, read
`cheap fix`, `review-feedback repair`, and `fixing commit` as P0/P1 blocking-repair concepts only.
They do not apply to P2/P3. If a secondary workflow's shorthand cannot represent all four
severities, this section and `PR_HOT_PATH.md :: Review feedback triage` govern.

##### Dispatcher receipt compatibility

The current `verification_closer_receipt` / `VerificationAgentLoop` contract can durably represent
only `blocking` and `clean` review events; it has no lossless P2 disposition or deferred-Issue
binding. Do not encode a P2-bearing review as `clean`, place an Issue URL in an otherwise
unvalidated `receipt_ids` list, or emit a dispatcher `delivered` receipt for it. Any of those would
create false-green closure evidence and therefore be a protected P1 defect.

When the independent review has a true P2, use the live-evidence closure path in this skill:

1. Keep the original GitHub review finding/thread as the stable finding record.
2. Create or update the defect Issue through `bug-to-issue`, then reply on that finding/thread with
   the Issue reference and mark or resolve the thread as deferred.
3. Record the PR head SHA, finding URL, Issue URL, and reply/disposition URL in the delivery
   receipt.
4. Re-read those GitHub artifacts immediately before merge and fail closed if any link, severity,
   or disposition is missing or contradictory.

This live-evidence path is the closure authority for that PR. A dispatcher run that encounters the
P2 must return `inconclusive` / `blocked_technical` before terminal delivery and hand off to this
path; it must not manufacture a clean review event. Completing the P2 disposition does not trigger
another review round. Dispatcher-native delivery for P2-bearing reviews remains unavailable until
its schema, validator, ledger, and tests can represent and validate the complete disposition.

#### Re-triggering after a fix

One round is not sufficient once a P0/P1 finding leads to a code change — a fix can introduce a
defect the original round never looked for, and self-verification by the same agent that wrote the
fix is weaker than independent re-review. P2/P3 disposition leaves the code unchanged for that
finding and does not re-trigger review.

- After a **substantive** P0/P1 fix (anything beyond a one-line wording/doc/formatting change with no
  logic change), re-run the local review gate scoped to the diff since the last review round before
  treating that finding as resolved. Do not rely on the fixing agent's own read of the diff as the
  verdict.
- A **trivial** P0/P1 fix (single-line wording/doc/formatting, no logic change) may be self-verified
  against the current head SHA without a full re-run.
- **Stop condition:** the gate passes once a round has no new P0/P1 finding and all P2/P3 findings
  are dispositioned. One independent final passing review is the default. Require a second
  consecutive passing round only when either
  (a) the PR changes a runtime surface on a declared high-risk TCD category (security, data,
  migration, auth, concurrency, external-API, credential-durability, or explicit state-machine surfaces),
  or (b) the
  low-convergence circuit breaker below was triggered for the same mechanism/domain key. A
  governance, docs, skill, or test-enforcement change carrying a high-risk label alone does not
  qualify as a runtime surface.
- Before publication, record that decision in the canonical PR body as exactly
  `Final-Review-Rounds: 1` or `Final-Review-Rounds: 2`. Use `2` for the declared high-risk runtime
  case above. The verification-dispatch producer authenticates this v3 field from the live PR and
  every normal, post-launch, and crash-recovery live-truth fence must match it before the durable
  closure ledger can proceed; changing prose or coordinator output cannot lower it.
- **Low-convergence circuit breaker:** if one round reports two or more P0/P1 blockers in the same
  stateful mechanism, or a later round finds an adjacent P0/P1 blocker in a mechanism already
  repaired, stop point-fixing and do not start another expensive validation or publish another
  head. P2/P3 observations do not count. Build the mechanism convergence packet and run the
  independent pre-expensive-gate review defined in
  `AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate`. Resume the expensive
  sequence only after that review is clean. Preserve the existing mechanism/domain binding and
  attempt count; this replan does not reset budget and requires the second final clean round only
  for that triggered mechanism/domain key.
- Repair budget applies only to blocking P0/P1 findings and is per stable failure mechanism and
  failure domain: two standard repair attempts followed, when needed, by two strongest-capability
  repair attempts for that same key. The closed domains are review/code correctness,
  static-quality, lease/concurrency, and deployment/model-schema compatibility. Multiple blocking
  findings may share one mechanism; the same finding must not be rebound to another mechanism or
  domain to reset accounting. P2/P3 findings consume no budget.
- Once 2 standard fix attempts have been spent on one mechanism/domain key and a blocking finding
  for that key remains or reappears, treat that as a **capability-escalation trigger**, not an
  automatic owner escalation.
  Start a fresh repair context at the strongest available capability selected through `AGENTS.md ::
  Total Cost of Development` and the current platform configuration, and pass it all prior findings,
  attempted fixes, changed mechanisms, and relevant evidence. Do not duplicate a provider/model
  ladder here; the canonical policy and live configuration may select any available agent family.
- Permit at most 2 additional capability-escalated fix attempts for that same mechanism/domain key.
  Independently re-review after each substantive attempt, and record the
  selected model/agent family, reasoning level, prior context supplied, fallback (if any), and outcome
  for every escalated round.
- After one key's budget of 2 standard plus 2 escalated fix attempts is exhausted, or when the
  strongest available capability cannot run or repeatedly fails, classify the stop under
  `AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Escalation classifier`. Continue with bounded
  technical recovery, backoff, or a blocked-technical receipt when safe; route through
  `owner-decision-brief` only if that classifier identifies an explicit authority/scope category.
  Do not reset an existing finding's binding, and do not ask the owner merely because the
  standard-capability attempts failed. Budget exhaustion alone does not create a Human Exception.
- Record each round's outcome and the final round count in the delivery receipt so convergence is
  auditable after merge.

### Reading the Codex verdict 🤖 (inactive — kept for reactivation)

> **Inactive as of the local-review-gate swap above.** This is not the current merge gate; it is kept
> intact so Codex review can be reactivated later without reconstructing this section. `_shared/CI_WAIT_CONTRACT.md`'s
> `--codex` flag still resolves this verdict for callers that opt into it, but `verification-and-closure`'s
> default flow no longer requires it.

Codex (`chatgpt-codex-connector[bot]`) reviews PRs in this repo automatically and often signals its
verdict with an **emoji reaction on the PR itself**, not a formal review or comment. Checking only
`/pulls/<n>/reviews` and `/comments` will miss it and read as "Codex hasn't reviewed yet."

Resolve the verdict through `_shared/CI_WAIT_CONTRACT.md` / `app.dispatcher.poll_backoff` so the
reactions, reviews, pull comments, and issue comments are read with one combined query where GitHub
supports it. The surfaces remain:

- Reactions (primary): `gh api repos/<owner>/<repo>/issues/<pr>/reactions --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | .content'`
  - 👍 `+1` (also `heart` ❤️, `hooray` 🎉, `rocket` 🚀, `laugh` 😄) → reviewed, no blocking findings → **pass**.
  - 👎 `-1` or `confused` 😕 → **blocking**: treat as requested changes until addressed.
- Reviews: `gh api repos/<owner>/<repo>/pulls/<pr>/reviews` — triage every
  `CHANGES_REQUESTED`/`COMMENTED` finding through `Severity routing`; only P0/P1 findings block,
  while P2/P3 findings require their non-blocking dispositions.
- Comments: `gh api repos/<owner>/<repo>/issues/<pr>/comments` and `/pulls/<pr>/comments` — Codex posts detailed findings here when it has them.

Rules:

- A 👍/`+1` reaction is a sufficient Codex pass even when there is no formal review or comment.
- Do not block indefinitely on a missing verdict: if Codex has posted no reaction, review, or comment
  and recent sibling PRs show the same silence (a repo-wide Codex stall), classify the outage under
  `AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Escalation classifier`, use bounded backoff or a
  `blocked_technical` receipt, and preserve the merge block. A technical outage never creates a
  CI/review/merge waiver. Route through `owner-decision-brief` only when the classifier finds an
  explicit authority category; that decision does not relax the gate.

When all prerequisites are met:

Verified-merge authority and phase body digests canonicalize GitHub PR-body storage by removing at
most one terminal LF before digest derivation or comparison. That LF is equivalent to its absence;
every other body byte and whitespace character remains exact, and substantive body drift fails
closed. This digest equivalence does not relax any head, title, closing-set, authority-receipt, or
phase-continuity gate below. For a pre-#4010 trusted authority receipt only, the stored raw digest
of the otherwise identical body with exactly one terminal LF may authenticate when GitHub returns
the LF-less form when the authenticated comment `created_at` and `updated_at` both precede #4010's
`2026-07-21T16:32:11Z` merge cutoff. Check normal canonical equality first so unchanged two-LF bodies
remain valid; the legacy fallback rejects any CR/CRLF, spaces, interior drift, post-cutoff receipt,
or other receipt/live-state mismatch. Preserve receipt identity, phase continuity, and repair budget.

For the singular pre-#4010 immutable PR #4052 compatibility deadlock, current-main/base-side
recovery may attach an additional auditable `pr-contract` result only after re-reading repository,
PR, fixed head, title, canonical neutralized body, empty closing links, issue sets, unique trusted
authority receipt, continuous `prepared` phase, and unchanged repair budget. It uses the current-main
validator and fails closed for mutable/foreign/unprepared, stale/forged/conflicting, noncanonical, or
drifted contexts. It is not a branch-protection waiver: it neither replaces unrelated checks nor
merges, restores closers, posts phases, closes issues, or changes dispatcher accounting. Hand the
same exact head back to the ordinary verified-merge sequence below.

1. freeze the authenticated v2 context (`run_id`, repository, PR, exact head, governing issue,
   `closing_issues`, durable `supporting_issues`, attempts, and 2+2 repair-budget projection); re-read
   the live PR title/body/head and GitHub `closingIssuesReferences`, and reject any mismatch or title
   closing attempt even when an earlier `pr-contract` run was green
2. run `scripts/prepare_verified_issue_set_merge.py` against those snapshots; require its
   `verified_issue_set_merge_authority.v1` receipt and neutralized body, then post that exact
   machine-readable authority receipt on the PR from an authenticated repository collaborator before
   changing the body so the original authority remains durable and auditable.
   **Neutralization precondition — this exact head must be the final head.** A neutralized body is
   only valid while the attempt it was prepared for is in flight, so the planner requires a
   head-bound `verified_issue_set_merge_readiness.v1` statement through `--merge-readiness-json`
   whose `head_sha` equals this exact head, with `required_checks_green: true`,
   `review_gate_resolved: true`, and `further_commits_anticipated: false`. Do not neutralize while
   any repair, rebase, base-branch update, review-feedback fix, or other commit is still expected;
   finish those commits first and restart at step 1 on the new head. A readiness statement is never
   reusable across heads, and the planner refuses neutralization when the precondition is unmet
3. replace the live PR body with the plan's neutralized body, which converts every authenticated
   closer to evidence-only `Refs`; immediately re-read the PR and fail closed unless the head and
   neutralized body matches the plan under the terminal-LF-only canonical digest contract above, the
   title and body contain no canonical or malformed closing attempt, and `closingIssuesReferences`
   is empty. Because the body edit triggers
   governance again, the triggered `pr-contract` must authenticate the trusted, non-conflicting
   exact-head authority receipt against the complete neutralized body issue set; fabricated
   `Refs`/`Verified-Closing-Issues` text is never sufficient. Wait for the latest `pr-contract` run
   triggered by that `edited` event to finish green on the same exact head, then re-read the head,
   body, title, and empty closing references once more. Never reuse the pre-edit green `pr-contract`
   result as merge authority
4. use `scripts/build_verified_issue_set_merge_phase.py` to post an authenticated
   `verified_issue_set_merge_phase.v1` `prepared` receipt bound to the durable authority receipt and
   exact neutralized PR snapshot. For the pre-#4010 legacy exception, also pass the complete trusted
   authority comment through `--authority-comment-json`; the receipt payload alone does not prove
   cutoff provenance. Require a single continuous prepared/merged/reconciled/restored
   phase ledger; duplicate identical receipts are idempotent, while missing, stale, forged, or
   conflicting receipts fail closed
5. merge through the exact-head REST endpoint using the verified SHA and only the plan's fixed
   non-closing commit title/message. Never use GitHub-synthesized or caller-supplied free-form merge
   text. A body/head/closing-link change before this request is a hard stop; never restore closers and
   retry around a failed gate. A hard stop ends this merge attempt, so apply
   `Restoring a neutralized body after a head change` below before any further repair work
6. verify merge success and re-fetch the merge commit to prove its title/message contains no
   canonical or malformed closing attempt, then post the authority-bound `merged` phase receipt
7. on resume, recover either authenticated interruption window without restarting accounting. If the
   exact-head PR is still open with the neutralized body, require the unique trusted exact-run
   authority receipt, its exact body digest/issue sets/repair budget, and a continuous `prepared`
   phase before resuming the pre-merge sequence. If the live PR is merged-but-incomplete,
   authenticate the same exact authority receipt and latest continuous phase, prove the live merge
   identity, and resume at the first missing phase. Missing, forged, stale, conflicting,
   body-mismatched, or unphased recovery evidence fails closed. Resume either path without resetting
   attempts or the 2+2 repair budget, and never reject an authenticated interrupted delivery merely
   because its neutralized or merged PR no longer satisfies canonical pre-merge intake
8. re-read post-merge closing references and issue state before explicit closure. Independently
   enumerate every non-PR `closed` candidate at or after `merged_at` through the repository
   issue-events feed, including live-shaped events whose REST `commit_id` is null: validate observed
   reverse-time ordering within and across bounded pages until the feed covers `merged_at`, and fail
   closed on any ordering, coverage, repository, issue, or response-bound violation. Union those
   numbers with authenticated and phase-known candidates under the existing candidate cap. Validate
   each candidate's REST node identity, then resolve exactly one bounded static GraphQL `nodes(ids:)`
   batch using raw string fields (never typed `gh api -F` fields) and prove cardinality, unique node,
   repository/issue/state, latest `ClosedEvent` timestamp/actor, mandatory `closer` field, and `closer`
   identity. Every `PullRequest` closer must carry a valid merge SHA, regardless of whether it is the
   target PR. Only an exact
   target PR number, repository, and merge SHA may attribute an automatic closure to this delivery;
   a same-number foreign repository or SHA fails closed, while a different valid PR remains
   unrelated even for an authenticated expected issue. A null closer counts only as the explicit
   manual close of an authenticated expected issue when its actor and timestamp satisfy the delivery
   fence; it never promotes a repository-discovered unauthorized candidate. Then use
   `plan_post_merge_reconciliation` with complete per-issue evidence; reopen only
   an unauthorized closure GitHub attributes to this PR, and block the final receipt on any unresolved
   unauthorized closure. This is the defensive race reconciliation, not a substitute for pre-effect
   neutralization
9. explicitly close every and only the authenticated `closing_issues`, verify their state, post the
   `reconciled` phase receipt, then
   restore the authenticated original PR body and prove its governing/closing identities equal the
   durable receipt, and post the `restored` phase receipt; bounded monotonic supporting additions may be retained only as evidence and may not expand closure authority
10. authenticate the durable authority receipt and complete phase ledger again, then repeat the
    bounded repository-event enumeration and live-read each bounded candidate's state and closure
    attribution. A terminal delivery receipt is forbidden unless every and only authenticated
    closing issue is closed by this delivery and no unrelated issue closure remains attributable to
    the exact target PR/repository/merge identity
11. if issue-backed, complete or release each applicable closing-issue dispatcher task
12. if issue-backed, remove all agent labels from every closed issue; do not remove active-state
   labels from a distinct governing parent unless its own lifecycle contract is complete
13. if issue-backed, set every closing Issue and the PR Project Status to `Done` when automation has
   not already projected it; never project an unclosed governing parent `Done`
14. if issue-backed, update spec files named by each closing issue's `Source Anchors` from stale
   `State: Not yet implemented` to `State: Implemented. Delivered by PR #<PR> (issue #<N>, <YYYY-MM-DD>).`
   Record child-delivery validation evidence on any distinct open governing parent
15. verify final state, including restored body authority and the absence of unauthorized closures
16. invoke `post-merge-owner-doc` on the merged PR. For issue-backed PRs, write the same PR-specific
    result on every exact closed issue and also on a distinct open governing parent; for issue-free
    lanes, use the PR thread
17. assert each required `post-merge owner-doc check: PR #<PR>;` receipt exists before emitting a delivery
    receipt; watchdog or pending reminders are not closure receipts. [owner-doc-receipt-gate]
18. if direct repair, write a direct repair delivery receipt instead of issue-closure state changes

### Restoring a neutralized body after a head change

A neutralized body's lifetime is bounded by the one merge attempt that justified it. It is never a
durable PR state, so it must not outlive its exact head.

Whenever a new head is observed on a PR whose body is still neutralized — a repair commit, a rebase,
a base-branch update, an abandoned attempt, or a resumed session — restore the canonical body before
any further repair, verification, or re-merge work. Leaving it neutralized fails `pr-contract`
deterministically on that head and on every head after it, because the exact-head authority receipt
no longer covers the live head. That happened on PR #4021, where one neutralized body survived six
later heads for about seven hours.

Detect the state instead of relying on noticing it per head:

```bash
python3 scripts/resolve_neutralized_body_restoration.py \
  --pr-json <pr.json> --comments-json <comments.json> --repository <owner/repo>
```

It is read-only and exits `2` when the live body is neutralized while no authority receipt covers the
current head, naming the durable receipt's `restore_body_sha256` as the only accepted restore target.

Rules for the restore:

- restore the exact authenticated pre-neutralization body; prove it with
  `restored_body_matches_authority` against that receipt digest and its governing/closing identities
  before writing, and fail closed rather than hand-editing a body the receipt cannot authenticate
- never rewrite, delete, or re-post the durable authority and phase receipt trail; it is historical
  evidence of the abandoned attempt, and restoration repairs only the mutable body
- never restore while a merge request for that head may still be in flight — resolve the attempt
  through step 7 first, so a restore cannot race a merge or grant authority
- resume normally afterwards: once the new head is final again, step 2 re-derives a fresh head-bound
  readiness statement, authority receipt, and neutralized body on that head

## When Not to Merge

- any issue-backed acceptance criterion is not met -> create a follow-up Issue instead
- any issue-backed behavioral AC `Verify:` test is missing, skipped, xfailed, or excluded from CI -> do not merge
- any issue-backed non-behavioral AC `Verify:` target is absent -> do not merge
- CI has regressed since PR integration handoff -> route back to PR integration
- scope drift detected -> route through issue maintenance
- work is only partial -> do not merge, keep the Issue open, create follow-up Issue(s)

## Lifecycle Rules During Verification

Project Status for the Issue and PR follows `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md` as the
single source (an open non-draft PR legitimately projects to `Review` via the shipped Project
automation — do not treat that as drift). Merge-stage-specific rules on top of the matrix:

- do not mark lifecycle `Done` before merge
- if project/PR automation already projected `Done`, verify that state rather than writing it again
- only apply the fallback `Done` mutation when the item still needs terminal projection

## BuilderOps Closure Checkpoint

Before merging or writing the delivery receipt, resolve BuilderOps routing: for each record type in
`.codex/skills/README.md :: BuilderOps Vault routing`, confirm the matching record exists (or the
receipt states none) for any divergence, docs-freshness finding, operational roadmap movement,
proposed authority crossing, or processed/promoted/superseded/discarded material noticed during
delivery.

If none apply, the delivery receipt may state `BuilderOps routing: none` with the reason. On Tier 1
PRs (`docs/development/GOVERNANCE_PROPORTIONALITY.md`), an absent `## BuilderOps Routing` section is
read as `none` — do not block closure on its absence. Do not use `docs/learning-log.md` as the
primary closure surface.

## Parent Issue Closure

Use [`docs/development/PARENT_ISSUE_CLOSURE.md`](../../../docs/development/PARENT_ISSUE_CLOSURE.md) only when closure is actually relevant.

- if a slice issue is fully delivered, merge the PR and deliver the Issue
- if the parent feature still needs validation, keep it open and record the child validation receipt on the parent issue
- if the parent feature is the final child slice or an explicit closure task, close the parent after repo-verifiable acceptance is satisfied and the parent-closure handoff or explicit parent-closure issue is resolved
- future adoption or retro work should move to a BuilderOps `LearningSignal`, `PromotionIntent`, discard/supersession receipt, or a follow-up GitHub Issue when it is executable work; it should not block delivered repo-verifiable scope

## Dependent Issue Unblocking

After merging and delivering work, scan for issues blocked by the delivered Issue.
Only unblock issues whose actual dependency is truly satisfied.

## Project State Operations

Use `gh` CLI and the GitHub GraphQL API to keep Project state truthful.
Do not leave state updates as recommendations when you can execute them directly.

## Status and Closure Enforcement

- do not validate code only; validate delivery state
- detect and correct false status where possible
- if issue-backed work is truly delivered, execute and confirm closure plus Project Status = `Done`
  for exact closing issues only; update any distinct governing parent without falsely closing it
- if direct repair work is truly delivered, write the direct repair delivery receipt and do not create or mutate a governing Issue
- direct repair delivery receipt shape:
  - `Direct repair merged: PR #<n>, type=<type>, validation=<checks>.`
- require owner-doc writeback only when acceptance changed supported truth
- require roadmap or plan cleanup
- produce a delivery receipt
- if work is only partial, do not merge, do not mark done, and create bounded follow-up Issue(s)

## Source-Anchor Enforcement

- confirm each `Source Anchors` entry resolves to a real doc path and intended source item
- if an anchor is stale, malformed, or no longer matches current docs, report it and recommend repair or replacement

## Capturing Learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output Format

Lead with the human summary; include later sections only when they have content, scaled to the tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`). For Tier 1, the summary plus the delivery receipt line is enough.

### 1. Summary For The Human

2–4 sentences: what was verified and merged, what remains, what needs a decision.

### 2. Delivery Verdict

AC-by-AC resolution: state whether each `Verify:` target resolves green and why.

For Tier-2/Tier-3 work, alongside the AC-by-AC verdict, emit a `tcd_review` block (fields per `AGENTS.md :: Total Cost of Development`): verdict, risk_level, blocking vs non-blocking issues, missing tests, residual risk, and under/over-modeling. On Tier-1 / trivial / docs-only verifications a one-line capability + residual-risk note suffices — do not pay a fixed audit-block tax on cheap work. Use the same policy for when to escalate verification depth versus stay on the hot path; do not restate the triggers or any model matrix here.

### 3. State Changes Executed

List every lifecycle mutation that ran.
Include the delivery receipt line.

### 4. Follow-up Issues

If work is partial, do not merge. Create bounded follow-up Issue(s) using the exact task-contract shape.
