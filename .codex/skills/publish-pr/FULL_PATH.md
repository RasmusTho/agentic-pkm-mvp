State: Canonical full-path publication procedure for `.codex/skills/publish-pr/SKILL.md`.

# Full-Path PR Publication

Use this file only after the publish-pr router rejects the normal plan/apply path. It owns the
publication boundary through exact PR readback; it does not own implementation, merge, Issue
closure, release, deployment, or claim release.

## Scope

| Trigger | Required route inside this procedure |
| --- | --- |
| Existing PR or review repair | Refresh exact PR scope, then use `pr-integration` before publication effects. |
| Pre-existing branch commit, non-`main` base, remote head, or any open/closed/merged head-branch history | Preserve the state and run the authority/collision checks below; never coerce it into normal plan/apply. |
| Multi-Issue PR | Apply `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`. |
| Issue-free docs/governance or Direct Repair | Apply the matching lane contract in `docs/development/PR_HOT_PATH.md`. |
| Tier 3 or auth/security/data/migration/concurrency/external-API/credential-durability/state-machine risk | Complete `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Mechanism Convergence Gate` on the local publishable SHA before expensive proof or an external effect. |
| Ambiguous transport/readback | Stop with the observed state and use `pr-integration`; no blind retry or alternate transport. |

Verified merge body fencing, merge, Issue closure, post-merge owner-doc writeback, release, and
promotion remain with their named skills.

## Procedure

1. Refresh the full governing Issue, active claim/lease, worktree registry row, branch, local `HEAD`,
   effective fetch and push repository identities, live target-base SHA, remote head, all-state PR
   history for the exact head branch, and—when present—the PR head/base/body/check/review state.
   Treat URL userinfo, multiple effective URLs, fetch/push repository mismatch, stale base, duplicate
   history, or a worktree/lease collision as a hard stop. Never retain or report raw remote URLs.
2. Bind the intended file set, lane, Issue set, target base, commit intent, PR title/body, TCD risk
   classification, BuilderOps routing, and owner-doc resolution. Re-run
   `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: PR-Level Scope Revalidation Gate`
   for an existing PR. Complete Mechanism Convergence when its trigger applies.
3. Generate and inspect the complete PR body through `scripts/pr_body_generator.py`. Run the
   affected focused checks and `scripts/review_before_ci_gate.py`; a high-risk mechanism receipt must
   name the current local publishable SHA. A failed or stale gate blocks publication.
4. Run `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` immediately before commit and again
   immediately before push. Stage only the bound paths and make an additive commit. Do not rebase,
   amend, reset, delete a ref, force-push, or rewrite unrelated history unless a separate explicit
   authority contract requires that exact action.
5. Immediately before a new PR effect, refresh the target base, effective fetch/push identities,
   remote head, and all-state PR history again. New-PR creation requires no conflicting history and
   one explainable remote branch state. Existing-PR publication requires one exact open PR whose
   repository, head ref/SHA, base ref/SHA, Issue scope, title, and body match the refreshed intent.
6. Use an ordinary non-force push only when branch truth proves it is a fast-forward of the observed
   remote state. Create at most one new PR, or update only the uniquely matched existing PR. A
   nonzero/timeout is not success: perform one immediate complete readback and continue only when it
   proves the exact intended effect; otherwise stop `unknown`.
7. Read back local `HEAD`, remote head, live base, all-state PR history, and the exact PR identity.
   Report commit SHA, PR number, base SHA, checks run, plan/gate receipts, and the next workflow.
   Never fabricate a receipt or treat publication as merge, closure, release, or delivery success.

## Recovery outcomes

- Exact unchanged pre-effect state: rerun the owning gate, then retry the single failed command.
- Exact intended commit and no PR: revalidate authority and create only the missing PR.
- One exact open PR: reconcile and hand off without another create.
- Exact closed/merged history, duplicate/mismatched history, unexpected remote movement, base drift,
  unavailable readback, or uncertain command outcome: stop and preserve evidence for
  `pr-integration`; no further publication effect is authorized.

## Handoff

Use `pr-integration` for concrete repair/readiness or ambiguity. Otherwise hand the exact PR to
`verification-and-closure`. The active claim and worktree lifecycle stay with `issue-to-code` until
that workflow performs governed closure.
