State: SoT v5.x forward line.
# Alpha E2E Contract

## Purpose
This document defines the end-to-end runtime contract for Alpha: the watcher detects a vault change, the DB outbox records the intent, the worker consumes it, and status/health expose the outcome. It also documents where the E2E note is written and how cleanup behaves.

## Preconditions
- `VAULT_ROOT` points at the live vault.
- Optional path overrides:
  - `VAULT_INBOX_DIR_REL` (default: `Inbox`)
  - `VAULT_RUNTIME_DIR_REL` (default: `System/Runtime`)
  - `VAULT_SYSTEM_DIR_REL` (default: `System`)

## Canonical Flow
Run these in order:

```bash
export VAULT_ROOT="/path/to/vault"
make alpha-up
python -m scripts.alpha_e2e
make alpha-smoke
```

## E2E Note Location
- alpha_e2e writes a temporary note under `${VAULT_ROOT}/${VAULT_INBOX_DIR_REL}/_alpha_e2e` so it is always in watcher scope.
- The note UUID is a real `uuid4().hex` value.
- On success, the note is deleted.
- On failure, the note is retained unless `--teardown` is used.

## Queue Semantics (Status)
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
