# Changelog

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
