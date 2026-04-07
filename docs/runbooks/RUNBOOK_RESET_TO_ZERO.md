State: Aligned (forward line v5.x)

# Reset to Zero Runbook

Use this procedure when you need to fully wipe runtime artifacts and restart the Reality-MVP stack from a deterministic state.

## 1. Stop the stack cleanly
```
docker compose down -v --remove-orphans
```
This stops every service and removes the docker volumes so state is not reused across runs.

## 2. Clear filesystem artifacts
```
scripts/reset_to_zero.sh
```
The script stops the stack (same as step 1), lists the runtime files it will delete, and removes:
- `tmp/index-outbox.jsonl` (append-only audit log for ingest/panel events)
- Heartbeat files: `tmp/worker_heartbeat.json`, `tmp/watcher_heartbeat.json`, plus watcher state files under `tmp/watcher_state*.json` and `tmp/watcher_states`
- `tmp/WATCHER_STOP`, so a fresh startup does not inherit a stale paused-watcher state from the previous run
- `tmp/health_incidents.jsonl`

It prompts for confirmation unless you run `RESET_FORCE=1 scripts/reset_to_zero.sh`.

> **Note:** The JSONL log at `INDEX_OUTBOX_PATH` is an audit trail. Runtime processing is driven by the DB outbox. Clearing `INDEX_OUTBOX_PATH` only affects audit/diagnostics, while `docker compose down -v` wipes the DB queue.

## 3. Start the stack deterministically
Before bringing the stack up, pick the desired LLM provider and embed configuration so the guardrail in `app.config.llm` can assert explicit intent.
```
export LLM_PROVIDER=<ollama|mock|openai>
export EMBED_MODEL=nomic-embed-text:latest
export EMBED_DIM=1536
docker compose up -d --build db api worker watcher
```

The docker services expose `LLM_PROVIDER_ENFORCE=1`, so `app.config.llm` raises if `LLM_PROVIDER` is unset. Export your chosen provider before running `docker compose up`.
If you point at a live Ollama daemon, make sure `OLLAMA_HOST`/`OLLAMA_URL` is set (the docker health checks use `OLLAMA_URL`). When you run `scripts/start_full_system.sh`, it will respect the same environment.

## 4. Verify the stack
- Confirm containers are healthy: `docker compose ps`
- Check health status: `python -m app.cli health status --json`
- Tail the worker log (`docker compose logs --tail=50 worker` or `tail tmp/watchdog.log`)
- Inspect the outbox audit tail: `tail -n 20 tmp/index-outbox.jsonl`
- Use `python -m app.cli status --json` or `python -m app.cli events-doctor --path $INDEX_OUTBOX_PATH` to understand recent events

## 5. Mini E2E smoke
1. Create a tiny runtime note under your vault:
   ```bash
   NOTE=file://$(pwd)/tmp/reset-note.md
   cat <<'NOTE' > "$NOTE"
   ---
   uuid: reset-to-zero
   ---
   # reset-to-zero
   This is a confirmation note for the alpha smoke.
   NOTE
   ```
2. Run the pipe stage to normalize/classify and append a line to the `INDEX_OUTBOX_PATH` audit log:
   ```bash
   python -m app.cli pipe "$NOTE"
   ```
3. Wait for the worker to process the corresponding DB outbox row (check `docker compose logs --tail=20 worker`).
4. Verify the event recorded in the audit log: `tail -n 5 tmp/index-outbox.jsonl` should show your event with the new timestamp.
4.1. Confirm the DB outbox row (the table uses `delivered_at`, not `processed_at`).
   ```bash
   docker compose exec -T db sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select topic, created_at, delivered_at from outbox order by created_at desc limit 5;"'
   ```
   Expect an `ingest.object.created` row with a recent `created_at`.
5. Optionally query the API with `curl -sS http://127.0.0.1:18000/api/status` or an `/api/ask` prompt to ensure the embeddings/index bank the event.

This runbook alongside `scripts/reset_to_zero.sh` and the `make` helpers (`reset-zero`, `reset-zero-force`, `alpha-e2e-smoke`) provides a repeatable reset workflow without leaking old health/state breadcrumbs.
