---
name: feature-breakdown
description: "Break a docs-defined capability into a specification directory with bounded implementation tasks, then create GitHub issues from those specs."
---

# Feature Breakdown

Use this skill when a docs-defined capability is too large for one implementation issue or when the work needs post-merge validation before owner docs should claim it as supported.

Do not use this skill for:

- a single already-bounded implementation issue
- direct coding from an existing ready task
- vague roadmap cleanup without an actionable capability boundary

## Canonical workflow

`Docs -> Specification -> Implementation tasks -> GitHub issues -> Agent -> PR -> PR integration -> CI -> Task verification -> Merge -> Capability validation -> Acceptance -> Owner Doc`

## Practical modes

- `enrich-docs`: tighten the capability boundary, verification path, and validation / acceptance path in docs before creating specs or issues.
- `create-or-update-breakdown`: create or update the specification directory plus bounded implementation tasks once the docs are clear enough.

## Core model

- **Specification directory**: a `docs/` directory that is the system-level source of truth for what needs to be built. Contains a README and one file per implementation task. This is not a plan — it is a specification.
- **Implementation task**: a specification document describing a discrete capability, its acceptance criteria, verification approach, and completion criteria. One task specification can map to one or many GitHub issues depending on implementation choices.
- **GitHub issues**: execution artifacts that reference the specification. The spec is the source of truth; the issues track backlog state and agent pickup.
- **Parent feature issue**: optional parent issue for the target outcome. Used as the live validation hub when the capability spans multiple tasks; while child slices are outstanding it is a blocked validation hub, not a direct pickup issue.
- **PRs**: task verification receipts.
- **Owner docs**: promoted only when accepted truth changes.

Key distinction:
- The specification describes **what the system needs to do**.
- The GitHub issues describe **what work to pick up next**.
- One specification task can produce multiple issues if the implementation is large enough.

## Naming and structure rules

Use human-first naming throughout. The goal is that someone browsing the docs tree can understand what each file is about without opening it.

### Specification directory

Place the specification directory in `docs/`, not in hidden directories:

```
docs/{CAPABILITY_NAME}/
├── README.md                      # Overview, execution order, acceptance
├── {TASK_NAME}.md                 # One file per implementation task
├── {TASK_NAME}.md
└── ...
```

Name the directory after the capability it specifies, using UPPER_SNAKE_CASE to match existing doc conventions.

### Task file naming

Name each task file with a descriptive UPPER_SNAKE_CASE name that says what it does:

- `RESET_RUNTIME_STATE.md` — not `SLICE_01.md`
- `VERIFY_RUNTIME_HEALTH.md` — not `TASK_004.md`
- `INITIALIZE_TEST_VAULT.md` — not `02_vault.md`

No numeric prefixes, no "SLICE" or "TASK" labels. The name is the description.

### GitHub issue naming

When creating GitHub issues from specs, use:

```
[{Capability}] {task-name}: {human description}
```

Example:
```
[Bootstrap] reset-runtime-state: clean state foundation
[Bootstrap] verify-runtime-health: deterministic readiness checks
```

### Frontmatter

Each task file uses this frontmatter:

```yaml
---
name: {Human-Readable Task Name}
description: {one-line description}
task_id: {CAPABILITY-NN}
source_anchor: {docs path :: anchor}
parent_capability: {capability name}
prerequisites: [{task_id list}]
depends_on: [{filename list}]
can_parallelize_with: [{task name list}]
---
```

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
- `## Related Docs` — links to parent plan, testing docs, implementation files
- `## Related GitHub Issues` — guidance for issue creation, not a template

AC verifiability rule for task specs:

- Every behavioral AC names the test that proves it (path and test name). New tests are acceptable — the name is the spec-level commitment.
- Every non-behavioral AC names a concrete observable target (doc writeback anchor, roadmap diff, runtime receipt).
- If an AC cannot name either, the specification is still too coarse. Refine or split the task before creating issues.

## Real-life operating rules

- Use the parent feature issue as the live validation hub after the first task merges.
- Each delivered child posts a validation receipt to the parent issue before the next child is picked up.
- After creating or closing the parent feature issue on GitHub, update the local `docs/{CAPABILITY}/PARENT_FEATURE_ISSUE.md` header so it reflects the live issue number and lifecycle state instead of remaining a pre-filing draft.
- In the same pass, update the capability `README.md` so it does not continue to read as an unfiled draft/spec-only lane when the parent issue has already been filed or closed.
- Child issues should form an execution chain: each child should leave the capability closer to acceptance, and the final child must include a parent-closure handoff or create/link an explicit parent-closure issue.
- When the parent issue closes, reconcile all three local surfaces together:
  - `PARENT_FEATURE_ISSUE.md` header/body state
  - `README.md` state/status lines
  - `README.md` relationship-to-GitHub-issues section and any capability-level acceptance checklist that is now satisfied
- Record post-merge validation as issue-body checklist progress or issue comments with links to runs, receipts, and operator notes.
- Keep owner docs stable while evidence is still accumulating.
- Open or update an owner-doc PR only when acceptance changes the supported truth the repo claims.
- Keep implementation tasks independently mergeable. If a task cannot be verified on its own, the breakdown is still too coarse.
- If the execution order cannot be explained as one flat ordered list, the capability boundary is still too large or needs a plan before breaking down.
- One task specification can map to many GitHub issues. The spec is the source of truth, not the issue.
- Parent issues are validation hubs during delivery. After child delivery and repo-verifiable acceptance, close the parent and split future observation into a follow-up issue or learning-log item.

