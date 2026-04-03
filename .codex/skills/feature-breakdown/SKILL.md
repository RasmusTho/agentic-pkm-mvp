---
name: feature-breakdown
description: "Break a docs-defined feature or capability into one parent feature issue plus bounded child slice issues, with explicit verification, validation, and acceptance paths."
---

# Feature Breakdown

Use this skill when a docs-defined feature is too large for one implementation issue or when the work needs post-merge validation before owner docs should claim it as supported.

Do not use this skill for:

- a single already-bounded implementation issue
- direct coding from an existing ready slice
- vague roadmap cleanup without an actionable feature boundary

## Canonical workflow

`Docs -> Feature issue -> Slice issues -> Agent -> PR -> PR integration -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

## Practical modes

- `enrich-docs`: tighten the feature boundary, verification path, and validation / acceptance path in docs before backlog creation.
- `create-or-update-breakdown`: create or update the parent feature issue plus bounded child slices once the docs are clear enough.

## Core model

- Feature issue: parent issue for the target outcome.
- Slice issue: bounded child issue, usually one PR-sized implementation unit.
- PR: slice verification receipt.
- Feature issue: live validation evidence and acceptance checklist.
- Owner docs: promoted only when accepted truth changes.

Practical rule:
- slices may close at merge
- the parent feature issue may stay open after merge until validation and acceptance are complete
- do not create a new docs PR for every post-merge rerun; update owner docs when the support claim changes

## Real-life operating rules

- Use the parent feature issue as the live validation hub after the first slice merges.
- Record post-merge validation as issue-body checklist progress or issue comments with links to runs, receipts, and operator notes.
- Keep owner docs stable while evidence is still accumulating.
- Open or update an owner-doc PR only when acceptance changes the supported truth the repo claims.
- Keep slices independently mergeable. If a slice cannot be verified on its own, the breakdown is still too coarse.
- If the execution order cannot be explained as one flat ordered list, the feature boundary is still too large or needs a plan before slicing.

## When to trigger

Trigger this skill when any of the following are true:

- one docs item clearly spans multiple PRs or implementation surfaces
- the work needs one parent feature outcome and several child slices
- post-merge validation matters enough that a parent issue should remain open after slice merges
- acceptance should be explicit before owner docs are promoted again

## First context to load

- `AGENTS.md`
- `docs/development/DEV_WORKFLOW.md`
- the most local owner docs named by the source material
- `.codex/skills/docs-to-issue/SKILL.md`
- `.codex/skills/issue-to-code/SKILL.md`
- `.codex/skills/verification-validation-feedback/SKILL.md`

## Authority order

1. Current-state owner docs and active SoT docs
2. Architecture docs
3. Roadmap / status / active plan docs
4. Existing feature or slice issues, if already present

## Working procedure

1. Read the governing docs and identify one concrete feature boundary.
2. Decide whether this should remain one bounded issue or become one parent feature issue plus child slices.
3. Search existing issues and PRs first so you do not create duplicates.
4. Define four things before creating anything:
   - feature intent
   - child slices
   - verification path
   - validation / acceptance path
5. Decide where post-merge evidence will live:
   - parent feature issue body, comments, or both
   - owner-doc promotion trigger
6. If docs are still too vague, stop at `enrich-docs` instead of creating weak Issues.
7. Create or update the parent feature issue.
8. Create or update the child slice issues in dependency order.
9. Keep labels and Project status truthful:
   - parent feature issue normally starts as `Backlog` plus `agent:needs-human`
   - ready slices use `Status=Ready` plus `agent:ready`
   - blocked or decision-dependent slices use `agent:blocked` or `agent:needs-human`
10. Emit one clear breakdown receipt showing the parent feature issue, child slices, evidence surface, and execution order.

## Feature issue requirements

The parent feature issue must still satisfy the repo issue contract and contain these required sections:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

Add these extra sections for feature issues:

- `## Child Slices`
- `## Verification Path`
- `## Validation / Acceptance Path`

Feature issue guidance:

- `Context` explains why the feature exists and what docs define it.
- `Scope` defines the outcome boundary, not one PR.
- `Acceptance Criteria` define what must be true before the feature can be claimed as supported.
- `Child Slices` list the bounded implementation issues and their intended order.
- `Verification Path` defines the slice-level proof surfaces.
- `Validation / Acceptance Path` defines the post-merge evidence, operator checks, and owner-doc promotion trigger.
- In live use, keep validation evidence in the parent issue itself rather than reopening owner docs for every rerun.

## Slice issue requirements

Each child slice issue must use the standard repo contract shape:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`

Slice issue guidance:

- keep each slice bounded enough for one agent and usually one PR
- give each slice a concrete acceptance target that can be verified pre-merge
- point back to the parent feature issue in `Context`
- do not make a child slice responsible for the entire feature acceptance path

## Real-life evidence surfaces

Use these surfaces deliberately:

- Docs: stable intent, constraints, and support claims
- Feature issue: live validation log and acceptance checklist
- Slice issues: bounded execution contracts
- PRs: slice verification receipts

This is the key rule that avoids unnecessary docs PR churn after merge.

Recommended habit:
- after each slice merge, add one short validation receipt to the parent feature issue
- when acceptance is complete, open one owner-doc promotion PR that updates the stable repo claim

## Routing rules to other skills

- Use `docs-to-issue` when one docs item can become one bounded implementation issue directly.
- Use `feature-breakdown` when one docs item should become one parent feature plus child slices.
- Use `issue-to-code` only on ready child slices, not on the parent feature issue.
- Use `verification-validation-feedback` to verify slice delivery, then validate the parent feature and decide whether owner-doc promotion is warranted.

## Output format

1. Feature Boundary
2. Parent Feature Issue
3. Child Slice Issues
4. Verification Path
5. Validation / Acceptance Path
6. Evidence Surface
7. Execution Order
8. GitHub Receipts

When creating issues, include:

- `FEATURE RECEIPT: Issue #123 created or updated as the parent feature issue.`
- `SLICE RECEIPT: Issue #124 created, Status=Ready, label=agent:ready.`

If no parent feature issue is needed, say so explicitly and explain why the work should remain a single bounded issue instead.
