State: ACCEPTED/DELIVERED CKM Evidence Profile Phase 1 specification and delivery history. Parent #4089 and children #4090–#4092 are closed after terminal canonical real-store replay and parent acceptance on 2026-07-24. Grounds the ratified Phase 1 redesign (retired render-time cross-dimension scalar, per-dimension tri-state, and per-subsystem counts view) from the advisory plan `research/CKM_EVIDENCE_PROFILE_IMPLEMENTATION_PLAN_2026-07-18.md` (BuilderOps Vault). Phase 2 as originally scoped was superseded 2026-07-18 by the validation-panel verdict (BuilderOps Vault: `research/CKM_PHASE2_VALIDATION_PANEL_2026-07-18.md`) in favor of a linker-precision workstream; Phase 3 is cut from ratification.
Doc role: Specification directory (capability breakdown)
Authority: Owns the Phase 1 task decomposition, execution order, cross-task invariants, and acceptance path for the CKM Evidence Profile redesign. Subordinate to ADR-0057 (CKM existence and projection-only posture), the accepted CKM MVP contract `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`, and the Direction A presentation contract `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`. Governs nothing that those owners govern; it specifies bounded implementation work only.
Owner: BuilderOps governance / Capability Knowledge Model
Temporal class: snapshot (accepted/closed contract and delivery history)
Review cadence: event-driven
Source of truth: this directory for Phase 1 implementation-task shape; ADR-0057 for CKM authority posture; `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` for the presentation contract this phase amends; the advisory plan in BuilderOps Vault for rationale/red-team history.
Last reviewed: 2026-07-28

# CKM Evidence Profile — Phase 1

The Capability Knowledge Model (CKM / Kvasir) renders a generated Development Overview whose current
render surfaces paint an **honest-looking but false picture**: a render-time cross-dimension
aggregate (the minimum of seven weighted dimension scores) drives a `critical` maturity band that
colours ~31 capability boxes red regardless of what evidence actually exists, and dimensions with
zero score and no citations are indistinguishable from dimensions that were never assessed. This
directory specifies **Phase 1** of the ratified evidence-profile redesign: stop rendering the
scalar, make the per-dimension "unassessed" state a first-class render state, fix the documentation
scorer's empty-set behaviour, and add a per-subsystem counts view — with **additive DDL but no
schema-version/epoch bump** and slice-specific real-store validation gates.

