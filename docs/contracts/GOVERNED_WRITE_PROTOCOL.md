State: Partial runtime implementation: context-bound capture and selected-binding effect fencing are shipped; the wider governed-effect contract remains target state.
Doc role: Contract
Authority: Owns the target governed-write protocol for GOV.
Owner subsystem: GOV - Governance, Policy, Authority & Receipts
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-10-25

# GovernedWriteProtocol

## Purpose

Ensure every authority-bearing durable mutation and every authority-bearing external/tool effect is
admissible before it occurs and accountable after its outcome is known.

## Inputs

- Actor/principal.
- Resource/artifact/memory/execution target.
- ActiveContextSet reference.
- Requested write/effect class.
- Evidence/proposal/context references.
- Policy profile and delegation state.

## Outputs

- PolicyDecision.
- DecisionToken for approved authority-bearing durable mutations or authority-bearing external/tool
  effects.
- AuthorityReceipt after the state-owner mutation or EXE effect outcome.
- Denial or review-required reason.

## Context-bound capture and ownership transfer (MVR-05C)

The production scoped capture endpoint is `POST /api/companion/capture/scoped`. Its bearer selects
one immutable `ActiveContextSetV1`; its `target_binding_id` must name exactly one member of that
selected set. Registration, ownership, or an independent GOV allow cannot widen the selection.
A batch gate requires a nonempty subset without duplicates. Client paths are never authority.
The existing carrier-free capture and compatibility endpoint preserve their request/response
journeys and translate their sealed sole target into an ephemeral server-derived context.

`DecisionToken` and `AuthorityReceipt` add `active_context` and `target_binding_id`. The frozen
context carries principal identity/kind/revision, instance identity, context ID/generation,
workspace or explicit no-workspace, scope, spheres, situated identity, dimension provenance,
selection capability digest, the complete selected binding set with each revision/authorization
epoch, registry revision, posture, and expiry. The raw bearer is absent. Other existing effect
producers serialize explicit nulls for these additive fields; retained non-context EXE receipts
have a bounded null-field migration. An unbound/legacy-shaped token cannot authorize a
context-bound vault write, and EXE cannot borrow a scoped capture token.

Immediately before effect, GOV validates actor, action, write class, resource, exact context and
selected target. The production window holds principal read authority, the host ownership fence
and the target binding's cross-process shared effect lease through the append, optional
same-note registration proposal, mutation/authority receipts, and durable event persistence.
The canonical locator's nearest initialized vault boundary must be the target root, including at
the state-owner append and proposal seams. Registered and unregistered nested children therefore
require their own selected binding and authority. Revocation/rotation and exclusive binding changes
wait for the existing authorized window or invalidate it before I/O. Removal and relocation retain
their later-slice capability refusals.

`InstanceRegistryRuntime.transfer_to` and `recover_transfer` own the source-channel transfer
journal. They close source ingress, drain original-source queue rows through the real worker,
repair compatibility through `settings_rebind.v1`, consume the production-derived stopped-window
inventory/restart fence, drain final shutdown emissions, and only then advance the foreground
ownership floor together with the qualified registry schema (`agentic-pkm.instance-vault-registry.v2`).
Pre-05C images reject that schema at their existing reader gate; bootstrap and retained compatibility
producers remain on v1 until activation. The host can supply the process-stop/proof port; it cannot replace authority,
inventory, drain, reference repair, or release logic. Missing, stale, or forged proof leaves
ownership unchanged. Source retirement atomically repairs default/dimension membership and
records its tombstone/lineage. Destination registration uses a minted destination-local binding;
no default, dimension, or watcher selection is inferred. The ledger activates one destination
owner, retaining the original source identity and immutable lineage. Recovery reuses those IDs
and refuses source-state drift instead of reinstalling a captured registration. After activation,
only that transfer's temporary stopped window is released; the retired source root remains fenced
against restart and foreground use. Root admission reads only qualified existing registry state;
missing or unqualified authority refuses before an effect and is never initialized or repaired by
a cached filesystem port or an admission probe. A retired scalar rollback target remains historical lineage
and cannot be used by an older image.

## Commands

