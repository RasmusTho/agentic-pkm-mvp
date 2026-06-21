State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative decision for contract-first, module-lazy SBS operationalization.
Owner: Architecture spine / CES practice
Temporal class: Durable decision
Source of truth: This ADR plus `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`

# ADR-0016: Use contract-first, module-lazy instantiation

**Date:** 2026-06-21
**Status:** Accepted

## Context

The target SBS names more conceptual boundaries than the current runtime should immediately split into modules, services, packages, teams, or deployment units.

## Decision

Declare all target SBS boundaries now as contracts and charters. Do not instantiate every conceptual subsystem as a separate physical module/service immediately.

A conceptual boundary becomes physically separate only when justified by volatility, ownership, failure mode, authority posture, deployment posture, storage lifecycle, repeated boundary violations, or failed replacement exercises.

## Consequences

- The repository gains clear conceptual ownership without premature module bloat.
- Boundary registers and contract stubs can exist before implementation splits.
- Physical separation remains evidence-driven.

## Validation

The boundary register must distinguish conceptual boundary, contract existence, enforcement, and physical module status.

## References

- `docs/architecture/SBS_BOUNDARY_REGISTER.md`
- `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