Phase 1 alone resolves the Gate-A contradiction (the operator's Retrieval capability renders a
`0.00` aggregate and a red `critical` band while its shipped functionality is real, delivered under
#3124). It is the uncontested repair of verified defects; it does **not** touch the contested
judgment calls (which dimensions, what merge formula, whether to rename the model) that the owner's
2026-07-16 decision reserves for the cross-provider inquiry.

**Work classification (SBS operating model):** Builder System. Implementation home
`app/builderops/ckm/`, tests `tests/builderops/ckm/`. CKM remains projection-only BuilderOps
analysis (INV-CKM-2); no Product/Runtime subsystem is touched, and the product repo stays a
read-only source. This directory is docs-only.

## Phase boundary (what Phase 1 is and is not)

Phase 1 is exactly three bounded implementation tasks plus a shared real-store validation gate.

| task_id | Task file | Work package | Outcome |
| --- | --- | --- | --- |
| CKM-EP-01 | [SCALAR_RETIREMENT.md](SCALAR_RETIREMENT.md) | WP0 | Retire the cross-dimension aggregate/band from every render surface (HTML overview + Markdown twin). The per-dimension vector becomes the display. `compute_aggregate` keeps writing its NOT-NULL column (dead data), so this task itself is zero-DDL. This — not the counts view — is what kills the 31 red boxes. |
| CKM-EP-02 | [TRISTATE_STATUS.md](TRISTATE_STATUS.md) | WP1 | Additive JSON `dimension_status` column (4-place additive pattern, no schema-version bump) adopting the `contracts.py` `SUPPORTED_VALUE_STATES` vocabulary; make per-dimension `unassessed` render distinctly from evidence-starved zero; fix `_documentation` empty-set → `unassessed` and bump its formula id `current-doc-evidence-v1` → `-v2`. |
| CKM-EP-03 | [SUBSYSTEM_COUNTS_VIEW.md](SUBSYSTEM_COUNTS_VIEW.md) | WP3 | New per-subsystem counts section in the overview (and optional Markdown twin) reusing `_forest` unmodified; **distinct-artifact counts** plus a **shared-evidence indicator** so the ~79% seed-path fan-out duplication is visible, not laundered; static-contract-compliant; purity tests preserved; global-linkage masthead denominator. |

### Superseded original Phase 2 (not authorized)

The original Phase 2 package — dimensions 7→3, schema epoch v5→v6 plus rebuild, a render-time
discrimination self-check, the maturity→evidence-profile rename, and a superseding ADR — was
superseded by the 2026-07-18 validation-panel verdict. It is **not deferred work**, cannot be filed
from this directory, and has no surviving waiver path. Its former prerequisite list is historical
input only, not an execution gate.

The panel selected a separate **linker-precision successor**: increase traceability rows that cite
real `app/` paths and resolve specification `parent_capability:` links before considering more
scorers or model-shape changes. That successor requires its own specification, authority decision,
and issue contract. This directory authorizes Phase 1 only.

### Cut — Phase 3 (not on the ratification path)

The escrow/quota scorers are **cut** from ratification. They would render "escrowed" for ~29/31
capabilities (one `app/` path in the whole traceability matrix; 4/357 spec docs resolve), so building
~6 days of scorers that display almost nothing is backwards. The real follow-up is the **linkage
workstream** (traceability-matrix rows citing real `app/` paths, spec `parent_capability:`
resolution), scoped as its own successor effort *after* Phase 1 ships because the linkage — not the
scorers — is the value item. Any later scorer proposal requires a new specification, authority
decision, and issue contract; this directory does not promise that it will be built.

## Known substrate defects

These are verified defects in the evidence substrate that Phase 1 must be *honest about* but must not
*fix* (if approved, fixing them would belong to a linker-precision successor that is not yet
specified or authorized, not Phase 1).

- **Seed-path fan-out duplication (~79% of the edge graph).** `_seed_path()`
  (`app/builderops/ckm/linkers.py:56-58` on `origin/main`) strips the `::` anchor from a capability's
  `existence_provenance`, so 22 of 31 capabilities (including all 8 SBS roots) collapse to the
  identical seed path `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`. One github-ref linker rule then fans an
  identical artifact bundle across all 22: 1,074 of 2,086 edges (51.5%) come from that single basis,
  and 1,649 edges (79.1%) sit on `(artifact_id, basis)` pairs duplicated across ≥2 capabilities.
  Consequence: any counts view built on **raw edge counts** would show inflated, near-identical numbers
  for those 22 capabilities — a fourth false picture. CKM-EP-03 therefore counts **distinct artifacts**
  and surfaces a **shared-evidence indicator**; it does not touch the linker. The linker fix is a
  potential linker-precision successor, which is not yet specified or authorized.

## Execution order

Flat order: **CKM-EP-01 → CKM-EP-02 → CKM-EP-03**.

```
CKM-EP-01 (retire scalar render) ── CKM-EP-02 (tri-state + doc fix) ── CKM-EP-03 (subsystem counts)
```

- CKM-EP-01 goes first because it is the package that actually removes the false picture; every later
  task then edits a render surface that no longer carries a misleading aggregate/band.
- CKM-EP-02 follows CKM-EP-01 because both edit the same overview render helpers
  (`_dimension_markup`, `_mini_dimensions_markup`, `_capability_markup`); doing the retirement first
  avoids CKM-EP-02 re-touching band markup that is about to be deleted.
- CKM-EP-03 is topically independent of the scalar/tri-state semantics (it adds a new counts section
  and reuses `_forest` unmodified) but shares the file `overview_html.py`; deliver it serially after
  CKM-EP-02 to avoid same-file merge conflict, not because of a data dependency.

Issue mapping: the serial parent contract maps CKM-EP-01, CKM-EP-02, and CKM-EP-03 to distinct
child issues [#4090](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4090),
[#4091](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4091), and
[#4092](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4092), respectively. Deliver them in
the stated order; the specification remains the source of task shape and the issues are the live
execution artifacts.

## Cross-Task Invariants / Interaction Safety

These invariants hold *across* the three tasks. Each task names the ones it must preserve.

- **INV-EP-1 (no schema-version bump / no epoch).** No task in Phase 1 bumps `CKM_SCHEMA_VERSION` (currently `5` in
  `app/builderops/ckm/schema.py`). CKM-EP-02's `dimension_status` column is added through the
  additive pattern (register in `CKM_REQUIRED_COLUMNS` **and** `CKM_LEGACY_ADDED_COLUMNS`, add to the
  `CREATE TABLE ckm_assessment` DDL, and back-fill existing rows via an idempotent
  `ALTER TABLE ckm_assessment ADD COLUMN … DEFAULT …` in `store.py`, mirroring
  `_migrate_assessment_explainability`). A version bump is what would trip #3775/#3777's
  version-mismatch refusal; Phase 1 must not.
- **INV-EP-2 (scalar written, never rendered).** `compute_aggregate` keeps computing and writing the
  NOT-NULL `aggregate` / `aggregate_formula_id` columns on every assessment (the column becomes dead
  data; no removal is authorized here). No Phase-1 task may read that column into any render surface —
  HTML band, `min` chip, `data-aggregate-band`, or Markdown "aggregate convenience score". Killing the
  false picture is a **render** change, not a data change.
- **INV-EP-3 (formula-id-bump rule).** Any change to a dimension's scoring *semantics* must bump that
  dimension's formula id. CKM-EP-02 changes `_documentation`'s empty-set result from `0.0` to
  `unassessed`, so it bumps `current-doc-evidence-v1` → `current-doc-evidence-v2` and registers the
  v2 formula in `FORMULAS`. This is load-bearing across `assess.py` and `store.py`: the
  `assessment_fingerprint` / formula-metadata equality check is what makes `assess` **skip**
  re-assessment when nothing changed; reusing the v1 id would make old (starved-zero) and new
  (unassessed) documentation assessments indistinguishable and silently skip the re-run, leaving the
  old false rendering in place. Bumping the id forces the re-assessment as a new bitemporal row
  (INV-CKM-5), never an in-place patch.
- **INV-EP-4 (purity-test preservation).** All three tasks edit `overview_html.py`. Rendering must
  stay pure, deterministic, read-only, and self-contained: `render_overview_html(store) -> str` must
  not mutate the store, two renders over unchanged state must be byte-identical, the CLI must keep
  refusing a missing database without creating it, and the output must stay one self-contained HTML
  file (no scripts/network references). These are asserted by
  `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`,
  `::test_cli_rejects_missing_database_without_creating_it`, and
  `::test_no_scripts_or_external_references` (Direction A / CKM11 criterion 11 and 8). No task may
  weaken them.
- **INV-EP-5 (Direction A acceptance-row impact).** `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
  is the shipped presentation contract (Implemented by #3689). CKM-EP-01 contradicts its acceptance
  rows that require the subordinate `min` aggregate and the text-and-shape maturity band (its rows 5
  and 22, the band-encoding language, and the CKM11 criteria that reference `min`/band). The
  implementer **must** update those Direction A rows in the **same PR** that removes the render, so
  the contract and shipped reality stay consistent (owner-doc/contract writeback bundled with the
  change, never a follow-up). CKM-EP-02 must keep Direction A's three-cell-state contract
  (scored / evidence-starved / unassessed) honest — Direction A already names the `unassessed` cell
  state, so CKM-EP-02 makes that per-dimension state actually reachable rather than reachable only
  when the whole assessment is `None`.
- **INV-EP-6 (slice-specific real-store validation gates).** Fixture purity tests are insufficient
  for changes whose job is killing a false picture, but a slice is gated only on surfaces it
  delivers: CKM-EP-01 proves Retrieval no longer renders falsely red / `critical`; CKM-EP-02 proves
  genuinely absent documentation evidence renders `unassessed`; CKM-EP-03 proves counts match the 5
  capabilities the owner knows cold and all 22 seed-path-sharing capabilities expose the
  shared-evidence indicator beside any near-identical total. The terminal parent acceptance gate
  replays `seed → ingest → link → assess → overview` and combines all three receipts. Real-store
  replay runs where authorized runtime DB access exists rather than on the laptop.

### Partial-failure paths

- **CKM-EP-01 merges, CKM-EP-02 not yet.** The per-dimension vector is the display and no aggregate
  band is rendered, so no capability renders a false red. Dimensions with zero score and no citations
  still render the honest pre-tri-state "evidence-starved" treatment. No data loss; the interim state
  is honest, just less precise than tri-state.
- **CKM-EP-02 merges, but `assess` has not re-run on a given store.** Existing assessment rows carry
  the back-filled default `dimension_status` and the old `current-doc-evidence-v1` formula id. Because
  INV-EP-3 bumps the documentation formula id, the next `assess` run sees a fingerprint change and
  re-mints those assessments as new bitemporal rows (INV-CKM-5), never patching in place. Until then,
  the render shows the honest pre-bump state (starved), not a false picture. The formula-id bump is
  precisely what guarantees the re-assessment happens instead of being skipped by the fingerprint
  equality check.
- **The additive `dimension_status` migration is interrupted mid-apply.** The
  `ALTER TABLE … ADD COLUMN` is guarded by an `if name not in columns` check with a default value, so
  re-running is idempotent (INV-CKM-7) and never leaves a half-written schema version. Because
  INV-EP-1 forbids a version bump, a partially migrated store never triggers a #3775/#3777
  version-mismatch refusal.
- **CKM-EP-03 merges while `assess` lags `ingest`.** The counts view reports structural counts
  (capabilities and evidence edges per subsystem) reusing `_forest`; it must not imply assessment
  freshness it does not have. Assessment staleness is surfaced elsewhere by INV-CKM-5; the counts
  masthead uses the global linkage denominator and makes no maturity claim.

## Acceptance criteria (capability level)

- [x] No render surface (HTML overview or Markdown twin) reads the cross-dimension aggregate or a
  maturity band; the per-dimension vector is the display. The `aggregate` column is still written.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_aggregate_demoted_label` updated/retired to
  assert absence of the `min` chip and band markup; `tests/builderops/ckm/test_projections.py`
  aggregate-line assertions updated; `tests/builderops/ckm/test_assessment_engine.py::test_aggregate_transparent_and_min_capped` still passes (column still written).
- [x] A per-dimension `unassessed` state is renderable and distinct from evidence-starved zero across
  both the mini-cell grid and the expanded dimension markup, backed by the additive `dimension_status`
  column and the `SUPPORTED_VALUE_STATES` vocabulary; `CKM_SCHEMA_VERSION` is unchanged.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_dimension_cells_render_three_states_and_proportional_fill` extended for per-dimension `unassessed`; `tests/builderops/ckm/test_store.py` additive-column round-trip + legacy-DB back-fill test.
- [x] `_documentation` returns `unassessed` (not `0.0`) on the empty documentation-evidence set, and
  its formula id is bumped to `current-doc-evidence-v2`, forcing re-assessment rather than a
  fingerprint skip.
  Verify: `tests/builderops/ckm/test_assessment_engine.py` documentation-empty-set case asserts `unassessed` + `current-doc-evidence-v2`.
- [x] A per-subsystem counts view exists in the overview (and optional Markdown twin), reuses `_forest`
  unmodified, counts **distinct artifacts** (raw edge counts omitted or secondary), surfaces a
  **shared-evidence indicator** so the ~79% fan-out duplication is visible, stays
  self-contained/deterministic, and uses the global linkage denominator.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_subsystem_counts_distinct_artifacts`; `::test_subsystem_counts_shared_evidence_indicator` (new).
- [x] Purity, determinism, read-only, and self-containment contracts still hold after all three tasks.
  Verify: `tests/builderops/ckm/test_overview_html.py::test_pure_render_over_fixture_graph`; `::test_cli_rejects_missing_database_without_creating_it`; `::test_no_scripts_or_external_references`.
- [x] `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md` acceptance rows referencing the
  `min` aggregate and the maturity band are updated in the same PR as CKM-EP-01.
  Verify: doc writeback at `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md :: Acceptance criteria` in the CKM-EP-01 PR diff.
- [x] The terminal real-store validation gate (INV-EP-6) records all three slice receipts: CKM-EP-01
  proves Retrieval no longer renders falsely red / `critical`; CKM-EP-02 proves one named,
  genuinely absent documentation-evidence case renders `unassessed`; and CKM-EP-03 proves the
  distinct-artifact totals and shared-evidence indicators for the five stable validation
  capabilities named in `SUBSYSTEM_COUNTS_VIEW.md`, plus the indicator for all 22
  seed-path-sharing capabilities.
  Verify: real-store replay receipt on the (coordinator-filed) parent feature issue containing the
  CKM-EP-01, CKM-EP-02, and CKM-EP-03 result sections.

## Relationship to GitHub issues

The authoritative backlog and acceptance surface was parent validation hub
[#4089](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089), which is closed and was never a
pickup issue. Its local pointer and validation-hub map is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md).

The three serial child slices are filed from this specification:

1. CKM-EP-01 — [#4090](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4090) —
   [SCALAR_RETIREMENT.md](SCALAR_RETIREMENT.md); delivered and closed.
2. CKM-EP-02 — [#4091](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4091) —
   [TRISTATE_STATUS.md](TRISTATE_STATUS.md); delivered and closed.
3. CKM-EP-03 — [#4092](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4092) —
   [SUBSYSTEM_COUNTS_VIEW.md](SUBSYSTEM_COUNTS_VIEW.md); delivered and closed.

Each delivered child posted its exact PR/SHA, validation, owner-doc result, and parent handoff to
#4089. The
[terminal INV-EP-6 replay receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089#issuecomment-5072782036)
and [parent acceptance](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4089#issuecomment-5072981172)
resolve the capability-level acceptance path.

## Verification and acceptance path

Each task shipped its named focused tests under `tests/builderops/ckm/`, ran `ruff check app tests`,
`mypy app`, and the standard `pytest -q -m "not pg"` suite, and passed current-SHA CI plus the local
review gate. Parent #4089 accepted the terminal INV-EP-6 receipt combining the CKM-EP-01 Retrieval
result, CKM-EP-02 named-absence result, and CKM-EP-03 five-capability count comparison plus
all-22 shared-evidence-indicator result on the operator's real 31-capability store.
No owner-doc promotion beyond the bundled Direction A row updates (INV-EP-5) is implied by Phase 1;
the maturity→evidence-profile rename and any broader owner-doc claim require a separate future
specification, authority decision, and issue contract.

## Source docs

- `research/CKM_EVIDENCE_PROFILE_IMPLEMENTATION_PLAN_2026-07-18.md` (BuilderOps Vault — advisory plan, v2 post red-team; Phase 1 ratified)
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/DEV_OVERVIEW_DIRECTION_A.md`
- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md` (Wave-2 query surface; #3775/#3777 version-mismatch coupling)
