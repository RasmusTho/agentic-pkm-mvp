---
name: feature-breakdown
description: "Decompose a docs-defined feature, multi-slice capability, or cross-subsystem contract into bounded implementation work and matching validation issues."
---

# Feature Breakdown

When a generated child is non-active, assign its compatible `action:*` subtype and
`blocker_action.v1` receipt from `_shared/BLOCKER_ACTION_CONTRACT.md`, never a coarse state alone.

Use this skill when a docs-defined user-facing feature spans multiple implementation issues, a
reusable capability needs multiple slices, or a cross-subsystem contract needs coordinated work and
post-merge validation. Keep the parent issue's acceptance focused on the source level being
decomposed.

## Repository target

Set `REPO` to the intended `owner/repo` before creating or updating GitHub issues. A specification
directory may be maintained in the hub while implementation issues target a constituent repository;
the repository named by the governing contract, not the current checkout, owns that lifecycle. Use
`gh issue create --repo "$REPO"` (and the same explicit target for follow-up reads and edits).
When delegating the live duplicate re-check to `docs-to-issue`, pass this selected `REPO` through;
the delegated skill must not replace it with the current checkout's remote.

Do not use this skill for:

- a single already-bounded implementation issue
- direct coding from an existing ready task
- vague roadmap cleanup without an actionable feature, capability, or contract boundary

## Canonical workflow

See `.codex/skills/README.md :: Workflow map` for the canonical chain (`PR integration` is
conditional readiness/repair, not an unconditional stage). Spec-lane-specific stages are
`Specification -> Implementation tasks`; after merge, validate and accept the matching feature
outcome, capability contract, or cross-subsystem contract before promoting owner docs.

## Practical modes

- `enrich-docs`: clarify the source-level boundary, subsystem ownership, verification path, and matching validation / acceptance path before creating issues.
- `create-or-update-breakdown`: create or update the specification directory plus bounded implementation tasks once the docs are clear enough.

## Core model and classification

- **Use case / scenario**: an actor's goal in a concrete situation, including outcome and failure
  modes. Anchor it in `docs/HUMAN-FLOWS.md` and
  `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`. It is human-facing acceptance input, not an
  implementation task.
- **Feature**: a user-facing outcome that may compose multiple use cases, capabilities,
  integrations, interaction surfaces, and subsystems. A feature specification owns target scope and
  flow; a parent feature issue, when needed, is the end-to-end validation hub.
- **Capability**: a reusable, surface-independent function with a typed contract. Its primary
  subsystem owner is Capability; use `docs/CAPABILITY_CONTRACT_MODEL.md` to define the contract and
  identify collaborators. A capability may support several features. Do not create one for each
  step in a feature flow or duplicate an existing capability.
- **Cross-subsystem contract**: a normative agreement across artifacts or subsystem boundaries. It
  constrains the capabilities and subsystem components that implement it; it is not itself a user
  outcome or executable capability. Keep it in its canonical owner doc and decompose implementation
  around the subsystem responsibilities it governs.
- **System Breakdown Structure (SBS)**: the target subsystem decomposition and change-impact model
  in `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`; the current eight-subsystem system-of-systems spine and
  subsystem responsibilities are in `docs/MODULAR_ARCHITECTURE.md`.
- **System Requirements Document (SRD)**: Yggdrasil has no consolidated formal SRD. A feature
  specification may be authoritative for its scope but is not a repository-wide SRD. Use the
  relevant feature spec, capability contracts, and Scenario Acceptance Matrix; do not create a
  global SRD or duplicate use-case catalog by default.

Some established specification directories and issue references use *capability* as a broad
historical label for a target area. Classify each item by the outcome or contract it actually
specifies, and preserve existing owner paths and names.

Artifact roles:

- **Feature specification**: owns the user outcome, target scope, flow, subsystem composition, and
  acceptance path. Add bounded task files only when needed.
- **Capability contract**: owns one reusable function's typed interface, authority, provenance,
  fallback, observability, maturity, replacement strategy, and primary subsystem owner.
- **Cross-subsystem contract specification**: remains in its authoritative concept or subsystem
  owner path; decompose implementation around the subsystem responsibilities it governs.
- **Implementation task**: describes one bounded slice, preferably within one subsystem, and names
  collaborators where boundaries cross. One task specification may map to one or more Issues.
