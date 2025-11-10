# Changelog

<!-- SECTION:RECENT-CHANGES:BEGIN -->
## 2025-11-15 – docs+ops: inventory, health CLI, diagrams, links, privacy & ops pack
- Ny `docs/INVENTORY.md` med env-var-tabell, spanlista, CLI-matrix och felkatalog.
- Health CLI (`python -m app.cli health --json`) + dokumentation (docs/HEALTH.md) samt CI-guard att köra kommandot.
- Uppdaterade referensdokument: ARCHITECTURE, DIAGRAMS (Mermaid), LLM_BACKENDS, DEPENDENCIES, QUALITY, TESTING, OPERATIONS, OBSERVABILITY, SECURITY, PRIVACY, CLI, GLOSSARY.
- README fick DOCS-länkar; smoke-workflow verifierar mermaid-block + CLI.
- ROADMAP/CHANGELOG posterar nästa inkrement (rerank, retries, batch-embedding, index-persistens).
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
- LangGraph PER-arkitektur för ingestion
- Enhetlig AMG/SetDB-schema
- E2E-tester för ingestion/curation
- Reasoning-modellstöd (DeepSeek R1 8B)
- Lokal Ollama (llama3.1 8B)

## v4.1 (2025-10-15)
- Första ingestion-skelettet
- Core-6 schema
- Alembic-bas och pgvector
