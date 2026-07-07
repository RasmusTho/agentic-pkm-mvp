---
name: Reconcile Promotion Workflow With Pinned Images
description: Make the six promotion skills and the RELEASE_CHANNELS contracts deployment-model-aware so post-cutover promotion is a pin bump + deploy script run, not a checkout fast-forward
task_id: CUTOVER-01
source_anchor: docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Build-once / promote model
parent_capability: PINNED_IMAGE_CUTOVER
prerequisites: []
depends_on: []
can_parallelize_with: [Cutover Readiness Preflight, Fleet-Model Fitness Guard]
---

# Reconcile Promotion Workflow With Pinned Images

## Purpose

Two deploy source-of-truths currently contradict each other: `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` specifies build-once/promote via pinned images and `scripts/deploy_channel.sh`, while the promotion skill chain (`.codex/skills/prepare-promotion`, `execute-promotion`, `verify-promotion`, `rollback-promotion`, `promote-to-test`, `promote-test-to-prod`) still executes the checkout model ("move the stable ref … restart the prod process from the updated checkout"). Every governed release run through those skills — including #3124 — re-entrenches the bind-mount model the epic exists to retire. This task makes the promotion workflow deployment-model-aware so the cutover has a workflow to land into.

## What This Task Does

- Adds an explicit **deployment-model switch** to the promotion chain: a channel is on the *checkout model* until its cutover receipt exists (a fleet-model fitness PASS recorded in `ops/deployments/<channel>-latest.json`, see FLEET_MODEL_FITNESS_GUARD), and on the *pinned-image model* after.
- Rewrites the execution steps of `execute-promotion` (and the staged wrappers `promote-to-test` / `promote-test-to-prod`) so that in pinned-image mode the physical deploy is: resolve authorized SHA → `scripts/deploy_channel.sh <channel> <sha>` (pin bump → migration gate → recreate api+worker+watcher+heimdal-capture-watch+gateway → liveness/readiness gate → UI smoke → receipt). The checkout-mode steps remain intact and clearly labeled interim.
- Rewrites `rollback-promotion` for pinned-image mode: rollback = pin bump to previous-good tag + recreate (no rebuild), per `DEPLOYMENT_AND_ENVIRONMENTS.md §Rollback procedure`; forward-only migration caveats unchanged.
- Reconciles `docs/RELEASE_CHANNELS/README.md` **Invariant 4** and **§Promotion model** wording so "code-ref-per-channel" covers both forms: a checkout pinned to the promotion ref (interim) or an image tag built from the promotion ref (post-cutover). Authority (ADR-0040: prod tracks `main` interim) does not move.
- Cross-references `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` as the physical-deploy owner from each touched skill instead of restating procedure.

## Concretely

Post-cutover, a prod promotion run should read like:

```bash
# prepare-promotion output now includes: deployment model = pinned-image, image tag availability check
# execute-promotion, pinned-image mode:
scripts/deploy_channel.sh prod <authorized-sha> --ack-forward-only   # only after operator ack
# verify-promotion consumes the deploy receipt at ops/deployments/prod-latest.json
```

Pre-cutover (today, and for #3124), the same skills still run the documented checkout sequence unchanged.

## Why This Matters

If the skills stay checkout-based, the first governed promotion after the cutover would edit a checkout that no longer feeds the running containers — a silent no-op deploy on prod (the exact "pull without restart serves stale code" class the epic repairs, inverted). If the skills flip to pinned-image-only *before* the cutover, the imminent #3124 release has no executable governed path. Both failure modes violate INV-1 (one live deploy mechanism per channel, no dead window).

## Acceptance Criteria

- [ ] Each of the six promotion skills states the deployment-model switch (checkout until the channel's cutover receipt exists, pinned-image after) and, for pinned-image mode, routes physical execution through `scripts/deploy_channel.sh` instead of ref-move/restart-from-checkout.
  - Verify: doc writeback at `.codex/skills/execute-promotion/SKILL.md :: deployment model`, `.codex/skills/prepare-promotion/SKILL.md :: deployment model`, `.codex/skills/verify-promotion/SKILL.md :: deployment model`, `.codex/skills/rollback-promotion/SKILL.md :: deployment model`, `.codex/skills/promote-to-test/SKILL.md :: deployment model`, `.codex/skills/promote-test-to-prod/SKILL.md :: deployment model`
- [ ] The checkout-model path remains fully documented and executable in every touched skill until a channel's cutover receipt exists — no step is deleted, only labeled interim and forked.
  - Verify: doc writeback — each touched SKILL.md retains its complete checkout-mode procedure under the model fork; reviewed against `origin/main` diff
- [ ] `docs/RELEASE_CHANNELS/README.md` Invariant 4 and §Promotion model cover the pinned-image form of "code-ref-per-channel" without moving promotion authority (ADR-0040 `main`-interim unchanged).
  - Verify: doc writeback at `docs/RELEASE_CHANNELS/README.md :: Promotion model` and `:: Invariant 4`
- [ ] `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` gains a short "Promotion workflow binding" note naming the six skills as the governed executors of §Deploy procedure, replacing the current silence about who runs the script.
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Promotion workflow binding`

## How to Verify (Pre-Merge)

- Diff review against `origin/main` confirming: six skills carry the model fork; no checkout-mode step removed; RELEASE_CHANNELS anchors updated; the new binding note present.
- `python scripts/docs_guard.py` (or the repo's docs lint entry point) passes if the touched surfaces are guarded.
- Grep receipts in the PR body: `grep -l "deploy_channel.sh" .codex/skills/{prepare,execute,verify,rollback}-promotion/SKILL.md .codex/skills/promote-to-test/SKILL.md .codex/skills/promote-test-to-prod/SKILL.md` returns all six files.

## Out of Scope

- Implementing the cutover-receipt/fitness predicate itself — FLEET_MODEL_FITNESS_GUARD owns the runnable guard; this task only references its receipt as the switch condition.
- Executing any promotion or touching any live channel.
- Re-deciding promotion authority (`stable` vs `main`) — ADR-0040 stands.
- Changing `scripts/deploy_channel.sh` behavior.

## Related Docs

- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (§Build-once / promote model, §Deploy procedure, §Rollback procedure)
- `docs/RELEASE_CHANNELS/README.md` (+ `DEFINE_PROMOTION_PLAN_CONTRACT.md`, `DEFINE_ROLLBACK_CONTRACT.md`)
- `docs/adr/ADR-0040-prod-promotion-ref-main-interim.md`
- [README.md](README.md) — cross-task invariants INV-1, INV-4

## Related GitHub Issues

- One governance-lane issue (`lane:governance`, skills + contract docs are Builder System artifacts). References epic #2655; must note #3124 as the live checkout-model consumer that must not break.
