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

The command path supports only a **new, open, single-Issue Tier 1/2 PR** in the `implementation`,
`docs-authoring`, or `governance` lane, with `Final-Review-Rounds: 0`, no declared high-risk surface,
no remote publication branch, and no open PR for the head branch. It preserves Git, GitHub, the
governing Issue, branch protection, PR checks, and generated PR-body rules as authority. At plan
time `HEAD` must equal the bound `origin/<base-ref>` exactly; a branch with any pre-existing commit
routes to the current full path so unrelated history cannot ride with the planned dirty paths.

Route every other case without trying to coerce it into the command:

- existing-PR update or review repair -> `pr-integration` and the exact
  `PR-Level Scope Revalidation Gate` in `docs/development/PR_HOT_PATH.md`;
- multi-Issue PR -> `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope` and the current full
  verification path;
- issue-free docs/governance publication or Direct Repair -> the matching current lane contract in
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

The normal plan reads all open PRs for the exact head branch and refuses any existing or ambiguous
match. Unsupported publication paths must perform their owning workflow's equivalent live overlap
read immediately before creation; an earlier analysis snapshot is not collision evidence.

## Normal plan/apply

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

The two completion flags are explicit caller attestations, not defaults; supply them only after the
named local prerequisites have actually completed. `plan` is read-only. It emits canonical
`builder.publication-plan.v1` JSON whose
`plan_sha256` binds repository, canonical worktree, branch, base/head, exact paths and content,
Issue authority, lane/risk inputs, commit intent, title, generated body, and body digest. Inspect the
plan and retain its exact hash; any unsupported state or drift routes through the exception list.

Apply only that exact plan:

```bash
python3 scripts/publication.py apply \
  --plan-file <plan.json> \
  --expected-plan-sha256 <64-hex-plan-sha256>
```

`apply` revalidates bound local and GitHub state before each effect, stages only planned paths,
commits, runs the existing workspace/review/PR-body gates, pushes without force, creates one PR, and
reads back exact remote and PR identity as `builder.publication-receipt.v1`. It reconciles a unique
exact local commit, remote head, or PR after interruption. Conflicting or ambiguous state returns a
typed `unknown`/drift result before retry; the plan and receipt are reconstructable evidence, never
a ledger or lifecycle authority.

Every command exit status is authoritative. Do not mask it, manually recreate a receipt, stage
additional paths, force-push, delete refs, or continue after typed refusal.

## Handoff

After exact receipt readback, use `pr-integration` only for a concrete readiness, mergeability, CI
attachment, branch-drift, or review-repair need. Otherwise hand the PR directly to
`verification-and-closure`. Publication does not make the Issue or delivery Done.

Report branch, commit, PR URL, plan/receipt hashes, validation, BuilderOps routing, and the next
owner workflow. On a plan divergence, invoke `capture-learning`; never append new operational state
to `docs/learning-log.md`.
