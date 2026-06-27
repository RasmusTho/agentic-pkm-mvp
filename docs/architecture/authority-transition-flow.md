State: Canonical Yggdrasil AuthorityTransition contract. Docs-only architecture/schema contract for the foundation backlog (#2533–#2552); the governed contract for durable mutation of human knowledge. Pairs with `schemas/authority-transition.schema.json`. Does not claim shipped runtime behavior.
Doc role: Architecture / contract
Authority: Owns the `AuthorityTransition` contract — the architecture state object behind WriteGuard-equivalent governed durable mutation. The machine-readable form is `schemas/authority-transition.schema.json`; this doc is its prose mirror. It composes with the existing GOV `GovernedWriteProtocol` (`docs/contracts/GOVERNED_WRITE_PROTOCOL.md`) and the runtime WriteGuard (`app/write_guard.py`). Subordinate to `docs/foundation/00-yggdrasil-doctrine.md`, `docs/architecture/functional-ontology.md`, and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`.
Owner: Architecture spine
Temporal class: strategic
Review cadence: event-driven
Source of truth: canonical (AuthorityTransition contract); subordinate to doctrine, ontology, SBS
Last reviewed: 2026-06-27
Last verified against: docs/architecture/functional-ontology.md, docs/architecture/semantic-dimensions.md, docs/contracts/GOVERNED_WRITE_PROTOCOL.md, docs/boundaries/GOV.md, docs/boundaries/HKA.md, docs/boundaries/EXE.md, schemas/authority-transition.schema.json

# Yggdrasil AuthorityTransition

Parent epic: [#2533](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2533) ·
Contract issue: [#2547](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2547) ·
Schema: [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json)

`AuthorityTransition` is the **governed contract for durable mutation of human knowledge**. The
earlier term *WriteGuard* names the runtime mechanism; the system breakdown is clearer if durable
mutation is described as a transition flow: proposal/correction → governance → durable artifact/state
transition → provenance → derived-representation invalidation. This document defines that contract;
the machine-checkable form is
[`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json).

> **Durable human knowledge changes only through an AuthorityTransition.**

Read first: the [doctrine](../foundation/00-yggdrasil-doctrine.md) §2.6, the
[GOV charter](../boundaries/GOV.md), and the existing
[GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md).

## 1. Relationship to WriteGuard and GovernedWriteProtocol

The term `WriteGuard` already exists in the codebase (`app/write_guard.py`) and docs. To avoid
renaming live terminology:

- **WriteGuard** is the **runtime enforcement mechanism** — the code that intercepts writes and demands
  a valid decision before a durable mutation proceeds.
- **GovernedWriteProtocol** ([contract](../contracts/GOVERNED_WRITE_PROTOCOL.md)) is the GOV-owned
  runtime protocol: `PolicyDecision` → `DecisionToken` (validated pre-mutation) → `AuthorityReceipt`
  (recorded post-mutation).
- **AuthorityTransition** (this contract) is the **architecture contract / state object** that
  describes a governed durable mutation end to end: actor, initiating source, target, prior/requested/
  approved authority state, approval, receipt, provenance, and affected derived representations.

An AuthorityTransition references a `decision_token_ref` and an `authority_receipt_id`, tying the
architecture state object to the runtime WriteGuard/GovernedWriteProtocol path. This contract does not
replace that live terminology.

## 2. Initiating sources

`initiating_source` ∈ `human_correction`, `human_approval`, `agent_proposal`,
`memory_promotion_request`, `repair`, `sync_conflict_resolution`, `external_import_review`.

## 3. Transition fields

`transition_id`, `actor_id`, `initiating_source`, `target_object_id`, `target_scope_id`,
`prior_authority_state`, `requested_authority_state`, `approved_authority_state` (conditional),
`operation_type`, `approval_required`, `approval_state`, `approval_exemption_policy_ref`
(conditional), `approved_by`/`approved_at` (conditional), `authority_receipt_id` (conditional),
`decision_token_ref`, `promotion_request_id` (conditional), `provenance_event_ids`,
`affected_derived_representation_ids`, `base_version`, `result_version`, `conflict_state`,
`rollback_ref`, `created_at`.

## 4. Required rules

1. **Durable human knowledge changes only through AuthorityTransition.**
2. **Persistence writes are not authority transitions.** Storing bytes (PDM) is not changing standing.
3. **Agent proposals are not mutations.** A `Proposal` mutates nothing; it may *initiate* a transition
   (`initiating_source: agent_proposal`) that GOV must approve.
4. **Memory promotion requires AuthorityTransition** (`initiating_source: memory_promotion_request`,
   carrying the `promotion_request_id`). See [memory-model](memory-model.md).
5. **Sync conflict resolution that changes semantic authority requires AuthorityTransition.** SFC
   stages conflicts; GOV decides. `conflict_state` records the posture.
