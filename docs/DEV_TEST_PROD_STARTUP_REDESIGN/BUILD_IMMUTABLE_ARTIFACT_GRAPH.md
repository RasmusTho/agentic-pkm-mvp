---
name: Build Immutable Artifact Graph
description: Make promotion artifacts digest-addressed and remove build/source fallback from promotion Compose.
task_id: STARTUP-02
github_issue: 4915
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Capability boundary
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: [STARTUP-01]
depends_on: [FREEZE_CHANNEL_MANIFEST_AND_OPERATION_CONTRACT.md]
can_parallelize_with: []
---

# Build Immutable Artifact Graph

State: Implemented in the repository by #4915. The renderer is side-effect free and does not claim
that a digest-addressed artifact has been published, deployed, or observed on a live channel.

## Purpose

Implement K2, K3, and K9 for delivery artifacts without slowing local iteration.

## What This Task Does

Introduces exact image-index/platform digest identity plus source-SHA, Compose, and migration identities. Promotion-test/prod Compose must render without `build`, source binds, broad host mounts, or fallback overrides; dev/local-test retains an explicit non-promotable local-source overlay.

## Concretely

`python -m app.release_channels.channel_manifest render --channel prod --mode promotion --intent promotion --manifest <path> --compose <path>` first validates the complete frozen ChannelManifest shape, including channel-bound Compose project, gateway identity, and secret references, then emits only digest-addressed images and the two channel-bound data mounts. The artifact-mode Compose input is deliberately narrow: it contains exactly the `api` and `database` service roles with their fixed field shapes, the API image equals the manifest platform digest, and its complete volume set is exactly the manifest's database and vault named volumes mounted once at their role-specific protected targets. Long mounts have exactly `type`, `source`, and `target`; short mounts have only the bounded two- or three-segment form. Host binds, additional services or named volumes, unknown mount fields/options, and other mount targets fail closed. Runtime command, environment, env-file, label, config, and credential seams are outside this artifact render and fail closed instead of being guessed or hashed; inline secret material is also rejected before output. `--channel dev --mode local-source --intent ordinary-boot` accepts the explicit source overlay unchanged, emits local SHA+dirty identity, and sets `promotion_eligible=false`; it does not require promotion-only identity extensions. Candidate admission is a separate deterministic function that re-renders against the independently supplied manifest and refuses every local-source or coherently tampered render.

## Why This Matters

An image label cannot prove what runs when a source bind overrides `/app`.

## Acceptance Criteria

- [ ] Promotion render rejects build directives, source binds, broad `/Users` or `/Volumes` write mounts, and image-tag-only identity. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_render_is_digest_only`.
- [ ] Local-source results are permanently non-promotable. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_local_source_cannot_create_promotion_candidate`.

## How to Verify (Pre-Merge)

Run `pytest -q tests/runtime/test_startup_artifact_call_sites.py::test_promotion_render_is_digest_only tests/runtime/test_startup_artifact_call_sites.py::test_local_source_cannot_create_promotion_candidate`.

## Out of Scope

Running a prod cutover or changing vault data.

## Related Docs

`docs/deployment/PINNED_IMAGE_CUTOVER/README.md`.

## Related GitHub Issues

Filed ownership: #4915 (P2), under parent validation hub #4913. The overlap with the existing pinned-image capability was reconciled before filing; this task owns only the newer digest-only promotion contract.
