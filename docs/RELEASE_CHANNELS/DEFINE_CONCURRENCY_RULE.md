---
name: Define Concurrency Rule
description: Specify how the prod process and dev process coexist on the same single-user machine without interfering with each other, including the separate-checkout requirement and the code-ref pin.
task_id: RELEASE_CHANNELS-05
source_anchor: docs/RELEASE_CHANNELS/README.md :: Invariants — Code-ref-per-channel
parent_capability: RELEASE_CHANNELS
prerequisites: [RELEASE_CHANNELS-01]
depends_on: [DEFINE_CHANNEL_IDENTITY.md]
can_parallelize_with: [SPLIT_POSTGRES_PER_CHANNEL, DEFINE_PROMOTION_PLAN_CONTRACT, DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION, DEFINE_ROLLBACK_CONTRACT]
---

# Define Concurrency Rule

## Purpose

Prevent the foot-gun where a running prod process picks up half-written dev code because both processes run from the same checkout. The canonical failure mode is: operator runs prod; operator checks out a branch in the same working copy; prod's next module reload — or next restart — picks up code that was never promoted. This task specifies the rule that eliminates that failure mode.

## What This Task Does

This task produces the concurrency contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- States the rule: the prod process and any dev process run from separate checkouts.
- Names the recommended shape: git worktrees, one per channel, each checked out to the channel's code ref.
- States that the prod checkout is pinned to the `stable` ref and is not used for dev work.
- States that dev may have any number of additional worktrees for feature branches, but none of them is the prod checkout.
- Specifies that the test channel's checkout is the current working checkout used by `make test-bootstrap`.
- States that vault, DB, and runtime-artifact separation (already specified by sibling tasks) combine with the checkout separation to give full channel isolation.

## Concretely

- **Prod checkout**: a dedicated working tree, e.g. `~/code/agentic-pkm-mvp.prod/`, checked out to `stable`. Only the prod process runs from here. Developers do not run `git checkout` in this tree.
- **Dev checkout(s)**: the primary repo checkout, `~/code/agentic-pkm-mvp/`, where `main` and feature branches live. The dev process runs from here. Worktree-based feature branches under `.claude/worktrees/` (as used today) are allowed and do not break the rule.
- **Test**: `make test-bootstrap` runs from the current working checkout (typically the dev checkout); this is intentional because test is the verification posture for code that is about to become dev or eventually stable.
- **Pin enforcement**: the prod checkout's HEAD resolves to the `stable` ref. Only `execute-promotion` and `rollback-promotion` move `stable` and then update the prod checkout.
- **No shared checkout rule**: even transiently, operators do not use the prod checkout for casual dev work. The mental model is "this is the running system; don't touch it."

## Why This Matters

Vault, DB, and runtime-artifact separation are useless if dev code can silently replace prod code. The concurrency rule is the piece that makes the rest of the isolation real. Without it, "prod is stable" is a statement about a git ref, not about what is actually executing.

## Acceptance Criteria

- [ ] The contract states the separate-checkout rule for prod and dev.
  Verify: `rg -n "separate checkouts|separate working trees|separate checkout" docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`.
- [ ] The contract names git worktrees (or equivalent) as the recommended shape.
  Verify: `rg -n "worktree|recommended shape" docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`.
- [ ] The contract states the prod checkout is pinned to `stable` and is not used for dev work.
  Verify: `rg -n "pinned|stable ref|not used for dev" docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`.
- [ ] The contract states that only `execute-promotion` and `rollback-promotion` move the prod checkout's HEAD.
  Verify: `rg -n "execute-promotion|rollback-promotion|moves|HEAD" docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`.
- [ ] The contract clarifies the test channel's checkout relationship.
  Verify: `rg -n "test|make test-bootstrap" docs/RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE.md`.
- [ ] The contract does not mandate specific directory paths; it specifies behavior only.
  Verify: doc review; example paths are illustrative, not prescriptive.

## How to Verify (Pre-Merge)

- Confirm the rule is expressible without tooling work — it is a usage discipline plus the `execute-promotion`/`rollback-promotion` rule.
- Confirm the spec does not conflict with the existing `.claude/worktrees/` convention used for agent worktrees.
- Confirm the test-channel behavior is described honestly: test uses the current working checkout, which is the existing practice.

## Out of Scope

- Enforcing the rule programmatically (e.g. lock files, file permissions).
- Process-level sandboxing between prod and dev.
- Hosted or containerized deployment topology.

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md) :: Invariants
- [docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md](DEFINE_CHANNEL_IDENTITY.md)

## Related GitHub Issues

When promoted: "Implements RELEASE_CHANNELS/DEFINE_CONCURRENCY_RULE." Follow-up: `execute-promotion` and `rollback-promotion` include the only supported flows that update the prod checkout's HEAD.