6. **Repair that changes authority or identity requires AuthorityTransition** (`initiating_source:
   repair`). Mechanical rebuilds that change nothing semantic do not.
7. **EXE may not use side effects to bypass AuthorityTransition.** Execution consumes authorization; it
   never mints it ([EXE charter](../boundaries/EXE.md): `execution_cannot_authorize_itself`).
8. **DRI must invalidate/rebuild affected derived representations after accepted transitions** — the
   `affected_derived_representation_ids` field makes the rebuild obligation explicit.

## 5. Schema requirements

[`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json):

- requires `prior_authority_state` and `requested_authority_state`;
- requires `actor_id` and `initiating_source`;
- requires `target_object_id` and `target_scope_id`;
- requires `approval_required` and `approval_state`;
- requires, once `approval_state` is `approved`, both the pre-mutation `decision_token_ref` and the
  post-mutation `authority_receipt_id` (plus `approved_by`, `approved_at`, `approved_authority_state`)
  — mirroring the [GovernedWriteProtocol](../contracts/GOVERNED_WRITE_PROTOCOL.md) invariant so an
  approved transition cannot bypass governed-write enforcement; otherwise the pending/rejected receipt
  state is explicit;
- guards on the **actual** grant, not just the request: any transition whose `approved_authority_state`
  is `accepted`/`canonical` must carry `decision_token_ref` + `authority_receipt_id` regardless of
  `requested_authority_state` or the approval path, and if it is approval-exempt
  (`approval_required: false`) it must also reference `approval_exemption_policy_ref` — closing the gap
  where a lower requested state with a canonical approved state could otherwise skip the governance
  artifacts;
- covers authority changes **out of** canonical too: a completed no-approval transition whose
  `prior_authority_state` is `accepted`/`canonical` (e.g. a deprecate/retract/correct of canonical
  knowledge) must carry `decision_token_ref` + `authority_receipt_id` — an authority-bearing durable
  write is tokened and receipted whether it moves into or out of canonical standing;
- requires `provenance_event_ids` and an explicit `affected_derived_representation_ids` array;
- keeps `approval_required` and `approval_state` consistent: `approval_required: true` forbids
  `approval_state: not_required`, and `approval_required: false` requires `approval_state: not_required`
  — a transition cannot claim both that approval is and is not required;
- forbids grant artifacts on a **non-grant** approval state: when `approval_state` is `pending`,
  `rejected`, or `withdrawn`, the transition must carry no `approved_authority_state`, `approved_by`,
  `approved_at`, `decision_token_ref`, or `authority_receipt_id` — authority is materialized only on
  `approved` or via the `approval_required: false` exemption path, so a transition can never be
  simultaneously rejected/pending and granting authority;
- requires approval for promotion to `accepted`/`canonical` authority unless an explicit
  `approval_exemption_policy_ref` is provided — and that exemption path **still** requires
  `decision_token_ref` + `authority_receipt_id` + `approved_authority_state`, because an
  approval-exempt canonical write is still a governed durable mutation and must not bypass the
  GovernedWriteProtocol token/receipt invariant;
- requires `promotion_request_id` for memory-promotion transitions;
- closes the object (`additionalProperties: false`) with an explicit `extensions` point.

## Related documents

- [Architecture context packet](../foundation/yggdrasil-architecture-context-packet.md)
- [System Breakdown Structure](../SYSTEM_BREAKDOWN_STRUCTURE.md)
- [Doctrine](../foundation/00-yggdrasil-doctrine.md) — human authority changes durable knowledge only through governed transition
- [Functional ontology](functional-ontology.md) (`AuthorityReceipt`, `AcceptedArtifact`, `ExecutionEffect`) · [Semantic dimensions](semantic-dimensions.md) (`authority_state`)
- [Metadata bundle](metadata-bundle.md) · [Memory model](memory-model.md) (promotion path) · [Retrieval contract](retrieval-contract.md)
- [Existing GovernedWriteProtocol contract](../contracts/GOVERNED_WRITE_PROTOCOL.md) — runtime protocol (DecisionToken + AuthorityReceipt)
- [Traceability matrix](traceability-matrix.md)
- [Boundary charters](../boundaries/README.md) — [GOV](../boundaries/GOV.md), [HKA](../boundaries/HKA.md), [SIP](../boundaries/SIP.md), [MEM](../boundaries/MEM.md), [CAO](../boundaries/CAO.md), [EXE](../boundaries/EXE.md), [SFC](../boundaries/SFC.md), [OEF](../boundaries/OEF.md)
- Schema: [`schemas/authority-transition.schema.json`](../../schemas/authority-transition.schema.json) · shared defs [`schemas/_defs.schema.json`](../../schemas/_defs.schema.json)
