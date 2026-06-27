---
scope_id: scope:general/programming
sphere: general
source_role: general_knowledge
authority_state: accepted
evidence_role: background
sensitivity: public
synthetic: true
---

# General Programming — Reusable Patterns (sanitized)

Sanitized, general-knowledge programming patterns. No project, private, or RPG specifics — just
widely-applicable technique. This is the material that *may* legitimately cross into a work scope,
but still only through an explicit `CrossScopeFlow` (as `background`/`reference`), never by an
implicit `general_knowledge: true` bypass.

- A **state machine** with explicit **transitions** and one **event** per transition is more
  auditable than scattered boolean flags.
- A **capability**-based design limits what an **agent** or **system** component may do.
- Treat caches and in-process **memory** as advisory; the durable store is the **authority**.
- Keep **policy** and **authority** checks at the **system** boundary.

These are deliberately the same concepts (system, agent, state, transition, event, workflow,
capability, memory, authority, policy, rule, context, scope) the work, private, and RPG fixtures use.
The difference is that this content is genuinely scope-agnostic and carries no identifying facts — so
correct behavior is "eligible to cross via a flow", not "auto-mixed because the words match".
