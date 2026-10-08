---
name: publish-pr
description: "Create or update the implementation, docs, or governance PR after local changes are ready."
---

# Publish PR

Use this skill only at the branch/commit/push/PR boundary. Implementation, claim, validation,
review repair, merge, Issue closure, image publication, and deployment remain with their owning
workflows. Never publish unrelated changes or bypass a failed command.

## Entry conditions

- The lane and governing contract are known and the local change is complete enough to publish.
- Focused checks have passed; BuilderOps routing and owner-doc resolution are concrete.
- The dedicated worktree, intended branch, base, file set, commit intent, PR title, and generated PR
  body inputs are explicit. Commit messages may use `Refs #<id>` but no closing-keyword reference.
- TCD risk classification is complete. A declared high-risk surface routes to the full path below;
  it is not supported by the normal command.

## Supported path and exception routing

The command path supports **bounded native Tier 1/2 publication targeting `main`** in the
`implementation`, `docs-authoring`, or `governance` lane, with `Final-Review-Rounds: 0` or `1` and
no declared high-risk surface. This includes issue-free docs/governance work, resumed linear
candidates, one explicitly named existing open PR, and explicit batches of at most ten unique
closing Issues. Review depth does not request executor ownership.

It binds canonical credential-free fetch/push repository identities and one live `main` SHA agreed
by local `origin/main`, remote readback, and GitHub REST. Every committed path since that base,
including reverted paths, and every dirty path must fit the explicit intended set. New PRs require
an absent remote head and empty all-state history. Existing updates require `--existing-pr-number`,
one exact open PR, matching repository/base/head/lane/Issue scope and local/remote heads, and the
existing PR scope-revalidation gate. Updates make only additive commits and non-force pushes;
metadata is changed only after exact current-head readback. Unrelated dirty paths are preserved by
refusing before staging.

`.codex/skills/publish-pr/FULL_PATH.md :: Procedure` is the canonical full-path publication owner.
Route every unsupported case there without trying to coerce it into the normal command:

- existing-PR repair that cannot satisfy exact native binding -> `pr-integration` and
  `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: PR-Level Scope Revalidation Gate`;
- multi-Issue scope follows `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope` and
  `verification-and-closure :: Routing`;
- Direct Repair or issue-free work outside the supported lanes -> the matching current lane contract in
  `docs/development/PR_HOT_PATH.md`;
- Tier 3, full-path, or any auth/security/data/migration/concurrency/external-API/
  credential-durability/state-machine risk ->
  `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate`, then
  the current reviewed publication path;
- verified-merge PR-body neutralization/restoration, merge, or Issue closure ->
  `verification-and-closure`;
- candidate image, UAT channel, release, deploy, promotion, or rollback -> the release/promotion
  skills; ordinary PR publication never performs those effects;
- closure plan/apply, context-pack generation, claim/worktree wrapping, or serial composition ->
  their owning workflows, not this adapter;
- transport defect #5123 or another ambiguous transport result -> preserve the live evidence and
  stop on the current governed path; do not add a workaround or blind retry.

## Publication preflight — live open-PR overlap re-check

The native plan reads open, closed, and merged history for the exact head branch. New publication
requires empty history; an update binds one explicitly requested exact open PR. Apply accepts only
that bound history or one uniquely reconcilable exact new open PR; exact
closed/merged history is terminal and mismatch/duplicates are `unknown`. Full-path publication must
perform the equivalent live all-state read immediately before creation; an earlier snapshot is not
collision evidence.

## Publication workflow (all steps are executable)

Prepare one JSON object accepted by `scripts/pr_body_generator.py`; it remains the PR-body policy
owner. Keep the plan file outside the intended commit set.

```bash
python3 scripts/publication.py plan \
  --repository <owner/repo> \
  --worktree <absolute-dedicated-worktree> \
  --branch <branch> \
  --base-ref main \
  --path <intended-path> \
  --lane <implementation|docs-authoring|governance> \
  --tier <1|2> \
  --risk-assessment-complete \
  --review-gate-complete \
  --governing-issue <number> \
  --commit-message <message> \
  --pr-title <title> \
  --pr-body-input-json <input.json>
```

Omit `--governing-issue` only for issue-free docs/governance work. Supply repeated `--closing-issue`
arguments for an explicit batch; they must agree with body input `closing_issues` when supplied.
The body still carries exactly one `Governing-Issue`; a distinct parent is not closed automatically.
Add `--existing-pr-number` only for a verified exact open PR update. A resumed candidate may already
contain bounded commits or be clean; the plan binds the complete candidate and any additive dirty
change. Merge commits and unrelated history use the protected full path.

The two completion flags are explicit caller attestations, not defaults; supply them only after the
named local prerequisites have actually completed. `plan` is read-only. It emits canonical
`builder.publication-plan.v1` JSON whose
`plan_sha256` binds strict fetch/push repository identities, canonical worktree, branch, live `main`
SHA, exact paths and content, Issue authority, lane/risk inputs, commit intent, title, generated
body, and body digest, including any existing PR's observed identity and metadata. Raw remote URLs
are neither retained nor emitted. Inspect the plan and retain
its exact hash; any unsupported state or drift routes through the exception list.

Apply only that exact plan:

```bash
python3 scripts/publication.py apply \
  --plan-file <plan.json> \
  --expected-plan-sha256 <64-hex-plan-sha256>
```

`apply` stages only planned paths, creates an additive sole-parent commit when dirty changes exist,
and runs the existing
workspace/review/PR-body gates. Before every external transition it revalidates the strict authority,
bound parent, exact governing/closing Issues, remote state, and all-state PR history. New-PR state advances as
`absent -> base-reserved -> exact-commit -> exact-PR`: GitHub REST create-ref atomically reserves the
branch at the bound base, then an ordinary non-force fast-forward push publishes the exact commit.
An existing update advances its bound head by fast-forward and updates only that PR's title/body.
Exact readback produces `builder.publication-receipt.v1`; interruption is reconciled only inside
the bound states. Conflict, terminal history, or ambiguous readback stops before another effect. The
plan and receipt remain reconstructable evidence, never a ledger or lifecycle authority.

Every command exit status is authoritative. Do not mask it, manually recreate a receipt, stage
additional paths, force-push, delete refs, or continue after typed refusal.

## Handoff

After exact receipt readback, use `pr-integration` only for a concrete readiness, mergeability, CI
attachment, branch-drift, or review-repair need. Otherwise immediately load and execute
`verification-and-closure`. Publication does not make the Issue or delivery Done.

Report branch, commit, PR number, plan/receipt hashes, validation, BuilderOps routing, and the next
owner workflow. On a plan divergence, invoke `capture-learning`; never append new operational state
to `docs/learning-log.md`.

## Workflow continuation

Apply `.codex/skills/README.md :: Workflow continuation`. The publication report is intermediate
evidence: execute `pr-integration` when triggered, then `verification-and-closure` through verified
merge and reconciliation before ending delivery. Do not return merely because the PR exists, checks
are pending, or verification is queued. For an explicit draft-only/publication-only task, verify
that requested output and return to the caller without widening authority.
