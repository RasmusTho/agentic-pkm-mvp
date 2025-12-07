State: SoT v4.10 Reality-MVP (current).
# Operations Playbook

Reality-MVP ops target local development and single-user runs. Production hardening (HA, backups, rate-limits) is out of scope for v4.10.

## Runtime stack (Reality-MVP)
- Local dev: `uvicorn app.main:app --reload --port 18000` (defaults `STORE_BACKEND=memory`, `LLM_PROVIDER=mock`).
- Docker Compose (`docker-compose.yaml`): starts Postgres (`db`), FastAPI (`api` → `app.main:app`), and a worker (`app.workers.outbox_worker`). Ports: Postgres `15432`, API `18000→8000`. Ensure `pgvector` is available in the db image (default `pgvector/pgvector:pg16`).
- Alembic: `scripts/start_api.sh` runs `alembic -c app/alembic.ini upgrade head` before launching the API. The worker uses the configured `STORE_BACKEND` and reads from the same database.
- Metrics: expose `/metrics` when `METRICS_ENABLED=1` (see `docs/OBSERVABILITY_STACK.md` for Prometheus/Grafana).

## Data/storage
- Primary stores: Postgres (object + vector tables via `STORE_BACKEND=pg`) or in-memory for smoke/tests. `INDEX_OUTBOX_PATH` defaults to `tmp/index-outbox.jsonl` for event/audit sinks.
- DuckDB/provenance files (`storage/agent.duckdb`, `provenance.jsonl`) are only used by legacy health checks; not required for the Reality-MVP pipeline.
- Back up Postgres volumes if you care about persisted objects/vectors; wiping the volume (`docker compose down -v`) clears all data.

## Common workflows
- **Health**: `python -m app.cli health --json` (checks ffmpeg, yt-dlp, Ollama when enabled, outbox path).
- **Ingest vault notes**: `python -m app.cli vault-alpha-ingest --max-notes 200 [--force]` (safe/idempotent ingest with UUID healing + mirror writes). For a quick non-recursive scan: `python -m app.cli ingest-vault-root --limit 10`.
- **ASK**: `python -m app.cli ask "Question"` (runs planner/orchestrator flow; mock LLM by default) or HTTP `POST /api/ask`.
- **Status**: `GET /api/status` (store counts, ingest/ASK metrics window).

## Runbooks (quick reference)
| Issue | Symptom | Action |
| --- | --- | --- |
| Ollama offline | Health `ollama=false`, LLM calls fail | Start `ollama serve`, pull the model (e.g., `ollama pull llama3.1:8b`). |
| Missing ffmpeg | Health `ffmpeg=false`, `transcribe` fails | Install ffmpeg; rerun health. |
| yt-dlp 403/429 | `transcribe` download errors | Retry with `yt-dlp -v URL`, add `--cookies-from-browser` if needed. |
| Outbox unwritable | Health `index_outbox=false` | Point `INDEX_OUTBOX_PATH` to a writable file/dir. |

## Targets (observational, not enforced)
- Retrieval p95 < 250 ms (tracked by fitness report QAS-003 in CI).
- Ingest→index propagation within ~2 s (fitness report QAS-010 in CI).
- ASR/transcribe < 30 s for a 5-minute clip (ffmpeg + mock ASR by default).

## Notes on legacy tools
- `scripts/start_agent_service.py` and `run_agent.py` remain for legacy agent loops; Reality-MVP uses the FastAPI + worker stack described above.
- `scripts/rotate_storage.py` only matters if you opt into DuckDB/provenance logging; otherwise ignore.
