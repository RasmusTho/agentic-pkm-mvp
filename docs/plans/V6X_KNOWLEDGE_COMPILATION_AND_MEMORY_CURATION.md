State: v6.x planning line for knowledge compilation and memory curation; first runtime-foundation support seams shipped, while storage/API/event/UI integration and durable promotion remain future work.
Doc role: Plan
Authority: Planning contract for v6.x knowledge compilation and memory curation framing; does not override current runtime truth in `docs/ARCHITECTURE.md`, `docs/STATUS.md`, or capability specs.
Owner: `docs/ROADMAP.md`
Temporal class: strategic
Review cadence: biweekly
Source of truth: mixed
Last reviewed: 2026-06-04
Last verified against: docs/HUMAN-FLOWS.md, docs/plans/V60_ARCHITECTURE_TARGET.md, docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md, docs/FINDING_AND_REORIENTING/README.md, docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md, docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md, docs/SEPARATING_PERSISTENCE_SURFACES/README.md, docs/ROADMAP.md, PR #1557

# v6.x Knowledge Compilation and Memory Curation Plan

## Purpose

Define a bounded v6.x planning line for how the system should support:
- knowledge compilation that helps humans stabilize meaning over time;
- memory curation that keeps retained artifacts findable, explainable, and reviewable;
- explicit governance so generated material does not silently become canonical truth.

This plan names the target semantic posture and sequencing recommendation. The first
runtime-foundation support seams shipped under #1534-#1538 as pure, provider-free,
non-canonical helpers; this plan still does not claim storage/API/event/UI integration,
durable promotion, or autonomous vault mutation.

## Human-Flow Grounding

This plan is grounded in `docs/HUMAN-FLOWS.md`, especially:
- `Capture -> clarify -> place`
- `Retrieve -> orient -> act`
- `Source -> interpret -> stabilize`
- `Review -> reclassify -> promote/archive`

Knowledge compilation and memory curation are support functions for those human loops, not replacements for them. The system should reduce cognitive load while preserving human authorship and review authority.

## Scope

In scope for this plan:
- define the semantic boundary between compilation support and curation support;
- define artifact classes and lifecycle posture for generated outputs;
- define review and promotion posture for non-canonical generated material;
- define suggested event families as design intent only;
- define sequencing recommendations for follow-up implementation and test work.

## Non-Goals

This plan does not:
- change runtime behavior or API contracts;
- define DB schema changes, event payloads, or on-disk layout;
- authorize autonomous vault rewriting;
- treat generated summaries/compilations as canonical truth by default;
- replace existing capability specs (`FINDING_AND_REORIENTING`, `SEPARATING_PERSISTENCE_SURFACES`, `COMMITMENT_AS_FIRST_CLASS`).

## Relationship to v6.0 Architecture Direction

This planning line is a v6.x extension of the v6.0 operating model in `docs/plans/V60_ARCHITECTURE_TARGET.md`:
- follows `observation -> normalization/contract -> admission -> execution`;
- keeps human writing surfaces canonical;
- treats runtime projections and generated supports as derived/system surfaces;
- requires explicit admission and receipt posture before durable promotion.

It also aligns with `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md` by treating retrieval, orientation, and resurfacing as reusable capabilities, not one architectural center.

## Retrieval, Orientation, and Resurfacing Relationship

Knowledge compilation and memory curation should consume the v6 capability split documented in `docs/FINDING_AND_REORIENTING/README.md`:
- Retrieval: find relevant material and provenance for a concrete question or task.
- Orientation: restore situational understanding after interruption or context shift.
- Resurfacing: proactively bring latent but newly relevant material back into view.

Compilation and curation are downstream cognitive-support functions that compose these capabilities. They must not collapse retrieval, orientation, and resurfacing back into one opaque operation.

## Ontology and Trust Semantics

