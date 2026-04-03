State: SoT v5.5 Reality-MVP baseline locked (watcher/panel safety + concurrency guardrails) with the forward line now tracking v5.6 (LangGraph + Reasoning rollouts). This document defines system-level agent architecture and coordination patterns.
# Agents

This document covers the system-level view of agents in the current architecture:
- shared agent design principles,
- the cross-agent matrix,
- LangGraph/AgentState direction,
- coordination via Outbox, Planner, and future A2A envelopes.

It does not claim that every important system behavior should become its own agent.
Where reusable behavior is better modeled as a capability or bounded subsystem, that should remain
the preferred direction.

This document is downstream of the human-function documents.
Its purpose is not to define what the system is for, but to describe how the current runtime
organizes assisting units in service of those functions.

This document uses `agent` primarily in the architecture/runtime sense.
For the broader ontology of `System Agent` as a bounded assisting actor within the second-brain
domain, see `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`.
For overloaded term guidance, especially the distinction between `System Agent`, role, component,
and artifact, see `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`.
For the canonical ontology of `System Agent`, `Agent Role`, `Delegation`, `Authority Boundary`, and
`Receipt`, see `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`.

This document is about agents that exist inside the PKM system/runtime.
It is not the instruction set for development-time builder agents or repo automation.
Development-time guidance lives in the root `AGENTS.md`, `docs/development/DEV_WORKFLOW.md`, and
`docs/plans/ONTOLOGY_EXECUTION_COORDINATION.md`.
System-level design rules for modularity, capability composition, and documentation layering live in `docs/DESIGN_PRINCIPLES.md`.

Use `docs/PANEL_AGENT.md` for PanelAgent-specific runtime behavior, panel syntax, emitted events, and wiring details.
See `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md` for the current recommendation on separating
execution-plan language, promotion transitions, and runtime projections from the broader ontology.
Use `docs/TESTING.md` for the canonical test layers, CI roles, and runtime/UAT validation model that agent changes must satisfy.

## Reading rules

- In this document, `agent` means an architectural/runtime unit of bounded decision-making or work.
- Not every runtime component is necessarily a first-class ontological `System Agent`.
- Some entries in the matrix below are closer to deterministic components or pipelines than to rich autonomous agents.
- The matrix is therefore best read as a runtime coordination map, not a pure ontology table.

## Design principle
- Agent structure should follow the system design principles in `docs/DESIGN_PRINCIPLES.md`: boundary-first design, capability-based composition, explicit mutation authority, and governance before autonomy.
- Non-trivial decision logic should move toward “LangGraph inner, events/A2A outer”: each agent owns an explicit `AgentState` and LangGraph graph for internal choices, while coordination between agents happens via Outbox events/A2A envelopes orchestrated by the Orchestrator/Planner.
- Agent-per-function decomposition should not be expanded when the same behavior is better modeled as a reusable capability.
- PanelAgent is the concrete example: LangGraph runtime with an action catalog driving a configurable decider (`PANEL_AGENT_DECIDER=rule|llm`), defaulting to LLM-backed interpretation in runtime while offering explicit rule-mode opt-out for tests and deterministic validation lanes.
- Current adoption is phased: ASK and PanelAgent use LangGraph with LLM-first defaults; most other agents remain deterministic pipelines until v5.6 rollout phases.
- When proposing tests or acceptance criteria, start from the human-flow contract first and then classify the scenario as `baseline`, `partial`, or `future` using `docs/TESTING.md` and `docs/plans/SCENARIO_ACCEPTANCE_MATRIX.md`.
- Agents must not treat the current runtime decomposition or active agent matrix as the full product definition; validation should distinguish "baseline regression" from "human-need target not yet reached".

## Current architectural direction

- The runtime should be read as capability-oriented even where older agent labels still exist.
- Retrieval, reranking, context building, reasoning support, and transformation support should evolve toward reusable capabilities rather than proliferating agent identities.
- Interaction, cognition, execution, memory, and governance are separate concerns; agent structure should not collapse those boundaries.
- Panel and Chat should be understood as distinct interaction surfaces with different authority, not as interchangeable shells around the same agent behavior.
- Richer cognition may be introduced incrementally, but governance and mutation authority remain upstream constraints on agent evolution.

Functional reminder:
- these runtime units exist to support capture, retrieval, commitment handling, review, learning,
  creative work, and accountable action for the human.
- they should not be treated as if their current runtime decomposition were itself the product's
  primary meaning.

## Ontology vs architecture

At the ontology level:
- a `System Agent` is a bounded assisting actor acting under delegation, policy, or explicit intent.
- `Agent Role`, `Delegation`, `Authority Boundary`, and `Receipt` are separate concepts and should
  not be collapsed into runtime labels alone.

At the architecture level used in this document:
- an `agent` may be:
  - a richer system agent with internal decision logic,
  - a deterministic pipeline stage,
  - or a migration-era runtime unit retained under agent naming for continuity.

When the distinction matters:
- use ontology documents to answer what an agent *is* in the domain,
- use this document to answer how current runtime units are organized and coordinated.

