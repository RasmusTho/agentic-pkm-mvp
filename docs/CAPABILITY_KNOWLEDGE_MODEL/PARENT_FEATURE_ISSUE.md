State: FILED as GitHub issue #3138 (2026-07-07) with children #3139-#3148; the GitHub issue is now the authoritative backlog/validation surface and this file is the archived draft.
Doc role: Parent feature issue draft (BuilderOps lane)

# feat: Capability Knowledge Model (CKM / Kvasir) MVP — evidence-backed capability model of the platform

## Context

Development knowledge is fragmented across code, git, PRs, Issues, ADRs, specs, tests, CI, and AI sessions; nothing describes the system itself. ADR-0057 (owner-accepted 2026-07-07) enacts the CKM: a projection-only Builder System subsystem that seeds a capability model from SBS + the Capability Contract Model, ingests engineering artifacts as typed evidence, and computes explainable seven-dimension maturity per capability. Grounding SRS: `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md`. Specification: `docs/CAPABILITY_KNOWLEDGE_MODEL/`. This is the validation hub, not a pickup issue.

## Scope

The CKM MVP outcome: CEG in the BuilderOps store, seeded + populated from repo and GitHub sources, deterministic + fenced-semantic evidence linking, explainable assessments, gap/missing-evidence findings, Markdown projections + CLI, and a static-HTML Development Overview. Implementation home `app/builderops/ckm/`, tests `tests/builderops/ckm/`.

## Source Anchors

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md :: Decision`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.8 Functional Requirements`

## SBS Impact

- Primary subsystem: Builder System (BuilderOps plane, ADR-0010)
- Secondary subsystem(s): none (product repo is read-only input)
- Write class: derived (analytical/projection/receipt objects only)
- Authority impact: none — projection-only by contract (INV-CKM-2)
- Persistence impact: rebuildable (INV-CKM-4); additive `ckm_*` tables in the BuilderOps SQLite store
- Derived/rebuildable impact: entire CEG is derived and re-synthesizable
- Human knowledge impact: none (no vault writes)
- Memory impact: none (no runtime memory surfaces)
- Retrieval/context impact: none at runtime; builder agents may read projections as context
- Sync/deployment impact: none
- External boundary impact: GitHub REST reads only
- New or changed contract: CKM object model (specified in `docs/CAPABILITY_KNOWLEDGE_MODEL/`)
- Owner-doc impact: follow-up owner-doc promotion after acceptance (see Validation path)
- Transition debt impact: reduces (replaces hand-maintained matrix upkeep with generated comparison projection)
- Fitness rule impact: strengthens (adds `evidence_kind` orthogonality fitness check)

## Constraints

- No product/runtime behavior, schema, or authority change; no vault writes; no GitHub writes from CKM code.
- Reuse — never fork — the SBS/Capability-Contract taxonomy; never overwrite `docs/architecture/traceability-matrix.md`.
- Drift detection (FR-8) stays deferred per OD-K1.
- All seven cross-task invariants INV-CKM-1..7 hold at every merge point.

## Acceptance Criteria

- [ ] CEG seeded, populated, and rebuildable from scratch. Verify: `tests/builderops/ckm/test_rebuild_roundtrip.py::test_drop_and_rebuild_reproduces_graph`
- [ ] Every capability assessed with per-dimension citations + candidate share. Verify: `tests/builderops/ckm/test_assessment_engine.py::test_every_dimension_cites_evidence`
- [ ] Gap/missing-evidence findings specific and cited. Verify: `tests/builderops/ckm/test_gap_detection.py::test_findings_name_capability_dimension_and_citation`
- [ ] All egress self-identifies with watermarks. Verify: `tests/builderops/ckm/test_projections.py::test_all_egress_self_identifies_with_watermark`
- [ ] Orthogonality contract enforced on the live path. Verify: `tests/builderops/ckm/test_evidence_kind_orthogonality.py::test_ckm_never_touches_runtime_evidence_role`
- [ ] Owner validation of the live Development Overview recorded here. Verify: validation comment on this issue (operator receipt)

## Implementation Tasks

Specification directory: `docs/CAPABILITY_KNOWLEDGE_MODEL/` — one child issue per task, in this order:
CKM-01 store/object model → (CKM-02 seed ∥ CKM-03 repo ingest ∥ CKM-04 github ingest) → CKM-05 deterministic linkers → (CKM-06 semantic association ∥ CKM-07 assessment) → CKM-08 gaps → CKM-09 projections/query → CKM-10 HTML overview + parent closure.

## Verification Path

Each child ships its named tests under `tests/builderops/ckm/` and passes `pytest -m "not pg"`. No integrated-runtime UAT needed (builder-plane only).

## Validation / Acceptance Path

After CKM-09/10: full live pipeline run; projections + overview attached here as the validation receipt; owner sanity pass on the capability map. Owner-doc promotion (BuilderOps owner doc + DOCS_INDEX supported-capability rows) in a follow-up docs PR only after acceptance is recorded here.

## Out of Scope

Drift detection (FR-8), closed-loop writeback (gap→issue automation), HTTP API, NL query, capability-existence inference, evolution-timeline UI, cross-repo federation, AI-session ingestion.

## Suggested Validation

- `python -m app.builderops ckm seed && python -m app.builderops ckm ingest --source all && python -m app.builderops ckm link && python -m app.builderops ckm assess && python -m app.builderops ckm gaps && python -m app.builderops ckm overview --out /tmp/ckm-overview.html`
- `python -m pytest tests/builderops/ckm/ -q`

## Source Docs

- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`
- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md`

## Applies learning (optional)

Slice shape informed by the Builder Capability Portfolio defer-rationale (`docs/development/BUILDER_CAPABILITY_PORTFOLIO.md` §1: drift detection deferred until the Correctness Kernel registry substrate lands).
