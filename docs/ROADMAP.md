
### `docs/ROADMAP.md`

# Roadmap — SoT v4.5 stable baseline

_Tracks strategic releases and planned features._

## Delivered (2025-11-08)
- Outbox helpers document the worker-compatible API (write/poll/ack) and defensive connection handling.
- Merge Resolver prompt-pack feeds a deterministic fallback that prefers concise edits and carries refs/links from overlapping versions; reasons surface in `info.reason`.
- Interesting API endpoints now call repository-backed methods first and fall back to in-memory stores for tests.
- Search hybrid flow (BM25 + vector via RRF) uses the corrected call signature and is covered by regression tests.
- Ingest module re-exports `ingest_object`, `normalize_payload`, `handle_post_ingest`, keeping CLI/tests aligned.

## Stable baseline — ✅ v4.5 (Search & Ingest Stabilization)
- Unified ingestion lifecycle, including OCR + AV, routes through ObjectStore with UUID guarantees.
- Deterministic FT-first hybrid search with rerank and guardrails produces traceable answers.
- Memory-mode CI is authoritative: smoke workflow runs `STORE_BACKEND=memory`, `LLM_PROVIDER=mock`, `SKIP_CLASSIFIER_TESTS=1` without Postgres services.
- Documentation (Architecture, Status, Diagrams) reflects the Store abstraction and Promotion Agent contracts.

## Next milestone — ▶️ v5 — Reasoning Layer (Logic & RDF/OWL integration)
- Introduce a reasoning tier that projects promotion/ingest facts into RDF/OWL so symbolic checks can co-exist with subsymbolic agents.
- Extend RelationIndex to emit triples + SHACL-like constraints and teach Promotion Agent to assert provenance edges.
- Add a lightweight logic engine (prolog-esque or `pyshacl`) to validate claims before publishing; surface violations via Outbox topics.
- Expose reasoning summaries in the CLI/API so humans can trace why an object moved between states.

## Next
1. Unify ingestion through the Store interfaces end-to-end (ObjectStore, VectorIndex, RelationIndex) so routers/agents never import psycopg directly.
2. Audit event coverage (Outbox + JSONL) and add contract checks so every state transition emits the documented topic.
3. Add fitness functions: hybrid search p95 < 250 ms under load, Outbox → index propagation ≤ 2 s (QAS-010) with alerts when exceeded.

## Pre-flight (carry-over from v4.4)

- Wire the semantic merge driver into git (`.gitattributes`) so `%A` is updated automatically; keep CLI exit!=0 on unresolved.
- Schedule Hygiene runs and assert `cleanup.done` in CI.
- Enforce `system-settings.yaml` schema in CI gates.
- Maintain deterministic-embedding fallback path.
- Keep Outbox table as the event bus until the broker ADR is accepted (Debezium/Kafka design drafted, not implemented).

## Near-term (next 1–2 sprints)

1. Extract real routers under `app/api/routers/{agent.py, interesting.py, dashboard.py}` and include them from `app/main.py`; keep the shim as a safety net for one sprint.
2. Harden the Store provider: document `STORE_BACKEND`, keep the fast Postgres probe, and add contract tests for both `"pg"` and `"memory"` paths.
3. Add baseline observability around Store writes (Outbox + `trace_id` log entries).
4. Clean up `_legacy` import paths once routers and Stores are the primary wiring surface.
5. Resume Classifier v2 work: drop `SKIP_CLASSIFIER_TESTS` once the new design lands and run the full suite (`SKIP_CLASSIFIER_TESTS=0` locally first).

---

## v4.3.1 — Obsidian-first (Delivered / Active baseline)

**Goal:** The vault (Markdown + YAML front matter) is the human source of truth. The system does the boring lifecycle work.

Delivered (selection)
- `system-settings.yaml` canonical runtime policy with JSON Schema + test validation.
- Promotion Agent: consumes `promote.intent.created`, enforces cooldown/idempotence, updates front matter, emits `promote.done`, triggers reindex.
- Indexer: deterministic embeddings; UUID-stable upsert; hybrid search boosts by `review_state`.
- Outbox propagation: content change → event → indexer → searchable.
- Tracing hooks: spans + `trace_id`; Jaeger path validated.
- MergeResolverAgent: semantic 3-way Markdown merge with UUID guard / non-regression of `review_state`.
- `app/cli/merge_driver.py`: prints merged result + `MERGE_STATUS`/`MERGE_REASON`; exit 0 only if resolved.
- NoteHygieneAgent: salvages link-only notes, archives empties, moves oversized dumps; emits `cleanup.done`.
- Smoke tests (`make smoke`) cover settings schema, promotion roundtrip, merge safety, merge driver CLI, hygiene.

