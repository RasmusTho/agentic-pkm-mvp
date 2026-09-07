---
name: Isolate Builder package boot
description: boot Builder without Product imports configuration or dependencies
task_id: FCA-04
github_issue: 5403
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Isolate Builder package boot

## Purpose

ADR-0062 requires a hard package/build boundary even while sources remain in this repository. Dockerfile.builderops copies all app and installs shared requirements; app/__init__.py loads Product LLM policy. This is a narrower independent-boot gap than #3793 authority cutover.

## What This Task Does

Isolate the standalone BuilderOps API/worker/migration bootstrap and its image dependency closure from Product LLM configuration and Product initialization. Adjust Dockerfile.builderops, package/dependency manifests and the minimum import seams necessary. Add clean-environment import/boot tests with Product LLM enforcement hostile/unconfigured and Product DB/vault/services absent. Use a supported independent dependency closure without extracting to a new source repository. Coordinate with #3793: this child owns package/import/bootstrap independence only; #3793 owns Product route/startup removal, legacy stores and authority activation.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is boot Builder without Product imports configuration or dependencies.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The actual Builder API/worker/migration bootstrap succeeds or reports only its own missing Builder dependency when Product LLM policy is enforced but unconfigured, without initializing Product services.
  - Verify: `tests/architecture/test_builderops_package_independence.py::test_builder_boot_does_not_load_product_configuration`
- [ ] An image/package smoke exercises the real Builder entrypoints with the declared Builder dependency closure and no Product DB, vault, process or provider settings.
  - Verify: `tests/ops/test_builderops_package_smoke.py::test_minimal_builder_package_boots_without_product_runtime`
- [ ] The documented package/build seam names retained neutral dependencies and proves its boundary without weakening PostgreSQL-only selection, auth or migrations.
  - Verify: doc writeback at `docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md :: Complete Dev System admission`

## How to Verify (Pre-Merge)

Run the two named tests and affected standalone Compose/import/auth regression tests; execute the real image/package smoke and preserve its build identity. Full baseline for touched code; shared host resources use the existing host lease. No deployment is part of validation.

## Out of Scope

No source-repo extraction, authority cutover, data migration, host activation or change to Product behavior. Do not duplicate #3793.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- Parent validation hub; see README.

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 architecture/import/runtime boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
