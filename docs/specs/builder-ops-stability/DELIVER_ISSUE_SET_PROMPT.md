State: Prompt artifact — input for the `docs-to-issue` conversion of the sibling README's capability spec. Not a spec itself; `README.md` owns the builder-ops-stability specification.

# Deliver Issue Set: Builder Ops Stability

Use this prompt with the `docs-to-issue` skill to create the issue set for the builder-ops-stability capability.

---

## Prompt

Create GitHub issues from the builder-ops-stability specification at `docs/specs/builder-ops-stability/README.md`. The target outcome is a trustworthy build → observe cycle where failures are visible and CI matches production.

Create the following bounded issues. For each, follow the `docs-to-issue` contract shape exactly (Context, Scope, Source Anchors, Constraints, Acceptance Criteria with Verify targets, Out of Scope, Suggested Validation, Source Docs).

### Issue 1 — Consolidate CI smoke workflows

**Type:** `type:refactor` · `prio:high` · `agent:ready`

Merge `smoke.yml` into `ci-smoke.yaml` so there is exactly one PR-triggered smoke workflow. Promote the useful bits from `smoke.yml` (pip caching) into the surviving workflow. Delete `smoke.yml`. Verify no branch-protection references break.

Source anchor: `docs/specs/builder-ops-stability/README.md :: ci-duplication`

AC:
- [ ] Only `ci-smoke.yaml` exists as the PR smoke gate. Verify: `ls .github/workflows/smoke.yml` returns "No such file"
- [ ] pip caching enabled in ci-smoke.yaml. Verify: `grep 'cache:' .github/workflows/ci-smoke.yaml`
- [ ] No other workflow references `smoke.yml`. Verify: `grep -r smoke.yml .github/workflows/`

### Issue 2 — Activate dead CI gates on PR path

**Type:** `type:refactor` · `prio:high` · `agent:ready`

Move the valuable gates from `ci.yml`, `ci-lite.yml`, and `architecture-ci.yaml` (import-linter, OpenAPI/AsyncAPI validation, YAML/JSON lint) into the PR-triggered `ci-smoke.yaml` as conditional jobs gated by `dorny/paths-filter`. Keep k6 and PG contract tests as nightly-only in `integration-nightly.yaml`. Remove or archive the now-empty workflow_dispatch files.

Source anchor: `docs/specs/builder-ops-stability/README.md :: dead-gates`

AC:
- [ ] import-linter runs on PRs touching `app/`. Verify: `grep import-linter .github/workflows/ci-smoke.yaml`
- [ ] OpenAPI validation runs on PRs touching `app/api/` or `openapi.*`. Verify: grep in ci-smoke.yaml
- [ ] `ci.yml` and `ci-lite.yml` are removed or clearly archived. Verify: ls check
- [ ] k6 load test remains in `integration-nightly.yaml`. Verify: grep in integration-nightly.yaml

### Issue 3 — Align Python version: Dockerfile ↔ CI

**Type:** `type:bug` · `prio:high` · `agent:ready`

Pin `Dockerfile` base image to `python:3.12-slim` (matching CI). Pin the digest for reproducibility. Update `.python-version` if it exists. Ensure `settings-ci.yaml` canary (3.13) is explicitly labeled as experimental, not the default.

Source anchor: `docs/specs/builder-ops-stability/README.md :: python-mismatch`

AC:
- [ ] Dockerfile FROM line uses `python:3.12-slim@sha256:...`. Verify: `head -5 Dockerfile`
- [ ] CI smoke and Dockerfile use the same minor version. Verify: diff grep
- [ ] Docker image builds successfully. Verify: `docker build -t test-build .`

### Issue 4 — Eliminate silent error swallowing in CI and build

**Type:** `type:bug` · `prio:high` · `agent:ready`

Remove `|| true` from `alembic upgrade head` in CI workflows — let migration failures fail the build. Remove `|| true` from `mypy` in Makefile — if mypy is configured, enforce it or remove the target. Audit the top-20 most critical `except Exception: pass` blocks (promotion queue, gates, health contract, tracing) and add logging.