- **Parent feature issue**: an optional end-to-end user-outcome validation hub; it is not pickup work
  while child slices remain.
- **Parent capability issue**: an optional acceptance hub for one reusable function's typed
  contract and named subsystem ownership; it does not replace feature-level acceptance.
- **Parent contract issue**: an optional coordination hub for shared policy/boundary behavior and
  subsystem ownership; it does not replace feature or capability acceptance.
- **Epic**: a tracker convention for grouping work, not a product or architecture concept.
- **PRs** are slice verification receipts. **Owner docs** are promoted only when accepted truth
  changes.

The specification describes **what the system needs to do**; issues describe **what work to pick up
next**. Do not turn each step in a feature's use-case flow into a new capability or issue.

Before drafting specs or GitHub issues, classify the capability and each child task as
Product/Runtime System, Builder System, or boundary work using
`docs/architecture/SBS_OPERATING_MODEL.md :: Builder System Boundary And Work Classification`.
Product/Runtime tasks route through Product owner docs and the SBS impact procedure. Builder System
tasks, including skill, issue/PR governance, CI/fitness, release/UAT, BuilderOps, learning, and TCD
work, route through the Builder System boundary/artifact map. Boundary tasks name both sides and must
not treat builder learning or BuilderOps records as runtime/user memory without Product System
authority.

When the input is accepted architecture-research or design material rather than an already
authoritative owner document/specification, require the upstream explicit disposition and durable
`PromotionIntent` accepted-transition `BuilderOpsReceipt` evidence before creating a specification
directory, parent feature issue, or child issue. Preserve its source reference in the handoff;
after materialization, record its result references and transition the same intent to `promoted`.
This check does not add a PromotionIntent wrapper to ordinary breakdown from an
already-authoritative, bounded owner document or specification.

One specification task can produce multiple issues when that matches the implementation boundary;
prefer one bounded slice per issue and preserve matching feature, capability, or contract acceptance.

## Naming and structure rules

Use human-first naming throughout. The goal is that someone browsing the docs tree can understand what each file is about without opening it.

Route by source level before using the templates below:

- For a **feature**, author or update its feature specification around the user outcome and
  subsystem composition; use a parent feature issue only when multiple slices need a shared
  end-to-end validation hub.
- For a **capability**, keep its reusable contract under its established Capability-subsystem owner
  path and use a parent capability issue only when that one typed function needs multiple slices.
- For a **cross-subsystem contract**, keep the normative contract in its canonical concept or
  subsystem owner path; create a parent contract issue only when coordinated slices need a shared
  policy/boundary validation hub.

The capability-specific directory, frontmatter, and task templates below apply to existing
capability breakdowns. Shared-state invariants apply to feature, capability, and contract
breakdowns; they do not turn a feature or cross-subsystem contract into a capability.

### Specification directory

For a feature decomposition, place the feature specification directory in `docs/`, not in hidden
directories. Preserve established paths for capability specifications, and do not create a second
directory that duplicates a cross-subsystem contract:

```
docs/{FEATURE_NAME}/
├── README.md                      # Overview, execution order, acceptance
├── {TASK_NAME}.md                 # One file per implementation task
├── {TASK_NAME}.md
└── ...
```

Name a feature directory after the user-facing outcome it specifies, using UPPER_SNAKE_CASE to
match existing doc conventions. Capability specification directories retain their established
capability name and owner path.

### Task file naming

Name each task file with a descriptive UPPER_SNAKE_CASE name that says what it does:

- `RESET_RUNTIME_STATE.md` — not `SLICE_01.md`
- `VERIFY_RUNTIME_HEALTH.md` — not `TASK_004.md`
- `INITIALIZE_TEST_VAULT.md` — not `02_vault.md`

No numeric prefixes, no "SLICE" or "TASK" labels. The name is the description.

### GitHub issue naming

When creating GitHub issues from capability task specs, use:

```
[{Capability}] {task-name}: {human description}
```

Example:
```
[Bootstrap] reset-runtime-state: clean state foundation
[Bootstrap] verify-runtime-health: deterministic readiness checks
```

### Frontmatter

Capability task files use this frontmatter. Feature and cross-subsystem contract task files follow
their owning specification's metadata shape and must not be relabeled as capabilities:

