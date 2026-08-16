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

## Purpose

Implement K2, K3, and K9 for delivery artifacts without slowing local iteration.

## What This Task Does

Introduces exact image-index/platform digest identity plus source-SHA, Compose, and migration identities. Promotion-test/prod Compose must render without `build`, source binds, broad host mounts, or fallback overrides; dev/local-test retains an explicit non-promotable local-source overlay.

## Concretely

`channel-manifest render --channel prod --mode promotion --intent promotion` emits only digest-addressed images and selected mounts; `--channel dev --mode local-source --intent ordinary-boot` emits local SHA+dirty identity and `promotion_eligible=false`.

## Why This Matters

An image label cannot prove what runs when a source bind overrides `/app`.

## Acceptance Criteria

- [ ] Promotion render rejects build directives, source binds, broad `/Users` or `/Volumes` write mounts, and image-tag-only identity. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_render_is_digest_only`.
- [ ] Local-source results are permanently non-promotable. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_local_source_cannot_create_promotion_candidate`.

## How to Verify (Pre-Merge)

Convert the strict-xfail call-site skeletons to real tests, then run their focused suite and Compose render fixtures.

## Out of Scope

Running a prod cutover or changing vault data.

## Related Docs

`docs/deployment/PINNED_IMAGE_CUTOVER/README.md`.

## Related GitHub Issues

Filed ownership: #4915 (P2), under parent validation hub #4913. The overlap with the existing pinned-image capability was reconciled before filing; this task owns only the newer digest-only promotion contract.
