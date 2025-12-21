State: SoT v4.10 Reality-MVP (baseline locked; v5.x Agentic PKM is the forward line).
# Components Catalog (Reality-MVP + forward line)

Canonical list of current modular building blocks.

This document is an implementation catalog (it may mention current entrypoints/config). Kernel-level intent and stability contracts live in `docs/PROJECT_KERNEL.md`.

## Maturity taxonomy

Use one label consistently:
- **Baseline** — part of the locked Reality-MVP backbone; relied upon for core workflows.
- **Active** — delivered in the v5.x forward line; used in practice but still evolving.
- **Experimental** — opt-in and not yet considered stable; safe defaults should keep it off.
- **Planned** — documented intent or stubs; not shipped as a user-reliable capability.

## Stores

| Store abstraction | Backend (current) | Notes |
| --- | --- | --- |
| ObjectStore | Postgres / in-memory | Durable object records + payloads (operational mirror over canonical artifacts) |
| VectorIndex | pgvector / in-memory | Embeddings + similarity search (derived, rebuildable) |
| RelationIndex | in-memory / Postgres (if enabled) | Relations graph (may be present even if not fully exploited in every flow) |
| Outbox | JSONL | Event/intent emission stream (audit + coordination artifact) |

- **ObjectStore (memory/pg)** — Persists object envelopes + payloads; access via store APIs. Maturity: Baseline.
- **VectorIndex (memory/pg)** — Embedding storage + similarity search. Maturity: Baseline.
- **RelationIndex (memory/pg)** — Relation graph storage for typed links and provenance edges. Maturity: Baseline.

## Ingest / pipeline agents

- **Normalizer** — Reads source material and emits normalized objects with provenance preserved. Maturity: Baseline.
- **Classifier** — Proposes classifications (types/tags/etc) under human-first constraints. Maturity: Baseline.
- **Chunker** — Splits content into spans for indexing/retrieval. Maturity: Baseline.
- **Deduper** — Detects likely duplicates and records decisions conservatively. Maturity: Baseline.
- **CitationChecker** — Validates outbound references for ASK outputs and review flows. Maturity: Baseline (with Experimental use in CI).
- **Indexer (agent + services)** — Creates embeddings and writes to the VectorIndex; emits index-related events. Maturity: Baseline.

## Retrieval & ranking

- **Hybrid retrieval** — Combined lexical + semantic retrieval with optional reranking overlays. Maturity: Baseline.
- **Rerankers** — Optional reranking providers with deterministic fallbacks. Maturity: Baseline.
- **Embeddings** — Embedding provider entrypoint with deterministic profiles for tests. Embedding profiles (vault settings) define provider/model/dim/normalization flags so cosine similarity stays consistent. Operational guardrails: `python -m app.cli embed_probe --profile <name>` (inspect provider/model/dim + normalization), `python -m app.cli index doctor --warn/--strict` (check identity drift), and `python -m app.cli index rebuild --profile <name>` (regenerate derived embeddings after changes). Maturity: Baseline.
Changing embedding profiles safely: 1) sanity-check with `python -m app.cli embed_probe --profile <name>`, 2) verify index health via `python -m app.cli index doctor --warn` (or `--strict` before rollout), 3) rebuild via `python -m app.cli index rebuild --profile <name>` to refresh derived vectors.

## ASK / reasoning

- **ASK API** — Question answering endpoint returning answers plus sources/latency. Maturity: Baseline.
- **Reasoning layer** — Optional structured reasoning overlays (claims/evidence/inference). Maturity: Experimental.
- **Panel agent** — Panel parsing + intent emission/execution for note interaction. Maturity: Active.

## Eval stack

- **DeepEval ASK** — Optional evaluation suite for ASK behaviors. Maturity: Experimental.
- **Ragas RAG** — Optional RAG evaluation suite. Maturity: Experimental.

## Infra & observability

- **Outbox/events** — Event emission stream for coordination and audit. Maturity: Baseline.
- **Status/metrics** — Runtime counters and status snapshots surfaced to humans. Maturity: Baseline.
- **Logging/audit** — Structured logs and receipts for actions and runs. Maturity: Baseline.
- **HealthContract + WriteGuard + incident snapshots** — Health state machine + write guard ensures safe transitions, emits `state/reason/since` snapshots, and logs incident JSONL entries (`tmp/health-incidents.jsonl` or vault overrides). Sidecar CLI surface: `python -m app.cli health status --json`, `python -m app.cli health explain`, `python -m app.cli health incidents tail --n N` plus index/events doctor commands (baseline readiness checks). Maturity: Baseline.

## Dev-layer helpers & governance

- **Architecture tests** — Layering/contract tests to keep determinism and boundaries intact. Maturity: Baseline.
- **AI development workflow** — Docs describing coding and review practices. Maturity: Baseline.
- **Frontmatter/data model docs** — Vault expectations and data model descriptions. Maturity: Baseline.
- **Eval docs** — Guidance on running optional suites. Maturity: Baseline.

## OCR extension points (placeholders)

- **Structured OCR** — Stubbed extension point; not wired as a user-facing feature. Maturity: Planned.
- **Compressive OCR** — Stubbed extension point; not wired as a user-facing feature. Maturity: Planned.


