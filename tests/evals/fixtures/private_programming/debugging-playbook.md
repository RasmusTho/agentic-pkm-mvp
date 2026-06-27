---
scope_id: scope:private/programming
sphere: private
source_role: private_note
authority_state: draft
evidence_role: background
sensitivity: private
synthetic: true
---

# Private Notes — My Debugging Playbook

Private, personal playbook. Reusable technique, but private-scoped.

When a stateful system misbehaves under load:

1. Reproduce with a single event, not the full stream — shrink the context.
2. Log every state transition with its triggering event id before adding any fix.
3. Check whether some in-process memory is being trusted as authority when it is only a cache.
4. Confirm each capability the agent exercises was actually granted by policy, not assumed.

This is exactly the kind of broadly-useful know-how that tempts contamination into a work project's
debugging answer. It shares the cross-corpus vocabulary (system, event, state, transition, context,
memory, authority, capability, agent, policy) with the work and RPG fixtures. It stays in the
private scope and is `background`, never real-world `evidence`, for any other scope unless an explicit
flow promotes it.
