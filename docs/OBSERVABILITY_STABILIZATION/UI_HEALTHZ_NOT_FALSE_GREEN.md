---
name: UI /healthz Not False-Green
description: >
  The companion-UI /healthz returns an unconditional 200 without probing its
  upstream API; make it probe upstream and return 503 when the runtime is down.
  Same in prod.
task_id: OBSSTAB-11
source_anchor: "companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py :: do_GET /healthz (line 14259)"
parent_capability: Observability Stabilization
prerequisites: []
depends_on: []
can_parallelize_with:
  - OPERATOR_HEALTH_GLYPH_AMBIENT.md
  - OPERATOR_DRAWER_RENDERS_LOADBEARING_HEALTH.md
  - OPERATOR_DRAWER_SHOWS_BACKLOG.md
---

# UI /healthz Not False-Green

## Purpose

The companion-UI `/healthz` endpoint returns `{"ok": true}` with HTTP 200
unconditionally, never probing the upstream runtime API it proxies. This makes
it useless as a liveness signal — any uptime monitor or the Companion UI health
doctor trusts it while every real request is failing (audit risk R11).

## What This Task Does

In `serve_dev_page.py :: make_handler._Handler.do_GET` (line 14259), the
`/healthz` branch sends a hardcoded 200 with no upstream check. Replace it with
a probe: attempt `self._client.get('/api/health', params={})` (or `/api/status`)
and return HTTP 200 `{"ok": true, "service": "companion-ui"}` only on success;
return HTTP 503 `{"ok": false, "upstream": "unreachable"}` on any
`WorkspaceClientError` or non-2xx response.

The production server (`serve_production_page.py`) calls the same `make_handler`
factory from `serve_dev_page`, so the fix applies identically to production with
no further changes needed there.

Signal the changed liveness semantics to the OBSSTAB-04 scheduled probe so it
treats the UI `/healthz` as a real upstream-aware signal.

## Concretely

Stop the runtime API, then:

```
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/healthz
```

Today: `200`. After this task: `503` with body
`{"ok": false, "upstream": "unreachable"}`.

When the runtime is up, the same curl returns `200` and
`{"ok": true, "service": "companion-ui"}`.

## Why This Matters

A UI process can report healthy while every request 502s because the backend is
down. The human operator reading the Companion UI health display — or any uptime
monitor watching `/healthz` — sees green and has no indication that all
substantive operations are failing. The operator is then the only error detector,
which defeats the purpose of a health endpoint. The same false-green applies in
production (R11).

## Acceptance Criteria

- [ ] UI `/healthz` returns HTTP 503 when the upstream runtime API is
  unreachable.
  - Verify: `tests/companion_ui/test_ui_healthz_probes_upstream.py::test_healthz_503_when_upstream_down`
- [ ] UI `/healthz` returns HTTP 200 only when upstream is reachable.
  - Verify: `tests/companion_ui/test_ui_healthz_probes_upstream.py::test_healthz_200_when_upstream_ok`
- [ ] The production page handler (via `make_handler(production_profile=True)`)
  has the same probe behavior.
  - Verify: `tests/companion_ui/test_ui_healthz_probes_upstream.py::test_prod_handler_healthz_probes_upstream`

## How to Verify (Pre-Merge)

1. Run `pytest tests/companion_ui/test_ui_healthz_probes_upstream.py -v` — all
   three tests must pass.
2. Run the full `not pg` suite (`pytest -m "not pg"`) to confirm no regressions
   in the existing handler tests.
3. Confirm `serve_production_page.py` required no source changes (it reuses
   `make_handler`).

## Out of Scope

- Auto-reconnect or backoff logic for the gateway (separate issue).
- The operator health glyph and runtime-status drawer (OBSSTAB-08/-09/-10).
- Any change to the `/api/operator/health` proxy endpoint (line 14519) — that
  already forwards to the upstream and is unrelated.

## Related Docs

- `companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`
  (handler factory `make_handler`, `do_GET` at line 14257)
- `companion-ui/companion-app/companion_ui/workspace/serve_production_page.py`
  (reuses `make_handler` at line 68)

## Related GitHub Issues

Child of #2597 (Observability Stabilization epic). Implements audit risk R11.
Coordinate with OBSSTAB-04 (#2601): the scheduled probe should treat UI
`/healthz` as upstream-aware once this lands.
