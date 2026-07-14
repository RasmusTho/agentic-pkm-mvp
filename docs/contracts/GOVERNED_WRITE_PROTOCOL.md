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
- The logical effect chain is ordered and non-collapsible:
  `evidence/proposal -> PolicyDecision -> DecisionToken -> state-owner mutation or EXE effect ->
  state-owner mutation receipt or EXE effect receipt -> AuthorityReceipt -> downstream effect
  notification / derived repair`.
  A producer may prepare evidence or a proposal, but it must not skip, combine, or reorder the
  governance and mutation stages.
- Chain ownership stays separated:
  - the initiating producer owns the evidence/proposal and requested write class;
  - GOV owns policy evaluation, DecisionToken issuance/validation, and AuthorityReceipt recording;
  - the state-owning subsystem owns mutation mechanics and its mutation receipt;
  - EXE is the effect owner for authorized external/tool effects and owns the corresponding effect
    mechanics and effect receipt, never their authorization;
  - SIP owns identity and provenance continuity;
  - DRI owns rebuildable projection repair or suppression after source correction; and
  - OEF observes and evaluates the chain but does not authorize, mutate, or close recovery state.
- A DecisionToken is bound to the actor, action, write class, resource, and decision that produced
  it. A state owner or EXE must reject a missing, invalid, expired, revoked, mismatched, or
  already-consumed token before mutation or effect.
- Success is not acknowledged until the state-owner mutation or EXE effect result, its corresponding
  mutation/effect receipt, and the durable AuthorityReceipt are known. An outbox/event notification
  is evidence of a completed stage, not a substitute for either receipt.
- Replays are idempotent by a stable operation/effect identity. Retrying an uncertain outcome must
  reconcile the state-owner mutation receipt or EXE effect receipt and AuthorityReceipt before
  repeating the mutation/effect.

### Partial-failure states

Every authority-bearing producer and consumer must preserve one of these explicit states; no state
may be collapsed into a generic success or silently retried:

| State | Required handling |
| --- | --- |
| `denied_or_review_required` | No token and no mutation/effect. Preserve the GOV reason for the caller/review surface. |
| `authorized_not_started` | No mutation/effect receipt exists. The token may expire or be revoked; retry requires token revalidation. |
| `mutation_or_effect_failed` | Preserve the state-owner/EXE failure result and record a failed AuthorityReceipt when the mutation/effect outcome is known. Never emit success. |
| `applied_receipt_pending` | The mutation/effect may have landed but its AuthorityReceipt is not durable. Do not acknowledge or blind-retry; reconcile by stable operation/effect identity. |
| `receipted_notification_pending` | Mutation/effect and AuthorityReceipt are durable, while outbox/event publication is pending. Replay notification only; never repeat the mutation/effect. |
| `completed` | Mutation/effect receipt and AuthorityReceipt are durable and any required notification is durably queued or recorded. |
| `source_corrected_repair_pending` | The original AuthorityReceipt remains immutable history. SIP preserves the correction lineage; DRI suppresses or rebuilds affected derived state idempotently before it is served as current. |

These are logical contract states, not a prescribed module, database table, package layout, or claim
that the transitional runtime already enforces the whole chain.

## Allowed Producers

- HIX human approvals/rejections.
- CAO proposals.
- EXE execution requests.
- State-owning subsystems requesting authority-bearing mutation.
- API/interaction producers that request capture, panel/canvas confirmation, settings changes, or
  other durable human-facing effects.
- Orchestrator/agent producers that request a real tool or vault effect through EXE.
- Evaluation-capture producers that submit a review candidate as evidence and request an explicit
  human promote/reject status transition; only the latter is authority-bearing.
- OEF findings only as evidence/proposals; an evaluator must never turn its own finding into
  authorization.

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
