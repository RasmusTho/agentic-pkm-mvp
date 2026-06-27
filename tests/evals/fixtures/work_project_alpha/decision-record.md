---
scope_id: scope:work/project-alpha
sphere: work
source_role: decision_record
authority_state: accepted
evidence_role: evidence
sensitivity: internal
synthetic: true
---

# Project Alpha — Decision Record ADR-A07

**Decision:** Atlas will treat a disputed invoice as a first-class state rather than a flag on the
`matched` state.

**Context:** The reconciliation workflow previously overloaded a boolean on `matched`, which made
the audit trail ambiguous. Promoting `disputed` to a real state in the Atlas state machine gives
each transition its own event and authority check.

**Consequences:** The `AtlasPolicy` class gains a `dispute_window_days` rule; the settlement
capability must now read dispute state before it may exercise settle authority. This is accepted,
canonical guidance for Project Alpha and is admissible as decision evidence within Alpha's scope.

Vocabulary shared with other scopes (state, transition, event, authority, capability, rule, policy,
workflow) is intentional; the decision itself — Atlas dispute-as-state, `dispute_window_days` — is
specific to Alpha and must not be applied to any sibling project without an explicit cross-scope
flow.
