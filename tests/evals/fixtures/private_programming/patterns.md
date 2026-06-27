---
scope_id: scope:private/programming
sphere: private
source_role: private_note
authority_state: draft
evidence_role: background
sensitivity: private
synthetic: true
---

# Private Notes — Patterns I Keep Reaching For

Personal learning notes. Genuinely useful and reusable — which is exactly why they are tempting to
leak into work — but they live in my **private** scope and must not surface in a work answer unless
a governed promotion / redaction / cross-scope flow allows it.

- **State machine over flags.** Whenever I model a workflow, prefer an explicit state machine with
  named transitions and one event per transition over scattered boolean flags. Easier to audit.
- **Capability objects.** Pass a small capability object instead of an ambient global; the agent can
  only do what its capability grants.
- **Memory vs source of truth.** Keep an in-process memory as a cache, never as authority; rebuild
  it from the durable system store on restart.
- **Policy at the edge.** Put policy/authority checks at the boundary of the system, not sprinkled
  through the core.

These are general techniques described in private words. The vocabulary (state, workflow,
transition, event, capability, agent, memory, authority, system, policy, scope, context) is the same
as the work projects and the RPG simulation notes on purpose. Usefulness is not permission: private →
work is denied by default.
