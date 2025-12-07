State: SoT v4.10 Reality-MVP (current core).
# Status — Operational Snapshot

Reference: `docs/SYSTEM_DESIGN_v4.10.md` captures the external dependencies and deployment topology for this SoT.

## Version ladder (summary)
| Version | Goal | State | Notes |
| --- | --- | --- | --- |
| Reality-MVP (SoT v4.10) | Reliable vault ingestion + minimal external plane + ASK API + observability + interim GUI | Active (current) | Single-user focus; collaboration deferred |
| v4.4–v4.6 | Observability + Store abstraction + retrieval quality uplift | Delivered (historical) | Foundation for hybrid retrieval and fitness gates |
| v4.8 | A2A Protocol V1 + Orchestrator messaging | Schema/mocks delivered; wiring deferred | Gated by `A2A_ENABLE` (post-MVP) |
| v4.9 | MCP Integration + Planner Agent | Delivered (schema, descriptors, mock/LLM planners) | Flags: `MCP_ENABLE`, `PLANNER_ENABLE` |
| v4.10 | Orchestrator Runtime skeleton | Delivered (audited, mocked) | Flag: `ORCHESTRATOR_ENABLE`; LangGraph/real MCP deferred |
| v5.x (planned) | Symbolic reasoning + reflexive agents + satellite sync | Planned | Builds on v4.10 baseline |

Eval baseline: DeepEval ASK + Ragas RAG suites are available under `@pytest.mark.eval` (seed cases; opt-in, diagnostics only).

## Reality-MVP snapshot
- Implemented: Vault ingest (UUID healing + mirror writes + fingerprints) into Stores + Outbox; ASK CLI/API over the vault plane with hybrid retrieval and optional rerank/LLM answers; status service for store counts and ASK latency; Planner/A2A/MCP/Orchestrator skeletons are present but flag-gated; planes/zones are defined but only `origin`/`path` are surfaced in ASK responses today.
- In progress: External drop ingest remains manual (`external_raw` objects only appear when inserted into the store); zone overlays and relation surfaces are not yet exposed in ASK answers; GUI/observability dashboards are minimal beyond the status endpoint.
- Planned/queued: Broader observability (dashboards/GUI), fuller PanelAgent → Planner/Orchestrator wiring, and collaboration/multi-user remain deferred.
- Smoke path: canonical note → ingest → index → ASK captured in `docs/scenarios/REALITY_MVP.md` and exercised by `tests/e2e/test_reality_mvp_pipeline.py`.

## SoT v4.10 — Completed pillars
- **Component catalog + dependency rules** — `docs/COMPONENTS.md` lists component families (API, agents, services, components, stores, retrieval, eval) and the dependency matrix enforced by `tests/architecture/test_import_rules.py` and `tests/guard/test_no_direct_db_imports.py`.
- **Canonical Outbox envelope** — `app/events/schema.py` defines the OutboxEvent contract (event, trace_id, source, timestamp, payload, meta); enforced by `tests/architecture/test_events_outbox_contracts.py`; documented in `docs/EVENTS.md`.
- **ASK graph and AgentState** — `/api/ask` runs the LangGraph-based ASK AgentState (`app/agents/ask/graph.py`) using component-based embeddings/rerankers and the hybrid store; contract tested via `tests/api/test_ask_api.py`, `tests/api/test_ask_contract.py`, `tests/api/test_ask_llm_answer.py`; described in `docs/AGENTS.md`, `docs/HUMAN-FLOWS.md`, `docs/SYSTEM_DESIGN_v4.10.md`.
- **PanelAgent / NoteInteractionAgent** — Implemented in `app/agents/panel/*`, documented in `docs/PANEL_AGENT.md`, tested under `tests/panel/`, emits canonical Outbox events; HUMAN-FLOWS covers panel integration in human flows.
- **Eval/QA stack (opt-in)** — DeepEval ASK eval (`tests/eval/test_ask_deepeval.py` + bilingual cases) and Ragas RAG eval (`tests/eval/test_rag_ragas.py` + `docs/eval/rag_cases.yaml`); opt-in via `@pytest.mark.eval` with clear skip paths; documented in `docs/eval.md` and `docs/guardrails.md`.
- **System design + diagrams** — `docs/SYSTEM_DESIGN_v4.10.md` is the global anchor; `docs/DIAGRAMS.md` contains C4 context/container/component diagrams aligned with the v4.10 topology (API, agents, Postgres/pgvector, Ollama, observability, Obsidian, CLI).
- **Onboarding + dev workflow** — README updated for SoT v4.10 (overview, flows, quickstart); `docs/DEV_WORKFLOW.md` and `docs/AI_DEVELOPMENT.md` describe TDD + schema-driven + AI-assisted development expectations.

## Historical baselines (for reference)
- v4.4–v4.6: Observability and store abstraction, deterministic ingestion, rerank/fitness gates, diarization hooks, relation coverage, golden evaluation.
- v4.8–v4.10 (pre-MVP overlays): A2A schema defined; MCP/Planner descriptors and mocks delivered; Orchestrator skeleton audited and flag-gated. These remain optional until integrated post-MVP.
