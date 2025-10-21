# UML Reference & Known Gaps

| Document | Purpose |
| --- | --- |
| [`agent_sequence.md`](agent_sequence.md) | Sequence diagram of `scripts/start_agent_service.py` through the agent loop, with runtime caveats. |
| [`agent_components.md`](agent_components.md) | Component diagram of the agent runtime and storage dependencies, highlighting missing pipelines. |

## Key Issues Highlighted

- **Module imports when running locally**: `scripts/start_agent_service.py` now injects the repo root into `sys.path`, but custom entrypoints must do the same.
- **Ingestion watcher**: Documentation now flags the watcher as legacy; rebuilding it (see `docs/TODO.md`) would restore filesystem-driven ingest.
- **Data seeding**: Agent actions depend on Postgres indices populated via `/ingest`; without data the loop does little and interestingness scores never exceed the threshold.
- **Error visibility**: Reflection queue failures now log warnings with tracebacks; add monitoring if these appear frequently.
- **Configuration validation**: Invalid YAML triggers logged warnings and defaults; consider richer diagnostics if multiple profiles are introduced.

## Missing or Future Files Mentioned in Docs

- `app/ingest/watcher.py` – removed; tracked as a TODO if filesystem ingest returns.
- `/ingest/pending`, `/ingest/review` endpoints – referenced in alignment notes but not implemented.
- Structured promotion pipeline scripts (e.g., `scripts/publish_review.py`) – implied in roadmap but absent.

Use these diagrams as a living reference when restoring the watcher, adding promotion automation, or wiring additional plugins.
