State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative doctrine-level decision on what kind of system Yggdrasil is (and is not).
Owner: Architecture spine (doctrine)
Temporal class: Durable decision
Source of truth: This ADR plus `../foundation/00-yggdrasil-doctrine.md` and `../foundation/yggdrasil-architecture-context-packet.md`
Parent issue: #2533
Related issue: #2549

# ADR-0026: Yggdrasil as cognitive prosthesis

**Date:** 2026-06-26
**Status:** Accepted

## Context

The architecture synthesis settled what *kind* of system Yggdrasil is. Left only in prose, that
framing erodes: future work drifts toward treating it as "just a vector DB", "a RAG app", or "a
chatbot wrapper", and silently hands authorship of meaning to the machine. This ADR freezes the
system-class decision so the distinction is not re-litigated by implementation pressure.

## Decision

> Yggdrasil is a cognitive prosthesis for a specific human and a low-trust agentic interlocutor. It
> is not merely a database, RAG application, note-search tool, or oracle.

## Consequences

- The human remains the locus of meaning and authority; the system proposes, recalls, relates, and
  explains, but does not decide what becomes durable knowledge.
- Human-authored material is **not** automatically canonical — authorship sets `source_role`, not
  `authority_state` (see [ADR-0029](./ADR-0029-source-authority-evidence-roles-are-orthogonal.md)).
- Agent contributions are guests until promoted through governance; they earn standing, never accrue
  it by similarity, accumulation, or repetition.
- The system reduces friction, not intelligence: when uncertain it proposes, confirms, or escalates
  rather than silently acting.

## Affected boundaries

HIX, HKA, SIP, GOV, MEM, CAO, OEF, CES — this ADR is the umbrella the per-boundary decisions hang
from; it constrains every boundary that touches human authority, agent contribution, or evaluation.

## Affected invariants

- Doctrine §1 (what Yggdrasil is) and §2 (load-bearing commitments).
- Traceability matrix row 17 (when uncertain, propose/confirm/escalate rather than silently act),
  row 15 (human-authored ≠ canonical), row 4 (agent memory noncanonical).

## Related docs

- [Doctrine](../foundation/00-yggdrasil-doctrine.md) · [Context packet](../foundation/yggdrasil-architecture-context-packet.md)
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md) · [Functional ontology](../architecture/functional-ontology.md)
- [Traceability matrix](../architecture/traceability-matrix.md)

## Related contracts / schemas

No new contract. This ADR governs the framing that the contract set
([ADR-0027](./ADR-0027-scope-as-frame-audience-policy-and-provenance.md)–[ADR-0039](./ADR-0039-retrieval-result-is-candidate-context-not-authority.md)
and `schemas/`) implements.

## Related tests / future fitness checks

- Invariant registry — #2550 (this decision is enforced indirectly through the per-distinction
  invariants it umbrellas).
