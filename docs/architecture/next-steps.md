# SoT 4.3.1–5 Bridge — Next Steps

**Focus:** Kvalitet, observability och robusthet före expansion.

## 4.3.1 Objectives (Status)

- [x] Establish settings source of truth in `vault/_system/settings/system-settings.yaml` and validate locally via schema tests.
- [ ] Ensure **CI** validates settings against `schemas/system-settings.schema.json` (wire into GH Actions).
- [x] Add OTel spans at agent/worker level (visibility in Jaeger pending config).
- [ ] Define deterministic merge/conflict policy for frontmatter/body (doc + code).
- [ ] Decide on broker-backed outbox via ADR (Debezium/Kafka spike → measure → decide).

### Definition of Done (4.3.1)

- [x] `settings.md` exists and local validation passes.
- [ ] CI enforces schema validation for settings.
- [x] `make smoke` runs locally and is green.
- [ ] `make smoke` is executed in CI.
- [ ] `yaml_roundtrip` (`write_on_diff`) exists as a reusable module with golden tests.

---

## Next Step: Integrate Promotion Agent (Status)

- [x] Implement the full chain: promotion intent → event → frontmatter → index.
- [x] Verify UX (checkbox disappears, no extra menus).
- [x] Extend smoke/E2E tests with scenario `intent → promoted → index visible`.
- [x] Prepare batch move job (launchd worker running `.venv/bin/python3 -m app.promotion.cli run` on interval).

### Promotion Agent — Next tasks

- [x] Create thin PER-wrapper: `app/agents/promotion/agent.py` calling `run_once()`, emitting agent-level spans/events.
- [x] Add OTel spans in `queue.run_once()` with `trace_id` propagation.
- [ ] Finalize `promote.*` event catalog and validate in CI.
- [ ] Optional: time-window guard (02–06) for launchd.
- [ ] Ensure promotion smoke is included in GH Actions.
- [ ] Commit ADR for Promotion Agent and link from `docs/ARCHITECTURE.md`.
- [ ] Flip `docs/STATUS.md` to Green after wrapper + spans.
- [x] Verify spans in Jaeger (enable_tracing=true + OTLP endpoint reachable).

---

## Gaps / Additions to plan

- [ ] CI: add `make smoke` job and settings schema validation in GitHub Actions.
- [ ] Implement `app/io/yaml_roundtrip.py` with `write_on_diff` and golden tests.
- [ ] Add `docs/merge-policy.md` and `app/merge/frontmatter.py` (3-way merge with deterministic priority) + tests.
- [ ] ADR for outbox broker (Debezium/Kafka) with a spike branch and measured SLA (≤ 2 s).
- [ ] Append `promote.*` events to `vault/_system/events/catalog.yaml` and ensure CI checks its YAML shape.

---

## Shortlist — Next three

1. Wire `make smoke` + settings validation into CI (low effort, high leverage).
2. Add thin PER-wrapper for Promotion Agent (structure parity with other agents).
3. Instrument OTel spans in promotion run and verify in Jaeger.

---
**CI Note:** Only `smoke` runs on push/PR. All other workflows are temporarily manual (workflow_dispatch) until v4.4.
---
**Agent run hint:** `make agent-run` executes the thin PER wrapper (delegates to promotion worker).
**Tracing hint:** Install `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp` locally and set `runtime.enable_tracing: true` in `system-settings.yaml`. Jaeger via OTLP HTTP exporter uses `observability.otlp_endpoint` (or `OTEL_EXPORTER_OTLP_ENDPOINT` env).
**Doc note:** This file tracks incremental progress during 4.3.1→4.4. Larger narrative edits will roll into ROADMAP after Jaeger verification and merge-policy landing.
