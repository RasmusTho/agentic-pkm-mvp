# Operations Playbook

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Runtime Compose Stack
- `docker-compose.yaml` spins up FastAPI (`api`), bakgrundsagenten (`agent`), Postgres och Redis för lokal utveckling.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data persists in the `postgres-data` volume; run `docker compose down -v` to wipe.
- API-containern kör `scripts/start_api.sh` som först kör `alembic -c app/alembic.ini upgrade head` innan `uvicorn`.
- Agent-containern kör `python scripts/start_agent_service.py`; scriptet laddar `.env`, skippar Alembic när `alembic current` redan visar `(head)`, och startar `python -u run_agent.py` i en 30s restart-loop.
- Supervisorloggar skrivs till `/tmp/agent.log` (stdout/stderr) och agentens output appendas till `/tmp/agent_app.log`; säkra volymer eller log shipping om containern återskapas.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Rotate them with `python scripts/rotate_storage.py [--dry-run|--copy|--truncate]`, which archives into `storage/archive/` by default and keeps a bounded history (`--max-backups`).
- Schedule the script (cron/systemd/GitHub Actions) to run routinely; review `--copy/--truncate` flags depending on whether live readers expect files to remain.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
- Use `--max-age-days` alongside `--max-backups` to purge old archives (set policy, e.g. 30 days).
- Run `pre-commit install` locally so lint/type/test hooks run automatically before each commit.
- Vektordata lagras nu i Postgres (`objects` + `embeddings`); säkerställ att `pgvector`-extensionen finns och kör `VACUUM ANALYZE embeddings` periodiskt om klustret växer snabbt.

## Agent Supervisor Runbook
1. **Starta lokalt** – `python scripts/start_agent_service.py` (lägg till `--dry-run` för att verifiera migrationskommandon utan att exekvera). Scriptet laddar `.env` om `python-dotenv` finns installerat; annars används befintligt env.
2. **Migrationer** – scriptet kör `alembic -c app/alembic.ini current`. Om output redan innehåller `(head)` loggas `Detected Alembic at HEAD — skipping migrations`. Annars körs `upgrade head` med 180s timeout; fel avslutar processen (`exit code 1`).
3. **Agent-loop** – supervisor kör `python -u run_agent.py` och väntar tills processen avslutas. Exit-kod !=0 loggas och triggar omstart efter 30s (konfigurerat i koden).
4. **Loggar** – följ `/tmp/agent.log` för supervisorstatus och `/tmp/agent_app.log` för agentens stdout/stderr. Implementera rotation via logrotate eller cron för att undvika växande filer.
5. **Stoppsignal** – SIGINT/SIGTERM sätter en intern flagga, väntar på att aktiva `run_agent.py` ska avslutas, och stoppar loopens fortsatta restarts. Vid seg nedstängning skickas SIGKILL efter 10s.
6. **Alerting** – sätt upp larm när samma host loggar `"Agent exited with code"` >3 gånger på 10 minuter; indikerar att `run_agent.py` behöver felsökas eller att det saknas input-data.

## Ingestion Review Runbook
1. **Förbered payload** – samla metadata i ett JSONB-kompatibelt dict och råtext i `text`-fältet.
2. **Ingesta** – `POST /ingest` med `{id?, kind?, source_ref?, payload, text}`. Svarar med `object_id` + modell/dimensioner.
3. **Validera** – kör `POST /search`:
   - Endast `query_text` för Lexikal träffbild.
   - Kombinera `query_text` + `query_embedding` (om extern embedding-generator används) för hybrid RRF.
4. **Underhåll** – använd `scripts/bench.py` efter större datavolymer för att övervaka latens (p50/p95) och justera `ivfflat`-parametrar vid behov.

## Auth & Rate Limiting
- Refer to `docs/AUTH_RATE_LIMITING.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.
- Run Redis (or alternative backend) alongside FastAPI to support shared rate-limit counters; configure via env in future work.

## Observability
- Logs: JSON-formatted via `app/observability.setup_logging()`. Hook into your logging stack (CloudWatch, ELK, etc.).
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
- Local Prometheus+Grafana recipe lives in `docs/OBSERVABILITY_STACK.md` (Docker Compose).
