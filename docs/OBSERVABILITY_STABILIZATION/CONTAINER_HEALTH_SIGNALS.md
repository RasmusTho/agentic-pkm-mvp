---
name: Container Health Signals
description: >
  Freshness-based worker/watcher healthchecks, an ollama healthcheck, and
  condition: service_healthy gating for db dependents.
task_id: OBSSTAB-02
source_anchor: "docker-compose.yaml :: worker/watcher/ollama services ; app/cli/health.py :: heartbeat staleness"
parent_capability: Observability Stabilization
prerequisites:
  - OBSSTAB-01
depends_on:
  - READINESS_REFLECTS_DEPENDENCIES.md
can_parallelize_with:
  - AUDIT_WRITER_STOPS_LYING
  - RUNTIME_VERSION_MARKER
---

# Container Health Signals

## Purpose

Make the worker/watcher container healthchecks detect staleness rather than mere
file presence, give the ollama service a container-level health signal, and order
startup so dependents wait for Postgres to accept connections before their first
query attempt.

## What This Task Does

Replaces the file-presence-only healthchecks at `docker-compose.yaml:120`
(`test -s "$${WORKER_HEARTBEAT_PATH}"`) and `:162`
(`test -s "$${WATCHER_HEARTBEAT_PATH}"`) with a freshness probe that reuses
`app/cli/health.py:436-460` — specifically `_watcher_runtime_status` and
`_worker_runtime_status`, which read the heartbeat JSON, compare the timestamp
against `WATCHER_HEARTBEAT_STALE_SECONDS` / `WORKER_HEARTBEAT_STALE_SECONDS`
(both default 60 s), and return `ok=False` when the process has stopped writing.
The probe must be callable as a small shell snippet or `python -c` invocation
that exits non-zero on stale.

Adds a `healthcheck` block to the ollama service (`docker-compose.yaml:16-24`,
currently none) hitting `http://localhost:11434/api/tags` and expecting HTTP 200.

Changes the `depends_on` entries for `api` (`:77-78`), `worker` (`:116-117`),
and `watcher` (`:158-159`) from plain service names to
`condition: service_healthy` against `db`, which already defines a real
`pg_isready` healthcheck (`:9-14`) that nothing currently consumes.

### Hardening follow-up (2026-07-11)

The freshness logic is unchanged, but the *probe delivery* was hardened after a
real resource leak on the test channel: the original `CMD-SHELL`
`python -c "... from app.cli.health import ..."` invocation cold-imported the
entire `app.cli` package (click/httpx/watchfiles + the ingest/LLM/DB stack)
every interval. Combined with containers that ran without an init/reaper and a
watcher `interval` (5 s) *below* its `timeout` (15 s), timed-out probes were
orphaned onto the non-reaping entrypoint PID 1 and accumulated unbounded — a
thundering-herd feedback loop that drove load into the hundreds while the
container reported `unhealthy` regardless of actual heartbeat freshness
(defeating the AC below).

The canonical status functions now live in the lean, stdlib-scale
`app/runtime/health_probe.py` (re-exported from `app/cli/health.py` for the
`/api/health` path and existing callers). The container healthcheck invokes
`python -m app.runtime.health_probe worker|watcher` via the **direct `CMD` exec
form** (no shell wrapper, so Docker's timeout kill targets the python process
itself), the worker/watcher services set **`init: true`** (tini reaps exited
probes and forwards signals), the probe arms a **`SIGALRM` self-timeout** so it
can never hang or accumulate independent of Docker, and both healthchecks keep
**`interval > timeout`**. Guarded by `tests/invariants/test_health_probe.py`.

## Concretely

```bash
# Simulate a stale worker heartbeat by writing an OLD `ts` into the heartbeat JSON.
# The reused probe (_worker_runtime_status) compares the JSON `ts` field against
# WORKER_HEARTBEAT_STALE_SECONDS — it does NOT read file mtime, so a `touch` would
# NOT register as stale (the heartbeat is rewritten with a fresh `ts` each cycle).
docker exec pkm-dev-worker-1 python - <<'PY'
import datetime, json, os
old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=120)
json.dump({"ts": old.isoformat()}, open(os.environ["WORKER_HEARTBEAT_PATH"], "w"))
PY

# After the next healthcheck interval (~20 s):
docker inspect --format '{{.State.Health.Status}}' pkm-dev-worker-1
# expected: unhealthy

# Ollama healthcheck exists and has fired:
docker inspect --format '{{.State.Health}}' pkm-dev-ollama-1
# expected: non-empty map (Status, FailingStreak, Log present)
```

## Why This Matters

A hung worker whose heartbeat file still exists on disk passes the Docker gate
indefinitely — the exact failure shape of the prior `processed_total=0` ingest
stall (risk **R4**). Without an ollama healthcheck, ollama-down is invisible at
the container orchestration layer. Without `condition: service_healthy` on db,
api/worker/watcher can start before Postgres accepts connections and fail with
transient connection errors rather than waiting (risk **R10**).

## Acceptance Criteria

- [ ] Worker container reports `unhealthy` when its heartbeat JSON `ts` is older
  than `WORKER_HEARTBEAT_STALE_SECONDS` (freshness is keyed on the JSON `ts` field,
  not file mtime — the test must backdate `ts`, not `touch` the file).
  - Verify: `tests/health/test_container_health_signals.py::test_worker_unhealthy_on_stale_heartbeat`
- [ ] Watcher container reports `unhealthy` on a stale heartbeat.
  - Verify: `tests/health/test_container_health_signals.py::test_watcher_unhealthy_on_stale_heartbeat`
- [ ] The ollama service defines a healthcheck block in `docker-compose.yaml`.
  - Verify: `tests/health/test_container_health_signals.py::test_ollama_has_healthcheck`
- [ ] `api`, `worker`, and `watcher` declare `depends_on: db: condition: service_healthy`.
  - Verify: `tests/health/test_container_health_signals.py::test_db_dependents_gate_on_service_healthy`

## How to Verify (Pre-Merge)

```bash
# Static parse tests (no running containers required):
pytest tests/health/test_container_health_signals.py -v

# Live smoke (optional, requires docker stack):
docker compose up -d
# backdate worker heartbeat as shown in Concretely, wait 30 s, then:
docker inspect --format '{{.State.Health.Status}}' pkm-dev-worker-1
```

## Out of Scope

- Readiness endpoint changes (OBSSTAB-01).
- Alerting or PagerDuty routing (OBSSTAB-04).
- A startup probe or pre-stop lifecycle hook.

## Related Docs

- `docker-compose.yaml` — worker `:119-123`, watcher `:161-165`, ollama `:16-24`, db healthcheck `:9-14`
- `app/cli/health.py` — `_worker_runtime_status` `:448-460`, `_watcher_runtime_status` `:436-446`
- `docs/HEALTH.md`

## Related GitHub Issues

This task is a child of the parent Observability Stabilization feature issue.
It must be serialized after OBSSTAB-01 because both tasks edit `docker-compose.yaml`
and concurrent edits to the same service blocks risk merge conflicts.