Source anchor: `docs/specs/builder-ops-stability/README.md :: silent-swallowing`

AC:
- [ ] No `|| true` after `alembic upgrade head` in any workflow. Verify: `grep -r 'alembic.*|| true' .github/workflows/`
- [ ] `make lint` mypy step either enforces or is removed. Verify: `grep mypy Makefile`
- [ ] `app/promotion/queue.py` bare except blocks log the exception. Verify: `grep -A2 'except Exception' app/promotion/queue.py`
- [ ] `app/promotion/gates.py` bare except blocks log the exception. Verify: same pattern

### Issue 5 — Wire structured logging for runtime services

**Type:** `type:task` · `prio:med` · `agent:ready`

Add `structlog` (or extend `app/obs/log.py` JSON span logger) as the default log formatter for API, worker, and watcher processes. Ensure correlation via `trace_id`. Keep stdlib logger names but route through JSON formatter. This makes logs parseable by any aggregator without requiring an external stack yet.

Source anchor: `docs/specs/builder-ops-stability/README.md :: observability-skeleton`
Related doc: `docs/OBSERVABILITY.md :: JSON log and span schema`

AC:
- [ ] API process emits JSON-formatted log lines to stdout. Verify: `docker compose up api` and inspect output format
- [ ] Worker process emits JSON-formatted log lines. Verify: same approach
- [ ] `trace_id` appears in log lines when present in context. Verify: `grep trace_id` in log formatter code
- [ ] Existing `app/obs/log.py` span schema is preserved. Verify: existing span tests pass

### Issue 6 — Expand Prometheus scrape targets and add basic alerts

**Type:** `type:task` · `prio:med` · `agent:ready`

Extend `ops/observability/prometheus.yml` to scrape worker and watcher metrics endpoints (if exposed) or add them. Add basic alerting rules: service down > 5min, error rate > 5% over 15min, worker queue depth growing. Wire Alertmanager in the observability compose stack.

Source anchor: `docs/specs/builder-ops-stability/README.md :: observability-skeleton`
Related doc: `docs/INFRASTRUCTURE.md`

AC:
- [ ] `prometheus.yml` scrapes at least API + worker. Verify: grep targets in prometheus.yml
- [ ] Alert rules file exists with at least 3 rules. Verify: `ls ops/observability/alerts.yml`
- [ ] Alertmanager service in `ops/observability/docker-compose.yaml`. Verify: grep alertmanager in compose
- [ ] `make dev-up` or equivalent still starts cleanly. Verify: smoke

### Issue 7 — Harden Docker build (multi-stage, .dockerignore)

**Type:** `type:refactor` · `prio:low` · `agent:ready`

Convert Dockerfile to multi-stage build: builder stage installs deps, runtime stage copies only `app/` and installed packages. Expand `.dockerignore` to exclude `tests/`, `docs/`, `.git/`, `*.md`, `ops/`, `scripts/`. Add a HEALTHCHECK instruction.

Source anchor: `docs/specs/builder-ops-stability/README.md :: build-hygiene`

AC:
- [ ] Dockerfile has at least two `FROM` stages. Verify: `grep -c '^FROM' Dockerfile`
- [ ] `.dockerignore` excludes tests, docs, .git. Verify: `cat .dockerignore`
- [ ] HEALTHCHECK instruction present. Verify: `grep HEALTHCHECK Dockerfile`
- [ ] Image builds and API starts. Verify: `docker build -t test && docker run --rm test python -c "import app"`

---

## Execution order

Dependency-free — all issues can be picked up in parallel. Suggested priority:

1. Issue 3 (Python mismatch) — highest correctness risk
2. Issue 1 (CI consolidation) — reduces noise for everything else
3. Issue 4 (silent swallowing) — makes failures visible
4. Issue 2 (activate dead gates) — depends on Issue 1
5. Issue 5 (structured logging) — foundational for Issue 6
6. Issue 6 (metrics + alerts) — depends on Issue 5 being useful
7. Issue 7 (Docker hygiene) — lowest risk, do anytime

## Labels

All issues: project `Agent Delivery Control Plane`.
