State: Concept contract companion (receipt/trace/accountability clarification; human-legible accountability first).

# Receipt, Trace, and Accountability Contract

## Purpose

This document clarifies a distinction that the repo already partly depends on but has not yet named
cleanly enough:
- `receipt`
- `operational trace`
- `audit record`

It exists so the system can preserve accountability without collapsing:
- human-legible action explanation,
- runtime coordination records,
- and longer-lived auditability surfaces.

This document is subordinate to:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`

It is upstream of:
- `docs/EVENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/AGENTS.md`

## Core rule

Not every record of system activity is a receipt.

A receipt is a human-legible accountability record.
A trace is a runtime coordination or diagnostic record.
An audit record is a durable inspectable record that may support accountability without necessarily
being the same thing as the human-facing receipt surface.

These concepts may support one another.
They must not be treated as interchangeable.

## 1. Receipt

A receipt is a human-legible accountability record of what happened, under what authority, on what
basis, and with what result.

Problem solved:
- the human must be able to understand consequential system action afterward without reconstructing
  everything from raw runtime internals.

A receipt should answer:
- what action occurred,
- who or what acted,
- what delegation, intent, or policy authorized it,
- what artifacts or surfaces were affected,
- what sources or rationale mattered,
- and what the outcome was.

### Receipt kinds

The ontology does not need many rigid receipt subclasses yet, but it does need to distinguish at
least these semantic kinds:

#### Human-approved action receipt

Used when:
- the human explicitly approved or triggered the action.

Must make visible:
- the explicit human authorization,
- the acting agent/component,
- and the resulting change or outcome.

#### Policy-bounded automatic action receipt

Used when:
- the system acted automatically within prior delegation or standing policy.

Must make visible:
- the policy/delegation basis,
- why automatic execution was allowed,
- what boundary conditions were in effect,
- and the resulting change or non-change.

#### Non-mutating or failed-action receipt

Used when:
- the system attempted, proposed, deferred, or failed to complete an action,
- and that outcome still matters for later understanding or trust.

Must make visible:
- what did not happen,
- why it did not happen,
- and what the human should infer from that.

## 2. Operational trace

An operational trace is a runtime record used for coordination, diagnostics, replay support,
correlation, or observability.

Problem solved:
- the system needs machine-usable history and runtime breadcrumbs,
- but those records are not automatically suitable as human accountability surfaces.

Examples:
- outbox events,
- `trace_id`-linked runtime logs,
- orchestration traces,
- watcher and worker run records,
- internal event chains.

An operational trace may be:
- partial,
- noisy,
- machine-oriented,
- or too low-level to count as a receipt by itself.

Operational traces support accountability.
They are not identical to accountability.

## 3. Audit record

An audit record is a durable inspectable record preserved for review, verification, compliance-like
inspection, or later reconstruction.

Problem solved:
- some records must remain inspectable beyond immediate runtime coordination,
- even when the human-facing receipt surface is abbreviated or local to one context.

An audit record may be:
- a structured event row,
- a durable execution summary,
- a policy decision record,
- or a persisted accountability-oriented system artifact.

An audit record may support or generate a receipt.
It does not automatically satisfy the human-legible receipt requirement.

## 4. Stable distinctions

### Receipt vs trace

- a receipt is for human accountability,
- a trace is for runtime coordination and diagnosis.

### Receipt vs audit record

- a receipt must be legible and explanatory for the human,
- an audit record must be inspectable and durable,
- and one may be derived from or linked to the other without being identical.

### Trace vs audit record

- a trace may be ephemeral or noisy,
- an audit record is intentionally preserved for later inspection.

## 5. Consequences for the repo

1. Outbox events and runtime traces should not be called receipts just because they record that
   something happened.
2. Mirror artifacts should not absorb accountability semantics by accident merely because they carry
   some history.
3. Agent actions should be described in terms of receipts plus supporting traces, not as if the raw
   event stream were already the full explanation.
4. Automated action requires receipt semantics that make delegation/policy basis visible.
5. Diagnostic logging alone is insufficient where human trust depends on accountability.

Current bounded projection note (#1279):
- the Vault Browser's per-artifact `receipts` field is an explicit read-only accountability
  projection over existing governed outbox/event records;
- the projection may use only event records that already carry receipt/accountability semantics
  (`promotion.transition.applied`, `panel.action.logged`, `panel.action.blocked` in the current
  implementation);
- it is not a final durable receipt store, not a new receipt authority, and not a browser write path;
- when the source is unavailable, the browser must preserve the `unavailable` state rather than
  fabricating receipt rows.

Vault Browser queue-review staging note (#1472):
- `POST /api/companion/vault-browser/actions/queue-review` stages a pending Panel governance
  proposal for `note_lifecycle` / `queue_review`;
- this pending intent is not a durable VaultReceipt row because no durable semantic transition has
  occurred at staging time;
- the response may expose `intent_id` / `proposal_id` and
  `receipt_state="pending_intent_not_durable_receipt"` so the UI can show pending posture without
  fabricating receipt authority;
- durable/accountability receipts remain sourced from governed Panel confirmation and
  receipt-supporting records such as `panel.action.logged` and `panel.action.blocked`;
- WriteGuard-blocked staging creates no proposal, no vault/frontmatter/ObjectStore mutation, and no
  receipt row.

Promotion transition note (#1438):
- `promote.done` / `PROMOTE_DONE` is an execution-result trace event, not the final durable receipt
  store;
- `promotion.transition.applied` / `PROMOTION_TRANSITION_APPLIED` is the current
  transition-accountability event and interim receipt-supporting record for successful promotion
  transitions;
- ObjectStore `payload["promotion"]` inline provenance is mirror provenance, not receipt authority;
- the formal promotion receipt query model is defined below.

Promotion receipt query model decision (#1489):
- The v1 formal promotion receipt model is a typed, read-only query/projection over durable
  receipt-supporting audit records, not a new write table in the first slice. The source authority
  for successful promotion applies is the durable `promotion.transition.applied` event record when
  it carries authority, basis, outcome, artifact linkage, event identity, trace identity, and
  timestamp.
- Consumers must use a stable receipt query/projection contract rather than direct ad hoc scans of
  DB outbox rows or JSONL diagnostics. The current per-artifact browser projection may remain an
  implementation of that read model while preserving the honest `unavailable` state when no
  receipt-supporting source is available.
- The four surfaces have separate authority roles:
  - `PROMOTE_DONE` is the execution/result trace: it records that promotion execution completed and
    which durable `maturity` / `review_state` result was applied.
  - `PROMOTION_TRANSITION_APPLIED` is the transition-accountability audit source and v1
    receipt-supporting authority for the queryable promotion receipt view.
  - ObjectStore `payload["promotion"]` is machine-mirror inline provenance and latest mirror
    posture; it may support display or reconstruction but must not authorize a change or satisfy
    receipt authority by itself.
  - The final durable/queryable receipt authority for v1 consumers is the typed promotion receipt
    read model derived from receipt-supporting audit records. A later implementation may materialize
    that model into a dedicated physical store, but consumers depend on the query contract rather
    than the storage shape.
- Minimum read/query surface: artifact UUID and path; receipt id or source event id; trace id;
  timestamp; transition family; target maturity; resulting `review_state` / `maturity`; authority;
  basis; outcome; artifact linkage; executor/source; and the triggering intent/source event. The
  query surface must support lookup by artifact UUID/path, receipt or event id, trace id,
  transition family, target maturity, and outcome status, ordered by timestamp.
- Follow-up posture: #1403 should be rewritten or split into a bounded implementation issue that
  wires promotion receipt writes/read queries to this model without changing frontmatter field
  names. #1474 may proceed only against a read-only, source-limited posture/receipt projection that
  uses this query contract and preserves non-authoritative agent-memory labeling; UI implementation
  remains blocked if that source/API is unavailable.

Orientation MemoryCandidate intent note (#1456):
- `GET /api/companion/orientation` may emit a bounded MemoryCandidate
  `mutation_intent` only as a reference-only handoff hint under
  `docs/adr/ADR-0009-orientation-memory-candidate-intent.md`;
- that emission requires an operational trace recording intent emission, source
  reference, threshold signals, intent ID, emitted time, and target queue
  reference;
- the trace must not carry raw candidate content;
- no governance receipt is created at intent emission, because no durable
  semantic transition has occurred.

## 6. Minimal accountability rule

For every meaningful system action, the overall system should make it possible to recover:
- the action,
- the acting entity or runtime context,
- the authority basis,
- the affected artifacts/surfaces,
- the relevant source/provenance basis where applicable,
- and the outcome.

This recovery may involve:
- one receipt surface,
- one or more traces,
- and one or more audit records.

But the existence of traces alone does not satisfy the rule.

## 7. Governed loop event/receipt boundary

For the runtime governed mutation path (`POST /api/panel/confirm`), two structurally distinct
types are produced and must not be conflated:

**`OutboxEvent`** (`app/events/schema.py`) — operational trace:
- Fields include `event`, `event_id`, `trace_id`, `source`, `timestamp`, `payload`,
  `context_dimensions`, and `meta`.
- Has `trace_id` and `event_id` for runtime coordination and deduplication.
- Does NOT carry `action_taken`, `inverse_action`, or `receipt` fields.
- Purpose: machine-usable runtime coordination, diagnostics, replay support, observability.

**`Receipt`** (`app/panel/confirmation.py`) — human-legible accountability record:
- Fields include `action_taken`, `outcome`, `timestamp`, `message`, and `inverse_action`.
- Has `action_taken` and `inverse_action` for accountability.
- Does NOT carry `trace_id`, `event_id`, or `source` fields.
- Purpose: human-legible record of what action was taken, under what authority, with what outcome.

**`ConfirmResponse`** (`app/panel/confirmation.py`) — governed mutation response:
- Contains `receipt: Receipt | None` — the accountability record.
- Contains `events_emitted: list[str]` — the list of emitted event trace names (strings).
- The `receipt` and `events_emitted` surfaces are intentionally separate: one is the
  accountability artifact, the other is the operational trace summary.

For read-only projection paths (e.g. orientation, resurfacing, vault-browser read operations),
only operational traces are emitted; no receipt is returned and no accountability record is
created. Read-only projection responses must not carry a top-level `receipt` field.

This structural separation is asserted by:
`tests/runtime/test_receipt_event_boundary.py::test_governed_mutation_receipt_is_distinct_from_event_trace`
`tests/runtime/test_receipt_event_boundary.py::test_read_only_projection_trace_has_no_mutation_authority`

## 8. Non-goals

This document does not yet define:
- a final physical receipt storage model,
- a final trace schema,
- exact event payload redesigns,
- or exact UI surfaces for accountability.

Those remain downstream of this clarification.

## Related documents

- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`
- `docs/CONCEPTS/MIRROR_RECEIPT_DECISION.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/EVENTS.md`
- `docs/ARCHITECTURE.md`
