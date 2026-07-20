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
- relevant repo-standard checks that cover the changed surface must be current, even when GitHub branch protection does not require them
- failing checks that cover the changed surface are hard stops until fixed, rerun green, or explicitly classified as unrelated by evidence; `Unit tests (not pg)` is a hard stop when red on an app/test/runtime-affecting PR

## PR Body Preparation

Before opening a PR, generate or preflight the body from lane inputs instead of reconstructing the
template by hand:

```bash
python3 scripts/pr_body_generator.py --input-json /path/to/pr-body-inputs.json > /tmp/pr-body.md
```

Use the generator for implementation, docs-authoring, governance, and direct-repair lanes when a PR
touches governance surfaces, closes an issue, or needs BuilderOps routing evidence. The generated
body remains editable before PR creation, but required lane inputs fail locally before any PR is
opened:

- implementation lane requires a linked issue;
- every body requires concrete SBS impact, validation, and owner-doc writeback resolution;
- issue-backed and direct-repair bodies require concrete BuilderOps routing lines;
- direct repair requires `Type`, `Reason`, `Validation`, and `Issue required: no`.

The generator does not weaken `pr-contract`, infer issues silently, open PRs, or write to GitHub. CI
remains the authority for whether the final PR body satisfies the repository contract.

## Multi-Issue PR Scope

Issue-backed PRs should normally close one child issue. A multi-issue PR is allowed only when every
child shares the same owner/review surface, validation set, rollback behavior, owner-doc writeback,
lane, and BuilderOps routing story. Use one closing keyword only for issues fully delivered by the
PR; list related children without closing keywords when they remain open or are only partially
addressed. The PR body must name the parent receipt expectation and explain why batching is safer
than separate PRs.

Never batch runtime behavior with governance/process changes, Product contract changes with Builder
System process edits, or children that need different reviewers, CI surfaces, rollback paths, or
owner-doc writebacks. The shared PR authority contract permits at most ten unique closing issues;
larger delivery sets must be split before publication so evidence collection and verification remain
bounded.

For an approved batch whose governing parent remains open, merge verification resolves every AC and
`Verify:` target on the exact closing children. The parent is validated as the governing issue-set
contract (batch authorization, child/scope map, shared constraints, source anchors, and validation
path); unfinished feature-acceptance ACs on that parent do not block delivery of completed children.
After merge, the owner-doc check leaves one PR-specific receipt on every closed child and on the
distinct open governing parent.

## Review-Before-CI

For every implementation and direct-repair PR, explicitly complete the TCD risk assessment before
the cheap local review gate, even when no high-risk surface applies. Supply every applicable
`--risk-surface`; omitting the option is not evidence that the change is low risk. High-risk work runs
the gate before its first expensive full suite as well as before push:

```bash
python3 scripts/review_before_ci_gate.py \
  --lane implementation \
  --changed-file app/example.py \
  --risk-assessment-complete \
  --risk-surface auth \
  --review-gate-complete
```

For docs-authoring and governance PRs, run the cheap local review gate before pushing or handing a
new PR head to expensive GitHub CI:

```bash
python3 scripts/review_before_ci_gate.py \
  --lane governance \
  --changed-file docs/development/PR_HOT_PATH.md \
  --review-gate-complete
```

The gate is a local ordering check: it exposes whether PR-body preflight, docs guard, and targeted
governance/contract review should run before CI waiting becomes the main feedback loop. It does not
replace required GitHub checks, branch protection, or final review triage.

An emergency direct repair may bypass the local gate only after an explicit completed risk
assessment finds no high-risk surface. A declared high-risk surface is never bypassable:

```bash
python3 scripts/review_before_ci_gate.py \
  --lane direct-repair \
  --changed-file docs/development/PR_HOT_PATH.md \
  --risk-assessment-complete \
  --bypass-reason "Emergency typo repair; receipt names skipped local gate."
```

## CI Status Handling

Use `scripts/await_pr_checks.sh` as the merge-gating wait path; it reads REST check-runs and classic
commit status with bounded sleeps and current-head verification. When a PR appears stuck before the
wait path reaches a terminal result, use the read-only classifier against the same REST check-runs
payload:

```bash
gh api "repos/<owner>/<repo>/commits/<sha>/check-runs?per_page=100" > /tmp/check-runs.json
python3 scripts/ci_stall_classifier.py \
  --check-runs-json /tmp/check-runs.json \
  --now "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```

Classifier output is advisory coordination evidence only:
- `wait`: pending checks are still within the bounded threshold; keep waiting with the REST/backoff
  path.
- `stalled`: queued or in-progress checks exceeded the threshold; record a CI-pending handoff or
  consider an explicit rerun workflow if one owns that action.
- `flaky_or_external_failure`: latest failed conclusions point to infrastructure-style behavior
  such as timeout/cancel/stale; rerun guidance is advisory and does not make the check acceptable.
- `actionable_failure`: latest failed checks need repair or failure-context collection, not waiting.
- `missing_checks`: expected checks have not attached yet; wait for attachment before trusting CI
  readiness.

The classifier must not bypass required checks, mark failures acceptable, auto-rerun workflows, or
poll GitHub. GitHub check conclusions and the PR head SHA remain the authority.

