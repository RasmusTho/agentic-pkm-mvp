State: Implemented — Issues #3891–#3897 delivered by merged PRs #3898, #3913, #3910, #3900, #3912, #3911, and #3902.
# Builder Ops Stability — Specification

Parent capability: harden the build → deploy → observe cycle so that failures are visible, CI is trustworthy, and production matches what CI tested.

## Original problem statement

An audit of the current builder ops surface found five load-bearing gaps:

1. **Observability is a skeleton.** Tracing is planned (otelcol.yaml, app/observability/tracing.py) but not wired — no Jaeger service, no OTel packages in requirements, tracing disabled by default. Prometheus scrapes only FastAPI; no worker/watcher/db metrics. No structured logging (stdlib only), no log aggregation, no alerting rules. 439 `except Exception` catches silently swallow errors.
2. **CI workflow duplication and dead gates.** `smoke.yml` and `ci-smoke.yaml` overlap with drift risk. `ci.yml`, `ci-lite.yml`, and `architecture-ci.yaml` are workflow_dispatch-only — OpenAPI validation, import-linter, k6 load, PG contract tests never run automatically.
3. **Python version mismatch.** Dockerfile uses 3.11-slim; CI uses 3.12; settings-ci uses 3.13. Production and CI diverge silently.
4. **Silent error swallowing.** `alembic upgrade head || true`, `mypy || true`, bare `except Exception: pass` in promotion queue, gates, tracing. Failures are invisible.
5. **Build hygiene.** No multi-stage Docker build, full repo copied into image, no pinned base image digest, no `.dockerignore` coverage.

## Delivered outcome

A builder working in this repo can trust that:
- CI catches what production will hit (same Python version, enforced gates).
- Failures are visible in logs and metrics, not swallowed.
- One canonical CI workflow runs on every PR with no dead-gate drift.
- The MVP observability stack is wired for structured logs, worker/API metrics, and alerting; distributed tracing remains outside this capability's scope.

## Delivery receipt

The bounded issue set is complete. CI workflow consolidation and PR-path gates shipped in #3891/#3892; Python and Docker build alignment shipped in #3893/#3896; silent-error visibility shipped in #3894; structured runtime logging shipped in #3895; and Prometheus scrape/alerting coverage shipped in #3897. The authoritative delivery evidence is the merged PR history and the focused validation recorded on each linked PR.

## Task breakdown

See sibling files for per-task specifications.

## Out of scope

- Full distributed tracing / APM SaaS integration
- Production deployment automation (separate capability)
- Test coverage thresholds (separate initiative)
- Pre-commit performance (pytest-in-hook removal is a nice-to-have, not blocking)
