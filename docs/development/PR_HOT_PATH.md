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

- `lane`: `docs-authoring` | `implementation` | `governance` | `direct-repair`
- `risk`: `low` | `normal` | `high`
- `touches_runtime`: `yes` | `no`
- `touches_ci`: `yes` | `no`
- `changes_skill_behavior`: `yes` | `no`
- `closes_issue`: `yes` | `no`

Promotion is not a PR hot-path lane. Route release-channel work through `prepare-promotion`,
`execute-promotion`, `verify-promotion`, or `rollback-promotion` as applicable; those skills own its
operator gates and evidence model.

Default rule:
- low-risk docs, governance, and skill-text changes stay on the hot path
- touching a skill does not itself escalate delivery depth; escalate only when the skill change
  alters high-risk runtime/release behavior or another trigger below applies
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

`.codex/skills/publish-pr/SKILL.md :: Step 6` is the authoritative source of the four PR-body
templates (implementation, docs-authoring, governance, direct-repair) actually used at publication
time. Copy the template for the chosen lane directly from that step. Each template already carries
the fields the `pr-contract` gate requires — a single `Final-Review-Rounds: 0` (light delivery path per `AGENTS.md :: Proportional delivery`), `1`, or `2` line, a
filled `## BuilderOps Routing` section with no `<...>` placeholder, and, for direct repair, the
complete `Type:` / `Reason:` / `Validation:` / `Issue required: no` block — so an agent that copies
one of them and fills in the bracketed content satisfies the gate by construction.

`scripts/pr_body_generator.py` implements the same field contract as a standalone generator
(`--input-json` in, a complete body out) and is available for ad hoc preflight or drift-checking
against these templates, but no skill invokes it as part of the publication path. Wiring
`publish-pr` to the generator is deliberately out of scope for now: the generator hard-enforces the
full 16-field `SBS Impact` block (`docs/architecture/SBS_OPERATING_MODEL.md`), and that block's
contract is under an open owner ruling tracked outside this doc — wiring the generator in before
that ruling lands would cement a contract that may be about to change. Revisit this section once
the ruling lands. Whichever source is used — skill template or generator — required lane inputs must
be concrete before any PR is opened:

- implementation lane requires a linked issue;
- closing authority must be declared only on a dedicated `Fixes #<id>`, `Closes #<id>`, or
  `Resolves #<id>` line; narrative prose must never place a closing keyword directly adjacent to
  `#<id>`;
- every body requires concrete SBS impact, validation, and owner-doc writeback resolution;
- issue-backed and direct-repair bodies require concrete BuilderOps routing lines;
- direct repair requires `Type`, `Reason`, `Validation`, and `Issue required: no`.

Neither the skill templates nor the generator weaken `pr-contract`, infer issues silently, open PRs,
or write to GitHub. CI remains the authority for whether the final PR body satisfies the repository
contract.

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

For every implementation, governance, and direct-repair PR, explicitly complete the TCD risk assessment before
the cheap local review gate, even when no high-risk surface applies. Supply every applicable
`--risk-surface`; omitting the option is not evidence that the change is low risk. High-risk work runs
the gate before its first expensive validation as well as before push. Validation remains
affected-subsystem scoped; high risk strengthens ordering and review, but does not by itself mandate
a repo-wide full suite:

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
  --risk-assessment-complete \
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
- P0/P1 correctness, contract, or safety defect -> block merge, fix, and independently re-review
- P2 real defect accepted for this PR -> leave the PR code unchanged for that finding, route it
  through `bug-to-issue`, reply on the finding/thread with the Issue reference, and merge without
  another review round once the durable disposition is live
- P3 informational advice or non-defect suggestion -> record when useful; do not block, repair, or
  open defect intake
- out-of-scope -> short response; follow-up only if useful
- incorrect or not applicable -> short response

The protected severity floors and dispatcher receipt compatibility rule are normative in
`.codex/skills/verification-and-closure/SKILL.md :: Severity routing`. There is no valid
`blocking P2`.

Compatibility for the current `pr-integration` consumer: its legacy `cheap fix` bucket is not a
fifth severity and does not include P2/P3. Read `cheap fix`, `review-feedback repair`, and
`fixing commit` there as P0/P1 blocking-repair concepts only. `pr-integration` requires
classification with this hot path first, so a true P2 follows the Issue/thread disposition above
and never requires a fixing commit; P3 remains informational. A secondary skill's abbreviated
bucket list cannot override this canonical routing.

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
  truth, and resumes a crashed post-merge sequence idempotently without resetting attempts or repair
  accounting. Explicit expected-issue closes require a null closer plus the delivery actor/time
  fence; automatic closes require the exact target PR/repository/merge SHA
- a neutralized PR body may not outlive its merge attempt: neutralization requires a head-bound
  readiness statement that CI and review are green and no further commits are anticipated, and a head
  change while the body is still neutralized requires restoring the canonical body before further
  repair work
- branch/worktree sanity before commit, push, or merge
- required and relevant repo-standard checks must be known and non-stale
- blocking review feedback must be addressed or explicitly classified
- review-thread closure checks are trigger-based; ordinary PRs without prior-review anchors or known unresolved feedback stay on the lightweight hot path
- failing required tests or checks must be classified before merge; failing relevant repo-standard checks cannot be bypassed just because the branch is unprotected
- minimal delivery receipt is required
- delivery traceability must be preserved through either an issue-backed PR or a direct repair block
