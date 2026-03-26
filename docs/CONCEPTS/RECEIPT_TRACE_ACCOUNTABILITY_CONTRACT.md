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

## 7. Non-goals

This document does not yet define:
- a final receipt storage model,
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
