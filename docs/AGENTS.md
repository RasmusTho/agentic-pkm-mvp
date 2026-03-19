State: SoT v5.5 Reality-MVP baseline locked (watcher/panel safety + concurrency guardrails) with the forward line now tracking v5.6 (LangGraph + Reasoning rollouts). This document defines system-level agent architecture and coordination patterns.
# Agents

This document covers the system-level view of agents in the current architecture:
- shared agent design principles,
- the cross-agent matrix,
- LangGraph/AgentState direction,
- coordination via Outbox, Planner, and future A2A envelopes.

This document uses `agent` primarily in the architecture/runtime sense.
For the broader ontology of `System Agent` as a bounded assisting actor within the second-brain
domain, see `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`.
For overloaded term guidance, especially the distinction between `System Agent`, role, component,
and artifact, see `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`.

Use `docs/PANEL_AGENT.md` for PanelAgent-specific runtime behavior, panel syntax, emitted events, and wiring details.

## Reading rules

- In this document, `agent` means an architectural/runtime unit of bounded decision-making or work.
- Not every runtime component is necessarily a first-class ontological `System Agent`.
- Some entries in the matrix below are closer to deterministic components or pipelines than to rich autonomous agents.
- The matrix is therefore best read as a runtime coordination map, not a pure ontology table.

## Design principle
- Non-trivial decision logic should move toward “LangGraph inner, events/A2A outer”: each agent owns an explicit `AgentState` and LangGraph graph for internal choices, while coordination between agents happens via Outbox events/A2A envelopes orchestrated by the Orchestrator/Planner.
- PanelAgent is the concrete example: LangGraph runtime with an action catalog driving a configurable decider (`PANEL_AGENT_DECIDER=rule|llm`), defaulting to deterministic rule-mode while offering opt-in LLM-based selection.
- Current adoption is phased: ASK and PanelAgent use LangGraph; most other agents remain deterministic pipelines until v5.6 rollout phases.

## Ontology vs architecture

At the ontology level:
- a `System Agent` is a bounded assisting actor acting under delegation, policy, or explicit intent.

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

Flow: `query → retrieve (hybrid search) → rerank (ask_score + reranker) → answer (LLM optional)`. The canonical implementation lives in `app/agents/ask/graph.py` and is invoked by `/api/ask`.

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
| Planner | Build plans from goals/events (including panel action intents) | Multi-agent orchestration | Planned (LLM-backed; panel-mode mapping shipped) | Outbox plan events; feeds Orchestrator | Active |
| Promotion Agent | Apply promotion/evergreen transitions | Review & Promotion | Planned (LangGraph to encode policy/branching) | Outbox promotion events; Orchestrator integration planned | Active |
| Reviewer | Human-aligned review of artifacts/transitions | Review & Promotion | Planned (LangGraph critique/approval) | Outbox review events; A2A planned | Active |
| SetEvaluator | Score/rank candidates for promotion/sets | Review & Promotion / ASK (ranking) | Planned | Outbox/Planner hooks; A2A planned | Active |
| MergeResolverAgent | Resolve conflicts/merges across sources | Capture & Ingest | Planned | Outbox ingest events; A2A planned | Parked (future) |
| NoteHygieneAgent | Suggest cleanups and consistency fixes | Capture & Ingest / Panel Interaction | Planned | Outbox panel/update events; A2A planned | Parked (future) |

Interpretation notes:
- `Normalizer`, `Chunker`, `Indexer`, and some other entries are active runtime units even when they are not yet rich ontology-level `System Agents`.
- `Planner` here means an execution-planning runtime unit; it should not be conflated with broader human commitment or project structures in the ontology.
- `Promotion` and `Review` in this table refer to transition/process families, not standalone entity types.

## Planner (Reality-MVP)
- Builds hierarchical plans (parent_plan + depth) and enforces bounds (max depth/steps/replans/total steps).
- Executes primitive steps via domain mutations (e.g., review_state updates) and tracks executed_steps.
- Wraps every primitive step in guardrail pre/post checks so policies can allow/modify/block/fail tool calls.
