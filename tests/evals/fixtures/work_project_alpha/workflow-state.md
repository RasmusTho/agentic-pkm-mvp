---
scope_id: scope:work/project-alpha
sphere: work
source_role: work_project
authority_state: draft
evidence_role: background
sensitivity: internal
synthetic: true
---

# Project Alpha — Workflow State Reference (draft)

Working notes on the Atlas reconciliation **workflow** state model. This is draft background
material within Project Alpha, not yet accepted as decision evidence.

States and their guarding rules:

- `received` — an invoice event has entered `atlas.ledger`; no authority required.
- `matched` — the matching capability has linked the invoice to a bank line; deterministic rule
  first, ML scorer fallback.
- `disputed` — a mismatch raised by the reconciliation agent; opens the `dispute_window_days`
  timer from `AtlasPolicy`.
- `settled` — terminal; requires the four-eyes approval workflow and writes an authority receipt.

Each transition is an event; the system never mutates an invoice's settled standing without a
governed transition. The terms (workflow, state, transition, event, agent, capability, rule,
authority, policy, system) overlap with Project Beta and the RPG simulation notes on purpose — only
the scope and the Atlas-specific facts distinguish this material.