---

## v4.4 — Observability, Stores & Conflict Resolution (Delivered)

**Goal:** Make the system boring-in-production while laying the Store foundation.

**Delivered**
- ObjectStore fronts ingestion; all writes via `save_object(emit_outbox=True)` with app-assigned UUIDs.
- UUID is canonical end-to-end. VectorIndex and RelationIndex live as Store modules.

**Hardening**
- Contract tests for Store APIs and Outbox payloads in CI.
- Promotion Agent uses ObjectStore (`emit_outbox=False`) + RelationIndex provenance edges.
- Enforce guardrail: no direct INSERTs into `objects`/`outbox`/`relations`.
- Maintain fitness functions **QAS-003**, **QAS-010**.

**Identity & flow**
- Remove legacy `id` → promote `uuid` to PRIMARY KEY.
- Outbox consumer loop drives Indexer/Reviewer by UUID + `trace_id`.
- RelationIndex powers provenance queries.

**Later (polyglot persistence)**
- Evaluate Cosmos DB for ObjectStore, graph backend for RelationIndex, vector DB for VectorIndex—without agent rewrites.

**Operational items**
- Git merge driver integration; hygiene scheduling; promotion observability; CI tightening; broker-backed Outbox ADR.

---

## v4.5 — Unified Ingestion & Rerank (Active)

**Goals**
- Make OCR and AV first-class (views + chunk + embeddings).
- Add lightweight cross-encoder rerank in the retrieval path.
- Keep Stores + Outbox canonical; preserve UUID invariants.
- Enforce CI fitness (QAS-003, QAS-010, RAG-accuracy@n).

**Milestones**

### A — Minimum Viable Ingestion
- OCR adapter → structure-aware Markdown + table JSON
- AV Step A: detect → normalize (ffmpeg) → ASR (faster-whisper) → `segments.jsonl`
- Chunk → Embed → Hybrid search
- Events wired: `ocr.document.completed`, `av.asr.completed`, `text.chunk.created`, `index.embedding.created`
- **Accept:** mixed-corpus eval queries return correctly cited spans/timestamps

### B — Precision & UX
- Diarization + alignment (whisperx + pyannote)
- Chapterizer → `chapters.json`
- Cross-encoder rerank in query path
- Citations with text spans and AV timestamps
- **Accept:** measurable lift in nDCG/MRR vs A; user-visible timestamps

### C — Graph & Fitness
- RelationIndex v1 (speakers/entities with temporal edges)

<!-- SECTION:NEXT-INCREMENT:BEGIN -->
## Next increment (target 2025-11)
1. **Cross-encoder rerank** – insert a lightweight cross-encoder after `hybrid_search`. Requirement: latency budget < 150 ms with fallback to the current scoring.
2. **LLM retry policy** – wrap `_call_llm` + embeddings with `DEFAULT_BREAKER` and short exponential backoff. Document gaps in `docs/LLM_BACKENDS.md`.
3. **Batch embedding** – extend `app.llm.embeddings.embed_texts` so Ollama POST accepts lists and writes back to the cache. Goal: 5× throughput during reindex.
4. **Index persistence** – sync `MemoryHybridStore` to Postgres (new `hybrid_documents` table). CLI should replay JSONL → DB without data loss.
<!-- SECTION:NEXT-INCREMENT:END -->
- Eval harness (text + AV) and CI publishing QAS metrics
- Dashboards: coverage, p95, RTF, WER estimates
- **Accept:** QAS-003 ≤ 250 ms; QAS-010 ≤ 2 s; eval suite green

**Risks & Mitigations**
- AV latency → VAD segmentation, batching, optional GPU
- Model churn → provider interface, versioned provenance
- Event drift → central alias map; schema lint in CI

---

## v5 — Reasoning Layer (Logic & RDF/OWL integration) — Longer-term

**Goal:** Add a reasoning / integrity layer on top of SetDB+AMG without letting hallucinations overwrite truth, using RDF/OWL vocab + logic constraints.

**Direction**
- Represent claims/relationships as explicit triples with provenance surfaced through RelationIndex APIs.
- Guard/Reasoner agent validates SHACL-style constraints, detects contradictions, and flags missing provenance before Promotion Agent can publish.
- Neurosymbolic loop: subsymbolic agents propose; symbolic layer evaluates; outputs become `decisions`/`audit`/`cleanup.intent.created`, not silent mutation of canonical notes.
- RDF/OWL export + SPARQL diagnostics keep reasoning explainable and replayable in CI.
