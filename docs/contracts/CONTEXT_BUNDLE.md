State: Target-state contract stub; aligns with existing concept and runtime ContextBundle docs.
Doc role: Contract stub
Authority: Owns the RCA target contract shape for scoped candidate evidence.
Owner subsystem: RCA - Retrieval & Context Assembly
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# ContextBundle

## Purpose

Carry moment-specific candidate evidence with scope, provenance, relevance explanation, and non-authority posture.

## Inputs

- Query, intent, or capability request.
- ActiveContextSet reference.
- DRI indexes/projections.
- HKA artifact references.
- MEM recall candidates.
- GOV filters or admissibility constraints.

## Outputs

- Scoped candidate evidence.
- Source/provenance references.
- Retrieval method/version where useful.
- Ranking/relevance explanation.
- Staleness and uncertainty signals.
- Explicit non-authority marker.

## Commands

- Retrieve.
- Rerank.
- Assemble bundle.
- Explain relevance.
- Mark stale or uncertain evidence.

## Queries

- Which evidence is relevant in this context?
- Why was this evidence selected?
- What is stale, uncertain, or excluded?
- Which sources support this bundle?

## Events

- `context_bundle.created`
- `context_bundle.emitted`
- `context_bundle.stale`
- `context_bundle.consumed`

## Invariants

- ContextBundle is candidate evidence, not accepted truth.
- RCA does not write HKA.
- Ranking does not grant authority.
- Provider-specific retrieval details stay behind RCA/DRI/EBF boundaries unless exposed as diagnostics.

## Allowed Producers

- RCA retrieval/runtime paths.
- DRI rebuild/invalidation signals as inputs, not bundle authorities.

## Allowed Consumers

- HIX, CAO, MEM recall/review, GOV evidence review, OEF evaluation.

## Forbidden Use

- Do not persist bundle content as accepted knowledge without HKA/GOV path.
- Do not use ContextBundle as memory instruction without MEM/GOV posture.
- Do not treat `may_write=false` evidence as mutation authority.

## Failure Modes

- Retrieval becomes truth.
- Memory becomes hidden instruction through cited but unreviewed evidence.
- Provider-specific result shape leaks to agents/UI.

## Transitional Implementation Notes

Existing `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and context-bundle runtime docs remain source references. This stub records the target SBS owner and required fields.

## Open Questions

- Which bundle fields are required for all consumers versus diagnostics-only?
- Which retrieval method/version details should be retained for audit and eval?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/CONTEXT_BUNDLES_RUNTIME/README.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`
