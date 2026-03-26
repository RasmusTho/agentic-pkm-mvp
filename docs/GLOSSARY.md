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
- **Mimer** - The current implemented knowledge surface centered on the Obsidian vault, ingestion/indexing, and vault-facing agent behavior.
- **Hugin** - The agent and reasoning layer concept within Yggdrasil; in the current codebase this mostly maps to agent/runtime logic rather than a separate deployable module.
- **Munin** - Planned media and raw-memory module for source artifacts that should not live directly as vault notes.
- **Ratatosk** - Ingest and pipeline boundary for moving material into the system with auditable routing and normalization.
- **Brokkr** - Planned project-workshop boundary for execution artifacts and deliverables outside the semantic vault layer.
- **Tyr** - Planned formal-records boundary for receipts, contracts, and administrative records.
- **Heimdall** - Infrastructure and observability boundary: runtime operations, metrics, logs, dashboards, and runbooks.
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
<!-- SECTION:GLOSSARY:END -->
