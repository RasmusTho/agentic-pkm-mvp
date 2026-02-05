State: SoT v5.5 (operator checklist; safe-by-default; update alongside startup scripts and compose).
# Go-Live Checklist (P0)

Use this checklist to validate a deployment before enabling full ingest + panel actions. All steps are safe-by-default and should be run from the `work` branch.

## 1) Backups and prerequisites
- Back up the vault and DB outbox (snapshots or git tag).
- Confirm environment variables are set for the target environment (at minimum: `VAULT_ROOT`, `DATABASE_URL`/`DB_DSN`, provider credentials, tracing/observability endpoints if used).
- Ensure networked dependencies (LLM provider, database) are reachable from the host.

## 2) Dry-run health checks
- Run `python -m app.cli go-live-check` (defaults to dry-run) to verify vault root resolution, settings load, and watcher readiness.
- If you want to target a specific profile, pass explicit paths: `python -m app.cli go-live-check --vault-root <path> --settings-path <path> --outbox-path <file>`.
- Review the watcher summary; address any errors before proceeding.

## 3) Small-scope UAT
- Run a single registry watcher tick with panel auto-exec disabled:
  ```bash
  WATCHER_ENABLE=1 WATCHER_VAULT_PATH=<vault> WATCHER_AUTO_EXEC=0 python -m app.cli watcher run --max-ticks 1
  ```
- Inspect emitted messages and ensure classification/panel policies match expectations. (DB outbox is canonical; JSONL is audit only.)

## 4) Gradual rollout
- Start runtime with a conservative scope (`WATCHER_SCOPE_GLOB`) and `WATCHER_AUTO_EXEC=0` until you confirm the ingest path is clean.
- Enable `WATCHER_AUTO_EXEC=1` only after observing clean runs (no errors, no limit-exceeded).

## 5) Rollback posture
- If ingest produces incorrect outputs, pause watcher runs and restore from the vault/DB backups.
- Re-run `go-live-check` after any rollback to ensure settings and paths are still valid.

## 6) Post-go-live hygiene
- Keep `LLM_TRACE_ENABLE=1` only when troubleshooting; traces are now hashed (no raw prompts/responses).
- Document any environment-specific overrides in the settings surface (vault `<vault>/_system/settings/system-settings.yaml`).

## HTTP endpoints

All FastAPI routes listen on `http://127.0.0.1:18000` (docker compose maps host `18000` → container `8000`). Operators should expect:

- `GET /healthz` – liveness probe returning plain `ok`. Example: `curl -sS http://127.0.0.1:18000/healthz`.
- `GET /readyz` – readiness probe gated by migrations and startup checks. Example: `curl -sS http://127.0.0.1:18000/readyz`.
- `GET /api/health` – structured health contract with watcher/worker/db/LLM statuses. Example: `curl -sS http://127.0.0.1:18000/api/health`.
- `GET /api/status` – status/SOT payload that drives dashboards. Example: `curl -sS http://127.0.0.1:18000/api/status`.
- `GET /search?q=...&k=...` – realtime hybrid search. Example: `curl -sS "http://127.0.0.1:18000/search?q=warm%20content&k=3"`.
- `POST /api/ask` – question endpoint returning answer + sources. Example: `curl -sS http://127.0.0.1:18000/api/ask -H "Content-Type: application/json" -d '{"question":"warm content"}'`.

There is no `/health` route in the Reality-MVP API; use `/healthz` for simple liveness and `/api/health` for the full contract. Swagger UI lives at `http://127.0.0.1:18000/docs` and the OpenAPI document is the source of truth (`/openapi.json`). If you are unsure which paths exist, run `curl -sS http://127.0.0.1:18000/openapi.json | python -c 'import sys,json; j=json.load(sys.stdin); print("\n".join(sorted(j["paths"].keys())))'`.

Note: `/api/health` may report `ok=false` when optional tools (for example, `ffmpeg`) are missing. Treat this as a degraded feature signal, not a full system outage, if `/healthz`, `/readyz`, search, and ask are healthy.

## CLI sanity (store stats)

- Memory mode: `STORE_BACKEND=memory python -m app.cli store stats --json`
- PG mode: `STORE_BACKEND=pg DATABASE_URL=postgresql://app:app@127.0.0.1:15432/app python -m app.cli store stats --json`
- Compose exec: `docker compose exec -T api sh -lc 'python -m app.cli store stats --json'`


## First index / bootstrap ingest

Use `scripts/start_full_system.sh` to bring the full stack up, check that `/app/vault` is mounted inside the api container, and perform the deterministic baseline ingest when the store is empty. Watchers run incrementally and do not sweep the whole vault, so this script explicitly drives the first job, runs the bootstrap `vault-alpha-ingest`, and verifies `/search` plus `/api/ask` before handing off to the live watcher. Re-run it only when you need a fresh baseline, then rely on watcher/worker increments for day-to-day updates.

## Stage 0 (Ollama embeddings: current default)
In the v5.5 baseline, embeddings default to Ollama via `app/llm/embeddings.py`:
- Primary endpoint: `${OLLAMA_URL}/api/embeddings`
- Fallback: `${OLLAMA_URL}/v1/embeddings` (OpenAI-compatible)

Recommended environment for local go-live:
- `LLM_PROVIDER=ollama`
- `OLLAMA_URL=http://host.docker.internal:11434` (inside Docker) or `http://127.0.0.1:11434` (host)
- `OLLAMA_EMBED_MODEL=nomic-embed-text:latest`
- `EMBED_DIM=1536` (or your configured dimension; must match provider output)

Note: eval tooling uses `OPENAI_BASE_URL` for OpenAI-compatible probes (DeepEval/Ragas), but the runtime embedding helper does not require that variable.
