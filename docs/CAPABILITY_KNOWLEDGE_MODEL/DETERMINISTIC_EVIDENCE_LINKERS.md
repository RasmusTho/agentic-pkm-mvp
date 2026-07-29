---
name: Deterministic Evidence Linkers
description: Mechanical evidence edges from traceability-matrix rows, ADR references, spec directories, and test↔code co-location — confirmed by construction
task_id: CKM-05
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.12 Evidence Model
parent_capability: Capability Knowledge Model
prerequisites: [CKM-02, CKM-03, CKM-04]
depends_on: [CAPABILITY_REGISTRY_SEED.md, REPO_ARTIFACT_INGESTION.md, GITHUB_ARTIFACT_INGESTION.md]
can_parallelize_with: []
---

# Deterministic Evidence Linkers

## Purpose

Create the confirmed structural spine of the Capability Evidence Graph from links the repo already declares — no inference, fully reproducible. This spine carries the assessment load; LLM association (CKM-06) only adds coverage on top.

## What This Task Does

Implements `app/builderops/ckm/linkers.py` — each linker reads ingested artifacts + the seeded registry and emits `ckm_evidence_edge` rows with `extraction_method=deterministic`, lifecycle `confirmed` (OD-K5), and a `basis` provenance string naming the mechanical rule that fired:

- **matrix linker** — parses `docs/architecture/traceability-matrix.md` rows. A row's control boundaries (`boundary_ref` on seeded capabilities) define a candidate pool, not a license to copy every citation to every sibling. When a boundary has multiple seeded capabilities, an edge is emitted only when the matrix row or cited source names that capability, or the citation is that capability's exact `seed_source`; the `basis` records the row, exact citation, and source-backed selector. Functional source evidence therefore requires an explicit `app/...` citation in the selected matrix row. A test citation never turns all of that test's imports into source evidence. The test↔code linker may attach test evidence only after an imported source file is already deterministically capability-linked.
- **spec-directory linker** — task files under a spec directory (frontmatter `parent_capability`) become `spec` evidence for that capability; their `Related GitHub Issues` / issue back-references (`Implements {DIR}/{TASK}` pattern from issue bodies captured by CKM-04) link issues/PRs to the same capability.
- **ADR linker** — ADR files referencing an owner doc that is a capability's `seed_source` become `adr` evidence for it.
- **test↔code linker** — mirrored paths (`tests/x/test_y.py` ↔ `app/x/y.py`) plus explicit imports (AST-level) attach `test` evidence to whichever capability the source module is already linked to by a confirmed deterministic source edge (transitive one hop, recorded in `basis`). Imports can add test evidence; they can never create source evidence.
- **github-ref linker** — issue/PR records whose captured refs name a capability's `seed_source` doc or spec directory become `issue`/`pull_request` evidence, with `maturity_dimension` hints (merged PR → functional completeness; closing an issue labeled `type:task` → requirement coverage).

Each linker is idempotent (INV-CKM-7: natural key = artifact+capability+basis) and re-runs incrementally over artifacts newer than its last watermark. CLI: `python -m app.builderops ckm link`.

