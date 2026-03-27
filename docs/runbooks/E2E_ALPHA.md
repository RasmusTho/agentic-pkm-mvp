State: SoT v5.x forward line.
# Alpha E2E Contract

## Purpose
This document defines the end-to-end runtime contract for Alpha: the watcher detects a vault change, the DB outbox records the intent, the worker consumes it, and status/health expose the outcome. It also documents where the E2E note is written and how cleanup behaves.

## Preconditions
- `VAULT_ROOT` points at the live vault.
- Optional path overrides (no repo defaults):
  - `VAULT_INBOX_DIR_REL` (if unset, resolved from `vault.layout.md`)
  - `VAULT_SYSTEM_DIR_REL` (if unset, resolved from `vault.layout.md` or system settings)
  - `VAULT_RUNTIME_DIR_REL` (if unset, resolved from system settings)

## Canonical Flow
Run these in order:

```bash
export VAULT_ROOT="/path/to/vault"
make alpha-up
python -m scripts.alpha_e2e
make alpha-smoke
```

For a full image + index rebuild before startup:

```bash
export VAULT_ROOT="/path/to/vault"
ALPHA_REBUILD=1 AUTO_BOOTSTRAP=1 make alpha-up
```

## E2E Note Location
- alpha_e2e writes a temporary note under `${VAULT_ROOT}/${VAULT_INBOX_DIR_REL}/_alpha_e2e` so it is always in watcher scope.
- The note UUID is a real `uuid4().hex` value.
- On success, the note is deleted.
- On failure, the note is retained unless `--teardown` is used.

## Embeddings Entry Point
Runtime embeddings and retrieval must go through `app.components.retrieval` (embed_query/embed_docs/search). This entrypoint returns the embedding identity so the vector index stays aligned and avoids legacy fallback providers.

## Auto-Heal (Index Rebuild)
- `AUTO_BOOTSTRAP=1` runs a deterministic preflight (`settings validate`) and checks `/api/health`; if `index_rebuild` is required in pg-mode, it will run the rebuild once and print `INDEX REBUILD: ran`.
- When `AUTO_BOOTSTRAP=1` is set, alpha_e2e expects the rebuild to have happened; if `index_rebuild` is still required, it fails with the command hint.
- Without `AUTO_BOOTSTRAP=1`, alpha_e2e will attempt the rebuild once if `/api/health` reports a required `index_rebuild`.
- Volumes persist between runs; use `docker compose down -v` to reset the DB fully.

## Queue Semantics (Status)
- In pg-mode, the DB outbox is the canonical queue; the JSONL events_log is audit-only.
- `events_log` is an append-only audit log.
- `worker_queue` is the active queue (db or file).
- When `worker_queue.mode=db`, do not infer pending from `events_log`.
- When `worker_queue.mode=file`, `pending` should match `max(events_log.total_lines - processed_total, 0)`.

## Debug Recipe
alpha_e2e prints a debug dump on failure:
- `/api/status` and `/api/health`
- `docker compose ps`
- `docker compose logs --tail=200 watcher`
- `docker compose logs --tail=200 worker`
- `docker compose logs --tail=200 api`

## Report Artifact
- `scripts.alpha_e2e` writes `tmp/alpha_e2e_report.json`.
- Treat that file as the DB-backed release/UAT artifact for the canonical runtime path.
- The report includes shared contract checks (`status_invariants_ok`, `worker_queue_mode_db`, `runtime_progress_ok`) plus any failure reasons.

You can also run these manually:

```bash
curl -sS http://127.0.0.1:18000/api/status
curl -sS http://127.0.0.1:18000/api/health
docker compose ps
docker compose logs --tail=200 watcher
docker compose logs --tail=200 worker
docker compose logs --tail=200 api
```

## Cleanup
To ensure the stack is torn down after E2E checks:

```bash
python -m scripts.alpha_e2e --teardown
```
