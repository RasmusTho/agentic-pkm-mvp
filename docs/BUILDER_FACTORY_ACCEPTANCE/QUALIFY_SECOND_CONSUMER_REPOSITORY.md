---
name: Qualify a second consumer repository
description: qualify Builder against an explicitly addressed second repo
task_id: FCA-06
github_issue: 5405
source_anchor: docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-04, "#3793", "#5181"]
depends_on: [ISOLATE_BUILDER_PACKAGE_BOOT.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Qualify a second consumer repository

## Purpose

RepoRef and delivery manifests already support multiple repositories with no policy borrowing. There is no inspected acceptance proving that the running Builder can govern an independent consumer without implicit Yggdrasil/Product or laptop-runtime dependencies.

## What This Task Does

Create a bounded conformance/pilot harness over existing manifest routing, DevUI read composition and the admitted agent/workflow launcher. Exercise two explicitly different repo identities with separate policies/credentials and a third unauthorized identity. The second consumer must have its own source/skill delivery contract and must not require a Product Runtime DB/vault/service or hub-specific default. A local fixture establishes pre-merge behavior; a separately authorized low-risk live second-consumer pilot belongs to parent validation. The pilot may use existing governed agent workflows and does not require full DDO. Select the live repo/branch/allowed effects explicitly in its admission receipt; do not create a repo or grant credentials in this child.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is qualify Builder against an explicitly addressed second repo.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The composed production admission/read/launch path resolves the addressed consumer policy and never borrows hub defaults, references or credentials; a third unconfigured repo is refused.
  - Verify: `tests/builderops/test_standalone_consumer_conformance.py::test_composed_path_is_repo_scoped_without_hub_fallback`
- [ ] Consumer boot/read/agent handoff works in the test harness with Product services absent and all host-local provider dependencies explicitly declared; disconnecting an owner UI does not lose the admitted workflow identity.
  - Verify: `tests/builderops/test_standalone_consumer_conformance.py::test_consumer_has_no_product_or_owner_client_runtime_dependency`
- [ ] A self-contained live-pilot procedure enumerates repo/branch/effects, credential boundaries, expected source/run/result receipt and stop/readback behavior, reserving external authorization and actual evidence for the parent.
  - Verify: runtime receipt: builder_second_consumer_pilot_plan.v1

## How to Verify (Pre-Merge)

Run the composed conformance tests plus existing delivery-manifest routing tests and affected code baseline. Publish the fixture/procedure and exact entrypoints. Parent validation records the real repo/commit and authorized effect readback; fixture success alone is not live acceptance.

## Out of Scope

No new routing/provider/tenant system, source extraction, mass portability refactor, repository creation, credential grant or live delivery effect in this pre-merge slice.

## Restart / Durability Posture

No new parallel authority store is introduced. Source facts and authorized operation receipts retain the durability of their existing owner. LLM text and views are derived; after restart regenerate them from current sources, show any unavailable history explicitly, and never redispatch an ambiguous action from the regenerated text. A previously accepted/tried fact must come from its durable source rather than memory of this view.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/audits/BUILDER_SYSTEM_VISION_DELIVERY_2026-09-07.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`

## Related GitHub Issues

- #3793
- #5181

Execution context: `fresh_issue_agent`; issue-local helper budget: 1.
Capability recommendation: Tier 3 multi-repo/auth boundary; fresh issue agent, configured Codex high reasoning, independent mechanism review; helper budget 1.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
