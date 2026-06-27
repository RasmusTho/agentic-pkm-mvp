State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative doctrine-level decision that machine/agent memory is noncanonical by default.
Owner: MEM / GOV / HKA
Temporal class: Durable decision
Source of truth: This ADR plus `../architecture/memory-model.md` and [ADR-0025](./ADR-0025-memory-authority-direct-write-policy.md)
Parent issue: #2533
Related issue: #2549

# ADR-0030: Agent memory is noncanonical

**Date:** 2026-06-26
**Status:** Accepted

## Context

Machine memory aids recall and reasoning, but it is reconstructive and revisable. Treating it as
durable knowledge would let claims accrue authority by accumulation or repetition, exactly the drift
the doctrine forbids.

## Decision

> Machine/agent memory is advisory and noncanonical by default. Promotion to durable human knowledge
> requires GOV authorization and HKA materialization.

## Consequences

- MEM may remember and *request* promotion; MEM cannot promote itself.
- On approval, HKA materializes a separate canonical `AcceptedArtifact` and GOV issues an
  `AuthorityReceipt`; the memory record's `authority_state` stays noncanonical (the artifact, not the
  memory, is the canonical thing).
- Memory cannot be cited as real-world evidence unless the claim is about the memory itself.
- The `MemoryItem` schema pins memory authority to noncanonical.

The direct-write / provisional-tier *mechanism* is recorded in
[ADR-0025](./ADR-0025-memory-authority-direct-write-policy.md); canonical-set survivability in
[ADR-0017](./ADR-0017-human-knowledge-and-governance-survivability.md). This ADR records the
doctrine-level commitment those mechanisms serve.

## Affected boundaries

MEM, GOV, HKA, SIP, RCA, CAO, OEF.

## Affected invariants

- Traceability matrix row 4 (agent memory is noncanonical by default).
- Doctrine §2.4 (memory is reconstructive and noncanonical until promoted).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [memory-model](../architecture/memory-model.md) · [MEM charter](../boundaries/MEM.md) ·
  [GOV charter](../boundaries/GOV.md) · [HKA charter](../boundaries/HKA.md)
- Related decisions: [ADR-0025](./ADR-0025-memory-authority-direct-write-policy.md),
  [ADR-0017](./ADR-0017-human-knowledge-and-governance-survivability.md),
  [ADR-0031](./ADR-0031-authority-transition-flow-governs-durable-mutation.md).

## Related contracts / schemas

- [`memory-item.schema.json`](../../schemas/memory-item.schema.json) ·
  [`authority-transition.schema.json`](../../schemas/authority-transition.schema.json) ·
  [`metadata-bundle.schema.json`](../../schemas/metadata-bundle.schema.json).

## Related tests / future fitness checks

- Invariant registry — #2550; anti-contamination eval corpus — #2551.
