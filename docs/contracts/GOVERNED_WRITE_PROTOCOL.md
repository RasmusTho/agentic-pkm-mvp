State: Target-state contract stub; current WriteGuard/receipt paths are transitional implementation evidence, not full contract implementation.
Doc role: Contract stub
Authority: Owns the target governed-write protocol for GOV.
Owner subsystem: GOV - Governance, Policy, Authority & Receipts
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-08-07

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
- Vault-bound append/reconcile cleanup must carry descriptor ownership through the cleanup state
  transition. A pathname check followed by pathname deletion is not ownership proof: the active
  stage entry must move atomically and without clobbering into scanner-inert recovery storage while
  the operation-owned descriptor remains open, and the moved inode must then match that descriptor.
  If the name disappeared, moved a foreign inode, or cannot be restored without clobbering, the
  implementation retains both the untrusted entry and operation-owned bytes as needed and fails
  loud. Retirement from the active stage namespace is not a claim of physical deletion.

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

## Vault-bound atomic append/reconcile

`app.knowledge.atomic_append_reconcile.atomic_append_reconcile_relative` is the filesystem-seam
primitive for one caller-authorized, vault-relative append record. It is deliberately an opt-in
primitive, not a replacement for ordinary `KnowledgePort.append_note`, and a caller retains its
own `WriteGuard` action and authority decision.

- The caller supplies a stable portable operation identity, the exact SHA-256 payload fingerprint,
  payload, and a pure reconciliation callback. The primitive rejects a fingerprint that does not
  bind the supplied payload before opening the vault, and asserts the caller's `WriteGuard` before
  any filesystem mutation.
- A durable record is a versioned framed payload with a matching identity/fingerprint commit
  marker. Only a complete frame with a valid length and digest is committed. A torn, malformed, or
  duplicate-identity frame is an explicit recovery error: reconciliation is not called and retry
  must not append ambiguously.
- The same identity and fingerprint returns `reconciled_replay` after reconciliation; the same
  identity with another fingerprint is an identity collision before publication. A new identity
  returns `appended`. These structured results, rather than a mutable path read, are the caller's
  outcome authority.
- The caller-authorized source binding, each parent component, and target are opened
  descriptor-relatively with no symlink
  following. The primitive rejects aliases, non-regular targets, or root/parent/target identity
  changes. Cooperating writers serialize on a separate descriptor-bound per-target lock whose inode
  survives target exchange; a replacement race is retained for recovery and fails without a success
  result.
- New and already-present parent links, staged data, atomic exchange, recovery retirement, and every
  directory whose durable link is relied on are fsynced. Replacement copies and verifies mode,
  owner, descriptor ACLs, ACL-bearing extended metadata, and required xattrs before publication and
  rechecks that metadata immediately before exchange. Missing metadata primitives or any failed
  clone/verification is fail-closed.
- Before mutation and again before success, the primitive takes a stable descriptor-bound inventory
  of both active and scanner-inert entries for the target/operation scope. Inventory races,
  malformed or aliased entries, and late active entrants fail loud. The transitional implementation
  caps the aggregate recovery directory at 256 entries. It atomically no-replace reserves two
  durable capacity slots before stage creation—one retirement plus one owner snapshot—across all
  target locks sharing that directory. An entry consumes its slot at the namespace transition, so
  crashes and failed durability fences cannot release occupied capacity; unused slots are restored
  without clobbering. Capacity exhaustion refuses mutation and never prunes evidence or adds a
  second blocking lock.
- The operation keeps its stage or displaced-target descriptor open until cleanup retirement. It
  atomically renames the active stage entry without replacement into a hidden recovery directory,
  then compares the moved inode with that descriptor. Matching evidence is retired from the active
  scanner namespace. Foreign or missing evidence is restored or retained without clobbering, the
  operation-owned descriptor is durably snapshotted when its link was lost, and the call fails loud.
  Retained entries are scanner-inert evidence; this primitive does not physically reclaim them.

The reconciliation callback receives only verified complete records and must retain their exact
set. It may repair derived bookkeeping in the replacement bytes, but it must not acknowledge,
delete, rewrite, or synthesize a committed operation frame. A target-scoped interrupted active
stage is classified and retired on retry; the complete target frame remains the sole replay
authority. This primitive does **not** migrate the Heimdal steering-log consumer or any other
consumer.

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