## ASK AgentState (Reality-MVP example)
- `trace_id`: propagated through ASK runs.
- `query`: user question.
- `hits`: retrieval results `{object_id, score, origin, zone, trust, title, path, snippet, payload}`.
- `answer`: composed answer text (LLM-backed when enabled; otherwise top-hit snippet).
- `reasoning`: optional reasoning trace.

Interpretation:
- `hits` are retrieval-layer results over runtime projections, not the full ontology of source
  artifacts.

Flow: `query → retrieve (hybrid search) → rerank (ask_score + reranker) → answer (LLM optional)`. The canonical implementation lives in `app/agents/ask/graph.py` and is invoked by `/api/ask`.

Direction note:
- this remains a valid current runtime surface,
- but the v6 direction treats ASK as a surface built on reusable capabilities rather than as the architectural center of retrieval or reasoning.

## Example graph
`retrieve -> draft -> self-check -> final` (max 2 iterations)

## Example prompt structure
- Instructions
- Context (quoted excerpts with source IDs)
- Question
- Requirements (format, language, citation requirements)

## Example answer contract
- `Summary`
- `Sources` (list: doc_id + timestamps when relevant)

## Agent Matrix (v5.5 baseline + forward line v5.6)

| Agent | Role | Primary Human Flow | AgentState / LangGraph | Coordination (events/A2A) | State (active/parked) |
| --- | --- | --- | --- | --- | --- |
| Normalizer | Normalize/parse vault files into canonical runtime projections | Capture & Ingest | No (deterministic pipeline) | Outbox ingest events | Active |
| Classifier | Propose types/facets and intent labels | Capture & Ingest / Panel Interaction | Planned (richer branching fits LangGraph) | Outbox ingest events; future A2A | Active |
| Chunker | Split content for indexing | Capture & Ingest | No (deterministic pipeline) | Outbox ingest events | Active |
| Deduper | Prevent duplicate runtime projections/embeddings | Capture & Ingest | Planned (decisioning could live in graph) | Outbox ingest events; future A2A | Active |
| CitationChecker | Validate citations for ASK answers | ASK | Planned (graph when critique/repair expands) | Outbox ASK events; future A2A | Active |
| Indexer | Write embeddings to VectorIndex | Capture & Ingest / ASK | No (deterministic pipeline) | Outbox ingest/index events | Active |
| ASK Agent | Retrieve, rerank, and draft answers | ASK | Yes (LangGraph + AgentState live in `app/agents/ask/graph.py`) | Planner/Orchestrator optional; Outbox for traces | Active |
| PanelAgent | Translate AI panels into intents/events | Panel Interaction | Yes (LangGraph runtime + PanelActionIntent) | Outbox panel intents; planner pipeline opt-in (`PANEL_AGENT_PIPELINE=planner`) with CLI-first orchestration | Active |
| Planner | Build execution plans from goals/events (including panel action intents) | Multi-agent orchestration | Planned (LLM-backed; panel-mode mapping shipped) | Outbox plan events; feeds Orchestrator | Active |
| Promotion Agent | Apply promotion/evergreen transitions | Review & Promotion | Planned (LangGraph to encode policy/branching) | Outbox promotion events; Orchestrator integration planned | Active |
| Reviewer | Human-aligned review of artifacts/transitions | Review & Promotion | Planned (LangGraph critique/approval) | Outbox review events; A2A planned | Active |
| SetEvaluator | Score/rank candidates for promotion/sets | Review & Promotion / ASK (ranking) | Planned | Outbox/Planner hooks; A2A planned | Active |
| MergeResolverAgent | Resolve conflicts/merges across sources | Capture & Ingest | Planned | Outbox ingest events; A2A planned | Parked (future) |
| NoteHygieneAgent | Suggest cleanups and consistency fixes | Capture & Ingest / Panel Interaction | Planned | Outbox panel/update events; A2A planned | Parked (future) |

Interpretation notes:
- `Normalizer`, `Chunker`, `Indexer`, and some other entries are active runtime units even when they are not yet rich ontology-level `System Agents`.
- `Planner` here means an execution-planning runtime unit; it should not be conflated with broader human commitment or project structures in the ontology.
- `Promotion` and `Review` in this table refer to transition/process families, not standalone entity types.
- Several rows operate mainly on runtime projections and event flows rather than directly on the full
  human ontology of artifacts.
- The table is a current coordination map, not a target-state claim that the system should keep or expand one-agent-per-function decomposition.

## Planner (Reality-MVP)
- Builds hierarchical plans (parent_plan + depth) and enforces bounds (max depth/steps/replans/total steps).
- Executes primitive steps via domain mutations (e.g., review_state updates) and tracks executed_steps.
- Wraps every primitive step in guardrail pre/post checks so policies can allow/modify/block/fail tool calls.

Normalization note:
- the active `Plan` object here is an execution artifact.
- the active runtime still compresses `promote_to_evergreen` and `update_review_state` toward the
  same mutation path, which is precisely why promotion/review/maturity remain distinct in the
  ontology work.
