---
name: Per-Subsystem Counts View
description: Add a per-subsystem counts section to the CKM overview using distinct-artifact counts and a shared-evidence indicator so seed-path fan-out duplication is visible, not laundered.
task_id: CKM-EP-03
source_anchor: docs/CKM_EVIDENCE_PROFILE/README.md :: Phase boundary (what Phase 1 is and is not)
parent_capability: CKM Evidence Profile
prerequisites: [CKM-EP-01]
depends_on: [SCALAR_RETIREMENT.md]
can_parallelize_with: []
---

# Per-Subsystem Counts View

## Purpose

Give the operator a per-subsystem count of capabilities and evidence so the overview answers "how
much is covered where" without a maturity scalar. The view must count **distinct artifacts**, not raw
edges, because 79.1% of the evidence graph is cross-capability fan-out duplication (see
[Known substrate defects](README.md#known-substrate-defects)); a raw-edge counts view would show
inflated, near-identical numbers for the 22 seed-path-sharing capabilities — a fourth false picture.

## What This Task Does

- Add a new per-subsystem counts section to `render_overview_html` in
  `app/builderops/ckm/overview_html.py` (and an optional Markdown twin in
  `app/builderops/ckm/projections.py`), reusing `_forest` **unmodified** for subsystem grouping.
- Count **distinct artifacts** per capability and per subsystem: `COUNT(DISTINCT artifact_id)` over a
  capability's evidence edges, aggregated up the `_forest` subsystem roots. Raw edge counts are either
  omitted or shown clearly as a secondary, de-emphasized number — never the primary figure.
- Add a **shared-evidence indicator** per capability and per subsystem: the share of a capability's
  edges whose `(artifact_id, basis)` pair also appears on ≥2 capabilities, labeled in plain language
  (e.g. `shared evidence: 92%`) so fan-out contamination is visible rather than laundered into a
  coverage number.
- Add a **linkage masthead** using the **global** denominator (share of the whole graph), not
  share-of-subsystem. (Small owner/delegate decision, recommended default: global.)
- Keep the output self-contained, deterministic, and read-only (INV-EP-4).

## Concretely

The counts section renders distinct-artifact figures with the duplication made explicit:

```
Retrieval subsystem      capabilities: 4    distinct artifacts: 37    shared evidence: 88%
  Retrieval              distinct artifacts: 21    (edges: 96)    shared evidence: 92%
  …
Linkage masthead: 612 distinct artifacts across 31 capabilities (global)
```

Counting by distinct `artifact_id` removes duplicate edges *within* a capability, but the same shared
artifact bundle can still produce identical totals across the 22 capabilities that share the seed
path `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`. The primary figure is therefore never interpreted alone:
the shared-evidence indicator exposes that cross-capability fan-out at ~79% graph-wide.
`CKM_SCHEMA_VERSION` is unchanged; no schema change is made.

## Why This Matters

The redesign's entire premise is an honest picture. A raw-edge counts view would replace the false
red-band picture (CKM-EP-01) with a different false picture: 22 capabilities showing near-identical
evidence counts driven by one github-ref linker rule fanning an identical artifact bundle across all
of them (1,074 of 2,086 edges = 51.5% from that single basis). Distinct-artifact counting plus the
shared-evidence indicator is what keeps the view honest **without** touching the linker (a Phase-2
workstream, out of scope here).

## Acceptance Criteria

- [ ] A per-subsystem counts section exists in the overview, reuses `_forest` unmodified, and reports
  **distinct-artifact** counts as the primary figure (raw edge counts omitted or clearly secondary).
  Verify: `tests/builderops/ckm/test_overview_html.py::test_subsystem_counts_distinct_artifacts` (new) asserts distinct-artifact counting and that a capability with N edges over M distinct artifacts (M<N) reports M.
- [ ] Each capability and subsystem shows a shared-evidence indicator = share of its edges whose
  `(artifact_id, basis)` also appears on ≥2 capabilities, labeled in plain language.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_subsystem_counts_shared_evidence_indicator` (new) asserts the indicator is present and computed over cross-capability `(artifact_id, basis)` pairs.
- [ ] The linkage masthead uses the global denominator.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_subsystem_counts_global_masthead` (new).
- [ ] Render stays pure, deterministic, read-only, and self-contained.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `::test_cli_rejects_missing_database_without_creating_it`; `::test_no_scripts_or_external_references`.
- [ ] Shared real-store validation gate (INV-EP-6), extended: on the operator's real 31-capability
  store every seed-path-sharing capability exposes the shared-evidence indicator alongside its
  distinct-artifact total; near-identical totals are explicitly labeled as shared fan-out rather
  than presented as independent coverage, and the counts match reality on the 5 capabilities the
  owner knows cold.
  Verify: real-store replay receipt on the coordinator-filed parent feature issue explicitly comparing the 22 seed-path-sharing capabilities' distinct-artifact counts and shared-evidence indicators.

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `python3 -m pytest -q -m "not pg" tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Build a fixture where one artifact fans out across several capabilities and confirm the distinct-
  artifact count and shared-evidence indicator both reflect the duplication.
- Real-store replay (authorized runtime host): confirm all 22 seed-path-sharing capabilities expose
  the shared-evidence indicator beside their totals; attach the receipt to the parent feature issue.

## Out of Scope

- Fixing the `_seed_path()` anchor-stripping linker defect or any linker/ingestion change — that is a
  Phase-2 linkage workstream (this task only makes the counts honest about the existing duplication).
- The aggregate/band retirement (CKM-EP-01) and the tri-state / documentation fix (CKM-EP-02).
- Any schema change or dimension merge/rename (Phase 2).

## Restart / Durability Posture

Not applicable in the trust sense: the counts view is a pure regeneration from the CKM store on every
render. No deferred or in-memory state is introduced; a restart changes nothing about the next render.

## Related Docs

- `docs/CKM_EVIDENCE_PROFILE/README.md` (see [Known substrate defects](README.md#known-substrate-defects))
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `app/builderops/ckm/overview_html.py`, `app/builderops/ckm/projections.py`, `app/builderops/ckm/linkers.py`

## Related GitHub Issues

Not yet filed. The coordinator creates this slice from the merged spec. Delivered as its own issue/PR
(separate from CKM-EP-01/CKM-EP-02). Point `Context` at the parent feature issue and reference
"Implements CKM_EVIDENCE_PROFILE/SUBSYSTEM_COUNTS_VIEW". TCD hint: Sonnet / high — the honest-counting
requirement (distinct-artifact + shared-evidence indicator over a 79%-duplicated graph) is the
correctness-sensitive part; a naive raw-edge implementation would ship a fresh false picture.
