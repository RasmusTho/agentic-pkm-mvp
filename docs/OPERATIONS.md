State: SoT v4.10 Reality-MVP (current core).
# Operations Playbook

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Runtime Compose Stack
- `docker-compose.yaml` starts FastAPI (`api`), the background agent (`agent`), Postgres, and Redis for local development.
- Ensure `.env` contains the desired secrets before running `docker compose up --build`.
- Postgres data lives in the `postgres-data` volume; `docker compose down -v` wipes it.
- The API container runs `scripts/start_api.sh`, which performs `alembic -c app/alembic.ini upgrade head` before launching `uvicorn`.
- The agent container runs `python scripts/start_agent_service.py`; the script loads `.env`, skips Alembic when `alembic current` already reports `(head)`, and executes `python -u run_agent.py` in a 30 s restart loop.
- Supervisor logs land in `/tmp/agent.log` (stdout/stderr) and agent output appends to `/tmp/agent_app.log`; secure volumes or log shipping if the container is recreated.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Rotate them with `python scripts/rotate_storage.py [--dry-run|--copy|--truncate]`, which archives into `storage/archive/` by default and keeps a bounded history (`--max-backups`).
- Schedule the script (cron/systemd/GitHub Actions) to run routinely; review `--copy/--truncate` flags depending on whether live readers expect files to remain.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
- Use `--max-age-days` alongside `--max-backups` to purge old archives (set policy, e.g. 30 days).
- Run `pre-commit install` locally so lint/type/test hooks run automatically before each commit.
- Vector data now lives in Postgres (`objects` + `embeddings`); ensure the `pgvector` extension is installed and run `VACUUM ANALYZE embeddings` periodically as the cluster grows.

## Agent Supervisor Runbook
1. **Start locally** – `python scripts/start_agent_service.py` (add `--dry-run` to validate migrations without executing). The script loads `.env` if `python-dotenv` exists; otherwise it uses the current environment.
2. **Migrations** – runs `alembic -c app/alembic.ini current`. If `(head)` is already present it logs `Detected Alembic at HEAD — skipping migrations`; otherwise executes `upgrade head` with a 180 s timeout (failures exit 1).
3. **Agent loop** – supervisor runs `python -u run_agent.py` and restarts it after 30 s whenever the exit code is non-zero.
4. **Logs** – tail `/tmp/agent.log` for supervisor events and `/tmp/agent_app.log` for agent stdout/stderr. Rotate via logrotate or cron to prevent unbounded growth.
5. **Stop signal** – SIGINT/SIGTERM sets an internal flag, waits for the active `run_agent.py` to finish, and stops further restarts. Sends SIGKILL after 10 s if shutdown stalls.
6. **Alerting** – page when the same host logs `"Agent exited with code"` more than three times within ten minutes; indicates `run_agent.py` needs investigation or lacks input data.

## Ingestion Review Runbook
1. **Prepare payload** – gather metadata in a JSON-compatible dict plus raw text under `text`.
2. **Ingest** – `POST /ingest` with `{id?, kind?, source_ref?, payload, text}`. Response returns `object_id` + model/dimensions.
3. **Validate** – call `POST /search`:
   - `query_text` only for lexical shape.
   - Combine `query_text` + `query_embedding` (if an external embedding generator is used) for hybrid RRF.
4. **Maintain** – run `scripts/bench.py` after major data imports to watch latency (p50/p95) and adjust `ivfflat` parameters.

