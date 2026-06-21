State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative survivability decision for human knowledge and governance receipts.
Owner: HKA / GOV / Architecture spine
Temporal class: Durable decision
Source of truth: This ADR plus HKA/GOV contracts

# ADR-0017: Preserve one irreplaceable human knowledge set plus durable governance receipts

**Date:** 2026-06-21
**Status:** Accepted

## Context

The platform distinguishes human knowledge, memory, semantic projection, retrieval, derived representation, and governance. Losing a derived machine artifact must not destroy human meaning or accountability.

## Decision

The survivability model is:

Irreplaceable:

- HKA artifact-origin facts.
- GOV decision/action receipts.

Rebuildable:

- SIP semantic projections.
- DRI indexes and derived representations.
- RCA context bundles.
- Embeddings.
- Retrieval artifacts.
- Derived memory indexes.

## Consequences

- SIP must not become a third irreplaceable store.
- If losing a record would destroy human meaning or accountability, it cannot live only in a rebuildable projection.
- HKA and GOV contracts must state survivability requirements explicitly.

## Validation

Fitness rules check that DRI and SIP records remain rebuildable unless reclassified into HKA, GOV, or MEM through the correct path.

## References

- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
