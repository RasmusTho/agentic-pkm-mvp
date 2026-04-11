State: Plan (v6.0 target-state sequencing for capability-based architecture and agent evolution).
Doc role: Plan
Authority: Working plan for the capability-based architecture, dual interaction model, and staged agent evolution. This document expands the roadmap with sequencing and design decisions, but does not override current runtime truth in `docs/ARCHITECTURE.md` or `docs/STATUS.md`.
Owner: `docs/ROADMAP.md`
Last reviewed: 2026-04-11
Last verified against: docs/DESIGN_PRINCIPLES.md, docs/ROADMAP.md, docs/ARCHITECTURE.md, docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md, current repo state on 2026-04-11

# v6.0 Capability-Based Architecture and Agent Evolution

## Purpose

This document holds the working plan for moving the system toward:
- capability-based composition,
- separate Panel and Chat interaction surfaces,
- staged Deep Agent introduction,
- and governed execution.

It exists so the roadmap can stay phase-oriented without turning into a delivery backlog.
It also makes explicit that the v5.6 line should be treated mainly as a stabilization layer for invariants rather than as a rigid step-by-step prerequisite chain.

## Scope

- Sequencing of the capability-based architecture shift.
- Structural decisions for ASK de-centering, retrieval extraction, and dual interaction surfaces.
- Staged introduction of Deep Agents and future execution runtimes.

## Out of Scope

- Current runtime truth.
- Narrow implementation mechanics for a single subsystem.
- Sprint-level work breakdown or task tracking.

## Related Docs

- `docs/DESIGN_PRINCIPLES.md` — stable design rules.
- `docs/ARCHITECTURE.md` — current structure and v6-direction layer framing.
- `docs/ROADMAP.md` — high-level migration sequence.
- `docs/STATUS.md` — present-tense operational posture.
- `docs/plans/V60_ARCHITECTURE_TARGET.md` — broader v6 wanted-state architecture context.

## Reading Order

- Read `docs/DESIGN_PRINCIPLES.md` first.
- Read `docs/ARCHITECTURE.md` next.
- Read `docs/ROADMAP.md` for the condensed phase sequence.
- Use this document for the working plan detail behind that roadmap section.

## Fixed Decisions

### ASK is deprecated as an architectural center

- ASK may remain a valid runtime/API surface in the v5.x line.
- ASK should not remain the conceptual center for retrieval, reasoning, or future cognition.
- New design work should not extend a special central-agent framing around ASK.

### Retrieval becomes a capability, not an agent

- Retrieval is reusable infrastructure that must serve multiple interaction surfaces.
- Treating retrieval as an agent encourages unnecessary control-center behavior and tighter coupling.
- The architecture should instead expose retrieval as a reusable capability that can be orchestrated by different surfaces and cognition mechanisms.

### Interaction is primary; retrieval is supporting

- The core design question is how the human interacts with the system, not where retrieval happens.
- Panel and Chat are therefore first-class architectural surfaces.
- Retrieval, reasoning, transformation, ingestion, and indexing support those surfaces rather than organizing the whole architecture around themselves.

### Bounded template agents remain part of the design

- The system is not moving toward one central general-purpose agent.
- It may still include many bounded agents with narrow roles, shared scaffolding, and differentiated prompts or policies.
- Capability-based composition and template-based agents should reinforce each other rather than be treated as opposites.

### Deep Agents start in Chat before Panel

- The first Deep Agent rollout starts in a read-only Chat slice.
- This lets the system validate cognition quality before coupling Deep Agent behavior to mutation paths.
- Per `docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md`, Chat itself is a canvas-shaped interaction surface and may later carry governed mutation rights through the gated execution pipeline; the read-only rule applies to the Deep Agent introduction phase, not to Chat's identity.
- Panel may later consume richer cognition, but only as planning and proposal support.

### Deep Agents do not precede v6.0 structural separation

- Structural separation must come before richer cognition so authority boundaries are clear first.
- Otherwise the repo risks binding architectural meaning to one implementation mechanism too early.
- Capability seams, interaction separation, and governance boundaries are prerequisites.

### Execution remains gated

- LLM reasoning must not directly mutate durable state.
- Any execution expansion must remain policy-bounded, approval-aware, auditable, and idempotent.
- Readiness for richer execution is a governance question before it is a tooling question.

