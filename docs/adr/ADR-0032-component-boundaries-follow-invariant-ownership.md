State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that Yggdrasil decomposes by invariant ownership, not by UI/storage/agent-implementation detail.
Owner: Architecture spine / CES practice
Temporal class: Durable decision
Source of truth: This ADR plus `../SYSTEM_BREAKDOWN_STRUCTURE.md` and the boundary charters
Parent issue: #2533
Related issue: #2549

# ADR-0032: Component boundaries follow invariant ownership

**Date:** 2026-06-26
**Status:** Accepted

## Context

Decomposing by feature, storage technology, or agent implementation produces boundaries that cut
across invariant ownership, which lets authority, provenance, and scope leak between concerns that
should stay separate.

## Decision

> Yggdrasil decomposes by authority, cognitive-context, and representation boundaries — not by UI
> feature, storage technology, or agent implementation detail. Component boundaries follow invariant
> ownership.

## Consequences

- Boundaries define ownership and *forbidden* ownership, not one-to-one runtime services
  (contract-first, module-lazy — [ADR-0016](./ADR-0016-contract-first-module-lazy-sbs.md)).
- The separations HKA/SIP/PDM, RCA/GOV/SIP, MEM/GOV/HKA, CAO/GOV/EXE, WSP/SFC, and OEF/GOV must
  remain distinct.
- CES is a stewardship practice, not a runtime peer subsystem
  ([ADR-0021](./ADR-0021-ces-architecture-stewardship-practice.md)).

## Affected boundaries

All Level 2 control boundaries — HIX, WSP, HKA, SIP, GOV, EBF, PDM, DRI, RCA, MEM, CAO, EXE, SFC, OEF
— plus the CES stewardship practice.

## Affected invariants

- Traceability matrix row 12 (storage preserves but does not define meaning) and the SBS
  forbidden-dependency rules.
- Doctrine §3–§4 (distinctions must not collapse; doctrine becomes real through boundaries).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) ·
  [Boundary charters index](../boundaries/README.md) ·
  [Context packet](../foundation/yggdrasil-architecture-context-packet.md)
- Related decisions: [ADR-0015](./ADR-0015-authority-first-target-sbs.md) (authority-first SBS),
  [ADR-0016](./ADR-0016-contract-first-module-lazy-sbs.md) (contract-first, module-lazy),
  [ADR-0021](./ADR-0021-ces-architecture-stewardship-practice.md) (CES as practice).

## Related contracts / schemas

No new schema. The boundary set is expressed by the charters under `../boundaries/` and the SBS
boundary register.

## Related tests / future fitness checks

- Existing fitness checks: `tests/architecture/test_component_boundaries.py`,
  `tests/architecture/test_sbs_boundary_register_verification.py`,
  `tests/architecture/test_semantic_boundary_fitness.py`.
- Invariant registry — #2550.
