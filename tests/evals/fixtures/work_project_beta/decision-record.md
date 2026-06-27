---
scope_id: scope:work/project-beta
sphere: work
source_role: decision_record
authority_state: accepted
evidence_role: evidence
sensitivity: internal
synthetic: true
---

# Project Beta — Decision Record ADR-B03

**Decision:** Borealis will back-pressure the `enriched` stage rather than drop telemetry events
when the geo-fence service is slow.

**Context:** The fleet-telemetry workflow was dropping events under load, which corrupted downstream
state. Adding back-pressure keeps every device event in the system and preserves the ordering the
publish capability depends on.

**Consequences:** The `BorealisPolicy` class gains a `max_inflight_events` rule; the enrichment
capability blocks instead of discarding. This is accepted, canonical guidance for Project Beta only.

This record reuses the cross-project vocabulary (decision, workflow, state, event, capability,
authority, rule, policy, system, class) on purpose. The decision content — Borealis back-pressure,
`max_inflight_events`, geo-fence — is Beta-specific and is **not** interchangeable with Project
Alpha's dispute-as-state decision, even though both are "work project ADRs about a state machine".
