State: Accepted (target-state architecture decision, 2026-06-21).
Doc role: Decision record (ADR)
Authority: Authoritative target decision for governed writes.
Owner: GOV / EXE / HKA / MEM
Temporal class: Durable decision
Source of truth: This ADR plus `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`

# ADR-0019: Enforce governed writes with DecisionToken and AuthorityReceipt

**Date:** 2026-06-21
**Status:** Accepted

## Context

Governance must be stronger than advisory warnings, but it must not become a mechanism god-core that owns every storage, rendering, routing, or execution detail.

## Decision

Any authority-bearing durable mutation must present a valid GOV-issued DecisionToken before mutation and emit a durable AuthorityReceipt after mutation.

GOV owns admissibility, policy, delegation, authority, and accountability. State-owning subsystems own their own mutation mechanisms.

## Consequences

- This avoids both governance-as-god-core and advisory-only governance.
- Write classes need explicit classification.
- EXE, HKA, MEM, and other state owners must preserve receipt linkage when performing governed effects.

## Validation

The SBS fitness rules treat authority-bearing durable writes without DecisionToken and AuthorityReceipt as a blocking target invariant.

## References

- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/contracts/EXECUTION_REQUEST.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
