# Go-Live Checklist (P0)
State: draft

Use this checklist to validate a deployment before enabling full ingest + panel actions. All steps are safe-by-default and should be run from the `work` branch.

## 1) Backups and prerequisites
- Back up the vault and outbox location (snapshots or git tag).
- Confirm environment variables are set for the target environment (at minimum: `VAULT_ROOT`, `INDEX_OUTBOX_PATH`, provider credentials, tracing/observability endpoints if used).
- Ensure networked dependencies (LLM provider, database) are reachable from the host.

## 2) Dry-run health checks
- Run `python -m app.cli go-live-check` (defaults to dry-run) to verify vault root resolution, settings load, and watcher readiness.
- If you want to target a specific profile, pass explicit paths: `python -m app.cli go-live-check --vault-root <path> --settings-path <path> --outbox-path <file>`.
- Review the watcher summary; address any errors before proceeding.

## 3) Small-scope UAT
- Run `python -m app.cli vault-watcher-run --dry-run --max-notes 10` to sample a small set of changes.
- Inspect emitted messages and ensure classification/panel policies match expectations.

## 4) Gradual rollout
- Start runtime with a low `max-notes` and `--force` disabled to prevent bulk ingestion surprises.
- Increase scope incrementally only after observing clean runs (no errors, no limit-exceeded).

## 5) Rollback posture
- If ingest produces incorrect outputs, pause watcher runs and restore from the vault/outbox backups.
- Re-run `go-live-check` after any rollback to ensure settings and paths are still valid.

## 6) Post-go-live hygiene
- Keep `LLM_TRACE_ENABLE=1` only when troubleshooting; traces are now hashed (no raw prompts/responses).
- Document any environment-specific overrides in the settings surface (vault `_system/settings/system-settings.yaml`).

## HTTP endpoints

All FastAPI routes listen on `http://127.0.0.1:18000` (docker compose maps host `18000` → container `8000`). Operators should expect:

- `GET /healthz` – liveness probe returning plain `ok`. Example: `curl -sS http://127.0.0.1:18000/healthz`.
- `GET /readyz` – readiness probe gated by migrations and startup checks. Example: `curl -sS http://127.0.0.1:18000/readyz`.
- `GET /api/health` – structured health contract with watcher/worker/db/LLM statuses. Example: `curl -sS http://127.0.0.1:18000/api/health`.
- `GET /api/status` – status/SOT payload that drives dashboards. Example: `curl -sS http://127.0.0.1:18000/api/status`.
- `GET /search?q=...&k=...` – realtime hybrid search. Example: `curl -sS "http://127.0.0.1:18000/search?q=warm%20content&k=3"`.
- `POST /api/ask` – question endpoint returning answer + sources. Example: `curl -sS http://127.0.0.1:18000/api/ask -H "Content-Type: application/json" -d '{"question":"warm content"}'`.

There is no `/health` route in the Reality-MVP API; use `/healthz` for simple liveness and `/api/health` for the full contract. Swagger UI lives at `http://127.0.0.1:18000/docs` and the OpenAPI document is the source of truth (`/openapi.json`). If you are unsure which paths exist, run `curl -sS http://127.0.0.1:18000/openapi.json | python -c 'import sys,json; j=json.load(sys.stdin); print(\"\\n\".join(sorted(j[\"paths\"].keys())))'`.

## Stage 0 (Ollama OpenAI-compatible embeddings)
During Stage 0 we run the worker against the Ollama OpenAI-compatible `/v1/embeddings` path.  Add a `docker-compose.override.yml` that overrides the worker's environment so every embedding request is routed through the OpenAI-style client:
- `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`
- `OPENAI_API_KEY=sk-local`
- `EMBED_MODEL=nomic-embed-text:latest`
- `EMBED_DIM=768`
- `EMBED_NORMALIZE=1`
This keeps `OLLAMA_HOST` available for chat while ensuring the embeddings helper targets `/v1/embeddings` via the OpenAI-compatible interface.
