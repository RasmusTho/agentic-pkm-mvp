---
name: Dev Overview HTML Projection
description: Static-HTML Development Overview — capability map + per-dimension evidence vector + gap list — rendered from the store, plus the parent-closure handoff
task_id: CKM-10
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.15 Interfaces (Development Overview UI)
parent_capability: Capability Knowledge Model
prerequisites: [CKM-09]
depends_on: [CKM_PROJECTIONS_AND_QUERY.md]
can_parallelize_with: []
---

# Dev Overview HTML Projection

## Purpose

Give the owner the one-glance surface: a static HTML Development Overview rendering the capability map with a per-dimension evidence vector and drill-down to evidence. One consumer of the model, not the product (SRS §System Context).

## What This Task Does

- Implements `app/builderops/ckm/overview_html.py`: a pure `render_overview_html(store) -> str` function (mirroring the companion-UI `render_index_html` pure-render pattern) producing one self-contained HTML file — no server, no build step, no external assets:
  - capability forest as an indented tree, each node carrying the seven-dimension mini-bars without a cross-dimension aggregate band or heatmap;
  - low-confidence, staleness, and candidate-share markers rendered per node (inheriting CKM-09's flags);
  - per-capability expandable detail: dimension citations, evidence list with basis strings, findings;
  - gaps panel listing current findings;
  - footer: generated-projection self-identification + watermark set (INV-CKM-2).
- CLI: `python -m app.builderops ckm overview --out /path/overview.html`.
- **Parent-closure handoff:** this final child updates `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md` acceptance checklist to reflect delivered state, posts the capability-level validation receipt (live-run outputs + overview screenshot/file) to the parent feature issue, and either closes the parent (if all capability ACs verify) or files the explicit parent-closure issue naming what remains.

## Concretely

```bash
python -m app.builderops ckm overview --out ~/Desktop/ckm-overview.html
open ~/Desktop/ckm-overview.html   # per-dimension view over real repo state, no server needed
```

## Why This Matters

The Development Overview is the owner-facing payoff and the surface most likely to be *believed* — so it must carry every honesty marker (staleness, candidate share, projection footer) or the CKM's chief risk (§8.1: the number read as truth) materializes exactly here.

## Acceptance Criteria

- [ ] `render_overview_html` is pure (store in, string out) and renders the fixture graph with tree and dimension bars present, without a rendered cross-dimension aggregate or maturity band; aggregate persistence remains a compatibility concern outside the render.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `tests/builderops/ckm/test_overview_html.py::test_aggregate_demoted_label`
- [ ] Staleness, low-confidence, and candidate-share markers from the store render in the HTML (enforcement of INV-CKM-3/5 at the final egress).
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_honesty_markers_render`
- [ ] The projection footer (self-identification + watermarks) is present in every rendered document.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_projection_footer_always_present`
- [ ] Output is self-contained: no external network references (script/link/img with remote src) in the HTML.
  - Verify: `tests/builderops/ckm/test_overview_html.py::test_no_external_references`
- [ ] Parent-closure handoff executed: README acceptance checklist reconciled + validation receipt on the parent issue.
  - Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Acceptance criteria (capability level)` + parent-issue validation comment

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_overview_html.py -q`
- Live render against the real repo; open in a browser; owner-facing sanity pass.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Any server/live runtime, companion-UI integration, interactivity beyond `<details>`-level expansion.
- Evolution timeline view (post-MVP; the bitemporal data already supports it).
- Publishing/hosting the HTML anywhere (handoff artifacts go to Desktop/Niflheim, not committed).

## Restart / Durability Posture

The HTML is a generated artifact, disposable by design; the durable state is the store it renders. Regenerate at will.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.15`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Validation / acceptance path`

## Related GitHub Issues

One issue (final child; carries parent-closure handoff). Blocked by CKM-09. TCD hint: Sonnet / medium (pure-render HTML; honesty markers are the review focus).