**Dimension coverage (2026-07-29, #4258).** Tracing every `_emit(...)` call site in
`linkers.py` against `MATURITY_DIMENSIONS` (`app/builderops/ckm/models.py`) shows the
five rule families jointly cover six of the seven dimensions: matrix → functional /
test / documentation / architectural (by cited artifact kind); spec-directory →
requirement coverage; github-ref's non-closing, non-merged branch → integration
completeness. **`operational_readiness` has no producing rule in any linker** — a live
run against this repo on 2026-07-28 confirmed it: `missing` for all 31 capabilities,
scoring `0.0` for every one, permanently, because nothing ever emits that
`maturity_dimension`. That is an instrument defect (a dimension that can never score,
regardless of how operationally ready the system actually is), not a finding about the
system. Building an operational-readiness linker is a separate design question (what
would even constitute deterministic operational evidence — runbooks? health-check
wiring? deploy scripts? — is unresolved) and is explicitly out of scope here.

Resolution: `operational_readiness` stays a declared dimension in `MATURITY_DIMENSIONS`
— narrowing the seven-dimension vector from
`docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 6` is a bigger, separate decision than
this defect calls for — but it is named in
`app/builderops/ckm/models.py :: UNMEASURABLE_MATURITY_DIMENSIONS`. `assess.py` reads
that set and stamps every such dimension's `dimension_status` as `"unsupported"`, a
state `SUPPORTED_VALUE_STATES` already defines and `overview_html.py` already renders
distinctly ("Unsupported is not a zero score"). This replaces the ambiguous `"missing"`
a scorer with genuinely zero evidence *this run* would otherwise report, so the
resolution is readable straight off the model rather than inferred from an empty
citations table.

`tests/builderops/ckm/test_linker_dimension_coverage.py` is the standing, deterministic
guard: it fails and names the offending dimension if any declared dimension outside
`UNMEASURABLE_MATURITY_DIMENSIONS` ever loses its last producing linker (or a new
dimension is declared without one), and separately checks that every declared
"unmeasurable" dimension genuinely still has zero producers — so the escape hatch can
never quietly cover for a regression instead of a real structural gap.

## Concretely

```bash
python -m app.builderops ckm link
# → "matrix: 214 edges, spec: 96, adr: 71, test↔code: 183, github-ref: 340 (0 new on re-run); unlinked artifacts: 3,912"
```

The honest `unlinked artifacts` count is required output — it is CKM-06's backlog and CKM-09's honesty signal.

## Why This Matters

If the deterministic spine is thin or wrong, assessment quality collapses and CKM-06's LLM has nothing to anchor against. The `basis` string is what makes every edge auditable (INV-CKM-1) — an edge that cannot cite its rule is indistinguishable from a hallucination.

## Acceptance Criteria

- [ ] The matrix linker reproduces live matrix citations for unambiguous boundaries and capability-specific citations beneath shared boundaries without mechanically sharing evidence among siblings.
  - Verify: `tests/builderops/ckm/test_linkers.py::test_matrix_rows_become_edges_on_live_matrix`
- [ ] Live Retrieval evidence is mechanically distinct from planned Context building evidence, and every shared-boundary selector resolves to the matrix row or cited source text.
  - Verify: `tests/builderops/ckm/test_linkers.py::test_live_retrieval_has_capability_specific_functional_evidence` and `tests/builderops/ckm/test_linkers.py::test_shared_boundary_evidence_is_capability_specific`
- [ ] Every emitted edge has `extraction_method=deterministic`, lifecycle `confirmed`, and a non-empty `basis` naming its rule.
  - Verify: `tests/builderops/ckm/test_linkers.py::test_edges_carry_method_lifecycle_basis`
- [ ] Linkers are idempotent and incremental (unchanged inputs ⇒ zero new edges; one new artifact ⇒ only its edges).
  - Verify: `tests/builderops/ckm/test_linkers.py::test_link_idempotent_incremental`
- [ ] The unlinked-artifact count is computed and exposed via the CLI/store (never silently dropped).
  - Verify: `tests/builderops/ckm/test_linkers.py::test_unlinked_backlog_reported`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_linkers.py -q`
- Live run: seed + ingest + link on the real repo; spot-check 5 edges against their basis (e.g. matrix row 7 selects Retrieval beneath RCA without assigning the same evidence to Context building).
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Any LLM/semantic association (CKM-06). Any edge whose basis is judgment, not rule.
- Capability-relationship inference (`depends-on` etc. — post-MVP; FR-4 minimum lands via `part-of` from seed).
- Fixing wrong links in source docs — a bad matrix row propagates and is *visible*, which is correct behavior.

## Related Docs

- `docs/architecture/traceability-matrix.md` (primary input), `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-02 + CKM-03 + CKM-04. TCD hint: Sonnet / high (five rule families, correctness matters, but each rule is unit-testable).
