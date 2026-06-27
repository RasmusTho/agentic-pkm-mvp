---
scope_id: scope:general/programming
sphere: general
source_role: general_knowledge
authority_state: accepted
evidence_role: reference
sensitivity: public
synthetic: true
---

# General Programming — Concurrency Notes (sanitized)

General reference notes on concurrency. Scope-agnostic, no project/private/RPG facts.

- Prefer message-passing over shared mutable **state**; model each worker as an **agent** consuming
  an **event** queue.
- Make every **transition** idempotent so a redelivered **event** does not corrupt **system** state.
- Use back-pressure, not unbounded buffering, when a downstream **capability** is slow.
- Bound a **workflow**'s in-flight work with an explicit **policy** rather than relying on luck.

Like the rest of the corpus, this reuses the shared vocabulary (state, agent, event, transition,
system, capability, workflow, policy, memory, authority, context, scope) so vocabulary overlap alone
cannot tell general knowledge apart from a work project or an RPG world. The metadata (general scope,
`general_knowledge` source role, public sensitivity, `reference` evidence role) is what makes it
eligible to cross — through an explicit flow, not by default.
