State: Target-state contract stub; current WriteGuard/receipt paths are transitional implementation evidence, not full contract implementation.
Doc role: Contract stub
Authority: Owns the target governed-write protocol for GOV.
Owner subsystem: GOV - Governance, Policy, Authority & Receipts
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-21

# GovernedWriteProtocol

## Purpose

Ensure every authority-bearing durable mutation is admissible before mutation and accountable after mutation.

## Inputs

- Actor/principal.
- Resource/artifact/memory/execution target.
- ActiveContextSet reference.
- Requested write class.
- Evidence/proposal/context references.
- Policy profile and delegation state.

## Outputs

- PolicyDecision.
- DecisionToken for approved authority-bearing durable mutations.
- AuthorityReceipt after mutation outcome.
- Denial or review-required reason.

## Commands

- Evaluate policy.
- Issue DecisionToken.
- Validate DecisionToken before mutation.
- Record AuthorityReceipt after mutation.
- Revoke delegation or token when required.

## Queries

- Is this actor/action/resource/context admissible?
- Which review class applies?
- Which receipts exist for this mutation?
- Is the token still valid?

## Events

- `governance.policy_decision.issued`
- `governance.decision_token.issued`
- `governance.authority_receipt.recorded`
- `governance.decision.denied`

## Invariants

- Authority-bearing durable writes require pre-mutation DecisionToken validation.
- Authority-bearing durable writes emit post-mutation AuthorityReceipt.
- Rebuildable projection writes may use lighter policy if they do not carry irreplaceable meaning or accountability.
- GOV owns admissibility and accountability, not state-owner mutation mechanics.

## Allowed Producers

- HIX human approvals/rejections.
- CAO proposals.
- EXE execution requests.
- State-owning subsystems requesting authority-bearing mutation.

## Allowed Consumers

- HKA, MEM, EXE, SFC conflict workflows, HIX review surfaces, OEF audit views.

## Forbidden Use

- Do not use GOV as a storage, execution, rendering, or adapter god-core.
- Do not treat warning-only policy output as authorization.
- Do not emit receipts before the mutation result is known.

## Failure Modes

- Advisory governance.
- Governance god-core.
- Durable writes with no accountability.

## Transitional Implementation Notes

Existing WriteGuard, APPLY gates, receipts, and policy surfaces are transitional evidence. They should be mapped to PolicyDecision, DecisionToken, and AuthorityReceipt before widening write authority.

## Open Questions

- Which write classes are token-required in V1?
- Which rebuildable projection writes need receipts for audit even when not authority-bearing?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