## Auth & Rate Limiting
- Refer to `docs/AUTH_RATE_LIMITING.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.
- Run Redis (or alternative backend) alongside FastAPI to support shared rate-limit counters; configure via env in future work.

## Observability
- Logs: JSON-formatted via `app/observability.setup_logging()`. Hook into your logging stack (CloudWatch, ELK, etc.).
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
- Local Prometheus+Grafana recipe lives in `docs/OBSERVABILITY_STACK.md` (Docker Compose).


## Startup telemetry (startup_status.json)
- Location: `tmp/startup_status.json` (workspace root on the host).
- Lifecycle: written by `scripts/start_full_system.sh` on phase changes and in the cleanup trap; the last write happens on exit. Values are merged with the existing file; fields with explicit `None`/empty values are cleared when the writer marks them as clearable.
- Fields:
  - `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `timestamp` (last write). `started_at`/`ended_at` may appear when callers add them.
  - `llm_probe_step`, `llm_probe_cmd`, `llm_probe_rc`, `llm_probe_output_snippet`
  - `compose_up_step`, `compose_up_cmd`, `compose_up_rc`, `compose_up_output_snippet`
  - `db_probe_step`, `db_probe_cmd`, `db_probe_rc`, `db_probe_output_snippet`
- Debugging cold-start failures after `docker compose down`:
  - Bucket A: compose-up failure → check `compose_up_*` fields; expect `exit_reason=compose_up_failed` and a short `compose_up_output_snippet`.
  - Bucket B: db container/CID failure → `db_probe_step=compose_ps_db` and an empty/failed `db_probe_output_snippet`.
  - Bucket C: exec/psql timing failure → `db_probe_step=db_env_*` or `db_probe_rc!=0`; `db_probe_output_snippet` shows the failing exec/psql error.
- What to paste into an issue/PR comment: `timestamp`, `phase`, `last_ok_phase`, `exit_code`, `exit_reason`, `compose_up_*`, `db_probe_*`, `llm_probe_*`.

<!-- SECTION:OPS-RUNBOOKS:BEGIN -->
## Runbooks (quick reference)
| Issue | Symptom | Action |
| --- | --- | --- |
| yt-dlp 403/429 | Health passes but `transcribe` fails with `DownloadError` | Run `yt-dlp -v URL`, add cookies (`--cookies-from-browser`), or download via a piped host (see `docs/DEPENDENCIES.md`). |
| Missing ffmpeg | Health `ffmpeg=false`, CLI raises `CalledProcessError` | Install the package, verify with `which ffmpeg`. |
| Ollama offline | Health `ollama=false`, agent replies “Insufficient evidence” | Start `ollama serve`, `ollama pull <model>`, confirm via `curl $OLLAMA_URL/api/tags`. |
| `INDEX_OUTBOX_PATH` write failure | Health `index_outbox=false`, CLI raises `ValueError: index-outbox entry missing ...` | Fix filesystem permissions or point env to a writable directory. |

## SLO / SLA
| Level | Target | Measurement |
| --- | --- | --- |
| Ingestion latency | < 5 s from CLI start to JSONL entry | Compare CLI start with `transcribe` / `agent.answer` spans. |
| Retrieval p95 | < 250 ms | `jq 'select(.node=="agent.answer") | .latency_ms'`. |
| ASR wall time | < 30 s for a 5-minute clip | `transcribe` span. |
| Health CLI | 100 % coverage before every release | Smoke step fails otherwise. |

## Incident handling (manual)
1. **Identify** – use `health` + `jq` to find the failing node.
2. **Stabilize** – set `LLM_PROVIDER=mock` or `STORE_BACKEND=memory` to keep working while debugging.
3. **Communicate** – add a short note to `docs/CHANGELOG.md` under “Unreleased incidents”.
4. **Restore** – restart Ollama/ffmpeg/CLI depending on the root cause. Restore `tmp/index-outbox.jsonl` from backup if corrupt.

## Backup / restore for index-outbox
- Default path is `tmp/index-outbox.jsonl`. Simple rotation:
  ```bash
  cp tmp/index-outbox.jsonl "tmp/index-outbox.$(date +%Y%m%d%H%M%S).jsonl"
  truncate -s 0 tmp/index-outbox.jsonl
  ```
- In CI, archive the file as an artifact when needed.
- Restore: copy the file back and rerun the indexer (future CLI) or inspect via `python -m json.tool`.
<!-- SECTION:OPS-RUNBOOKS:END -->
