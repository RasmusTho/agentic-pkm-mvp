# Pinned-Image Cutover — historical delivery and receipt index

State: Historical specification and receipt index; the original #2698 cutover issue is closed.
Doc role: Historical reference
Parent epic: #2655 — deployment + environment-separation architecture
Owning SoT: `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md` (current deployment mechanics), `docs/RELEASE_CHANNELS/README.md` (promotion authority)
Temporal class: historical
Review cadence: when a new authoritative cutover receipt supersedes this record
Source of truth: GitHub delivery receipts and current deployment owner docs
Last reviewed: 2026-09-25
Last verified against: issue #2698 and its final public receipt; PRs #3205, #3206, #3207; `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Delivered scope

Epic #2655 delivered the build-once/pinned-image deployment tooling and follow-up governance/readiness work. The original implementation breakdown and invariants below are retained by the child task specifications in this directory; this README no longer represents open work.

- The pinned-image promotion reconcile, readiness preflight, and fleet-model fitness guard were delivered by PRs #3206, #3205, and #3207 respectively (issues #3155, #3157, #3158).
- The terminal cutover issue [#2698](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2698) is closed as completed.
- Its [final public receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2698#issuecomment-4918410789) records a production pinned-image deployment at SHA `311631b08efdf08809a5677d20e3612f80a0022c`.
- This receipt index does not contain fresh equivalent `dev` and `test` receipts. Do not infer their current image, residency, health, or deployment status from the recorded production result.

## Original implementation breakdown (historical)

| Task | File | Outcome | State |
| --- | --- | --- | --- |
| Reconcile promotion workflow with pinned images | [RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES.md](RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES.md) | Deployment-model-aware promotion skills and channel contracts | Delivered by PR #3206; issue #3155 closed |
| Cutover readiness preflight | [CUTOVER_READINESS_PREFLIGHT.md](CUTOVER_READINESS_PREFLIGHT.md) | Read-only per-channel readiness check and cutover-plan refresh | Delivered by PR #3205; issue #3157 closed |
| Fleet-model fitness guard | [FLEET_MODEL_FITNESS_GUARD.md](FLEET_MODEL_FITNESS_GUARD.md) | Guard asserting a cut-over channel runs its pin and live gateway | Delivered by PR #3207; issue #3158 closed |
| **Cutover execution (terminal, operator-gated)** | — (#2698) | Operator-supervised pinned-image cutover | Issue #2698 closed; final public receipt records prod at SHA `311631b08efdf08809a5677d20e3612f80a0022c` |

## Original execution order (historical)

The following sequence records the original plan only; the child tasks are delivered and #2698 is closed.

1. `CUTOVER_READINESS_PREFLIGHT` and `RECONCILE_PROMOTION_WORKFLOW_WITH_PINNED_IMAGES` and `FLEET_MODEL_FITNESS_GUARD` — independent, can run in parallel (`can_parallelize_with` in each task's frontmatter).
2. #2698 (cutover) executes only after all three land, under operator gate.

The #3124 release sequencing note is historical: it called for checkout-model operation while the staged pinned-image cutover work was in progress. It is not current deployment guidance.

## Retained invariants from the original cutover plan

- **INV-1 — one live deploy mechanism per channel, no dead window.** At any moment each channel has exactly one authoritative deploy path: the checkout model until that channel's cutover receipt exists, the pinned-image model after. The promotion-skill reconcile (task 1) must keep the checkout path fully executable until the cutover receipt flips the switch — an interim state where *neither* path is executable would strand the operator mid-release (#3124 is scheduled on the checkout path).
- **INV-2 — cutover is terminal only once the fitness guard passes.** A pin bump alone does not make a channel "cut over". Partial-failure path: the pin file is updated but the recreate fails or the container still carries the `/app` bind-mount — the channel is then still on the old model and the deploy receipt must say so. The fleet-model fitness guard (task 3) is the predicate; #2698's per-channel completion claim must cite a guard PASS, and the readiness preflight (task 2) must treat a stale guard state as "not cut over".
- **INV-3 — schema changes flow only through the migration gate.** `scripts/deploy_channel.sh` diffs alembic migrations and stops on unacked forward-only ones. In-process bootstrap DDL self-heal paths must not become a side channel that applies schema outside that gate during a deploy; the readiness preflight reports alembic head vs. DB revision so the operator sees the true migration delta before acking.
- **INV-4 — promotion authority is unchanged.** *Which* SHA prod may run stays owned by `docs/RELEASE_CHANNELS/README.md §Promotion model` (ADR-0040: `main` interim). This capability changes *how* a deploy physically happens, never which code is authorized. Task 1 rewords Invariant 4 for the pinned-image form without moving the authority.
- **Receipt staleness bound.** The original plan treated a readiness-preflight PASS as evidence for one cutover window, not forever, and required a fresh preflight before #2698. This historical requirement is not an open #2698 action.

## Original verification path (historical)

- The original tasks specified behavioral tests under `tests/deploy/` and a docs-writeback check for the promotion reconcile; the child issues are now closed as delivered.
- Live-host receipts were not pre-merge CI targets; the final #2698 receipt is the operator evidence surface for the cutover. Do not infer additional channel receipts from this historical verification description.

## Original validation / acceptance path (historical)

- The original acceptance target covered per-channel pinned images and SHA visibility at `/version`. #2698 is closed; the final public receipt linked above records production at its exact SHA. This index does not claim equivalent current `dev`/`test` state or receipts.
- The original #2527 residual acceptance target concerned a clean production tree receipt; current authority and runtime facts remain with the channel owners and their evidence.

## Current relationship to GitHub issues

- Parent epic: #2655 — deployment + environment-separation architecture.
- Child issues #3155, #3157, and #3158 are delivered/closed by PRs #3206, #3205, and #3207 respectively.
- Terminal issue #2698 is closed; the final public receipt is linked above. This README is not a live issue hub and does not claim present `dev`/`test` acceptance.
- The separate proposal for automatic post-merge `dev` → `test` delivery is [FAST_PR_TO_DEV_TEST_AUTOMATION](../../plans/FAST_PR_TO_DEV_TEST_AUTOMATION.md); production promotion stays governed by `docs/RELEASE_CHANNELS/README.md`.
- Related historical context: #2527, #3124, ADR-0040.
