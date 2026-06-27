State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative that external standards are adapters/interoperability layers, not Yggdrasil's ontology.
Owner: Architecture spine / CES practice
Temporal class: Durable decision
Source of truth: This ADR plus doctrine §2.7 and `../architecture/functional-ontology.md`
Parent issue: #2533
Related issue: #2549

# ADR-0036: Standards are adapters, not the ontology

**Date:** 2026-06-26
**Status:** Accepted

## Context

PROV-O, SKOS, ABAC/ReBAC, MCP, OpenTelemetry, and similar standards are attractive shortcuts.
Adopting one as *the model* would let an external vocabulary define Yggdrasil's distinctions instead
of its own doctrine.

## Decision

> External standards and frameworks may be used as adapters, implementation patterns, or
> interoperability layers, but Yggdrasil's ontology is defined by its own doctrine, functional
> ontology, semantic dimensions, boundaries, and contracts.

## Consequences

- Standards may be mapped at the edge (EBF) but do not redefine `source_role`, `authority_state`,
  `evidence_role`, or the boundary set.
- Interoperability adapters must preserve the metadata bundle and provenance, not strip them.

## Affected boundaries

EBF, SIP, GOV, CES.

## Affected invariants

- Doctrine §2.7 (standards are adapters, not the ontology).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md) and [traceability matrix](../architecture/traceability-matrix.md).
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) ·
  [Functional ontology](../architecture/functional-ontology.md) ·
  [Context packet](../foundation/yggdrasil-architecture-context-packet.md) ·
  [Boundary charters index](../boundaries/README.md) (EBF charter pending).

## Related contracts / schemas

No new schema. This decision constrains how external schemas/standards may be adapted into the
existing contract set, not a contract of its own.

## Related tests / future fitness checks

- Invariant registry — #2550 (advisory); CES stewardship review at standard-adoption time.