## When to trigger

Trigger this skill when any of the following are true:

- one docs item clearly spans multiple PRs or implementation surfaces
- the work needs one parent capability outcome and several implementation tasks
- post-merge validation matters enough that a parent issue should remain open after task merges
- acceptance should be explicit before owner docs are promoted again

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

1. Read the governing docs and identify one concrete capability boundary.
2. Decide whether this should remain one bounded issue or become a specification directory with multiple implementation tasks.
3. Search existing issues and PRs first so you do not create duplicates.
4. Define four things before creating anything:
   - capability intent
   - implementation tasks (human-named, not numbered)
   - verification path, including the test-or-receipt target for every behavioral and non-behavioral AC in every task
   - validation / acceptance path
5. Create the specification directory under `docs/{CAPABILITY_NAME}/` with:
   - `README.md` — overview, task list with links, execution order, acceptance criteria, relationship to GitHub issues
   - One `.md` file per implementation task, named after what it does
6. Decide where post-merge evidence will live:
   - parent feature issue body, comments, or both
   - owner-doc promotion trigger
7. If docs are still too vague, stop at `enrich-docs` instead of creating weak specs.
8. Create or update the parent feature issue on GitHub (if needed).
   - If you create it, immediately update the local `PARENT_FEATURE_ISSUE.md` to state that the GitHub issue now exists and is the authoritative backlog/validation surface.
   - In the same commit, update the capability `README.md` so its `State:` line and relationship-to-GitHub-issues section match the new GitHub issue state.
   - If the GitHub parent issue later closes, update the local `PARENT_FEATURE_ISSUE.md` again so it no longer reads as an unfiled or active draft.
   - When closing, also update the capability `README.md` so it no longer reads as an active pre-delivery lane and so any now-satisfied acceptance checklist truthfully reflects the delivered docs/spec state.
9. Create or update GitHub issues from the task specifications, in dependency order.
10. Keep labels and Project status truthful:
    - parent feature issue normally starts as `Backlog` plus `agent:blocked`
    - ready tasks use `Status=Ready` plus `agent:ready`
    - blocked tasks use `agent:blocked`
    - decision-dependent tasks use `agent:needs-human` only when a named human decision, tradeoff, missing input, or authority question is still open
11. Emit one clear breakdown receipt showing the parent feature issue, implementation tasks, evidence surface, and execution order.

## Parent feature issue requirements

The parent feature issue must satisfy the repo issue contract and contain these required sections:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

Add these extra sections for feature issues:

- `## Implementation Tasks` — links to spec directory and task files
- `## Verification Path`
- `## Validation / Acceptance Path`

Feature issue guidance:

- `Context` explains why the capability exists and what docs define it.
- `Scope` defines the outcome boundary, not one PR.
- `Acceptance Criteria` define what must be true before the capability can be claimed as supported. Each AC carries a `Verify:` marker — test pointer (behavioral) or doc/receipt target (non-behavioral).
- `Implementation Tasks` links to the specification directory and lists the bounded task files with their intended order.
- `Verification Path` defines the task-level proof surfaces.
- `Validation / Acceptance Path` defines the post-merge evidence, operator checks, and owner-doc promotion trigger.
- In live use, keep validation evidence in the parent issue itself rather than reopening owner docs for every rerun.

## GitHub issue requirements for implementation tasks

Each GitHub issue created from a task specification must use the standard repo contract shape:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

Issue guidance:

- keep each issue bounded enough for one agent and usually one PR
- give each issue a concrete acceptance target that can be verified pre-merge
- every AC on every issue carries a `Verify:` marker, matching the parent task spec: test pointer for behavioral ACs, doc/receipt target for non-behavioral ACs
- point back to the parent feature issue in `Context`
- reference the task specification: "Implements {CAPABILITY}/{TASK_NAME}"
- do not make one issue responsible for the entire capability acceptance path
- one task specification may produce multiple issues if the implementation is large

## Real-life evidence surfaces

Use these surfaces deliberately:

- Specification docs: stable intent, constraints, acceptance criteria, and verification approach
- Feature issue: live validation log and acceptance checklist
- GitHub issues: bounded execution contracts
- PRs: task verification receipts

This is the key rule that avoids unnecessary docs PR churn after merge.

Recommended habit:
- after each task merge, add one short validation receipt to the parent feature issue
- when acceptance is complete, open one owner-doc promotion PR that updates the stable repo claim

## Routing rules to other skills

- Use `docs-to-issue` when one docs item can become one bounded implementation issue directly.
- Use `feature-breakdown` when one docs item should become a specification directory plus implementation tasks.
- Use `issue-to-code` only on ready GitHub issues created from task specifications, not on the parent feature issue.
- Use `verification-and-closure` to verify task delivery, then validate the parent capability and decide whether owner-doc promotion is warranted.


## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

1. Capability Boundary
2. Specification Directory (path + file listing)
3. Parent Feature Issue (if created)
4. Implementation Tasks (from spec, with execution order)
5. Verification Path
6. Validation / Acceptance Path
7. Evidence Surface
8. Execution Order
9. GitHub Receipts

When creating issues, include:

- `FEATURE RECEIPT: Issue #123 created or updated as the parent feature issue.`
- `TASK RECEIPT: Issue #124 created from LOCAL_TEST_BOOTSTRAP/RESET_RUNTIME_STATE, Status=Ready, label=agent:ready.`

If no parent feature issue is needed, say so explicitly and explain why the work should remain a single bounded issue instead.
