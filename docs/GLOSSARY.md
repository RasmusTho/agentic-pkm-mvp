State: SoT v5.5 Reality-MVP baseline locked.
Doc role: Reference
Authority: Shared vocabulary for active concepts and module names used across the docs; if terminology changes in the active system, update this glossary with the owner docs.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run defaults on (`WATCHER_AUTO_EXEC=1`); set `WATCHER_AUTO_EXEC=0` for emit-only mode. LangGraph/Reasoning rollout remains opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Glossary

Brief definitions for recurring concepts.

<!-- SECTION:GLOSSARY:BEGIN -->
- **Artifact (PKA usage)** - A persistent thing the system tracks across human, system, or runtime surfaces; not every artifact is a vault note, and not every runtime object is the artifact itself.
- **Human surface** - The human-facing writing/reading surface, currently centered on vault notes in Obsidian.
- **System surface** - The system-owned file/artifact surface for continuity, repair, receipts, and other bounded non-human-authoring artifacts.
- **Runtime surface** - Local operational persistence such as DB objects, chunks, embeddings, and derived summaries.
- **Companion note** - First-class system artifact for continuity and repair of a tracked vault note; typically one per note; not a cache or convenience projection.
- **Healing** - Conservative identity/continuity repair process. Priority order: frontmatter UUID, companion note, DB identity record, source_ref/path, exact content hash, semantic triage only, then new UUID.
- **source_ref** - Vault-relative path or equivalent locator used as a mutable secondary identity/continuity field; useful for repair, but not a stable primary identity.
- **ingest_state** - Bounded note-tracking state used by the companion artifact: `untracked`, `known`, `indexed`, `stale`, `healing_needed`, `soft_deleted`, `archived`.
- **SyncLayer** - Operational abstraction where the system reacts to changed files and sync consequences without treating iCloud or Git as semantically primary.
- **EmbeddingProvider** - Abstraction boundary for embedding generation; each embedding is tagged with the generating provider/model and remains a derived runtime artifact.
- **Yggdrasil** - The ecosystem apex: the whole acknowledged System of Systems, not a system in its own right (ADR-0044). Constituents hang off it — currently **Mimer**, **Heimdall**, and a thin private-bindings constituent. Do not use "Yggdrasil" to denote the knowledge-and-cognition product itself; that is **Mimer**. Most legacy prose across this repo that says "Yggdrasil" while describing the product/runtime/vault system predates this reconciliation and denotes Mimer under the current model. See also the "System of Systems" entry below for the repo's separate, older internal-decomposition usage of the SoS phrase.
- **Mimer** - The knowledge-and-cognition constituent: the current implemented system — the Obsidian vault surface, ingestion/indexing, retrieval, the correctness kernel, the 14 control boundaries, CES, and the Knowledge Acquisition Platform (KAP). One undivided constituent, not split into knowledge and agent-runtime. Reverted to its original name by ADR-0044 (the system was named Mimer before an earlier rename to Yggdrasil; Mímir is the well of wisdom at Yggdrasil's root).
- **Heimdall** - The sensor / event-capture constituent: continuous observation of reality converted into attributed, timestamped events with confidence and provenance, published as an append-only stream that Mimer consumes as candidate evidence, never as authority (ADR-0044, ADR-0045). Unrelated to this repo's runtime observability concern, which keeps its own shipped boundary code **OEF** (Observability, Evaluation & Fitness, `docs/boundaries/OEF.md`) and does not use a Norse alias.
- **Hugin / Munin** - **Reserved, not active constituents** (ADR-0044). A superseded draft (ADR-0043) proposed splitting knowledge-and-cognition into two constituents — **Munin** (knowledge/memory) and **Hugin** (agent-runtime). That split failed the constituent-independence test (six control boundaries and the governed-write invariant chain cross it on every durable mutation) and was replaced by the single undivided **Mimer** constituent. The names stay reserved for a possible future split only if one ever passes that test; they do not denote any active module today.
- **Ratatosk** - Ingest and pipeline boundary for moving material into the system with auditable routing and normalization.
- **Brokkr** - Planned project-workshop boundary for execution artifacts and deliverables outside the semantic vault layer.
- **Tyr** - Planned formal-records boundary for receipts, contracts, and administrative records.
- **Outbox** – Canonical DB outbox queue used by watcher/worker (`app/services/outbox.py`). JSONL (`INDEX_OUTBOX_PATH`) is a non-canonical audit log (`app/outbox/events.py`, `app/index/outbox.py`).
- **Embedding** – Floating-point vector from `app/llm/embeddings.py` (Ollama `/api/embeddings` or mock); used in retrieval/indexing.
- **BM25** – Lexical scorer (`rank_bm25.BM25Okapi`) used in hybrid retrieval.
- **Rerank** – Optional reordering stage in retrieval, enabled via `RERANK_ENABLE` and implemented under `app/retrieval/rerank/`.
- **Span** – `@span("node")` decorator in `app/obs/log.py` logging latency + `trace_id`.
- **Guardrails** – Rules in `app/quality/guardrails.py` preventing forbidden content, enforcing sources, and capping tokens.
- **Circuit breaker** – `CircuitBreaker` in `app/quality/guardrails.py` limiting failures per time window.
- **Index outbox JSONL** – `{object_id, kind, source_ref, payload}` audit lines (see `docs/INVENTORY.md`).
- **Hybrid store** – In-memory combination of BM25 + embeddings + fuzzy overlap (`app/retrieval/hybrid.py`).
- **Health CLI** – `python -m app.cli health --json` validates local deps (ffmpeg/yt-dlp), outbox settings, and LLM reachability.
- **System of Systems** – Two distinct usages coexist in this repo; do not conflate them.
  (1) **Internal-decomposition usage (colloquial, pre-dates ADR-0044).** "Modular,
  authority-separated single system" (ADR-0015's modularity intent;
  `docs/plans/V60_CAPABILITY_AND_AGENT_EVOLUTION.md:97-101`), applied to Mimer's internal
  8-subsystem decomposition in `docs/MODULAR_ARCHITECTURE.md`. This is **descriptive of repo
  usage, not a normative INCOSE ruling**. Per the 2026-07-03 audit
  (`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §3`, cited as advisory, not
  settling), the INCOSE sense of System of Systems requires operationally- and
  managerially-independent constituents, which Mimer's internal subsystems fail
  (`docs/MODULAR_ARCHITECTURE.md:26` states they are "not separate deployments, services,
  or processes"). Whether to rename `docs/MODULAR_ARCHITECTURE.md` on the strength of that
  finding is an **open owner decision** (audit §15 Q2, routed to
  `docs/SYSTEM_CONTEXT_OVERLAY/ROUTE_RESHAPE_DECISIONS_TO_OWNER.md`, SBI-8) — this entry links
  the question rather than settling it.
  (2) **Ecosystem usage (ratified, ADR-0044).** The one INCOSE-defensible SoS reading is the
  **acknowledged System of Systems at ecosystem/apex level**, named **Yggdrasil**: the operator's
  assembled environment, apex ⊃ { **Mimer** (knowledge-and-cognition constituent), **Heimdall**
  (sensor constituent), a private-bindings constituent, plus external systems it interoperates
  with such as Obsidian and iCloud } (`docs/ARCHITECTURE.md:239`; ADR-0044; see also the
  "Yggdrasil"/"Mimer"/"Heimdall" entries above). This SoS relationship is **not** called
  "federation" — that word is reserved for SFC's intra-constituent replication/consensus
  (`docs/boundaries/SFC.md`); the ecosystem relationship is acknowledged constituents
  interoperating via capability contracts (ADR-0045). See also
  `docs/architecture/system-context-overlay.md :: System of Systems (SoS) — repo usage vs INCOSE`
  and `docs/architecture/ecosystem-federation.md`.
<!-- SECTION:GLOSSARY:END -->
