---
name: Cutover Readiness Preflight
description: A committed read-only per-channel readiness check for the pinned-image cutover, plus refresh of the stale current-reality matrix and the #2698 execution plan
task_id: CUTOVER-02
source_anchor: docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Deploy procedure
parent_capability: PINNED_IMAGE_CUTOVER
prerequisites: []
depends_on: []
can_parallelize_with: [Reconcile Promotion Workflow With Pinned Images, Fleet-Model Fitness Guard]
---

# Cutover Readiness Preflight

## Purpose

The cutover (#2698) was planned on 2026-06-29 and its inputs have drifted: ADR-0040 changed the prod pin authority, Heimdal v1 added a runtime env requirement and a new health-gated compose service, BGE-M3 added per-channel embedding config, and the spec's own current-reality matrix no longer matches the host (the 2026-07-06 recon in #3124 found dev on a baked `pkm-app:dev-local` image and prod reading `tmp/runtime.env`). The operator gate on #2698 is only meaningful if what it gates is current. This task gives the operator a runnable, read-only readiness verdict per channel and refreshes the plan surfaces.

## What This Task Does

- Adds a read-only preflight module `app/release_channels/cutover_readiness.py` (sibling to the existing `channel_isolation_preflight.py` / `prod_ref_fitness.py` guards) that, for a named channel and target SHA, reports:
  - **Image availability** — the GHCR tag `ghcr.io/<owner>/pkm-app:<sha>` for the target SHA exists locally or is pullable (fail-loud with the exact tag when not).
  - **Env completeness for the containerized model** — a declared required-env manifest for pinned-image operation, checked against the channel's env sources; the manifest must include at least `HEIMDAL_RAW_READ_ALLOWLIST` (Heimdal v1 fail-loud requirement), the embedding-identity vars (`EMBED_PROFILE` posture per ADR-0052), and `COMPANION_TRUSTED_PROXY_HOSTS` where the channel's gateway crosses the docker bridge. Machine-local env files (e.g. prod's local secrets file) are checked for *presence of keys*, never printed.
  - **Recreate-set completeness** — the channel's compose project declares all app-code services that must recreate together: `api`, `worker`, `watcher`, `heimdal-capture-watch`, and the managed gateway unit.
  - **Migration state** — alembic head in the target SHA vs. the channel DB's current revision; pending forward-only migrations listed by name (feeding the §Deploy step-2 operator ack).
  - **Pin sanity** — `config/deploy/<channel>.env` parses, and the recorded/target `APP_IMAGE_TAG` is a real commit reachable from the promotion ref.
- Refreshes the **current-reality matrix** in `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` to the verified 2026-07 host state (dev = baked local image; test+prod = shared `workspace-app` bind-mount; prod env source `tmp/runtime.env`), so the spec stops describing a June snapshot as "current".
- Refreshes the **#2698 issue body** (via `issue-maintenance-change-control`): prod pin authority = `main` interim per ADR-0040 (the body still says "stable-ref"), sequencing note vs. #3124, the Heimdal/BGE-M3 config deltas, and the requirement to run this preflight inside the cutover window (receipt-staleness bound, README INV cross-task rule).

## Concretely

```bash
# On the runtime host (read-only; no stack mutation):
python -m app.release_channels.cutover_readiness prod --target-sha <sha>
# → per-check PASS/FAIL lines + one exit code; FAIL names the missing env key,
#   unpullable tag, absent compose service, or pending forward-only migration.
```

CI exercises the same logic against fixtures (fake env files, fixture compose files, a fixture alembic dir) — the live run happens on the runtime host and its receipt folds into #2698.

## Why This Matters

Without this, the operator acks a stale plan: the cutover could recreate prod onto an image whose container immediately fail-exits (missing `HEIMDAL_RAW_READ_ALLOWLIST` is a designed fail-loud), silently drop the `heimdal-capture-watch` service from the recreate set (reintroducing the silent-broken-capture class #3113 just fixed), or discover mid-downtime that the GHCR tag for the authorized SHA was never built. Every one of these turns authorized-but-brief downtime into an unplanned incident on the owner's real vault.

## Acceptance Criteria

- [ ] `cutover_readiness` reports a FAIL naming the missing key when a required containerized-model env var (e.g. `HEIMDAL_RAW_READ_ALLOWLIST`) is absent from the channel's env sources.
  - Verify: `tests/deploy/test_cutover_readiness.py::test_missing_required_env_named_in_failure`
- [ ] `cutover_readiness` reports a FAIL when a channel's compose project lacks one of the recreate-set services (api/worker/watcher/heimdal-capture-watch/gateway unit).
  - Verify: `tests/deploy/test_cutover_readiness.py::test_incomplete_recreate_set_fails`
- [ ] `cutover_readiness` lists pending forward-only migrations between the DB revision and the target SHA, and exits non-zero when any exist un-acked.
  - Verify: `tests/deploy/test_cutover_readiness.py::test_pending_forward_only_migrations_listed_and_gated`
- [ ] `cutover_readiness` never mutates state: no docker mutation, no file writes outside its receipt output, no secret values echoed.
  - Verify: `tests/deploy/test_cutover_readiness.py::test_read_only_and_no_secret_values_in_output`
- [ ] The current-reality matrix in the deployment SoT reflects the verified 2026-07 host state instead of the 2026-06-29 snapshot.
  - Verify: doc writeback at `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: Current reality`
- [ ] Issue #2698's body is refreshed: ADR-0040 `main`-interim pin authority, #3124 sequencing, Heimdal/embedding config deltas, and the in-window preflight requirement.
  - Verify: runtime receipt — updated #2698 body (edit visible in the issue's edit history), with a receipt comment on #2698 naming this task spec

## How to Verify (Pre-Merge)

- `pytest tests/deploy/test_cutover_readiness.py -q` (new suite, fixture-driven; no docker/pg required — must pass in the `not pg` lane).
- `ruff check app tests`.
- Diff review of the matrix refresh against the #3124 recon facts.
- The #2698 body edit is performed at delivery time via `gh api` and receipted in the PR body (it is a GitHub-state change, not a repo file).

## Out of Scope

- Running the preflight against the live host as a pre-merge gate — live receipts belong to #2698's operator-supervised window (the repo's laptop-vs-runtime posture).
- Asserting the *running fleet's* model (bind-mount vs pinned) — FLEET_MODEL_FITNESS_GUARD owns container inspection; this task checks *readiness inputs*, not runtime state.
- Any change to `scripts/deploy_channel.sh` behavior or the promotion skills.
- Executing migrations or acking forward-only ones.

## Related Docs

- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (§Deploy procedure step 2, §Environment matrix)
- `docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md`
- `docs/ENVIRONMENTS.md` (channel/env source ownership)
- [README.md](README.md) — INV-2, INV-3, receipt-staleness bound

## Related GitHub Issues

- One implementation issue (Product/Runtime + ops boundary). References epic #2655 and #2698; notes that the live readiness run is deferred to #2698's window.
