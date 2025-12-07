State: SoT v4.10 Reality-MVP (current).
# Agent Spec — Reality-MVP

Concise contracts for the active agents. Canonical behaviour is defined in `docs/AGENTS.md`, `docs/PANEL_AGENT.md`, `docs/EVENTS.md`, and the implementations under `app/agents/*`. Anything not described here is planned or legacy.

## Active agents (Reality-MVP)

| Agent | Inputs | Outputs / Events | Side effects | Notes |
| --- | --- | --- | --- | --- |
| Normalizer | `path`, `trace_id` | Dict with `event=ingest.normalize.done`, `object_id`, `core6` | Saves to `ObjectStore` (memory/pg) without emitting outbox; best-effort audit | Parses markdown-ish file, generates uuid/title/core6; idempotence not guaranteed for duplicate paths. |
| Classifier | `object_id`, `trace_id` | Classification dict (type/tags/trust/confidence) | Writes via `decisions` store and `memory.store.remember`; best-effort audit | Uses LLM+heuristic fallback; no outbox event emitted. |
| Chunker | `object_id`, `trace_id`, `max_tokens`, `overlap`, `strategy` | Dict with `event=ingest.chunk.done`, `chunks` count | Audit only; chunks are not persisted in Reality-MVP | Fallback: single chunk when text exists; no structured offsets yet. |
| Deduper | `object_ids` (list), `threshold`, `trace_id` | Dict with `event=curation.dedupe.done`, similarity pairs | No store writes in current code | Uses deterministic embeddings for similarity; marking duplicates is planned. |
| CitationChecker | `object_id`, `trace_id` | Dict with `event=curation.citation_check.done`, `status`, `reason` | Writes to `memory.store.remember` | Simple URL heuristic + latest classification trust; no LLM. |
| Indexer | `object_id`, `trace_id` | Dict with `event=ingest.index.done`, `embeddings` count | In-memory vector map only (no DB write); best-effort | Embeds raw_text/title via deterministic client; pgvector/BM25 indexing is planned beyond MVP. |
| Reviewer | `object_id`, `trace_id`, `threshold?` | Dict with `event=curation.review.done`, `allow`, `score`, `reasons` | Inserts decision via `services.decisions`, audits | Uses reasoning provider + deterministic allow/deny alternation for tests. |
| SetEvaluator | `object_id`, `trace_id`, `threshold?` | Dict with `event=promotion.evaluate.done`, `allow`, `promote`, `score` | Inserts decision (best-effort), audits | Requires prior review decision; no membership writes in MVP. |
| ASK Agent | `query`, `trace_id` | `AgentState` with `hits`, `answer` | Reads hybrid search + optional rerank; no writes | Path: retrieve → rerank → answer. Default answer is top snippet when reasoning is disabled. |
| PanelAgent | Panel payload, `trace_id` | Intent + events | Emits panel-derived intents/events (flag-gated) | Uses `NoteInteractionAgent`; panels are not indexed. |
| Promotion/Projector | `object_id`, `trace_id` | Promotion summary | Emits audit/membership events; frontmatter projection is stubbed | Filesystem/frontmatter writes beyond audit are future work. |

## Parked / future agents
- MergeResolverAgent, NoteHygieneAgent, Planner/Orchestrator/MCP flows are **planned** for v5.x and not part of Reality-MVP. Keep references in ROADMAP; do not rely on them for current behaviour.

## Usage notes
- All events must follow the Outbox envelope in `docs/EVENTS.md`; many agents currently return event-shaped dicts without emitting to Outbox—mark these as planned before claiming full integration.
- Stores/Components are the only allowed integration points (no raw DB or provider SDKs).
- If you extend an agent, add/adjust tests first (`tests/api/test_ask_*`, `tests/e2e/test_reality_mvp_pipeline.py`, agent-specific tests).
