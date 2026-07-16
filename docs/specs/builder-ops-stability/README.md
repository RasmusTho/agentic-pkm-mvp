State: Not yet implemented
# Builder Ops Stability — Specification

Parent capability: harden the build → deploy → observe cycle so that failures are visible, CI is trustworthy, and production matches what CI tested.

## Problem statement

An audit of the current builder ops surface found five load-bearing gaps:

1. **Observability is a skeleton.** Tracing is planned (otelcol.yaml, app/observability/tracing.py) but not wired — no Jaeger service, no OTel packages in requirements, tracing disabled by default. Prometheus scrapes only FastAPI; no worker/watcher/db metrics. No structured logging (stdlib only), no log aggregation, no alerting rules. 439 `except Exception` catches silently swallow errors.
2. **CI workflow duplication and dead gates.** `smoke.yml` and `ci-smoke.yaml` overlap with drift risk. `ci.yml`, `ci-lite.yml`, and `architecture-ci.yaml` are workflow_dispatch-only — OpenAPI validation, import-linter, k6 load, PG contract tests never run automatically.
3. **Python version mismatch.** Dockerfile uses 3.11-slim; CI uses 3.12; settings-ci uses 3.13. Production and CI diverge silently.
4. **Silent error swallowing.** `alembic upgrade head || true`, `mypy || true`, bare `except Exception: pass` in promotion queue, gates, tracing. Failures are invisible.
5. **Build hygiene.** No multi-stage Docker build, full repo copied into image, no pinned base image digest, no `.dockerignore` coverage.

## Target outcome

A builder working in this repo can trust that:
- CI catches what production will hit (same Python version, enforced gates).
- Failures are visible in logs and metrics, not swallowed.
- One canonical CI workflow runs on every PR with no dead-gate drift.
- The observability stack is wired end-to-end for the MVP runtime (structured logs → aggregation, metrics → alerting, traces optional but functional).

## Task breakdown

See sibling files for per-task specifications.

## Out of scope

- Full distributed tracing / APM SaaS integration
- Production deployment automation (separate capability)
- Test coverage thresholds (separate initiative)
- Pre-commit performance (pytest-in-hook removal is a nice-to-have, not blocking)
