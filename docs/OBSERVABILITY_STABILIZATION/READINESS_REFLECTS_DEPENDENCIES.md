---
name: Readiness Reflects Dependencies
description: >
  Fold a live DB ping (+active-LLM reachability) into HealthContract.evaluate() so
  /readyz flips on dependency-down, and repoint the container healthcheck from
  unconditional /healthz to /readyz.
task_id: OBSSTAB-01
source_anchor: "app/health_contract.py :: HealthContract.evaluate ; docs/HEALTH.md :: Health contract snapshot"
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - AUDIT_WRITER_STOPS_LYING
  - RUNTIME_VERSION_MARKER
  - DEV_DB_SNAPSHOT_RESTORE
---

# Readiness Reflects Dependencies

## Purpose

Make readiness reflect real dependency health so `/readyz` and the container
healthcheck stop reporting healthy during a Postgres or active-LLM outage.
The existing outbox-age state machine stays intact; this task adds a dependency
layer that short-circuits to a non-ready state when a required dependency is
unreachable.

## What This Task Does

Call `ping_postgres()` (`app/db/dsn.py:33-46` — real `SELECT 1`, bounded
`connect_timeout=1.0` s) inside `HealthContract.evaluate()`
(`app/health_contract.py:197-291`). When the ping fails and `STORE_BACKEND=pg`,
force state to `degraded` (or `unhealthy`) regardless of outbox age, so the
caller sees a non-ready result.

Repoint `API_HEALTHCHECK_URL` in `docker-compose.prod.yml:7` from `/healthz`
to `/readyz`. The base healthcheck command at `docker-compose.yaml:80-84`
reads `API_HEALTHCHECK_URL` at runtime, so the URL change cascades to
dev/test stacks automatically; no inline `test:` edit is needed in the base
file.

Keep `/healthz` (`app/api/routes/health_contract.py:12-14`) as an
unconditional `{"ok": true}` liveness probe — no changes to that handler.

## Concretely

With the prod stack running:

```bash
# Stop the DB and wait one healthcheck interval (10s)
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod stop db
sleep 12

# Container should now be unhealthy
docker ps --filter name=pkm-prod-api-1 --format '{{.Status}}'
# expected: Up ... (unhealthy)

# /readyz must 503
curl -s -o /dev/null -w '%{http_code}' localhost:18000/readyz
# expected: 503

# /healthz must still 200 (liveness unchanged)
curl -s localhost:18000/healthz
# expected: {"ok":true}
```

## Why This Matters

Every always-on signal currently over-reports: a DB-down prod stack appears
perfectly healthy between manual `make verify-runtime` runs (risks R1 + R5).
This is the central health-correctness gap.

Repointing the probe URL alone is insufficient — `/readyz` itself is a
false-green because it keys only on outbox age (`READY_STATES` check in
`app/api/routes/health_contract.py:17-31`). The DB ping **must** live inside
`evaluate()`, not only in the probe URL swap.

## Acceptance Criteria

- [ ] `/readyz` returns 503 when Postgres is unreachable.
  - Verify: `tests/health/test_readiness_dependency_aware.py::test_readyz_flips_red_when_db_down`
- [ ] The prod/dev/test container healthcheck targets `/readyz`, not unconditional `/healthz`.
  - Verify: `tests/health/test_readiness_dependency_aware.py::test_container_healthcheck_targets_readyz`
- [ ] `evaluate()` performs a live DB ping with a bounded (<=1 s) timeout and the probe never hangs.
  - Verify: `tests/health/test_readiness_dependency_aware.py::test_evaluate_db_ping_bounded_timeout`
- [ ] `/healthz` remains an unconditional liveness probe (returns 200 regardless of DB state).
  - Verify: `tests/health/test_readiness_dependency_aware.py::test_healthz_still_liveness_only`

## How to Verify (Pre-Merge)

```bash
# Unit + integration (no pg required — mock ping_postgres)
python -m pytest tests/health/test_readiness_dependency_aware.py -v

# Full not-pg suite (must stay green)
python -m pytest -m "not pg" --timeout 120 -q

# Compose smoke (requires local docker)
docker compose -f docker-compose.yaml -f docker-compose.prod.yml -p pkm-prod up -d
grep API_HEALTHCHECK_URL docker-compose.prod.yml  # must show /readyz
```

## Out of Scope

- Alerting and metrics (OBSSTAB-04).
- A dedicated startup probe.
- Gemini-fallback reachability beyond the active LLM provider.
- Worker, watcher, and Ollama container probes (OBSSTAB-02).

## Related Docs

- `docs/HEALTH.md` — health contract snapshot section
- `app/health_contract.py` — `HealthContract.evaluate()` (lines 197-291)
- `app/api/routes/health_contract.py` — `/healthz` (lines 12-14), `/readyz` (lines 20-36)
- `app/db/dsn.py` — `ping_postgres()` (lines 33-46)
- `docker-compose.prod.yml` — `API_HEALTHCHECK_URL` (line 7)
- `docker-compose.yaml` — healthcheck command (lines 80-84)

## Related GitHub Issues

This is a child of the Observability Stabilization parent feature issue.
Serialized with OBSSTAB-02 (both touch `docker-compose.yaml`); prerequisite
for OBSSTAB-04 (alerting depends on /readyz being truthful).
