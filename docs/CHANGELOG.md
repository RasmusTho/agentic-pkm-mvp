State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.

# Changelog

<!-- SECTION:RECENT-CHANGES:BEGIN -->
## 2025-11-15 – docs+ops: inventory, health CLI, diagrams, links, privacy & ops pack
- Added `docs/INVENTORY.md` with the env-var table, span list, CLI matrix, and known issues.
- Health CLI (`python -m app.cli health --json`) documented in `docs/HEALTH.md` plus CI guards to run it.
- Updated references: ARCHITECTURE, DIAGRAMS (Mermaid), LLM_BACKENDS, DEPENDENCIES, QUALITY, TESTING, OPERATIONS, OBSERVABILITY, SECURITY, PRIVACY, CLI, GLOSSARY.
- README now links the documentation pack; smoke workflow asserts both Mermaid blocks and CLI commands.
- ROADMAP / CHANGELOG note the upcoming increment (rerank, retry policy, batch embedding, index persistence).
<!-- SECTION:RECENT-CHANGES:END -->

## 2025-11-08 – chore/ingest-export-fixes
- Merge Resolver: deterministic fallback plus explicit “prefer concise” reasons and link-carry on overlapping edits.
- Search / Hybrid: corrected vector index call signature and RRF-based blending.
- Interesting API: repository-backed methods with in-memory fallback retained for tests.
- Outbox: worker-compatible helper API with defensive connection handling documented.
- Ingest: exported `ingest_object`, `normalize_payload`, and `handle_post_ingest` again for downstream imports.

## v4.3 (2025-10-25)
- Added: Obsidian vault integration and lifecycle mirroring
- Added: Export pipeline (`scripts/export_objects.py`)
- Added: Promotion flow (Reviewer → SetEvaluator → Projector) completion
- Added: Backfill job (`make backfill`) for ingestion hygiene
- Added: Episodic memory wiring across agents
- Changed: Agents now run via LangGraph PER loops
- Changed: Documentation unified to SoT v4.3 baseline

## v4.2 (2025-10-18)
- LangGraph PER architecture driving ingestion
- Unified AMG/SetDB schema
- E2E tests for ingestion/curation
- Reasoning model support (DeepSeek R1 8B)
- Local Ollama (llama3.1 8B)

## v4.1 (2025-10-15)
- Initial ingestion skeleton
- Core-6 schema
- Alembic base + pgvector