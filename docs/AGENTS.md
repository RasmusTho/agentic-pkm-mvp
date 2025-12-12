State: SoT v4.10 Reality-MVP (baseline locked; v5.x Agentic PKM is the forward line).
# 6.0 Agentloop (deterministisk)

## Design principle
- Non-trivial decision logic should move toward “LangGraph inner, events/A2A outer”: each agent owns an explicit `AgentState` and LangGraph graph for internal choices, while coordination between agents happens via Outbox events/A2A envelopes orchestrated by the Orchestrator/Planner.
- PanelAgent is the concrete example: LangGraph runtime with an action catalog driving a configurable decider (`PANEL_AGENT_DECIDER=rule|llm`), defaulting to deterministic rule-mode while offering opt-in LLM-based selection.

## ASK AgentState (Reality-MVP)
- `trace_id`: propagated through ASK runs.
- `query`: user question.
- `hits`: retrieval results `{object_id, score, origin, zone, trust, title, path, snippet, payload}`.
- `answer`: composed answer text (LLM-backed when enabled; otherwise top-hit snippet).
- `reasoning`: optional reasoning trace.

Flow: `query → retrieve (hybrid search) → rerank (ask_score + reranker) → answer (LLM optional)`. The canonical implementation lives in `app/agents/ask/graph.py` and is invoked by `/api/ask`.

## Graf
`retrieve -> draft -> self-check -> final` (max 2 iterationer)

## Promptstruktur
- Instructions
- Context (quoted excerpts with source IDs)
- Question
- Requirements (format, language, citation requirements)

## Svarskontrakt
- `Summary`
- `Sources` (list: doc_id + timestamps when relevant)

## Agent Matrix (Reality-MVP)

| Agent | Role | Primary Human Flow | AgentState / LangGraph | Coordination (events/A2A) | State (active/parked) |
| --- | --- | --- | --- | --- | --- |
| Normalizer | Normalize/parse vault files into canonical objects | Capture & Ingest | No (deterministic pipeline) | Outbox ingest events | Active |
| Classifier | Propose types/facets and intent labels | Capture & Ingest / Panel Interaction | Planned (richer branching fits LangGraph) | Outbox ingest events; future A2A | Active |
| Chunker | Split content for indexing | Capture & Ingest | No (deterministic pipeline) | Outbox ingest events | Active |
| Deduper | Prevent duplicate objects/embeddings | Capture & Ingest | Planned (decisioning could live in graph) | Outbox ingest events; future A2A | Active |
| CitationChecker | Validate citations for ASK answers | ASK | Planned (graph when critique/repair expands) | Outbox ASK events; future A2A | Active |
| Indexer | Write embeddings to VectorIndex | Capture & Ingest / ASK | No (deterministic pipeline) | Outbox ingest/index events | Active |
| ASK Agent | Retrieve, rerank, and draft answers | ASK | Yes (LangGraph + AgentState live in `app/agents/ask/graph.py`) | Planner/Orchestrator optional; Outbox for traces | Active |
| PanelAgent | Translate AI panels into intents/events | Panel Interaction | Planned (PanelAgent 2.0 LangGraph + PanelAgentState) | Outbox panel/promotion intents; A2A planned | Active |
| Promotion Agent | Apply promotion/evergreen actions | Review & Promotion | Planned (LangGraph to encode policy/branching) | Outbox promotion events; Orchestrator integration planned | Active |
| Reviewer | Human-aligned review of objects/promotions | Review & Promotion | Planned (LangGraph critique/approval) | Outbox review events; A2A planned | Active |
| SetEvaluator | Score/rank candidates for promotion/sets | Review & Promotion / ASK (ranking) | Planned | Outbox/Planner hooks; A2A planned | Active |
| MergeResolverAgent | Resolve conflicts/merges across sources | Capture & Ingest | Planned | Outbox ingest events; A2A planned | Parked (future) |
| NoteHygieneAgent | Suggest cleanups and consistency fixes | Capture & Ingest / Panel Interaction | Planned | Outbox panel/update events; A2A planned | Parked (future) |

## Planner (Reality-MVP)
- Builds hierarchical plans (parent_plan + depth) and enforces bounds (max depth/steps/replans/total steps).
- Executes primitive steps via domain mutations (e.g., review_state updates) and tracks executed_steps.
- Wraps every primitive step in guardrail pre/post checks so policies can allow/modify/block/fail tool calls.
