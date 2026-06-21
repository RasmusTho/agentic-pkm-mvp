State: Target-state contract stub; aligns with existing agent-memory docs and current memory runtime posture.
Doc role: Contract stub
Authority: Owns the target MemoryRecord lifecycle seam for MEM.
Owner subsystem: MEM - Machine Memory & Learning
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# MemoryRecord

## Purpose

Define inspectable machine memory and learning feedback without letting memory become hidden authority or human knowledge by default.

## Inputs

- Candidate observation, feedback, outcome, or receipt.
- Memory class: working, episodic, semantic, prospective, procedural, preference, interaction, project, or policy-adjacent.
- Scope and ActiveContextSet reference.
- Provenance and source references.
- Confidence, staleness, and contradiction signals.

## Outputs

- MemoryRecord with review state.
- Recall result with explanation.
- Correction/revision/forgetting result.
- Promotion request through GOV when memory should become HKA.

## Commands

- Create candidate.
- Review, promote, reject, revise.
- Recall.
- Correct.
- Forget or decay.
- Report contradiction.

## Queries

- Which memories apply in this context?
- What is their review/provenance/confidence posture?
- What was corrected or forgotten?
- Which memories are eligible for promotion?

## Events

- `memory.candidate_created`
- `memory.reviewed`
- `memory.recalled`
- `memory.corrected`
- `memory.forgotten`
- `memory.promotion_requested`

## Invariants

- Memory is advisory unless promoted through GOV.
- Unreviewed memory cannot silently act as instruction.
- Review state, provenance, scope, confidence, staleness, and correction path are explicit.
- HKA owns accepted human knowledge; MEM owns machine memory lifecycle.

## Allowed Producers

- HIX feedback/review.
- CAO workflow outcomes.
- GOV receipts and execution outcomes as memory candidates.
- RCA recall support as input evidence.

## Allowed Consumers

- RCA, CAO, HIX, GOV, OEF, HKA only through governed promotion.

## Forbidden Use

- Do not write memory into HKA without GOV.
- Do not use memory as hidden system instruction.
- Do not store policy in MEM when GOV should own it.

## Failure Modes

- Memory becomes hidden instruction.
- Memory becomes shadow human knowledge.
- Memory lacks correction/forgetting path.

## Transitional Implementation Notes

Existing Agent Memory and Durable Memory/Recall docs provide current behavior and shipped slices. This target contract adds the SBS owner boundary and required lifecycle fields.

## Open Questions

- Which memory classes require human review, agent review, or policy-only review?
- Which decay/forgetting semantics are required before multi-workspace memory is safe?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/AGENT_MEMORY/README.md`
- `docs/DURABLE_MEMORY_AND_RECALL/README.md`
