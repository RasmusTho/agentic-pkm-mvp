# STATUS — Snapshot (2025-11-08)

## Current status
- 🟢 Test suite green on `chore/ingest-export-fixes` (`pytest -q`).
- 🟢 Merge Resolver now reports deterministic fallback reasons (“prefer concise”, “carry refs/links from B”) in addition to LLM prompt-pack output.
- 🟢 Interesting API endpoints prefer repository-backed methods with an in-memory fallback for tests.
- 🟢 Outbox helpers documented and stable: worker-compatible API, optional connection handling, idempotent ack semantics.
- 🟢 Ingest exports restored (`ingest_object`, `normalize_payload`, `handle_post_ingest`) and imported consistently.

## Known limitations
- None beyond roadmap items; keep tracking pending work in [`docs/ROADMAP.md`](docs/ROADMAP.md).
   