3. Review feedback triage
- after CI is green and current, fetch existing review comments before any handoff or merge recommendation; do not park the PR as "awaiting human review" until posted comments are classified
- branch protection is not the process gate: an unprotected branch or absent required-status-check rule does not waive the current-checks and review-feedback wait before merge
- do not run GraphQL `reviewThreads` closure sweeps by default
- run GraphQL review-thread closure checks only when triggered by a review-fix or direct-repair PR, a PR body or source anchor that names prior review feedback, a terminal issue/PR closure audit, or known unresolved review feedback
- blocking regression risk -> fix before merge
- valid non-blocking improvement -> fix if cheap, otherwise file a follow-up
- out-of-scope -> short response; follow-up only if useful
- incorrect or not applicable -> short response

4. Minimal delivery receipt
- record PR number, issue number(s), current head SHA, lane, risk, checks run, review classification, and next handoff
- record BuilderOps routing: records/projections/receipts created, or `none` with a short reason
- include enough traceability to prove the current delivery state without replaying the full procedure

## Default Non-Blockers

These are follow-up tasks, not default PR blockers:

- BuilderOps learning retrospective over `LearningSignal` records
- future adoption observation captured as `LearningSignal`, `PromotionIntent`, or a follow-up Issue
- owner-doc reflection
- full dependency scan
- board or project polish
- parent issue closure, unless this PR is the final child slice

## Issue-Backed vs Direct Repair PRs

Issue-backed PRs are required for normal planned work, delegated agent work, feature slices, runtime behavior changes, architecture changes, multi-step refactors, dependency-bearing work, and anything needing backlog tracking or parent/child acceptance.

Direct repair PRs are allowed without a governing issue when the change is bounded, immediate, and the PR body contains a complete Direct Repair block.

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
- direct repair block is complete
- no parent/child tracking needed
- no long-lived acceptance needed
- if scope expands, create or link an issue

## Direct Repair

Type: docs | governance | code
Reason: <one or two sentences>
Validation: <checks run>
Issue required: no — bounded immediate repair

## BuilderOps Routing

- Records/projections/receipts: <ids or "none">
- Reason: <why no BuilderOps material was created, or what was routed>

The `Direct Repair` block is the contract for bounded direct repair PRs. The `BuilderOps Routing`
section is mandatory delivery traceability for Tier 2+ PRs, not a second lane classifier. Tier 1
PRs (docs-authoring or governance lane, per `docs/development/GOVERNANCE_PROPORTIONALITY.md`) may
omit the section entirely when nothing was routed — absence means `none`.

- If the `Direct Repair` block is present and complete, no governing issue is required.
- If the `Direct Repair` block is present and complete, no separate lane checkbox is required.
- The merge receipt may reference the `Direct Repair` block instead of restating it.
- If the repair expands beyond bounded scope, create or link an issue.

Placement: prefer placing the `## Direct Repair` block first in the PR body (before `## Summary`) so it is immediately visible to reviewers. The governance check accepts the block in any position — first, middle, or last — regardless of whether a trailing newline follows.

## Governance Lane vs Direct Repair for Workflow Files

The Governance lane checkbox (`- [x] Governance lane`) has a narrow allowed-file set in `issue-pr-governance.yml`. It covers `docs/`, `.codex/skills/`, and a small set of exact files. It does **not** cover `.github/workflows/*.yml` files broadly — only `issue-pr-governance.yml` itself is in the exact-file allowlist.

Rule: any PR that changes `.github/workflows/` files other than `issue-pr-governance.yml` must use **Direct Repair** (not the Governance lane checkbox). Direct Repair bypasses the file restriction and is the correct path for bounded CI/workflow repairs.

Summary:
- `issue-pr-governance.yml` change → Governance lane or Direct Repair both work
- Any other `.github/workflows/*.yml` change → Direct Repair required
- `docs/**` or `.codex/skills/**` change → Governance lane or Direct Repair both work

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
- issue-backed merge neutralizes authenticated body closers immediately before the exact-head merge,
  revalidates the neutralized live body/head/closing links and requires `pr-contract` to authenticate
  its trusted exact-head authority receipt, uses a fixed non-closing merge message,
  persists trusted authority plus continuous prepared/merged/reconciled/restored phases, explicitly
  closes only the authenticated issue set, reconciles any body-race closure attributable to that PR,
  proves every and only authenticated issue is closed with delivery attribution, restores the
  authenticated body, resumes an open neutralized `prepared` window from exact receipt/body/phase
  truth, and resumes a crashed post-merge sequence idempotently without resetting attempts or the
  2+2 repair budget. Explicit expected-issue closes require a null closer plus the delivery actor/time
  fence; automatic closes require the exact target PR/repository/merge SHA
- branch/worktree sanity before commit, push, or merge
- required and relevant repo-standard checks must be known and non-stale
- blocking review feedback must be addressed or explicitly classified
- review-thread closure checks are trigger-based; ordinary PRs without prior-review anchors or known unresolved feedback stay on the lightweight hot path
- failing required tests or checks must be classified before merge; failing relevant repo-standard checks cannot be bypassed just because the branch is unprotected
- minimal delivery receipt is required
- delivery traceability must be preserved through either an issue-backed PR or a direct repair block