Semantic posture for this line:
- Salience is derived and situational (`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`), not a durable artifact essence.
- Trust semantics (`ASSERT`, `SUGGEST`, `APPLY`) from `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md` govern how generated outputs may be surfaced or promoted.
- Compilation outputs default to suggestion posture until explicit human adoption.
- Cross-context use must preserve provenance and boundary clarity.

## Artifact Model

Planned artifact classes (semantic model only):
- `Compilation draft`: generated synthesis candidate, explicitly non-canonical.
- `Curation candidate`: proposed retained-material set with source links and rationale.
- `Promotion receipt`: evidence that a human reviewed and promoted selected content.
- `Reorientation packet`: compact context bundle for return-to-work flows.

Surface posture:
- Human writing surface remains canonical for adopted knowledge.
- Retention surface stores source-rich materials and curation context.
- System surface stores derived operational supports, receipts, and traces.

## Suggested Event Families (Design Intent Only)

The following event families are planning anchors only (not implemented claims):
- `knowledge.compilation.requested`
- `knowledge.compilation.proposed`
- `knowledge.compilation.promoted`
- `memory.curation.candidate_built`
- `memory.curation.reviewed`
- `memory.curation.promoted`
- `memory.reorientation.packet_generated`

Event-family naming and payload contracts, if implemented later, must be defined in bounded implementation issues and owner-doc updates.

## Review and Promotion Posture

Default posture for generated artifacts:
- Generated outputs are not canonical truth by default.
- Promotion requires explicit human review and durable receipt evidence.
- Provenance must be preserved across all compilation and curation artifacts.
- Promotion can be partial; non-promoted material remains suggestive, not asserted.

Governance rule:
- The system may propose and organize; humans authorize what becomes durable knowledge truth.

## Follow-up Issue Anchors

Current related backlog anchors:
- Parent feature: #803
- Human-flow grounding follow-up: #805
- Roadmap/index cross-reference follow-up: #806
- Plan authoring slice (this issue): #804

Delivered runtime-foundation anchors under #1533:
- Runtime artifact contracts: #1534
- Deterministic proposal builders: #1535
- Read-only reorientation packet assembly: #1536
- Explicit admission handoff: #1537
- Diagnostic trace harness: #1538

These shipped slices are support seams only. Follow-up implementation/test anchors for
storage, API, event, UI, durable promotion, or governed writeback should still be filed as
bounded child issues before that broader runtime work starts.

## Acceptance Criteria for This Plan

This plan is complete when:
- [ ] The document exists at `docs/plans/V6X_KNOWLEDGE_COMPILATION_AND_MEMORY_CURATION.md`.
- [ ] It defines purpose, scope, non-goals, and v6 relationship without claiming shipped implementation.
- [ ] It grounds knowledge compilation and memory curation in canonical human loops from `docs/HUMAN-FLOWS.md`.
- [ ] It states generated artifacts are non-canonical by default and require explicit review/promotion posture.
- [ ] It preserves provenance, trust semantics, and authority boundaries.
- [ ] Suggested event families are documented as design intent only.
- [ ] Follow-up issue anchors are linked for sequencing continuity.

## Sequencing Recommendation

Recommended sequencing under parent feature #803:
1. Land planning baseline and semantic boundaries (this document, #804).
2. Ground the line in Human Flows language and acceptance path (#805).
3. Add roadmap/index cross-references and visibility in planning maps (#806).
4. Decompose bounded implementation and test slices from #803 with explicit `Verify:` targets.
5. Deliver runtime slices incrementally with owner-doc writeback and verification receipts.
6. Filed and shipped first runtime-foundation support seams (#1534-#1538).
7. File separate bounded slices before claiming storage/API/event/UI integration or durable promotion.

## Status Note

This plan is a strategic design surface with the first runtime-foundation seams delivered. Current runtime behavior remains authoritative in `docs/ARCHITECTURE.md`, `docs/STATUS.md`, `docs/ROADMAP.md`, and capability owner docs; future storage/API/event/UI integration requires bounded follow-up slices and owner-doc writeback.
