State: SoT v5.5 baseline (descriptive component catalog; update alongside wiring changes).
Doc role: Core SoT
Authority: Current component catalog and dependency boundary reference for the active baseline; descriptive of wiring and ownership, not a replacement for ARCHITECTURE-level contracts.
# Components Catalog (Reality-MVP + forward line)

Canonical list of current modular building blocks.

This document is an implementation catalog (it may mention current entrypoints/config). Kernel-level intent and stability contracts live in `docs/PROJECT_KERNEL.md`.
System-level design rules for modularity, capability-based composition, and documentation-layer boundaries live in `docs/DESIGN_PRINCIPLES.md`.
For the ontology/runtime distinction behind terms such as `artifact`, `object`, `agent`, `plan`,
and `promotion`, also read:
- `docs/CONCEPTS/COGNITIVE_ONTOLOGY.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/plans/RUNTIME_ONTOLOGY_NORMALIZATION.md`

## Maturity taxonomy

Use one label consistently:
- **Baseline** — part of the locked Reality-MVP backbone; relied upon for core workflows.
- **Active** — delivered in the v5.x forward line; used in practice but still evolving.
- **Experimental** — opt-in and not yet considered stable; safe defaults should keep it off.
- **Planned** — documented intent or stubs; not shipped as a user-reliable capability.

## Stores

| Store abstraction | Backend (current) | Notes |
| --- | --- | --- |
| ObjectStore | Postgres / in-memory | Durable runtime object records + payloads (runtime mirror over tracked artifacts; rebuildable from file-based continuity artifacts) |
| VectorIndex | pgvector / in-memory | Embeddings + similarity search (derived, rebuildable) |
| RelationIndex | in-memory / Postgres (if enabled) | Relations graph (may be present even if not fully exploited in every flow) |
| Outbox | Postgres (canonical) + JSONL audit | Canonical queue is DB outbox (`outbox` table). JSONL (`INDEX_OUTBOX_PATH`) is audit/diagnostic only. |

- **ObjectStore (memory/pg)** — Persists object envelopes + payloads; access via store APIs. Maturity: Baseline.
- **VectorIndex (memory/pg)** — Embedding storage + similarity search. Maturity: Baseline. See `docs/EMBEDDINGS.md` for the embedding contract.
- **RelationIndex (memory/pg)** — Relation graph storage for typed links and provenance edges. Maturity: Baseline.

## File-based system artifacts

- **Companion Note** — First-class system artifact linked 1:1 with a tracked vault note in the
  normal case; preserves continuity, identity-repair context, and bounded ingest/healing metadata.
  Portable and file-based; not a cache. Maturity: Planned/forward-line contract.

## Ingest / pipeline agents

Interpretation note:
- several entries in this section are runtime components that produce or transform projections of
  artifacts.
- they should not be read as the canonical ontology of the artifact classes they touch.

- **Normalizer** — Reads source material and emits normalized runtime projections with provenance preserved. Maturity: Baseline.
- **Classifier** — Proposes classifications (types/tags/etc) under human-first constraints. Maturity: Baseline.
- **Chunker** — Splits content into spans for indexing/retrieval. Maturity: Baseline.
- **Deduper** — Detects likely duplicates across runtime projections and records decisions conservatively. Maturity: Baseline.
- **CitationChecker** — Validates outbound references for ASK outputs and review flows. Maturity: Baseline (with Experimental use in CI).
- **Indexer (agent + services)** — Creates embeddings and writes to the VectorIndex; emits index-related events. Maturity: Baseline.

## Retrieval & ranking

Interpretation note:
- retrieval and ranking entries in this section should be read as reusable building blocks,
- not as evidence that retrieval must remain architecturally centered in one agent surface.

- **Hybrid retrieval** — Combined lexical + semantic retrieval with optional reranking overlays.
  Current runtime scope filtering uses `ASK_DOMAIN_SCOPE` + `bridge_domains` as compatibility
  labels for a narrower operational-scope policy, not as the full context model. Maturity:
  Baseline.
- **Rerankers** — Optional reranking providers with deterministic fallbacks. Maturity: Baseline.
- **EmbeddingProvider** — Abstraction boundary for embedding generation. Every embedding is tagged
  with the generating provider/model and remains a derived runtime artifact rather than an identity
  anchor. Maturity: Active direction.
