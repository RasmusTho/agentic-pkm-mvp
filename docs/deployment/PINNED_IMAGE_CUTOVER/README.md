# Pinned-Image Cutover — closing the tooling↔fleet gap for epic #2655

State: Active specification directory. Child issues filed; the terminal operator-gated execution slice is the pre-existing issue #2698 (S7), not a new issue.
Doc role: Specification directory (feature-breakdown lane)
Parent epic: #2655 — deployment + environment-separation architecture
Owning SoT: `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (deploy mechanics), `docs/RELEASE_CHANNELS/README.md` (promotion authority)
Last reviewed: 2026-07-07

## Why this capability exists

Epic #2655 delivered its build-once/promote **tooling** in June 2026 (S2–S6: CI SHA-tagged images to GHCR, per-channel pins in `config/deploy/<env>.env`, compose-managed gateway units, `scripts/deploy_channel.sh` with migration/health gates, trusted-proxy auth — PRs #2701, #2711, #2715, #2716, #2713). The **running fleet never adopted it**:

- The 2026-07-06 host recon (issue #3124) shows `test` + `prod` still bind-mount one shared checkout (`/Users/rasmus/workspace:/app`, image `workspace-app`); `dev` runs a locally baked `pkm-app:dev-local` image. No channel runs a GHCR-pinned image.
- All three deploy pins still carry their initial June-29 placeholder SHA — never bumped by a real deploy.
- The promotion skill chain that landed after the epic's slices (`prepare-promotion` → `execute-promotion` → `verify-promotion`, staged via `promote-to-test` / `promote-test-to-prod`) is **checkout-based** ("move the stable ref, restart the prod process from the updated checkout") and actively re-entrenches the bind-mount model on every release — including the imminent #3124 release.
- Post-epic landings changed the cutover's inputs: ADR-0040 (prod tracks `main` interim, not `stable`), Heimdal v1 (new `cryptography` dependency that a bind-mount cannot deliver, `HEIMDAL_RAW_READ_ALLOWLIST` runtime env, the `heimdal-capture-watch` compose service now health-gated by #3113), and the BGE-M3 per-channel embedding config (#3124).

This capability closes that gap: reconcile the two competing deploy mechanisms, prove per-channel readiness, guard the post-cutover state against silent regression, and hand the operator a current, truthful cutover plan (#2698).

For the operator, the consequence of not doing this is concrete: every "deploy" remains a shared-tree fast-forward that moves test and prod together, dependency changes silently don't ship until someone remembers an image rebuild, and `/version` can lie about what is actually running.

## Implementation tasks

| Task | File | Outcome | State |
| --- | --- | --- | --- |
| Reconcile promotion workflow with pinned images | [RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES.md](RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES.md) | The six promotion skills + `docs/RELEASE_CHANNELS/` contracts become deployment-model-aware: checkout model until a channel's cutover receipt exists, pinned-image model (`scripts/deploy_channel.sh`) after | Issue filed |
| Cutover readiness preflight | [CUTOVER_READINESS_PREFLIGHT.md](CUTOVER_READINESS_PREFLIGHT.md) | A committed, read-only per-channel readiness check (image availability, env completeness incl. Heimdal/embedding vars, recreate-set completeness, migration state, pin sanity) + refresh of the stale current-reality matrix and the #2698 execution plan | Issue filed |
| Fleet-model fitness guard | [FLEET_MODEL_FITNESS_GUARD.md](FLEET_MODEL_FITNESS_GUARD.md) | A read-only guard asserting a cut-over channel really runs its pin (no `/app` repo bind-mount, `/version` == pin, gateway unit live), wired into deploy receipts and `verify-promotion` | Issue filed |
| **Cutover execution (terminal, operator-gated)** | — (pre-existing issue #2698) | All three channels recreated onto pinned images under operator supervision; full-environment downtime authorized; forward-only migrations acked | Existing, `agent:needs-human` |

## Execution order

1. `CUTOVER_READINESS_PREFLIGHT` and `RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES` and `FLEET_MODEL_FITNESS_GUARD` — independent, can run in parallel (`can_parallelize_with` in each task's frontmatter).
2. #2698 (cutover) executes only after all three land, under operator gate.

The #3124 release (main → test+prod + BGE-M3 cutover) runs on the **checkout model** and may execute before, during, or after tasks 1–3 land. Nothing in tasks 1–3 may break the checkout path while it is still the live model (see INV-1).

## Cross-Task Invariants / Interaction Safety

- **INV-1 — one live deploy mechanism per channel, no dead window.** At any moment each channel has exactly one authoritative deploy path: the checkout model until that channel's cutover receipt exists, the pinned-image model after. The promotion-skill reconcile (task 1) must keep the checkout path fully executable until the cutover receipt flips the switch — an interim state where *neither* path is executable would strand the operator mid-release (#3124 is scheduled on the checkout path).
- **INV-2 — cutover is terminal only once the fitness guard passes.** A pin bump alone does not make a channel "cut over". Partial-failure path: the pin file is updated but the recreate fails or the container still carries the `/app` bind-mount — the channel is then still on the old model and the deploy receipt must say so. The fleet-model fitness guard (task 3) is the predicate; #2698's per-channel completion claim must cite a guard PASS, and the readiness preflight (task 2) must treat a stale guard state as "not cut over".
- **INV-3 — schema changes flow only through the migration gate.** `scripts/deploy_channel.sh` diffs alembic migrations and stops on unacked forward-only ones. In-process bootstrap DDL self-heal paths must not become a side channel that applies schema outside that gate during a deploy; the readiness preflight reports alembic head vs. DB revision so the operator sees the true migration delta before acking.
- **INV-4 — promotion authority is unchanged.** *Which* SHA prod may run stays owned by `docs/RELEASE_CHANNELS/README.md §Promotion model` (ADR-0040: `main` interim). This capability changes *how* a deploy physically happens, never which code is authorized. Task 1 rewords Invariant 4 for the pinned-image form without moving the authority.
- **Receipt staleness bound.** A readiness-preflight PASS is evidence for a cutover window, not forever: any checkout-model release after the preflight run (e.g. #3124) invalidates the receipt, and #2698 must re-run the preflight inside its own execution window.

## Verification path

- Tasks 2 and 3 carry behavioral ACs with named tests under `tests/deploy/` (extending the existing `test_deploy_channel_script.py` / `test_ghcr_push_and_pin.py` suites).
- Task 1 is a governance/docs reconcile; its ACs verify by doc-writeback anchors across the six skills and `docs/RELEASE_CHANNELS/README.md`.
- Live-host receipts (image pull, real container inspection, real gateway probes) are **not** pre-merge CI targets — they execute on the runtime host and fold into #2698's operator-supervised run, per the repo's test-channel UAT posture.

## Validation / acceptance path

- Evidence surface: epic #2655 (child delivery receipts, as for S2–S6) and #2698 (the cutover's own operator receipts in `ops/promotions/` / `ops/deployments/`).
- The epic's outstanding acceptance criteria discharge here: "each env runs its own pinned image tag" and "a merge to main becomes live via a single deploy action with the SHA observable at `/version`" become true claims only at #2698 completion with fitness-guard PASS per channel; the owner-doc claim in `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (current-reality matrix) is promoted then.
- #2527's residual AC2 (clean prod tree receipt) is satisfied as a side effect of the cutover — a pinned-image prod has no editable checkout feeding the runtime.

## Relationship to GitHub issues

- Parent hub: epic **#2655** (existing — no new parent feature issue; the epic already carries the validation-hub role with per-child delivery receipts).
- Terminal slice: **#2698** (existing S7 cutover, `agent:needs-human`) — deliberately **not** re-filed; task 2 refreshes its body so the operator gate reads a current plan.
- Child issues from this directory: one per task file, titled `[Pinned-Image Cutover] <task-name>: <description>`, each referencing this spec via "Implements PINNED_IMAGE_CUTOVER/<TASK_FILE>".
- Related: #2527 (AC2 residual), #3124 (checkout-model release that sequences around this capability), ADR-0040.
