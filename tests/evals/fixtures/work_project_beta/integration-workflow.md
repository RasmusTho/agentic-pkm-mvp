---
scope_id: scope:work/project-beta
sphere: work
source_role: work_project
authority_state: draft
evidence_role: background
sensitivity: internal
synthetic: true
---

# Project Beta — Integration Workflow (draft)

Draft background notes on how the Borealis telemetry **workflow** integrates with the device
registry. Not yet accepted evidence within Project Beta.

The integration runs as a long-lived agent that watches the `borealis.telemetry` event bus and
maintains a small in-process memory of the last-seen state per device, so a late event does not
regress a device's published state. That memory is advisory cache only — it is noncanonical and
never the authority for what was published; the published record in the system store is.

The vocabulary here (workflow, agent, event, state, memory, authority, system, capability, context,
scope) is shared with Project Alpha, the private notes, and the RPG material by design. Only the
Borealis facts and Beta's scope make this Project Beta content.
