---
scope_id: scope:work/project-beta
sphere: work
source_role: work_project
authority_state: accepted
evidence_role: evidence
sensitivity: internal
synthetic: true
---

# Project Beta — System Architecture Notes

Project Beta is the **Borealis fleet-telemetry system**. Like Alpha it is built around a stateful
workflow engine and an event bus, and it uses an agent service to process a stream — but Beta has
nothing to do with billing. Beta ingests device telemetry through the state machine
`ingested → validated → enriched → published`.

Key facts specific to Beta:

- The validation policy is owned by the `BorealisPolicy` class and tuned per device class.
- The enrichment capability joins telemetry against a geo-fence rule set, not a bank feed.
- Authority to `publish` a telemetry batch belongs to the on-call SRE workflow, not a finance team.
- Beta's scope is the vehicle-fleet domain; it shares no entities with Project Alpha.

The architecture vocabulary (system, agent, workflow, state, event, capability, authority, rule,
policy, class) is deliberately the same as Project Alpha's, so a naive similarity search would happily
mix the two. The distinguishing facts — Borealis, telemetry, `BorealisPolicy`, geo-fence, fleet —
are Beta's alone. Alpha must not retrieve Beta material (or vice versa) without an explicit,
directional cross-scope flow.
