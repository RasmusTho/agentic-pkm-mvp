---
name: Fleet-Model Fitness Guard
description: A read-only guard asserting a cut-over channel actually runs its pinned image — no repo bind-mount, /version matches the pin, gateway unit live — wired into deploy receipts and verify-promotion
task_id: CUTOVER-03
source_anchor: docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Build-once / promote model
parent_capability: PINNED_IMAGE_CUTOVER
prerequisites: []
depends_on: []
can_parallelize_with: [Reconcile Promotion Workflow With Pinned Images, Cutover Readiness Preflight]
---

# Fleet-Model Fitness Guard

## Purpose

The epic's identity claims ("test and prod no longer share a code source", "the deployed SHA is observable at `/version`") are runtime properties of the live fleet, but every existing check is either static (compose-file tests) or checkout-oriented (`prod_ref_fitness.py`). Nothing today can answer: *is this channel actually running its pin?* After the cutover, a single `docker compose up` with the wrong overlay would silently re-attach the `./:/app` bind-mount and resurrect the shared-checkout model with `/version` lying about it. This guard makes the fleet's deployment model observable and fail-loud.

## What This Task Does

- Adds a read-only guard `app/release_channels/fleet_model_fitness.py` (sibling of `prod_ref_fitness.py`) that, for a named channel, inspects the live containers and reports:
  - **Model detection** — whether the channel's app services run with a repo `/app` bind-mount (checkout model) or from an image only (pinned-image model). Pre-cutover channels report `model=checkout` as information, not failure — the guard is honest, not aspirational.
  - **Pin match (pinned-image mode)** — every app-code service (`api`, `worker`, `watcher`, `heimdal-capture-watch`) runs the image tag recorded in `config/deploy/<channel>.env`, and the channel API's `/version` `git_sha` equals that pin.
  - **No half-deployed state** — API and gateway report the same SHA (the §Gateways-as-managed-units lockstep rule); a version-diverged gateway is a FAIL.
  - **Gateway unit liveness** — the channel's managed gateway unit is up and its `/healthz` responds.
- Embeds the guard verdict in the deploy receipt written by `scripts/deploy_channel.sh` (the `ops/deployments/<channel>-latest.json` receipt gains a `fleet_model_fitness` block) — this recorded PASS is the **cutover receipt** that README INV-2 and the promotion-workflow model switch (CUTOVER-01) key on.
- Wires the guard into the `verify-promotion` skill's check list so every post-promotion verification asserts the fleet model, catching regressions on every subsequent deploy, not only at cutover.

## Concretely

```bash
# On the runtime host (read-only):
python -m app.release_channels.fleet_model_fitness prod
# → model=pinned-image | checkout
#   pinned-image mode: PASS only if no /app repo bind-mount on app services,
#   image tag == config/deploy/prod.env APP_IMAGE_TAG == /version git_sha,
#   gateway up + same SHA. Any mismatch → non-zero exit naming the divergent service.
```

## Why This Matters

Without a live-fleet predicate, "cut over" is a claim in a receipt, not a property of the system — and the first regression (an old Makefile target, a stale overlay, a hand-run compose command) silently reverts prod to the bind-mount model while `/version` keeps reporting the baked SHA of an image that isn't executing. That is precisely the false-green class the owner's verify-the-verifier rule targets: the check that proves the epic's outcome must itself run against the live runtime path.

## Acceptance Criteria

- [ ] In pinned-image mode the guard fails, naming the service, when any app-code service carries a repo `/app` bind-mount.
  - Verify: `tests/deploy/test_fleet_model_fitness.py::test_bind_mount_in_pinned_mode_fails_naming_service`
- [ ] In pinned-image mode the guard fails when the running image tag, the channel pin file, and `/version` `git_sha` are not all equal, and when API and gateway SHAs diverge.
  - Verify: `tests/deploy/test_fleet_model_fitness.py::test_pin_version_and_gateway_sha_must_agree`
- [ ] A checkout-model channel reports `model=checkout` informatively without failing, so the guard is adoptable fleet-wide before the cutover.
  - Verify: `tests/deploy/test_fleet_model_fitness.py::test_checkout_model_reports_without_failing`
- [ ] `scripts/deploy_channel.sh` invokes the guard after its health gate and embeds the verdict in the deploy receipt — the enforcement point is the production deploy path, not the guard in isolation.
  - Verify: `tests/deploy/test_deploy_channel_script.py::test_deploy_receipt_embeds_fleet_model_fitness` (asserts the guard is invoked from the deploy script's receipt step and its verdict lands in `ops/deployments/<channel>-latest.json`)
- [ ] The `verify-promotion` skill lists the guard as a required post-promotion check.
  - Verify: doc writeback at `.codex/skills/verify-promotion/SKILL.md :: fleet-model fitness`

## How to Verify (Pre-Merge)

- `pytest tests/deploy/test_fleet_model_fitness.py tests/deploy/test_deploy_channel_script.py -q` — fixture/stub-driven (docker inspection stubbed), must pass in the `not pg` lane; the call-site AC executes against the deploy script's receipt path with a stubbed guard.
- `ruff check app tests` and `bash -n scripts/deploy_channel.sh`.
- Live-host guard runs are deferred to #2698's window and to routine `verify-promotion` runs thereafter.

## Out of Scope

- Performing the cutover or any recreate — the guard observes, never mutates.
- The readiness *inputs* checks (env manifest, image pullability, migration delta) — CUTOVER-02 owns those.
- Rewriting the promotion skills' model fork — CUTOVER-01 owns the skill text; this task only adds the one `verify-promotion` check line and provides the receipt the fork keys on.
- Replacing `prod_ref_fitness.py` — the checkout-era guard stays valid for checkout-model channels.

## Related Docs

- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (§Build-once / promote model — identity invariant; §Deploy procedure step 5)
- `docs/RELEASE_CHANNELS/README.md` (Invariant 4; `prod_ref_fitness` precedent)
- [README.md](README.md) — INV-2 (guard PASS is the cutover-terminal predicate)

## Related GitHub Issues

- One implementation issue (Product/Runtime + Builder boundary: runtime guard + deploy-script wiring + one skill line). References epic #2655; its receipt is consumed by #2698 and by CUTOVER-01's model switch.