- **Embeddings** — Embedding provider entrypoint with deterministic profiles for tests. Embedding profiles (vault settings) define provider/model/dim/normalization flags so cosine similarity stays consistent. Operational guardrails: `python -m app.cli embed_probe --profile <name>` (inspect provider/model/dim + normalization), `python -m app.cli index doctor --warn/--strict` (check identity drift), and `python -m app.cli index rebuild --profile <name>` (regenerate derived embeddings after changes). Maturity: Baseline.
Changing embedding profiles safely: 1) sanity-check with `python -m app.cli embed_probe --profile <name>`, 2) verify index health via `python -m app.cli index doctor --warn` (or `--strict` before rollout), 3) rebuild via `python -m app.cli index rebuild --profile <name>` to refresh derived vectors.

## ASK / reasoning

Interpretation note:
- current ASK and panel-related entries below describe active runtime surfaces and scaffolding,
- while the broader direction is to separate interaction surfaces from reusable cognition and capability layers.

- **ASK API** — Question answering endpoint returning answers plus source references/latency. Maturity: Baseline.
- **Reasoning layer** — Optional structured reasoning overlays (claims/evidence/inference). Maturity: Experimental.
- **ReasoningFacade** — Shared reasoning/tool entrypoint for LangGraph agents. Maturity: Planned. Forward-line only; not part of the locked v5.5 baseline.
- **BaseLangGraphAgent** — Common agent scaffolding for LangGraph inner loops. Maturity: Planned. Forward-line only; not part of the locked v5.5 baseline.
- **Panel agent** — Panel parsing + intent emission/execution for note interaction. Maturity: Active.
- **LLM router + fabric** — Canonical access layer for chat + embeddings (`app/components/llm/router.py`, `app/components/llm/fabric.py`). High-level modules must use `get_chat_client` / `get_embeddings_client`; routes are reported via `/api/health`. Maturity: Active.

Direction note:
- ASK remains a valid current runtime surface,
- but the design direction is to build retrieval and reasoning as reusable capabilities that can serve multiple interaction surfaces rather than extending an agent-per-function model.

## Eval stack

- **DeepEval ASK** — Optional evaluation suite for ASK behaviors. Maturity: Experimental.
- **Ragas RAG** — Optional RAG evaluation suite. Maturity: Experimental.

## Infra & observability

- **Outbox/events** — DB outbox queue + JSONL audit log. Maturity: Baseline.
- **Status/metrics** — Runtime counters and status snapshots surfaced to humans. Maturity: Baseline.
- **Logging/audit** — Structured logs, traces, and receipt-like operational records for actions and runs. Maturity: Baseline.
- **SyncLayer** — Operational abstraction that reacts to file changes and sync consequences without
  making iCloud or Git architecturally primary. In current reality this is implemented through
  watcher/worker flows over local files and replicas. Maturity: Active direction.
- **HealthContract + WriteGuard + incident snapshots** — Health state machine + write guard ensures safe transitions, emits `state/reason/since` snapshots, and logs incident JSONL entries (`tmp/health-incidents.jsonl` or vault overrides). Sidecar CLI surface: `python -m app.cli health --json` and `python -m app.cli health status --json`, plus the index/events doctor commands (baseline readiness checks). Maturity: Baseline.

## Concurrency & safety

- **DedupTaskQueue** — TTL-based in-process dedup queue (`app/components/concurrency.py`). Maturity: Baseline.
- **Optimistic writes** — Version-checked note writes (`OptimisticWriteGuard`) to prevent corruption. Maturity: Baseline.
- **Idempotency guards** — `EventDedupStore` / `IdempotencyGuard` for event/action dedup in consumers. Maturity: Baseline.

## Optional extension points (not active runtime)

- **Structured OCR** — Stubbed extension point in `app/components/ocr.py`; not wired into the active runtime. Maturity: Planned.
- **Compressive OCR** — Stubbed extension point in `app/components/ocr.py`; not wired into the active runtime. Maturity: Planned.

Documentation and governance surfaces are intentionally tracked elsewhere:
- development workflow: `docs/DEV_WORKFLOW.md`
- data/frontmatter contracts: `docs/DATA_MODEL.md`, `docs/FRONTMATTER.md`
- eval guidance: `docs/eval.md`, `docs/TESTING.md`
