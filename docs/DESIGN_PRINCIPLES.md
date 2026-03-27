State: SoT v5.5 baseline locked with the forward line clarifying v6 design direction.
Doc role: Core SoT
Authority: Canonical design principles for how architecture and roadmap changes should be framed. This document owns the stable principles for modularity, flexibility, authority boundaries, and documentation layering. It does not override current runtime behavior defined in `docs/ARCHITECTURE.md` and `docs/STATUS.md`.
Owner: Architecture / SoT coordination
Last reviewed: 2026-03-27

# Design Principles

## Purpose

This document defines the stable design principles that guide architectural evolution in the Agentic PKM / Yggdrasil system.

It exists to keep high-level design work systematic:
- principles define the enduring rules,
- architecture defines the system structure,
- roadmap defines transition sequencing,
- status defines current truth,
- track and spec docs define implementation detail.

## Scope

- System-level design principles for modularity and flexibility.
- Authority boundaries for interaction, cognition, execution, memory, and governance.
- Documentation-layer rules for where architectural intent, sequencing, and implementation detail belong.

## Out of Scope

- Current runtime wiring and implementation detail.
- Sprint planning, backlog management, or task decomposition.
- Narrow subsystem behavior owned by documents such as `docs/PANEL_AGENT.md`, `docs/EVENTS.md`, or `docs/COMPONENTS.md`.

## Related Docs

- `docs/ARCHITECTURE.md` — active system structure and runtime boundaries.
- `docs/ROADMAP.md` — migration sequencing and adoption gates.
- `docs/STATUS.md` — present-tense operational posture.
- `docs/AGENTS.md` — current runtime agent architecture.
- `docs/plans/V60_ARCHITECTURE_TARGET.md` — wanted-state context for larger target-state moves.

## Reading Order

- Read this document before making structural changes to architecture or roadmap language.
- Read `docs/ARCHITECTURE.md` next for current-state and near-term structural boundaries.
- Read `docs/ROADMAP.md` for sequencing.
- Read `docs/STATUS.md` to confirm what is active now.
- Use plans and track docs only after the owner docs are clear.

## System Design Principles

### 1. Boundary-First Design

- Define stable system boundaries before defining implementations.
- Separate responsibilities before choosing tools, runtimes, or event families.
- A design is incomplete if authority, mutation rights, or accountability boundaries are unclear.

### 2. Capability-Based Composition

- Reusable capabilities are preferred over agent-per-function decomposition.
- Capabilities should be composable, testable, and reusable across multiple interaction surfaces.
- Agents and orchestrators may use capabilities, but capabilities should not become hidden control centers.

### 2A. Interaction-First Architecture

- Interaction is primary; retrieval, reasoning, and transformation are supporting capabilities.
- The architecture should be organized first around how the human interacts with the system and what authority that interaction carries.
- Retrieval should not become the conceptual center of the architecture just because it is widely reused.
- Different interaction surfaces may share capabilities while still preserving different authority, persistence, and output semantics.

### 3. Separation of System Layers

- Interaction, cognition, execution, memory, and governance are distinct layers.
- A layer should have one primary responsibility and a clear contract with adjacent layers.
- A layer may depend on another layer’s contract, but should not absorb its authority.

### 4. Explicit Mutation Authority

- Mutation rights must be explicit and narrow.
- Cognition alone must not imply execution authority.
- Any path that can mutate durable state must be policy-bounded, auditable, and reviewable.

### 5. Governance Before Autonomy

- Governance is a prerequisite, not an afterthought.
- New cognition or automation must be introduced only where policy, admissibility, provenance, approval, and auditability remain intact.
- Read-only cognition surfaces should precede mutation-capable autonomous behavior.

### 6. Contracts Over Implementations

- Stable contracts matter more than specific implementation choices.
- Event names, runtimes, and libraries may evolve; authority boundaries and contract semantics should remain clear.
- High-level docs should define invariants and interfaces before concrete mechanisms.

### 7. Modularity With Replaceability

- The system should be designed so individual mechanisms can change without collapsing the whole architecture.
- Frameworks such as LangGraph, Deep Agents, or future execution runtimes are replaceable implementation choices, not architectural identities.
- Roadmap language should avoid binding the architecture too tightly to one tool before the contract is stable.

### 8. Flexibility Without Semantic Drift

- Flexibility does not mean vague authority.
- Generality should come from clean seams and reusable contracts, not from collapsing distinct concepts into one runtime construct.
- When a distinction matters semantically, the design should preserve it even if one implementation temporarily compresses it.

### 9. System-of-Systems Thinking

- Yggdrasil should be treated as a system-of-systems, not as one undifferentiated agent runtime.
- Interaction, cognition, execution, memory, and governance must be able to evolve at different speeds.
- Cross-layer coupling should be deliberate, minimal, and documented.

## Documentation Design Principles

### Document Responsibilities

- `docs/DESIGN_PRINCIPLES.md` owns stable design rules and document-layer boundaries.
- `docs/ARCHITECTURE.md` owns structural boundaries, responsibilities, and invariants.
- `docs/ROADMAP.md` owns sequencing, gates, and intentional deferrals.
- `docs/STATUS.md` owns current operational truth.
- `docs/plans/*` and `docs/tracks/*` own implementation planning and detailed delivery work.

### Documentation Rules

- High-level docs should describe invariants, boundaries, and decisions, not backlog tasks.
- Backlog-like decomposition belongs in tracks, specs, or implementation plans.
- If roadmap text starts to read like a kanban board, move detail into a track or plan doc.
- If architecture text starts to prescribe implementation mechanics prematurely, move detail into a reference or plan doc.
- If status text mixes present truth with aspirational direction, split the aspirational part into roadmap or plan docs.

## Change Classification Rules

- Current-state correction:
  - Fixes a mismatch between current implementation and accepted SoT.
- Enablement change:
  - Creates modular seams or governance scaffolding without claiming the target state already exists.
- Target-state change:
  - Introduces a larger structural shift that depends on broader design alignment and phased adoption.

When in doubt, classify the change before editing the docs.

## Sequencing Rules

- Treat stabilization lines such as v5.6 primarily as invariant layers, not as sacred linear delivery order.
- Respect the contracts those lines establish even when target-state design work begins in parallel.
- Extract the must-have blockers from a stabilization line before moving structural work forward; do not assume every active item is a prerequisite.
- Starting target-state design early is valid when it does not break current contracts or blur current truth.

## Decision Heuristics

- Prefer adding a capability when a function should be reused across multiple agents or surfaces.
- Prefer adding or refining a layer when authority or responsibility is unclear.
- Prefer a plan or track doc when the content is mainly sequencing, work breakdown, or implementation detail.
- Prefer a current-state SoT doc change only when the system truth has already changed or is changing in the same bounded work.