- Evaluate policy.
- Issue DecisionToken.
- Validate DecisionToken before state-owner mutation or EXE effect.
- Record AuthorityReceipt after the mutation/effect outcome and its mutation/effect receipt are known.
- Revoke delegation or token when required.

## Queries

- Is this actor/action/resource/context admissible?
- Which review class applies?
- Which mutation/effect receipt and AuthorityReceipt exist for this mutation/effect?
- Is the token still valid?

## Events

- `governance.policy_decision.issued`
- `governance.decision_token.issued`
- `governance.authority_receipt.recorded`
- `governance.decision.denied`

## Invariants

- Authority-bearing durable writes and authority-bearing external/tool effects require DecisionToken
  validation before the state-owner mutation or EXE effect.
- Authority-bearing durable writes and authority-bearing external/tool effects emit an
  AuthorityReceipt after the mutation/effect outcome and mutation/effect receipt are known.
- Rebuildable projection writes may use lighter policy if they do not carry irreplaceable meaning or accountability.
- GOV owns admissibility and accountability, not state-owner mutation or EXE effect mechanics.
- The logical effect chain is ordered and non-collapsible:
  `evidence/proposal -> PolicyDecision -> DecisionToken -> state-owner mutation or EXE effect ->
  state-owner mutation receipt or EXE effect receipt -> AuthorityReceipt -> downstream effect
  notification / derived repair`.
  A producer may prepare evidence or a proposal, but it must not skip, combine, or reorder the
  governance and mutation/effect stages.
- Chain ownership stays separated:
  - the initiating producer owns the evidence/proposal and requested write/effect class;
  - GOV owns policy evaluation, DecisionToken issuance/validation, and AuthorityReceipt recording;
  - the state-owning subsystem owns mutation mechanics and its mutation receipt;
  - EXE is the effect owner for authorized external/tool effects and owns the corresponding effect
    mechanics and effect receipt, never their authorization;
  - SIP owns identity and provenance continuity;
  - DRI owns rebuildable projection repair or suppression after source correction; and
  - OEF observes and evaluates the chain but does not authorize, mutate, or close recovery state.
- A DecisionToken is bound to the actor, action, write/effect class, resource, and decision that produced
  it. A state owner or EXE must reject a missing, invalid, expired, revoked, mismatched, or
  already-consumed token before mutation or effect.
- Success is not acknowledged until the state-owner mutation or EXE effect result, its corresponding
  mutation/effect receipt, and the durable AuthorityReceipt are known. An outbox/event notification
  is evidence of a completed stage, not a substitute for either receipt.
- Replays are idempotent by a stable operation/effect identity. Retrying an uncertain outcome must
  reconcile the state-owner mutation receipt or EXE effect receipt and AuthorityReceipt before
  repeating the mutation/effect.

The shipped reviewed semantic-memory materialization path is one concrete producer integration:
MEM derives the authority request from the persisted human promotion decision, GOV issues and
validates a token bound to `memory.materialize`, `semantic_memory_materialization`, the reviewer,
and the exact HKA artifact path, and HKA owns the create-once note mutation receipt. The promotion
receipt and GOV AuthorityReceipt remain separate durable facts, and MEM does not mark the review
decision terminal until both are queryable. An HKA artifact alone cannot be used to synthesize a
missing governed mutation receipt; that state fails closed for explicit remediation. This integration
does not claim that unrelated runtime write paths implement the full protocol.

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
- Do not emit an AuthorityReceipt before the state-owner mutation or EXE effect result and its
  mutation/effect receipt are known.

## Failure Modes

- Advisory governance.
- Governance god-core.
- Authority-bearing durable writes or authority-bearing external/tool effects with no accountability.

## Transitional Implementation Notes

Existing WriteGuard, APPLY gates, receipts, and policy surfaces are transitional evidence. They
should be mapped to PolicyDecision, DecisionToken, mutation/effect receipt, and AuthorityReceipt
before widening write or effect authority.

## Open Questions

- Which write/effect classes are authority-bearing and token-required in V1?
- Which rebuildable projection writes need receipts for audit even when not authority-bearing?

## Linked Source-Of-Truth Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
- `docs/architecture/SBS_FITNESS_RULES.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/CONCEPTS/WORKFLOW_MUTATION_AND_GOVERNANCE_SEMANTICS.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
