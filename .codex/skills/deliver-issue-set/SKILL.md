---
name: deliver-issue-set
description: "Review, plan, make ready, and deliver an epic, parent feature issue, Kanban/Project lane, or larger ready-issue set in agentic-pkm-mvp; build a pickup order and verification ledger, repair readiness when needed, and execute issues through the repo delivery chain, including rational parallel sub-agent delivery."
---

# Deliver Issue Set

Use this skill when asked to review, plan, make ready, or deliver an epic, parent feature issue, Kanban/Project lane, or larger set of issues that should move through agent pickup.

The goal is to produce an executable implementation plan and, when requested, deliver the full epic or all in-scope Kanban/Project issues that can truthfully be delivered. When the ready pool is too small, repair or create bounded ready issues using the repo's existing backlog workflows.

This skill is a coordinator. It does not replace `issue-to-code`, `verification-and-closure`, `issue-maintenance-change-control`, `docs-to-issue`, or `feature-breakdown`.

## First Context To Load

1. `AGENTS.md`
2. `docs/architecture/SBS_OPERATING_MODEL.md` — mandatory. This skill always classifies the issue set as Product/Runtime vs Builder System vs boundary work *before* dispatch; §3 (Builder System boundary and classification procedure) is the source of that classification, §5 (Definition of Ready) defines the `## SBS Impact` readiness gate used below, and §9/§10 define the owner-doc and transition-debt writeback the parent validation hub checks at closure.
3. `.codex/skills/README.md`
4. `.codex/skills/issue-to-code/SKILL.md`
5. `.codex/skills/verification-and-closure/SKILL.md`
6. `docs/development/DEV_WORKFLOW.md`
7. `docs/development/AGENT_OPERATING_PROTOCOL.md`
8. `docs/development/GOVERNANCE_PROPORTIONALITY.md`
9. `docs/DOCS_INDEX.md`
10. Owner docs and `Source Docs` referenced by the epic or candidate issues

Load secondary skills only when the work needs them:

- `.codex/skills/issue-maintenance-change-control/SKILL.md` for stale, malformed, drifted, mislabeled, blocked, or false Project/Issue state.
- `.codex/skills/docs-to-issue/SKILL.md` when active docs already define one bounded executable issue.
- `.codex/skills/feature-breakdown/SKILL.md` when one parent/spec/capability needs a parent validation hub plus multiple child slice issues.
- `.codex/skills/publish-pr/SKILL.md` when local issue work is ready to commit, push, and publish.
- `.codex/skills/pr-integration/SKILL.md` only when mergeability, CI attachment, branch drift, or review-feedback repair is needed before verification.

## Modes

### Planning / Readiness Mode

Use this mode when the user asks to review, plan, prepare, triage, or make issues ready.

Allowed:

- inspect epic, parent issue, child issues, linked PRs, Project state, owner docs, and source anchors
- classify issue readiness
- repair issue contracts when the owner docs make the intended contract unambiguous
- create bounded issues through `docs-to-issue` or `feature-breakdown` when source docs already support the work
- correct labels and Project Status for readiness truth
- produce implementation order, parallelization plan, and verification ledger

Forbidden in planning / readiness mode:

- claim issues
- move issues to `In Progress`
- remove `agent:ready` as a pickup claim
- edit code for implementation
- create commits
- open implementation PRs
- merge PRs
- close delivered issues except as an explicit maintenance correction after following `issue-maintenance-change-control`

All GitHub label, Issue body, Project Status, and issue-creation mutations must be executed with explicit `gh` or GraphQL commands, verified, and reported with receipts.

### Delivery Mode

Use this mode when the user asks to deliver the epic, finish all ready issues, work through the Kanban lane, clear the board, or otherwise execute the in-scope issue set.

Delivery mode may claim, implement, publish, verify, merge, and close issues only through the repo's existing skills and only when each step's prerequisites are satisfied.

Delivery rules:

- Default to delivering one issue at a time.
- You may claim multiple issues only when you are immediately assigning them to active sub-agents with isolated worktrees and the parallelization is rational from both token-budget and quality perspectives.
- Before selecting or dispatching work, classify each candidate as Product/Runtime System,
  Builder System, or boundary work using
  `docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`.
  Product/Runtime issues must route SBS impact through the Product owner docs and SBS operating
  procedure; Builder System issues route through the Builder System boundary/artifact map; boundary
  issues name both sides.
