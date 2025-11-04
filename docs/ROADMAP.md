
### `docs/ROADMAP.md`

# Roadmap — SoT v4.3.1 → v4.4 → v4.5 → v5.0

_Tracks strategic releases and planned features._

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

## v4.4 — Observability, Stores & Conflict Resolution (In progress / Running)

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
- Eval harness (text + AV) and CI publishing QAS metrics
- Dashboards: coverage, p95, RTF, WER estimates
- **Accept:** QAS-003 ≤ 250 ms; QAS-010 ≤ 2 s; eval suite green

**Risks & Mitigations**
- AV latency → VAD segmentation, batching, optional GPU
- Model churn → provider interface, versioned provenance
- Event drift → central alias map; schema lint in CI

---

## v5.0 — Reasoning Alpha (Longer-term)

**Goal:** Add a reasoning / integrity layer on top of SetDB+AMG without letting hallucinations overwrite truth.

**Direction**
- Represent claims/relationships as explicit triples with provenance.
- Guard/Reasoner agent validates constraints (SHACL-style), detects contradictions, flags missing provenance.
- Neurosymbolic loop: subsymbolic agents propose; symbolic layer evaluates; outputs become `decisions`/`audit`/`cleanup.intent.created`, not silent mutation of canonical notes.