### System-of-systems framing is intentional

- Interaction, cognition, execution, memory, and governance are treated as separate but coordinated subsystems.
- The design goal is modularity with replaceability, not one monolithic agent runtime.
- This keeps the architecture flexible without erasing important authority distinctions.

### The operating spectrum is broad

- The intended system spans manual, assisted, reactive automation, and proactive automation.
- The design should therefore support both interaction-rich and automation-heavy paths under the same governance model.
- The target is not one mode of operation, but a governed spectrum.

## Planned Sequence

## v5.6 Invariants vs. Deferred Work

The repo should not treat all v5.6 work as equally blocking for v6 structure.

### Must-have invariants before structural progression

- `AgentState` is stable enough to act as a shared runtime-state contract.
- The intent and action pipeline is stable enough to preserve deterministic mutation paths.
- The settings/compiler layer is reliable enough to expose topology and policy with provenance.
- Panel is stable enough to act as the current mutation-capable interaction baseline.

### Can continue later without blocking the v6 structure definition

- Full watcher automation rollout.
- Non-critical edge-case hardening outside the core invariants above.
- Broader LangGraph adoption across every runtime unit.
- Advanced or optional flows that do not define the core layer boundaries.

Working rule:
- respect the invariants that v5.6 is establishing,
- but do not force the entire v6 structural design to wait on every forward-line task.

### Phase 0 — Stabilization (v5.6)

- Complete PanelAgent as the default mutation-capable interaction path.
- Stabilize `AgentState`, LangGraph rollout posture, and settings/compiler work.
- Preserve current runtime compatibility and contract safety.
- Keep Deep Agents out of production mutation flows.

### Phase 1 — v6.0 Baseline (Structural Separation)

Target outcome:
- interaction, cognition, execution, memory, and governance are separated clearly enough to support safe future evolution.

Expected shifts:
- ASK is no longer treated as the architectural center.
- Retrieval is extracted into a capability layer.
- Panel uses capabilities rather than embedded retrieval-centric logic.
- Mutation-capable flows are modeled as `intent -> plan -> proposal -> validation -> execution`.
- Foundational capabilities such as ingestion and indexing remain explicit and first-class in the architecture.

### Phase 2 — Deep Agent Introduction in Chat

Target outcome:
- read-only cognition can be introduced without widening mutation authority.

Expected constraints:
- Chat only.
- No system mutation.
- No execution access.
- Retrieval orchestration and multi-step reasoning are allowed only within read-only bounds.

### Phase 3 — Panel Integration as Controlled Cognition

Target outcome:
- Panel can benefit from richer cognition without weakening governance.

Expected constraints:
- planning and proposal generation only.
- no direct execution.
- policy, validation, and the event/action pipeline remain mandatory.

### Phase 4 — Execution Layer Expansion

Target outcome:
- future execution runtimes can be evaluated without collapsing reasoning and execution authority.

Expected constraints:
- sandboxing,
- approval gates,
- policy enforcement,
- idempotency,
- full auditability.

### Phase 5 — Governance and Scale

Target outcome:
- governance becomes strong enough to support broader automation safely.

Expected focus:
- policy engines,
- stronger audit trails,
- execution constraints,
- scaling rules for richer autonomy without losing inspectability.

## Interaction Model

### Panel

- Command-oriented surface.
- Explicit intent.
- Mutation-capable, but only through controlled and validated paths.
- Remains a primary governed mutation surface in the planned model.

### Chat

- Exploration-oriented surface.
- Canvas-shaped surface for externalizing and manipulating thought.
- The Deep Agent introduction slice starts read-only and remains the safe cognition sandbox for richer reasoning and decomposition.
- May later participate in governed mutation paths through the gated execution pipeline; this is the recorded Candidate A decision in `docs/INTERACTION_SURFACES_AND_AUTHORITY/RECONCILE_CHAT_MUTATION_AUTHORITY.md`, not a current runtime claim.

## What Stays Out of the Roadmap

The following belong in narrower specs, track docs, or implementation work rather than the top-level roadmap:
- exact file moves,
- exact event-family renames,
- backlog-style work lists,
- subsystem-specific implementation mechanics,
- framework-specific rollout detail that does not affect the phase decision itself.
