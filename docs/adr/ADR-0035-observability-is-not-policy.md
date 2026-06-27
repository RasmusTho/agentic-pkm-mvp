State: Accepted (doctrine-level architecture decision, 2026-06-26).
Doc role: Decision record (ADR)
Authority: Authoritative doctrine-level decision that observation/evaluation does not constitute policy or authority.
Owner: OEF / GOV / CES
Temporal class: Durable decision
Source of truth: This ADR plus the OEF charter and [ADR-0022](./ADR-0022-oef-first-class-non-authoritative.md)
Parent issue: #2533
Related issue: #2549

# ADR-0035: Observability is not policy

**Date:** 2026-06-26
**Status:** Accepted

## Context

OEF can observe, trace, evaluate, warn, and block CI. That visibility is necessary for trust, but it
must not silently become policy or authority — otherwise the thing that *watches* behavior quietly
starts *deciding* it.

## Decision

> OEF observes and evaluates behavior; GOV gives normative meaning and makes policy and authority
> decisions. Observability is not policy.

## Consequences

- Metrics, evals, and traces can reveal drift but cannot silently control behavior.
- Audit visibility is not an authority receipt.
- Fitness tests belong to OEF; policy and authority decisions belong to GOV.

The OEF first-class-but-non-authoritative *posture* is recorded in
[ADR-0022](./ADR-0022-oef-first-class-non-authoritative.md), and CES-as-practice in
[ADR-0021](./ADR-0021-ces-architecture-stewardship-practice.md). This ADR records the doctrine-level
principle those decisions serve.

## Affected boundaries

OEF, GOV, CES.

## Affected invariants

- Traceability matrix row 13 (observability is not policy).
- Doctrine §4 (doctrine becomes real through boundaries; OEF enforces, GOV governs).

## Related docs

- Anchored in the [doctrine](../foundation/00-yggdrasil-doctrine.md).
- [OEF charter](../boundaries/OEF.md) · [GOV charter](../boundaries/GOV.md) ·
  [CES charter](../boundaries/CES.md) · [Traceability matrix](../architecture/traceability-matrix.md)
- Related decisions: [ADR-0022](./ADR-0022-oef-first-class-non-authoritative.md),
  [ADR-0021](./ADR-0021-ces-architecture-stewardship-practice.md).

## Related contracts / schemas

No new schema. OEF reads the metadata bundle and receipts; it does not own a mutation contract.

## Related tests / future fitness checks

- [SBS fitness rules](../architecture/SBS_FITNESS_RULES.md) /
  `tests/architecture/test_sbs_fitness_rules.py`; invariant registry — #2550.
