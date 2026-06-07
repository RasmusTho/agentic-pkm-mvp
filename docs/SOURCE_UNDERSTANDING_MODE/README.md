---
name: Source Understanding Mode Specification
description: Specification directory for #1646 Source Understanding Mode and its bounded child delivery chain.
type: specification
authority: SoT for the SOURCE_UNDERSTANDING_MODE capability boundary and child task breakdown
source_of_truth: GitHub Issue #1646, GitHub Issue #1647, docs/HUMAN-FLOWS.md, docs/COGNITIVE_LOAD_PROJECTION_LAYER.md
related_docs:
  - docs/HUMAN-FLOWS.md
  - docs/COGNITIVE_PROSTHESIS_CHARTER.md
  - docs/COGNITIVE_LOAD_PROJECTION_LAYER.md
  - docs/research/COGNITIVE_LOAD_REDUCTION_RESEARCH.md
  - docs/CONCEPTS/ARTIFACT_PROJECTION_AND_SOURCE_CONTRACT.md
  - docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md
  - docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md
---

State: Active breakdown for GitHub Issue #1646. #1646 is the live parent and validation hub. #1647 is the first pickup child. Later children are blocked until the P0 source-to-understanding pattern is delivered and validated.

# Source Understanding Mode

This directory specifies Source Understanding Mode as one governed capability for helping the human understand complex source material while preserving source authority. It is not a generic summarizer, citation manager, PDF reader replacement, or automatic literature-review agent.

The capability supports the human loop:

```text
source artifact or selected passage
-> source-anchored understanding projection
-> human review
-> stabilized-note proposal path
-> human promote / revise / defer / reject
```

The understanding packet is non-authoritative. It helps the human orient, inspect claims and evidence, critique the source, connect it to existing material, and decide what to do next. It does not mutate canonical source artifacts and does not become durable knowledge unless a separate governed proposal/promotion path accepts it.

## Capability Boundary

Source Understanding Mode produces reviewable, source-preserving projections over whole source artifacts or selected passages. It must:

- preserve source references, source spans, trace IDs, or explicit anchor limitations;
- distinguish source facts and claims from agent interpretation;
- scope selected-passage output to the selection unless full-document context is actually available;
- keep integration and action output proposal-class until human confirmation;
- avoid hidden memory promotion or canonical note creation from a projection; and
- degrade visibly when source anchors, source identity, or broader context are unavailable.

## Why The Chain Is Gated

Issue #1646 explicitly says not to split all eight lenses into pickup work until the first vertical slice proves the source-to-understanding pattern. This directory therefore treats #1647 as the only ready first child. The later task specs are pre-shaped for traceability, but their GitHub issues must stay `agent:blocked` until #1647 posts a validation receipt to #1646 and the parent confirms the packet shape is still correct.

## Tasks

1. **[DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md](DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md)** - existing #1647. Deliver the first Orientation / Structure / Claims / Evidence packet for one narrow source or selection input path.
2. **[CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md](CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md)** - blocked post-P0, #1684. Turn the validated packet into a reviewable stabilized-note proposal path without auto-promotion.
3. **[EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md](EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md)** - blocked post-P0, #1685. Add Concept and Critique lenses only after the P0 packet contract is proven.
4. **[EXTEND_INTEGRATION_AND_ACTION_LENSES.md](EXTEND_INTEGRATION_AND_ACTION_LENSES.md)** - blocked post-P1, #1686. Add Integration and Action lenses as source-bounded proposals, not vault mutations or task authority.
5. **[PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md](PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md)** - final closure, #1687. Promote supported truth into owner docs and close #1646 after child receipts are complete.

Execution order (flat): `DELIVER_P0_SOURCE_UNDERSTANDING_PACKET -> CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF -> EXTEND_CONCEPT_AND_CRITIQUE_LENSES -> EXTEND_INTEGRATION_AND_ACTION_LENSES -> PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS`.

## Parent / Validation Hub

The parent feature issue is GitHub Issue #1646. Its local source lives at [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). #1646 remains open and blocked while child slices deliver. Each delivered child must post a validation receipt to #1646 before the next blocked child is unblocked.

## Relationship To #1638

#1646 is related to the cognitive-load reduction track, but it is a separate Source Understanding parent path. #1638 focuses on runtime adoption of cognitive-load support. #1646 owns complex source comprehension and source-to-stabilized-understanding validation.

## Capability Acceptance

- [ ] P0 Source Understanding runs on one chosen whole-source or selected-passage input path. Verify: #1647 PR tests and #1646 receipt.
- [ ] P0 output includes Orientation, Structure, Claims, and Evidence while preserving non-authoritative source projection posture. Verify: #1647 PR tests and packet fixture.
- [ ] A reviewable stabilized-note proposal handoff exists without auto-creating durable knowledge. Verify: stabilized-note handoff issue tests and #1646 receipt.
- [ ] Concept and Critique lenses preserve source anchors and separate source claims from agent critique. Verify: Concept/Critique issue tests and #1646 receipt.
- [ ] Integration and Action lenses remain proposal-class, do not mutate the vault, and degrade when broader context is unavailable. Verify: Integration/Action issue tests and #1646 receipt.
- [ ] Owner docs distinguish shipped Source Understanding support from remaining target-state work before #1646 closes. Verify: owner-doc promotion issue diff and #1646 closure checklist.

## Out Of Scope

- Building a full citation manager.
- Building a generic PDF reader replacement.
- Building a broad literature-review automation agent.
- Auto-creating canonical concept notes or literature notes from source documents.
- Treating generated understanding packets as durable knowledge or hidden agent memory.
- Making Integration or Action mutate the vault without the existing governed proposal/confirmation path.

## Navigation

- Parent: [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)
- P0 packet: [DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md](DELIVER_P0_SOURCE_UNDERSTANDING_PACKET.md)
- Stabilized-note handoff: [CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md](CONNECT_STABILIZED_NOTE_PROPOSAL_HANDOFF.md)
- Concept/Critique: [EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md](EXTEND_CONCEPT_AND_CRITIQUE_LENSES.md)
- Integration/Action: [EXTEND_INTEGRATION_AND_ACTION_LENSES.md](EXTEND_INTEGRATION_AND_ACTION_LENSES.md)
- Closure: [PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md](PROMOTE_SOURCE_UNDERSTANDING_OWNER_DOCS.md)
