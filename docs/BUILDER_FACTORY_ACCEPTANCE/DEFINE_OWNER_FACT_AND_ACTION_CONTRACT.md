---
name: Define owner facts and bounded action handoff
description: define source-backed owner decisions trials and agent handoff
task_id: FCA-02
github_issue: 5401
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Capability intent"
parent_capability: Builder Factory Acceptance
prerequisites: [FCA-01]
depends_on: [RECONCILE_EXECUTABLE_CONTRACTS.md]
can_parallelize_with: []
---

State: Target-state task specification; not implemented or runtime acceptance.
Doc role: Specification
Authority: Accepted research-to-backlog handoff; existing owner contracts remain binding.

# Define owner facts and bounded action handoff

## Purpose

DEVUI ARO-01 deliberately withdrew Needs you and Ready to try because no source owned those facts. #4742 closed with that decision and #4743 was superseded. The owner permits LLM interpretation, but decisions, deployed tryability and acceptance must remain distinguishable from a model suggestion.

## What This Task Does

Specify the minimal source-owned owner ask, ready-to-try, trial and acceptance facts using existing GitHub Issue/PR, deployment receipts and BuilderOps receipt infrastructure. Name the precise producer, identifier/version, authorization, revision/supersession, readback, retention and projection behavior for each; do not invent a new generic task or intent store. Extend the relevant owner sections in docs/DEVUI.md, docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md and docs/plans/DEVUI_IMPLEMENTATION.md. Define LLM summary/proposal output as non-authoritative and source-linked. Specify the first bounded authenticated handoff through the action owner retained by FCA-01/#4169/#4697, including ambiguous launch outcome and restart reconciliation. Do not require DDO for an existing admitted agent workflow.

## Concretely

A consumer of this task can inspect the named production seam or document and run the exact acceptance targets below. A passing fixture proves that finite contract; runtime and human observations remain on the parent. The expected outcome is define source-backed owner decisions trials and agent handoff.

## Why This Matters

A component or proposal must not be mistaken for a working owner platform. This task closes its named interface while preserving the existing source, action and deployment owners.

## Acceptance Criteria

- [ ] The owner fact table names source/producer/identity/auth/revision/readback for the four finite fact kinds, including withdrawal and changed-candidate behavior.
  - Verify: doc writeback at `docs/DEVUI.md :: Owner language and source states`
- [ ] The plan distinguishes model suggestions, actual owner asks and accepted actions; a single existing action boundary owns exact-target approval and destination readback, with the first non-DDO path and later DDO scope explicit.
  - Verify: doc writeback at `docs/plans/DEVUI_IMPLEMENTATION.md :: Three delivery stages`
- [ ] Nonvisual examples cover genuine decision, technical wait, deployed-but-untried, owner rejection, changed candidate and ambiguous start without assigning new authority to DevUI.
  - Verify: runtime receipt: builder_owner_fact_contract.v1

## How to Verify (Pre-Merge)

Review the finite examples against existing source contracts and production seams; validate source anchors and docs. The receipt must identify committed source sections and any remaining decision, with no runtime support claim.

## Out of Scope

No UI, provider activation, database migration or runtime writer; no blanket inference from labels/merge to owner intent or acceptance; no duplicate action service.

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
Capability recommendation: Tier 2 governance; configured Codex, high reasoning for source/authority boundaries.
The implementation owner re-derives capability/risk at pickup; serial delivery is the default.
