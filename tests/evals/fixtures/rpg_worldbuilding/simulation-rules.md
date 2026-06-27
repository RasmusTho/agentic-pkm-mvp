---
scope_id: scope:rpg/worldbuilding
sphere: rpg
source_role: rpg_rule
authority_state: working_fiction
evidence_role: analogy
sensitivity: private
synthetic: true
---

# Aethelgard — Simulation Rules (working fiction)

Draft mechanics for the Aethelgard downtime **simulation**. Working fiction, not yet locked canon.

The downtime engine is a turn-based state machine. Each turn is an `event`; each faction `agent`
resolves its actions, then the world `state` advances through the `transition` table below:

- `dormant → stirring` when a faction's influence rule threshold is met.
- `stirring → active` when the GM authority approves an uprising (a fictional "authority transition").
- `active → spent` after the capability that triggered it is exhausted.

The engine keeps a `memory` of past turns so the political `context` carries forward, and a `policy`
layer decides which random `event`s are eligible per `scope` (region).

Every mechanical term here — simulation, state machine, event, agent, state, transition, rule,
authority, capability, memory, context, policy, scope — is borrowed from systems language on purpose.
It describes an imaginary game world. It is `analogy` material at most for any real project, never
`evidence`, and only through an explicit cross-scope flow that permits analogy use.