- Route the serial-vs-parallel dispatch and slot-count decision through `AGENTS.md :: Total Cost of Development` (parallelization and coordination are TCD cost terms); per-issue model and reasoning routing is owned by `issue-to-code`. Run every parallel sub-agent under `AGENTS.md :: Parallel-agent execution` — isolated worktree per issue, never the shared root; reconcile claim races on evidence rather than re-implementing.
- Do not claim the whole epic or entire Kanban pool up front.
- Do not claim more issues than there are ready sub-agent execution slots.
- Never make speculative claims. Every claimed issue must have an owner agent, worktree/branch plan, validation plan, and expected return receipt.
- Confirm each selected issue is claimable before dispatching: `Status=Ready`, labeled `agent:ready`, and carrying no conflicting prior claim. Do not pre-transition status or remove `agent:ready` from the coordinator before dispatch — `issue-to-code` selects only `Ready` + `agent:ready` issues, so pre-claiming would force a compliant sub-agent to reject the assignment. The fast-claim handshake (`Ready -> In Progress` + remove `agent:ready` via `scripts/issue_pickup_claim.sh`) is performed by the sub-agent as the first step of its own `issue-to-code` pickup. An issue counts as dispatched only once that pickup has acquired the lease and recorded a claim receipt comment naming the coordinator session, assignee/sub-agent, worktree/branch plan, and expected return receipt.
- For each issue, follow `issue-to-code` from claim through implementation and local validation.
- Use `publish-pr` for branch, commit, push, and PR creation/update.
- Use `pr-integration` only when the PR needs readiness or repair before verification.
- Use `verification-and-closure` for merge, Issue closure, Project `Done`, dispatcher release, dependent unblocking, and post-merge owner-doc routing.
- When coordinating autonomous delivery, do not treat an unprotected branch or absent required-status-check rule as permission to skip the process gate. `verification-and-closure` still owns the current CI/checks plus Codex-review prerequisites before merge.
- After every delivered issue, re-read the parent feature issue / Project state and recompute the next pickup target.
- Stop instead of forcing delivery when an issue is blocked, malformed, stale, already delivered, missing `Verify:` targets, missing authority, or needs human input.

Parallel claim is allowed only when all are true:

- each issue is independently `Status=Ready` and labeled `agent:ready`
- each issue has concrete `Verify:` targets and source authority
- dependency order allows parallel work
- likely touched files, migrations, schemas, release channels, and owner-doc writebacks do not create uncontrolled conflicts
- each sub-agent receives the relevant owner docs, issue contract, `Verify:` ledger, validation commands, and required skills
- each sub-agent can publish and verify its work without relying on hidden chat context
- the expected token savings or quality gain is explicit, for example isolating unrelated subsystems, avoiding repeated context reload, or letting independent validation run concurrently

If any parallel worker stalls, fails claim, loses branch/worktree truth, or discovers contract drift, release or reclassify that issue before claiming replacements.

If a sub-agent starts pickup and finds an existing claim receipt or lifecycle claim that does not match
the dispatching coordinator, scope the collision check to the active/latest unreleased lease before
deciding. Because an Issue can be claimed, released, closed, and re-Readied over its lifetime, only the
most recent lease that is still open governs pickup. A non-matching receipt counts as a real collision
only when it is the latest lease and has not been released or superseded — i.e. the Issue is currently
`In Progress` / not `agent:ready`, and no later release/superseded receipt or re-Ready transition has
reclaimed it. Stale receipts from a prior, already-released lease on a re-Readied Issue (the Issue is
back to `Ready` + `agent:ready` with no live foreign lease) do not block valid pickup; treat them as
historical and proceed. When the latest lease is a genuine foreign claim, stop and report the collision
instead of implementing — do not rationalize a live foreign claim as belonging to the current dispatch;
the coordinator must reconcile, release, or choose a different issue before work continues.

Delivery mode is complete only when every in-scope issue is either:

- delivered and verified through `verification-and-closure`, or
- explicitly classified as non-executable with a maintenance receipt, blocker reason, and next action

Do not report the whole epic or Kanban scope as delivered while blocked or non-executable issues are silently left behind.

## Scope Resolution

For an epic or parent feature issue:

