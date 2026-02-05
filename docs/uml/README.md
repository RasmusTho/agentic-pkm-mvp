State: Legacy (archived).
# UML Reference & Known Gaps

| Document | Purpose |
| --- | --- |
| [`agent_sequence.md`](agent_sequence.md) | Sequence diagram of the supervisor: env load → Alembic check → `run_agent.py` restart loop. |
| [`agent_components.md`](agent_components.md) | Component diagram of supervisor + agent runtime, storage dependencies, and missing ingest/promotion pieces. |

## Key Issues Highlighted

- **Supervisor loop kräver data**: utan seedade objekt blir `run_agent.py` kortlivad och övervakaren restartar var 30:e sekund.
- **Ingestion watcher**: Dokumentationen markerar watchern som legacy; bygg ett ersättningsscript eller ta bort referensen.
- **Loggrotation & alerting**: `/tmp/agent.log` och `/tmp/agent_app.log` växer annars obegränsat; sätt upp rotation och larm.
- **Konfigurationsvalidering**: Ogiltig YAML loggas och faller tillbaka till defaults; förbättra diagnostics om flera profiler införs.

## Missing or Future Files Mentioned in Docs

- `app/ingest/watcher.py` – borttagen; finns som TODO för eventuell återintroduktion.
- `/ingest/pending`, `/ingest/review` endpoints – refererade i alignment, fortfarande obefintliga.
- Scripts för promotion/logrotation (`scripts/publish_review.py`, `scripts/rotate_agent_logs.py`) – antydda i roadmap men ej skapade.

Use these diagrams as a living reference when restoring the watcher, adding promotion automation, or wiring additional plugins.
