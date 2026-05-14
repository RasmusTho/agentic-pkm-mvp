State: Development reference. Default PR delivery hot path.
Doc role: Hot-path reference
Authority: Default PR workflow for normal delivery; escalates to `PR_ESCALATION_PATHS.md` only when a trigger applies.
Owner: Builder-agent governance
Temporal class: operational

# PR Hot Path

Use this document first for normal PR delivery. It is intentionally short.
If any escalation trigger applies, stop and read [`PR_ESCALATION_PATHS.md`](PR_ESCALATION_PATHS.md) before proceeding.

## Quick Classification

Fill these out before deciding whether the PR stays on the hot path:

- `lane`: `docs` | `code` | `governance` | `maintenance` | `promotion`
- `risk`: `low` | `normal` | `high`
- `touches_runtime`: `yes` | `no`
- `touches_ci_or_skills`: `yes` | `no`
- `closes_issue`: `yes` | `no`

Default rule:
- if the PR is low-risk and does not touch runtime, CI, skills, migrations, APIs, or public contracts, stay on the hot path
- if any escalation trigger is true, use the escalation path instead of adding heavyweight checks here

## Mandatory Hot-Path Gates

1. Branch, worktree, and current-SHA sanity
- confirm the active worktree is the PR worktree
- confirm local branch name matches the PR head branch before commit or push
- confirm local `HEAD`, tracked remote branch, and PR head SHA agree before trusting CI attachment or merge readiness
- if they do not agree, stop and recover branch truth first

2. Relevant checks for lane and risk
- run the smallest checks that still cover the changed surface
- do not expand into a full governance sweep for a low-risk PR
- required checks must be known, current, and attached to the current head SHA
- failing checks must be classified before merge

3. Review feedback triage
- blocking regression risk -> fix before merge
- valid non-blocking improvement -> fix if cheap, otherwise file a follow-up
- out-of-scope -> short response; follow-up only if useful
- incorrect or not applicable -> short response

4. Minimal delivery receipt
- record PR number, issue number(s), current head SHA, lane, risk, checks run, review classification, and next handoff
- include enough traceability to prove the current delivery state without replaying the full procedure

## Default Non-Blockers

These are follow-up tasks, not default PR blockers:

- learning-log retro
- future adoption observation
- owner-doc reflection
- full dependency scan
- board or project polish
- parent issue closure, unless this PR is the final child slice

## Issue-Backed vs Direct Repair PRs

Issue-backed PRs are required for normal planned work, delegated agent work, feature slices, runtime behavior changes, architecture changes, multi-step refactors, dependency-bearing work, and anything needing backlog tracking or parent/child acceptance.

Direct repair PRs are allowed without a governing issue when the change is bounded, immediate, and the PR body can serve as the full contract.

Direct repair examples:

- typo or wording fix
- small docs correction
- broken link
- minor skill routing clarification
- small review-fix
- small governance friction fix
- obvious cleanup discovered during current work

Direct repair guardrails:

- bounded change
- clear rationale in PR body
- validation listed in PR body
- no parent/child tracking needed
- no long-lived acceptance needed
- if scope expands, create or link an issue

Minimal PR body shape:

## Direct PR Rationale
No governing issue is used because this is a bounded immediate repair.

Reason:
- ...

Validation:
- ...

## Escalation Triggers

Read [`PR_ESCALATION_PATHS.md`](PR_ESCALATION_PATHS.md) when any of these apply:

- CI or test failure
- blocking review feedback
- runtime, CI, migration, API, public contract, or behavior-changing skill changes
- large or mixed-scope PR
- stale SHA, branch drift, or merge conflict
- missing delivery traceability for a PR that is not a valid direct repair PR
- final child slice of a parent issue

Low-risk wording or reference-only skill edits may stay on the hot path if safety invariants remain intact.

## Safety Invariants

- current SHA truth before merge
- branch/worktree sanity before commit, push, or merge
- required checks must be known and non-stale
- blocking review feedback must be addressed or explicitly classified
- failing required tests or checks must be classified before merge
- minimal delivery receipt is required
- delivery traceability must be preserved through either an issue-backed PR or a direct repair PR rationale
