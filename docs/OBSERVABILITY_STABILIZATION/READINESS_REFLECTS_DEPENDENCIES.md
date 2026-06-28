---
name: Readiness Reflects Dependencies
description: >
  Fold a live DB ping into HealthContract.evaluate() so /readyz flips on a
  Postgres outage, and repoint the container healthcheck from unconditional
  /healthz to /readyz. (Active-LLM reachability as a readiness gate is deferred
  to #2621 — Postgres is the hard readiness dependency for Fas 0.)
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
healthcheck stop reporting healthy during a Postgres outage. The existing
outbox-age state machine stays intact; this task adds a dependency layer that
short-circuits to a non-ready state when Postgres is unreachable.

Active-LLM reachability as a *readiness gate* is deliberately out of this slice
(deferred to #2621): for a vault-first PKM, reads/browsing/capture do not need
the LLM, so 503-ing the whole API on an LLM hiccup is too aggressive for Fas 0.
LLM-down stays visible to the operator through the `HEALTH_ERGONOMICS.md` **Minne**
group (ASK latency/error), it just does not flip `/readyz`.

## What This Task Does

Call `ping_postgres()` (`app/db/dsn.py:33-46` — real `SELECT 1`, bounded
`connect_timeout=1.0` s) inside `HealthContract.evaluate()`
(`app/health_contract.py:197-291`). When the ping fails and `STORE_BACKEND=pg`,
force state to **`unhealthy`** regardless of outbox age, so the caller sees a
non-ready result.

> **Do not use `degraded` here.** `READY_STATES` in
> `app/api/routes/health_contract.py:17` is `{"running", "catch_up", "degraded"}`
> — `degraded` is a *ready* state, so forcing `degraded` would leave `/readyz`
> returning `200` during a DB outage (the false-green this slice exists to kill).
> `unhealthy` (and `safe_mode`) are in `WRITE_BLOCKED_STATES` and **not** in
> `READY_STATES`, so they correctly flip `/readyz` to 503. The AC test
> `test_readyz_flips_red_when_db_down` asserts the 503.

Repoint the container healthcheck from `/healthz` to `/readyz`. The base
healthcheck command at `docker-compose.yaml:80-84` reads `API_HEALTHCHECK_URL`
at runtime, but **the URL is defined in three independent places** and all must
move to `/readyz` for the prod/dev/test AC to hold:

- `config/runtime.defaults.env:30` — `API_HEALTHCHECK_URL=...:8000/healthz` (the
  default dev/base value)
- `docker-compose.test.yml:16` — overrides with `...:18002/healthz`
- `docker-compose.prod.yml:7` — overrides with `...:18000/healthz`

Editing only `docker-compose.prod.yml` would leave dev/test container
healthchecks on the unconditional liveness endpoint; update all three.

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
# all three URL sources must show /readyz
grep -n API_HEALTHCHECK_URL config/runtime.defaults.env docker-compose.test.yml docker-compose.prod.yml
```

## Out of Scope

- Alerting and metrics (OBSSTAB-04).
- A dedicated startup probe.
- **Active-LLM reachability as a readiness gate — deferred to #2621.** Postgres is
  the only hard readiness dependency in this slice. LLM-down stays observable via
  the Minne group, not via `/readyz`. Gemini-fallback reachability is likewise out
  of scope.
- Worker, watcher, and Ollama container probes (OBSSTAB-02).

## Related Docs

- `docs/HEALTH.md` — health contract snapshot section
- `app/health_contract.py` — `HealthContract.evaluate()` (lines 197-291)
- `app/api/routes/health_contract.py` — `/healthz` (lines 12-14), `/readyz` (lines 20-36)
- `app/db/dsn.py` — `ping_postgres()` (lines 33-46)
- `config/runtime.defaults.env` — `API_HEALTHCHECK_URL` (line 30, dev/base default)
- `docker-compose.test.yml` — `API_HEALTHCHECK_URL` (line 16)
- `docker-compose.prod.yml` — `API_HEALTHCHECK_URL` (line 7)
- `docker-compose.yaml` — healthcheck command (lines 80-84)

## Related GitHub Issues

This is a child of the Observability Stabilization parent feature issue.
Serialized with OBSSTAB-02 (both touch `docker-compose.yaml`); prerequisite
for OBSSTAB-04 (alerting depends on /readyz being truthful).
