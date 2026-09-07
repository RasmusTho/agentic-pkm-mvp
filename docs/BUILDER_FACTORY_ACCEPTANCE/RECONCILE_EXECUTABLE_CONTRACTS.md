---
name: Reconcile executable Builder contracts
description: reconcile VM102 and owner-control execution contracts
task_id: FCA-01
github_issue: 5400
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Reconcile executable Builder contracts

## Purpose

A4 supersedes mandatory the former operator host and Builder backup gates, but #5052/#3793 and BCP05 still retain them. #3603 closed after read-only topology reconciliation, not live executor activation. The DevUI plan also understates its delivered shell. The owner now prioritizes usable LLM-assisted overview/control over completing DDO.

## What This Task Does

Reconcile docs/BUILDEROPS_CONTROL_PLANE/DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md, its README, docs/plans/DEVUI_IMPLEMENTATION.md, the FCP README, and live #5052/#3793/#3604/#4169/#4697/#5181 contracts. Preserve completed receipts and existing scope owners. Separate reusable authenticated inquiry/agent handoff in #4169 from DDO-specific effects; either make a verified bounded amendment or specify a non-overlapping child under that existing owner. Do not mark dependent runtime work ready from #3603 closure. Distinguish repository implementation, host operation and acceptance gates. Keep #4982 responsible for bounded visual follow-up, with the smallest useful control path first.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is reconcile VM102 and owner-control execution contracts.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] Current docs and issue contracts agree with A4, backup deferral, delivered shell and the actual #3603 receipt outcome; no historical evidence is erased.
  - Verify: runtime receipt: builder_factory_contract_reconciliation.v1
- [ ] DevUI plan explicitly prioritizes LLM-assisted overview and bounded agent control before full DDO, with an exact owner/dependency for the first authenticated action and later DDO effects.
  - Verify: doc writeback at `docs/plans/DEVUI_IMPLEMENTATION.md :: Three delivery stages`

## How to Verify (Pre-Merge)

Read complete live bodies/comments and accepted owner sections; use issue-maintenance-change-control for exact body/label changes, source-anchor/readiness validators and docs_guard. Attach one receipt with before/after issue body hashes, issue URLs and unresolved gates.

## Out of Scope

No host/deploy/secret/merge operation; no Product changes; no new orchestrator or duplicate #4169/#4697 action owner.

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

Execution context: `fresh_issue_agent`; issue-local helper budget: 0.
Capability recommendation: Tier 1/2 governance; configured Codex, high reasoning because contradictory contracts cross runtime boundaries.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
