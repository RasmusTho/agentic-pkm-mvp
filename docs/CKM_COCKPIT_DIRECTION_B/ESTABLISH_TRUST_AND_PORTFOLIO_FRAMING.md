---
name: Establish Trust and Portfolio Framing
description: Add the opt-in cockpit generation boundary and a complete portfolio-first trust frame over the existing CKM overview.
task_id: CKM-DB-01
source_anchor: docs/CKM_COCKPIT_DIRECTION_B/README.md :: Capability boundary
parent_capability: CKM Cockpit Direction B
prerequisites: [CKM-EP-01, CKM-EP-02, CKM-EP-03]
depends_on: [docs/CKM_EVIDENCE_PROFILE/README.md]
can_parallelize_with: []
---

# Establish Trust and Portfolio Framing

## Purpose

Create the single generation and information-architecture seam every later cockpit slice extends,
without forking the Development Overview or changing the default Direction A output.

## What This Task Does

- Add an opt-in `--cockpit` flag to the existing `ckm overview` command.
- Extend, rather than replace, `render_overview_html` and `write_overview_html` with an optional
  immutable cockpit render context.
- Build the cockpit over the same one-transaction bounded `CkmProjectionBatch` used by the map.
- Render the fixed banner/header/trust/hazard-slot/comparison-slot/filter-slot/map/gaps/proposal-slot/
  footer structure, with unimplemented later slots explicitly unavailable rather than simulated.
- Bind the output to generation time, CKM epoch/state revision/schema version, exact sorted
  watermarks, bounded object counts, and a deterministic projection-input digest.
- Keep `render_overview_html(store)` and the default CLI output byte-compatible with the Direction A
  no-script contract except for changes already delivered by CKM Evidence Profile Phase 1.

## Concretely

This task introduces the future public command:

```text
python -m app.builderops --db-path <builderops.sqlite3> ckm overview \
  --cockpit --out <ckm-cockpit.html>
```

The Python boundary is:

```text
render_overview_html(store, generated_at=<explicit>, cockpit=<CockpitRenderContext>) -> str
write_overview_html(store, output_path, generated_at=<explicit>, cockpit=<context>) -> Path
```

`cockpit=None` is the existing Direction A path. The context is data-only; it carries later
comparison/refusal inputs but no callbacks, stores, network clients, clocks, or write handles.

## Why This Matters

A sibling renderer would duplicate map semantics and eventually drift from the delivered overview.
An implicit default-mode change would break Direction A's static contract. One opt-in seam keeps
later work additive, testable, and reversible while ensuring every section shares one captured CKM
state.

## Acceptance Criteria

- [ ] The existing `ckm overview` command accepts `--cockpit`, while invoking it without the flag uses the unchanged default render path.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cli_cockpit_is_opt_in_and_default_remains_direction_a`
- [ ] Cockpit generation extends `render_overview_html`/`write_overview_html`; no sibling cockpit renderer or second dashboard entry point exists.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_uses_existing_overview_renderer_call_site`
- [ ] Trust, map, gaps, and footer use one bounded read-only `CkmProjectionBatch` and one state identity; no section performs a second CKM read.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_uses_one_projection_batch_without_mutation`
- [ ] The trust frame exposes generated time, epoch, state revision, schema version, exact sorted watermarks, complete bounded object counts, and a deterministic projection-input digest.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_trust_frame_binds_complete_projection_identity`
- [ ] The fixed portfolio/detail section order and four owner questions are present even when the CKM store is empty.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_empty_store_keeps_fixed_information_architecture`
- [ ] Missing, old, over-bound, or mixed-epoch CKM state fails before an output file is written and never creates or migrates the store.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_cli_fails_closed_before_writing_partial_output`
- [ ] Identical explicit generation time and store state produce byte-identical cockpit HTML.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_cockpit_render_is_byte_deterministic`
- [ ] The implementation PR records the owner-doc posture as “target-state remains linked; no supported Direction B claim” and hands a receipt to the parent.
  Verify: CKM-DB-01 delivery receipt on the Direction B parent issue

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Invoke both CLI forms over the same fixture store and compare the default output against the
  post-Evidence-Profile baseline.
- Inspect the generated cockpit with an empty store and one stale-assessment fixture.

## Out of Scope

- Hazard interpretation beyond empty reserved state
- Reading the metric-retention sidecar or rendering O1b deltas
- Filtering script or enabled controls
- Proposal draft content
- Print-specific expansion
- Any implementation of CKM Evidence Profile Phase 1

## Related Docs

- `docs/CKM_COCKPIT_DIRECTION_B/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_HTML_PROJECTION.md`
- `docs/CKM_EVIDENCE_PROFILE/README.md`
- `app/builderops/ckm/overview_html.py`
- `app/builderops/cli.py`

## Related GitHub Issues

Delivery history: child [#4081](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4081) and parent
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) are closed. Evidence Profile Phase
1 delivered before this slice. The planned cheapest acceptable TCD route was **Terra/high** because
this was a multi-file public CLI/render boundary with determinism and prerequisite-integration risk.
