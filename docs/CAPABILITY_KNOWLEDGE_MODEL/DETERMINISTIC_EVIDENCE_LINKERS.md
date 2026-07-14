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

- **matrix linker** — parses `docs/architecture/traceability-matrix.md` rows. A row's control boundaries (`boundary_ref` on seeded capabilities) define a candidate pool, not a license to copy every citation to every sibling. When a boundary has multiple seeded capabilities, an edge is emitted only when the matrix row or cited source names that capability, or the citation is that capability's exact `seed_source`; the `basis` records the row, citation, and source-backed selector. A cited test may also link its explicitly imported `app.*` module to the same selected capability, with both the test citation and selector in the basis, producing mechanically auditable functional evidence.
- **spec-directory linker** — task files under a spec directory (frontmatter `parent_capability`) become `spec` evidence for that capability; their `Related GitHub Issues` / issue back-references (`Implements {DIR}/{TASK}` pattern from issue bodies captured by CKM-04) link issues/PRs to the same capability.
- **ADR linker** — ADR files referencing an owner doc that is a capability's `seed_source` become `adr` evidence for it.
- **test↔code linker** — mirrored paths (`tests/x/test_y.py` ↔ `app/x/y.py`) plus explicit imports (AST-level) attach `test` evidence to whichever capability the source module is already linked to via seed/spec edges (transitive one hop, recorded in `basis`).
- **github-ref linker** — issue/PR records whose captured refs name a capability's `seed_source` doc or spec directory become `issue`/`pull_request` evidence, with `maturity_dimension` hints (merged PR → functional completeness; closing an issue labeled `type:task` → requirement coverage).

Each linker is idempotent (INV-CKM-7: natural key = artifact+capability+basis) and re-runs incrementally over artifacts newer than its last watermark. CLI: `python -m app.builderops ckm link`.

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
