State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative decision splitting provenance ownership across HKA, GOV, and SIP.
Owner: HKA / GOV / SIP / Architecture spine
Temporal class: Durable decision
Source of truth: This ADR plus target SBS and contracts

# ADR-0018: Split provenance into artifact-origin, action/decision, and derived semantic lineage

**Date:** 2026-06-21
**Status:** Accepted

## Context

Provenance is overloaded across artifact origin, human/agent decisions, actions, semantic lineage, retrieval support, and derived projections.

## Decision

Provenance is not one thing.

- Artifact-origin provenance belongs in HKA.
- Action / decision / agent provenance belongs in GOV receipts.
- Derived semantic lineage belongs in SIP only if rebuildable.

## Consequences

- Origin survivability, accountability, and semantic enrichment are preserved without creating unnecessary irreplaceable stores.
- SIP projections cannot be the only record of origin facts or decision accountability.
- Contract and fitness work must classify provenance by owner.

## Validation

Review new provenance fields for owner: HKA for artifact origin, GOV for decisions/actions, SIP for rebuildable semantic lineage.

## References

- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/SEMANTIC_AUTHORITY_MATRIX.md`