```yaml
---
name: {Human-Readable Task Name}
description: {one-line description}
task_id: {CAPABILITY-NN}
github_issue: {issue number, written back at filing time; absent only before the issue exists}
source_anchor: {docs path :: anchor}
parent_capability: {capability name}
prerequisites: [{task_id list}]
depends_on: [{filename list}]
can_parallelize_with: [{task name list}]
---
```

`github_issue:` is the machine join between the task doc and its filed slice issue (INV-DG-5,
#4444). It is not authored speculatively: the filing step below writes the created issue number
back into the frontmatter in the same delivery, so a filed task doc never carries an empty or
stale value.

### Task file structure

Each task specification must contain these sections:

- `# {Task Name}` — title matches the filename
- `## Purpose` — why this task exists (1–3 sentences)
- `## What This Task Does` — concrete behavior description
- `## Concretely` — example commands and expected output
- `## Why This Matters` — what breaks if this is wrong
- `## Acceptance Criteria` — checkboxes for definition of done; each AC carries an inline `Verify:` target (test pointer for behavioral ACs, doc/receipt target for non-behavioral ACs)
- `## How to Verify (Pre-Merge)` — concrete local and CI verification steps that execute the `Verify:` targets from `Acceptance Criteria`; the two sections are coupled and must stay consistent
- `## Out of Scope` — what this task does not do
- `## Restart / Durability Posture` (required only when the task ships a user-facing surface backed by deferred, in-memory, or otherwise non-durable state) — state explicitly what survives a process restart, what does not, and what the user experiences when it does not. Being honest that the state is in-memory is **not** sufficient for a user-facing surface; name the trust consequence (for example "reviewed items reappear unreviewed after restart").
- `## Related Docs` — links to parent plan, testing docs, implementation files
- `## Related GitHub Issues` — guidance for issue creation, not a template

AC verifiability rule for task specs:

- Every behavioral AC names the test that proves it (path and test name). New tests are acceptable — the name is the spec-level commitment.
- Every non-behavioral AC names a concrete observable target (doc writeback anchor, roadmap diff, runtime receipt).
- When a behavioral AC claims an **enforcement guarantee** — a guard, gate, or invariant that must hold on the live runtime path (for example "unreviewed memory cannot authorize writeback") — the named test must assert the guard is **invoked from its production call site**, not only that the guard function returns the right value in isolation. "Module exists + unit-tested" does not satisfy an enforcement AC; "wired into the runtime path and asserted there" does. The matching `## How to Verify (Pre-Merge)` step must execute that call-site assertion.
- If an AC cannot name either, the specification is still too coarse. Refine or split the task before creating issues.

### Cross-task invariants / interaction safety

When two or more tasks read or write the same state, the owning feature, capability, or contract
specification must carry a `## Cross-Task Invariants / Interaction Safety` section that states the
invariants holding *across* tasks and walks the **partial-failure paths** — what happens when one
task records a decision but the downstream task that should act on it is blocked, fails, or runs
out of order. Put the section in the appropriate specification README or canonical contract owner
doc; do not force every source level into a capability README. A breakdown whose tasks are each
locally correct can still lose data in the seam between them (for example a promote decision
recorded while its materialization is WriteGuard-blocked); this section names that seam and gives
it an invariant (for example "a promotion is terminal only once its artifact is materialized"). If
you cannot state the cross-task invariants, the slice boundaries are wrong — re-cut them before
creating issues.

## Real-life operating rules

- Use the matching parent validation issue as the live evidence hub after the first task merges; feature, capability, and contract acceptance remain distinct.
- Each delivered child posts a validation receipt to that matching parent issue before the next child is picked up.
- After creating or closing a capability parent issue on GitHub, update the local `docs/{CAPABILITY}/PARENT_FEATURE_ISSUE.md` header (preserving this legacy filename) so it reflects the live issue number and lifecycle state instead of remaining a pre-filing draft. For new feature or contract specs, use the appropriate issue-pointer surface without renaming the source level.
- In the same pass, update the relevant specification `README.md` so it does not continue to read as an unfiled draft/spec-only lane when the parent issue has already been filed or closed.
- Register each new feature or capability specification directory in `docs/DOCS_INDEX.md` during the same publication pass — add rows for the `README.md` and every task/spec file, not just the directory itself. A spec directory that ships unregistered is invisible to the canonical index and to builder-agent source routing (the repeated miss recorded from PR #3154 / PR #3167 / PR #3193). Cross-subsystem contracts stay in their canonical owner paths and should not be duplicated as a second directory.
- Place those rows under the `docs/DOCS_INDEX.md` section that matches the directory's actual document role. For a docs-only specification directory with a parent feature issue and bounded child slices, use `docs/DOCS_INDEX.md :: v6.0 Capability Specifications` as the default precedent; only choose a different section when the directory's role clearly belongs elsewhere. Do not restate the DOCS_INDEX role-map policy here — follow the section that owns it.
- Child issues should form an execution chain: each child should leave the matching feature, capability, or contract outcome closer to acceptance, and the final child must include a parent-closure handoff or create/link an explicit parent-closure issue.
- When the parent issue closes, reconcile all three local surfaces together:
  - matching issue-pointer header/body state
  - `README.md` state/status lines
  - `README.md` relationship-to-GitHub-issues section and the acceptance checklist for the matching source level
- Record post-merge validation as issue-body checklist progress or issue comments with links to runs, receipts, and operator notes.
- Keep owner docs stable while evidence is still accumulating.
- Open or update an owner-doc PR only when acceptance changes the supported truth the repo claims.
- Keep implementation tasks independently mergeable. If a task cannot be verified on its own, the breakdown is still too coarse.
- If the execution order cannot be explained as one flat ordered list, the source-level boundary is still too large or needs a plan before breaking down.
- One task specification can map to many GitHub issues. The spec is the source of truth, not the issue.
- Parent issues are validation hubs during delivery. After child delivery and repo-verifiable acceptance, close the parent and split future observation into a BuilderOps `LearningSignal`, `PromotionIntent`, discard/supersession receipt, or a follow-up GitHub Issue when it is executable work.

## When to trigger

Trigger this skill when any of the following are true:

- one docs item clearly spans multiple PRs or implementation surfaces
- one user-facing feature needs an end-to-end acceptance hub across multiple slices
- a cross-subsystem contract needs a policy/boundary validation hub across multiple slices
- a new mechanism has to preserve one invariant across several existing interaction sites, even if each local edit looks small
- the work needs one parent feature, capability, or contract outcome and several implementation tasks
- post-merge validation matters enough that a parent issue should remain open after task merges
- acceptance should be explicit before owner docs are promoted again

By contrast, additive work on a single surface that mirrors an existing pattern can stay a single bounded slice when it does not introduce a new cross-cutting invariant.

## First context to load

- `AGENTS.md`
- `docs/development/DEV_WORKFLOW.md`
- the most local owner docs named by the source material
- `.codex/skills/docs-to-issue/SKILL.md`
- `.codex/skills/issue-to-code/SKILL.md`
- `.codex/skills/verification-and-closure/SKILL.md`

## Authority order

1. Current-state owner docs and active SoT docs
2. Architecture docs
3. Roadmap / status / active plan docs
4. Existing feature or task issues, if already present

## Working procedure

1. Read the governing owner docs and classify the source as a user-facing feature, reusable capability, or cross-subsystem contract before choosing an issue shape.
2. Decide whether this should remain one bounded issue or become a specification directory with multiple implementation tasks. At the boundary and again after decomposition, apply `docs/development/DELIVERY_FEEDBACK_LOOP.md :: Cross-stage simplicity check`; if the child map adds untriggered mechanisms, return to scope correction instead of creating more tasks.
3. Search existing issues and PRs first so you do not create duplicates.
4. Define four things before creating anything:
   - the source-level outcome or contract behavior and its subsystem ownership
   - implementation tasks (human-named, not numbered, with the owning subsystem named)
   - verification path, including the test-or-receipt target for every behavioral and non-behavioral AC in every task
   - validation / acceptance path
5. Create or update the appropriate specification surface:
   - for a feature, use `docs/{FEATURE_NAME}/README.md` for the user outcome, flow, scope, subsystem composition, and acceptance path, with one task file per bounded implementation slice when needed;
   - for a capability, keep the typed contract under its established Capability-subsystem owner path and use the capability task template above when multiple slices are needed; and
   - for a cross-subsystem contract, update its canonical concept or subsystem owner doc and add linked task specs only when the owner surface needs them.
6. Decide where post-merge evidence will live:
   - the matching parent feature, capability, or contract issue body, comments, or both
   - owner-doc promotion trigger
7. If docs are still too vague, invoke `docs-governance` and its `docs-authoring` route to resolve the gaps within existing authority, then resume decomposition. A genuine missing owner decision uses `owner-decision-brief`; do not create weak specs.
8. Immediately before the first `gh issue create` (parent or child), run the **Live duplicate re-check — immediately before creation** step from `.codex/skills/docs-to-issue/SKILL.md :: Before creating any Issue`. The step-3 search is an analysis-time snapshot, and spec authoring (steps 4–7) leaves a wide gap in which a concurrent session can file the same backlog (seen 2026-07-29: hub #4286 + children #4287–#4292 duplicated by #4298–#4304).
9. Create or update the matching parent validation issue on GitHub (if needed); label its source level as feature, capability, or cross-subsystem contract.
   - If you create it, immediately update the appropriate local issue-pointer doc so it identifies the live GitHub issue as the authoritative backlog/validation surface. Preserve established filenames such as `PARENT_FEATURE_ISSUE.md` in existing capability specs.
   - In the same commit, update the relevant specification README so its `State:` line, matching acceptance checklist, and relationship-to-GitHub-issues section reflect the new issue state.
   - If the parent issue later closes, update the local pointer and specification README so neither reads as an unfiled or active draft and any satisfied acceptance checklist reflects the delivered truth.
10. Create or update GitHub issues from the task specifications, in dependency order.
    Immediately after each child `gh issue create`, write the created issue number back into that
    task doc's `github_issue:` frontmatter and include the writeback in the same breakdown
    commit/PR — the filing-time invariant INV-DG-5; a task doc with a filed issue must never
    leave the breakdown without its `github_issue:` key.
11. Keep authoritative labels truthful; Project status is optional projection:
    - parent feature, capability, or contract validation issues normally start with `agent:blocked`
    - ready tasks use `agent:ready` after strict validation
    - blocked tasks use `agent:blocked`
    - decision-dependent tasks use `agent:needs-human` only when a named human decision, tradeoff, missing input, or authority question is still open
12. Emit one clear breakdown receipt showing the matching parent validation issue, implementation tasks, evidence surface, and execution order.

## Parent feature issue requirements

Use this section for a parent feature issue: its acceptance is about the end-to-end user outcome.
For a parent capability issue, keep acceptance on the reusable function's typed contract and
subsystem ownership. For a parent contract issue, keep acceptance on the normative policy or
boundary and its subsystem responsibilities. Neither replaces another level's acceptance.

The parent feature issue must satisfy the canonical issue contract (`.codex/skills/_shared/ISSUE_CONTRACT.md` — section list and `Verify:` marker rule).

Add these extra sections for feature issues:

- `## Implementation Tasks` — links to spec directory and task files
- `## Verification Path`
- `## Validation / Acceptance Path`

Feature issue guidance:

- `Context` explains the user outcome and what docs define it.
- `Scope` defines the outcome boundary, not one PR.
- `Acceptance Criteria` define what must be true before the feature outcome can be claimed as supported. Each AC carries a `Verify:` marker — test pointer (behavioral) or doc/receipt target (non-behavioral).
- `Implementation Tasks` links to the specification directory and lists the bounded task files with their intended order.
- `Verification Path` defines the task-level proof surfaces.
- `Validation / Acceptance Path` defines the post-merge evidence, operator checks, and owner-doc promotion trigger.
- In live use, keep validation evidence in the parent issue itself rather than reopening owner docs for every rerun.

## GitHub issue requirements for implementation tasks

Each GitHub issue created from a task specification must use the canonical contract shape from `.codex/skills/_shared/ISSUE_CONTRACT.md`.

Issue guidance:

- keep each issue bounded enough for one agent and usually one PR
- mark each child execution context as `inline_deterministic` or `fresh_issue_agent`; every
  independent non-trivial child uses `fresh_issue_agent`, while `can_parallelize_with` describes
  scheduling independence rather than requiring concurrent execution
- give each issue a concrete acceptance target that can be verified pre-merge
- every AC on every issue carries a `Verify:` marker, matching the parent task spec: test pointer for behavioral ACs, doc/receipt target for non-behavioral ACs
- point back to the matching parent validation issue in `Context`
- reference the task specification using its actual source level and path, for example "Implements MEETING_CONTEXT_ASSISTANCE/RESOLVE_PARTICIPANT_CONTEXT" or the canonical capability/contract owner path
- persist the per-child TCD capability recommendation (execution context, issue-local helper budget
  `0|1`, model family + reasoning effort, and a one-line rationale) into the issue body `Context`, so
  the implementing `issue-to-code` agent reads it from the canonical task contract — not only from
  the breakdown response. Persist only source anchors, owner-doc refs, constraints, the `Verify:`
  ledger, and this compact hint — never the full parent narrative or planning transcript. It is a
  non-binding hint: `issue-to-code` still re-derives capability per `AGENTS.md :: Total Cost of
  Development` from the issue's risk and artifact class, so the route never silently drops at the
  handoff.
- do not make one issue responsible for the entire capability acceptance path
- one task specification may produce multiple issues if the implementation is large

## Real-life evidence surfaces

Use these surfaces deliberately:

- Specification docs: stable intent, constraints, acceptance criteria, and verification approach
- Matching parent validation issue: live validation log and acceptance checklist for the feature, capability, or contract
- GitHub issues: bounded execution contracts
- PRs: task verification receipts

This is the key rule that avoids unnecessary docs PR churn after merge.

Recommended habit:
- after each task merge, add one short validation receipt to the matching parent validation issue
- when acceptance is complete, open one owner-doc promotion PR that updates the stable repo claim

## Routing rules to other skills

- Use `docs-to-issue` when one docs item can become one bounded implementation issue directly.
- Use `feature-breakdown` when one docs item should become a specification directory plus implementation tasks.
- Use `issue-to-code` only on ready GitHub issues created from task specifications, not on the parent feature issue.
- Use `verification-and-closure` to verify task delivery, then validate the matching feature, capability, or contract acceptance and decide whether owner-doc promotion is warranted.


## Publication discipline

This lane writes specification directories and creates issues in the explicitly selected repository.
When a hub specification governs a constituent-repository delivery, name both repositories and keep
each lifecycle action targeted to its owner. When you commit and push those spec docs, route the
branch / commit / push / PR actions through `.codex/skills/publish-pr/SKILL.md` — do not run an ad
hoc commit/push from this skill. `publish-pr` owns the branch-truth gate.

Branch-truth gate (mandatory, same canonical gate as every lane) [branch-truth-gate]: run `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` — dedicated worktree preferred, capture `EXPECTED_BRANCH`/`EXPECTED_WORKTREE` at branch creation, hardened preflight with `--allow-dirty` before commit and again before push.

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output format

1. Source classification and subsystem ownership
2. Specification surfaces (path + files updated/created)
3. Matching parent validation issue (type and link, if created)
4. Bounded implementation tasks (with execution order)
5. Verification and matching acceptance path
6. Validation / Acceptance Path
7. Evidence Surface
8. Execution Order
9. GitHub Receipts
10. TCD Plan — for a non-trivial breakdown, emit a `tcd_plan` using `docs/development/TOTAL_COST_OF_DEVELOPMENT.md :: Output blocks`; a single bounded task needs only a one-line capability note, not the full block. Tie complexity, verification difficulty, defect blast radius, execution context, issue-local helper budget, context-cost estimate, scheduling (`can_parallelize_with`), and review gate to the slice cuts and per-AC verification depth decided above, and record the cheapest acceptable capability per child task so downstream `issue-to-code` routes model and reasoning honestly.

When creating issues, include:

- `FEATURE RECEIPT: Issue #123 created or updated as the parent feature issue.`
- `TASK RECEIPT: Issue #124 created from LOCAL_TEST_BOOTSTRAP/RESET_RUNTIME_STATE, label=agent:ready; optional Project repair: none.`

If no parent feature issue is needed, say so explicitly and explain why the work should remain a single bounded issue instead.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation`. Publish changed governing specifications
through `publish-pr`. When implementation is in scope, invoke `deliver-issue-set` for the child
chain, or `issue-to-code` for a single ready slice. Return verified specification and issue receipts
when the requested scope is breakdown only.
