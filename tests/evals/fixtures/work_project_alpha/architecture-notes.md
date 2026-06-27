---
scope_id: scope:work/project-alpha
sphere: work
source_role: work_project
authority_state: accepted
evidence_role: evidence
sensitivity: internal
synthetic: true
---

# Project Alpha — System Architecture Notes

Project Alpha is the **Atlas billing reconciliation system**. The core is a stateful workflow
engine that drives each invoice through a fixed state machine: `received → matched → disputed →
settled`. Every state transition emits a domain event onto the `atlas.ledger` event bus, and an
agent service consumes those events to reconcile against the bank feed.

Key facts specific to Alpha:

- The reconciliation policy is owned by the `AtlasPolicy` class and versioned per fiscal quarter.
- The matching capability uses deterministic rules first, then an ML scorer as a fallback.
- Authority to mark an invoice `settled` requires a four-eyes approval workflow.
- Alpha's scope is the EU billing entity only; the US entity is a separate system.

This document is accepted work-project evidence within Project Alpha's scope. It uses the same
vocabulary (system, agent, rule, state, event, workflow, authority, capability, policy) as other
projects, but the facts — Atlas, `atlas.ledger`, `AtlasPolicy`, EU billing entity — are Alpha's
alone.