- Treat the parent as the validation hub.
- Deliver child/slice issues in dependency order.
- Keep parent validation evidence on the parent issue after each child delivery.
- Before closing the parent validation hub, confirm on the parent that, across the delivered set:
  - **child receipts** exist — every in-scope child has a recorded delivery receipt (PR link, merge/closure state, validation evidence), and no child was silently left blocked or non-executable;
  - **owner-doc writeback** is resolved per `docs/architecture/SBS_OPERATING_MODEL.md` §9 — each child either updated its owner doc in-PR or created and linked a follow-up issue; a "to update later" note does not count;
  - **transition debt** is handled per `docs/architecture/SBS_OPERATING_MODEL.md` §10 — each relevant slice reduced a debt row, added a bounded one, or stated no effect, and for a Builder System or boundary set the D11/D12 outcome from the [SBS classification and impact gate](#sbs-classification-and-impact-gate) is recorded;
  - **learning capture** ran when plan divergence occurred — if any child diverged from its contract or an earlier artifact was found wrong during delivery, `capture-learning` was invoked (it owns the invocation gate; see [Capturing Learning](#capturing-learning)).
- Close the parent only when repo-verifiable acceptance is satisfied and parent-closure rules allow it.
- These hub-closure checks are scoped to epic / parent / Project-lane coordination; ordinary single-issue delivery carries only its own issue-contract, `## SBS Impact`, and verification requirements (`docs/development/GOVERNANCE_PROPORTIONALITY.md`).

For a Kanban / Project request:

- Resolve the Project, view, lane, or status filter before execution.
- If the user says "all issues on Kanban" without a narrower lane, inspect the shared Project state and define the in-scope set explicitly before mutating anything.
- Treat `Ready` plus `agent:ready` issues as executable pickup candidates.
- Treat `Backlog`, `agent:blocked`, and `agent:needs-human` as non-active until readiness repair proves otherwise.
- Do not mark blocked or unclear items as delivered just to clear the board.

## Ready Pool Rule

Treat "several ready issues" as at least 3 executable pickup issues unless the user gives another target number.

If fewer than the target number are ready:

1. Inspect the epic, parent feature issue, related child issues, active docs, Project backlog, and linked PRs.
2. Run the relevant Project/lifecycle truth audit from `issue-maintenance-change-control` before readiness mutations.
3. Identify candidates that are close to ready.
4. Repair existing issue contracts only when the source authority is clear.
5. Use `docs-to-issue` or `feature-breakdown` for new issues, not ad hoc issue creation.
6. Do not invent scope, strategy, dependencies, or acceptance criteria not supported by owner docs or `Source Anchors`.

An issue may be made ready only when all are true:

- it is a bounded child/slice issue, not a parent validation hub
- `Source Anchors` resolve or have a safe nearest-authority fallback
- `Scope`, `Constraints`, `Out of Scope`, and `Source Docs` are clear
- every Acceptance Criterion has a concrete `Verify:` target
- behavioral ACs name concrete tests
- non-behavioral ACs name concrete doc anchors, roadmap diffs, runtime receipts, or closure evidence
- `Suggested Validation` executes the `Verify:` targets
- its `## SBS Impact` block is present, complete, and consistent with the issue's Product/Runtime vs Builder System vs boundary classification, per `docs/architecture/SBS_OPERATING_MODEL.md` §5 (Definition of Ready) — every field resolved, with "none"/"unaffected" stated explicitly rather than left blank or as a template placeholder (see [SBS classification and impact gate](#sbs-classification-and-impact-gate))
- no dependency, human decision, or authority ambiguity remains
- repo reality does not already satisfy the issue

Parent feature issues remain validation hubs unless explicitly scoped as one executable slice.

## Issue Review Procedure

For each candidate issue, inspect:

- issue number and title
- parent / child relationship
- labels
- Project Status
- priority
- linked PRs
- Product/Runtime System vs Builder System vs boundary classification, with the owner docs required
  by that classification
- the `## SBS Impact` block: presence, completeness, and consistency with that classification
- every canonical Issue contract section (`.codex/skills/_shared/ISSUE_CONTRACT.md`)

Classify each candidate as exactly one:

- `ready for pickup`
- `ready but lower priority`
- `blocked by dependency`
- `malformed contract`
- `stale / already delivered`
- `too large and needs feature-breakdown`
- `needs issue-maintenance-change-control`
- `needs docs-to-issue`
- `needs human decision`

When classifying priority, follow `issue-to-code`: `prio:high` before `prio:med` before `prio:low`, then prefer clear source anchors, bounded scope, dependency-unlocking work, smallest safe implementation surface, and reduced rollout drift.

### SBS classification and impact gate

A candidate must not be made Ready or selected for pickup unless its `## SBS Impact` block is present, complete, and consistent with its Product/Runtime vs Builder System vs boundary classification, per `docs/architecture/SBS_OPERATING_MODEL.md` §5 (Definition of Ready). Treat a missing, partially filled, placeholder, or classification-inconsistent block as a readiness failure: repair it under the Ready Pool Rule when the source authority is clear, otherwise classify the candidate `needs issue-maintenance-change-control` or `needs human decision`. This gate is the issue contract's own SBS requirement applied at the issue's existing risk tier — not extra ceremony layered on single-issue delivery (`docs/development/GOVERNANCE_PROPORTIONALITY.md`).

For a Builder System or boundary issue set, also check the set against the Builder-System transition debts in `docs/architecture/SBS_TRANSITION_DEBT.md` and record, for the set, whether it **reduces**, **preserves**, or **adds** each:

- **D11 — CES overloaded into the whole Builder System.** Does the set concentrate more stewardship/coordination authority into one skill, agent, or surface (pushing CES toward a development control plane), or keep Builder System workflows, skills, BuilderOps, and TCD governance within their own bounded enabling-system boundary?
- **D12 — builder learning and TCD signals not uniformly captured across all workflows.** Does the set make `capture-learning` and TCD-signal capture more consistent across the workflows it touches, or leave gaps where learning/cost evidence can vanish from receipts or be over-promoted into runtime/user memory?

Run this D11/D12 check only for Builder System or boundary sets; Product/Runtime-only sets resolve the standard `## SBS Impact` transition-debt field without it. The transition-debt register and its lifecycle remain owned by `docs/architecture/SBS_OPERATING_MODEL.md` §10 — record the set's D11/D12 outcome in the readiness/verification ledger; do not duplicate the register here.

## Implementation Plan

Group ready issues by:

- dependency order
- priority
- touched subsystem
- owner doc
- validation command overlap
- risk surface
- whether they can safely run in parallel

For each ready issue, produce an implementation card:

- Issue
- role in epic / parent feature
- bounded outcome
- Product/Runtime System vs Builder System vs boundary classification
- owner docs to read before coding
- likely files or modules touched
- test-first targets from `Verify:`
- expected docs writeback, if any
- suggested validation commands
- closure proof required by `verification-and-closure`
- PR lane and expected PR body link
- risks / likely blockers
- parallelization notes

For the epic or parent feature, produce:

- parent validation hub status
- child issue dependency graph
- recommended pickup order
- parallelization plan
- final-child / parent-closure considerations
- where post-merge validation evidence should be recorded
- owner-doc promotion trigger
- roadmap/plan cleanup trigger

## Delivery Procedure

When delivery mode is active:

1. Build or refresh the readiness table and verification ledger.
2. Make additional issues ready if the ready pool is too small and source authority supports it.
3. Select either the next single issue or a rational parallel batch by `issue-to-code` priority, dependency, and quality rules.
4. Claim exactly the selected issue, or exactly the selected parallel batch assigned to active sub-agents, through `issue-to-code`.
5. Implement the smallest complete change satisfying the issue contract.
6. Run the issue's `Suggested Validation` and any required focused checks.
7. Publish the PR through `publish-pr`.
8. Run `pr-integration` only if readiness/repair triggers apply.
9. Run `verification-and-closure` to verify every `Verify:` target, merge when prerequisites are met, close/update lifecycle state, and invoke post-merge owner-doc routing.
10. Record the delivery receipt on the issue and parent validation hub when relevant.
11. Recompute remaining scope and repeat until the epic/Kanban scope is delivered or blocked.

If the work spans multiple sub-agents:

- assign one bounded ready issue per sub-agent at a time, unless a tightly coupled pair has an explicit quality reason to stay with the same sub-agent
- state the token/quality rationale for the parallel batch before claiming
- claim only after the sub-agent handoff is ready
- include the relevant owner docs, `Verify:` ledger, validation commands, and required skills in each handoff
- require each sub-agent to report lifecycle actions, PR link, validation, doc writeback, and closure state
- never let sub-agents work from parent feature issues unless the parent is explicitly one executable slice

## Verification Ledger

Use `verification-and-closure` as the closure lens.

For every issue, map each AC to:

- `Verify:` target
- expected proof type: test, doc writeback, roadmap diff, runtime receipt, parent issue evidence, or closure receipt
- exact command or inspection needed
- whether proof is pre-merge slice verification or post-merge feature validation
- owner-doc promotion condition, if any

Do not mark an issue ready if any `Verify:` target is missing, unresolvable, skipped, xfailed, excluded from relevant CI, or disconnected from `Suggested Validation`.

## Output Format

Lead with the human summary, then include a section only when it has content — omit empty sections instead of reporting "none". Scale depth to the risk tier per `docs/development/GOVERNANCE_PROPORTIONALITY.md`.

1. Summary For The Human (2–4 sentences: what was done, what remains, what needs a decision)
2. Readiness Table (issue-set state, classifications, ready pool, issues made ready or left unready)
3. Pickup Order And Parallelization (dependency order, batch plan, parallel claim rationale)
4. Verification Ledger
5. Delivered Issues And Receipts (PRs merged, lifecycle mutations, delivery progress)
6. Blockers And Non-Executable Items (reason and next action per item, stop conditions)
7. Maintenance And Follow-Ups (issues needing maintenance or breakdown, owner-doc and source-anchor notes)

Receipts for mutations must name the issue number, labels, Project Status, command family used, and verification result.

## Capturing Learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.
