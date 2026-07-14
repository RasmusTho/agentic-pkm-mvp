State: Specification directory for the Capability Knowledge Model (CKM / Kvasir) MVP, enacted by ADR-0057. Backlog FILED: parent #3138, children #3139-#3148. System-level source of truth for what the MVP must do; GitHub issues are execution artifacts created from these task specs. Builder System work (BuilderOps plane); not Product/Runtime truth.
Doc role: Specification directory (capability breakdown)
Authority: Owns the MVP task decomposition, execution order, cross-task invariants, and acceptance path for the CKM. Subordinate to ADR-0057 (decisions), ADR-0010 (BuilderOps authority), `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md` (grounding SRS), `docs/CAPABILITY_CONTRACT_MODEL.md` and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (seed taxonomy owners).
Owner: BuilderOps governance
Temporal class: operational (active delivery lane)
Review cadence: event-driven
Source of truth: mixed (this directory for task shape; ADR-0057 for decisions)
Last reviewed: 2026-07-07

# Capability Knowledge Model (CKM / Kvasir) — MVP Specification

The CKM is the Builder System subsystem that continuously constructs and maintains an evidence-backed model of the Yggdrasil platform: **Capability** as primary entity, every engineering artifact as typed **Evidence**, and an explainable seven-dimension **maturity assessment** per capability. Full rationale, prior art, and requirements: [DEVELOPMENT_KNOWLEDGE_MODEL.md](../research/DEVELOPMENT_KNOWLEDGE_MODEL.md). Decisions: [ADR-0057](../adr/ADR-0057-capability-knowledge-model-kvasir.md).

**Work classification (SBS operating model):** Builder System. Implementation home `app/builderops/ckm/`, tests `tests/builderops/ckm/`, store = existing BuilderOps SQLite substrate (OD-K4). No Product/Runtime subsystem is touched; the product repo is read-only input.

**MVP scope (OD-K1):** seed → ingest → link → assess → detect gaps → project. **Deferred:** drift detection (FR-8; waits for the Correctness Kernel registry), closed-loop writeback, predictive maturity, cross-repo federation.

## Implementation tasks

| Task file | task_id | What it delivers |
| --- | --- | --- |
| [CKM_STORE_AND_OBJECT_MODEL.md](CKM_STORE_AND_OBJECT_MODEL.md) | CKM-01 | CEG tables (capability, evidence edge, assessment, finding) in the BuilderOps store + orthogonality fitness check |
| [CAPABILITY_REGISTRY_SEED.md](CAPABILITY_REGISTRY_SEED.md) | CKM-02 | Checked-in seed manifest from SBS + Capability Contract Model + idempotent loader |
| [REPO_ARTIFACT_INGESTION.md](REPO_ARTIFACT_INGESTION.md) | CKM-03 | Deterministic local adapters: docs/ADRs/specs/tests/git → artifact records with watermark |
| [GITHUB_ARTIFACT_INGESTION.md](GITHUB_ARTIFACT_INGESTION.md) | CKM-04 | Issues/PRs adapter via `gh` REST → artifact records with watermark |
| [DETERMINISTIC_EVIDENCE_LINKERS.md](DETERMINISTIC_EVIDENCE_LINKERS.md) | CKM-05 | Mechanical evidence edges: traceability-matrix rows, ADR refs, spec dirs, test↔code |
| [SEMANTIC_EVIDENCE_ASSOCIATION.md](SEMANTIC_EVIDENCE_ASSOCIATION.md) | CKM-06 | LLM association for unlinked artifacts; candidate-labeled, confidence-scored, skip-on-unavailable |
| [MATURITY_ASSESSMENT_ENGINE.md](MATURITY_ASSESSMENT_ENGINE.md) | CKM-07 | Seven-dimension explainable vector + transparent aggregate + citations, incremental |
| [GAP_AND_MISSING_EVIDENCE_DETECTION.md](GAP_AND_MISSING_EVIDENCE_DETECTION.md) | CKM-08 | Gap findings (starved dimensions, uncovered boundaries) + claim-exceeds-evidence tensions |
| [CKM_PROJECTIONS_AND_QUERY.md](CKM_PROJECTIONS_AND_QUERY.md) | CKM-09 | BuilderOps Markdown projections + CLI query surface, watermark + self-identification |
| [DEV_OVERVIEW_HTML_PROJECTION.md](DEV_OVERVIEW_HTML_PROJECTION.md) | CKM-10 | Static-HTML Development Overview (capability map + maturity heatmap) + parent-closure handoff |

## Execution order

```
CKM-01 ──┬── CKM-02 ──┐
         ├── CKM-03 ──┼── CKM-05 ──┬── CKM-06 (parallel with CKM-07)
         └── CKM-04 ──┘            └── CKM-07 ── CKM-08 ── CKM-09 ── CKM-10
```

Flat order: CKM-01 → (CKM-02 ∥ CKM-03 ∥ CKM-04) → CKM-05 → (CKM-06 ∥ CKM-07) → CKM-08 → CKM-09 → CKM-10.
CKM-06 is not on the critical path: assessment (CKM-07) runs on deterministic edges alone and simply gains coverage when semantic edges exist.

## Cross-Task Invariants / Interaction Safety

These invariants hold *across* task boundaries; each task names the ones it must preserve.

- **INV-CKM-1 (provenance everywhere).** Every artifact record, evidence edge, assessment, and finding carries provenance (source ref, extraction method, model/provider when inferred, timestamps). No CKM row exists without a reconstructible origin. A row that cannot answer "where did you come from" is a bug, not a degradation.
- **INV-CKM-2 (projection-only egress).** Nothing the CKM emits (projection file, CLI output, HTML page) is authority. Every egress self-identifies as a generated projection and carries the ingestion watermark. No CKM code path writes product-plane files, GitHub state, or runtime stores.
- **INV-CKM-3 (candidate vs confirmed, OD-K5).** Inferred capabilities/edges are `candidate` until a human confirmation receipt promotes them; deterministic-linker edges are `confirmed` by construction. Every consumer surface (assessment, projections, HTML) must distinguish the two — an assessment must state how much of its evidence is candidate.
- **INV-CKM-4 (rebuildability).** Drop CKM tables → re-run seed + ingestion + linking ⇒ equivalent CEG (minus confirmation receipts, which live as BuilderOps receipts and re-apply). No task may introduce state that survives only in the CKM tables.
- **INV-CKM-5 (watermark honesty — the ingest/assess seam).** Ingestion advances a per-source watermark; assessment records the watermark set it read. If ingestion has advanced past the newest assessment (partial failure: ingest committed, assess crashed or not yet run), every projection must display the assessment as **stale relative to evidence**, not silently current. An assessment is never patched in place; a re-assessment is a new bitemporal row.
- **INV-CKM-6 (orthogonality, OD-K3).** CKM `evidence_kind` never reads, writes, or maps onto the runtime `evidence_role`/`authority_state`/`source_role`. Enforced by the CKM-01 fitness check; every later task inherits it.
- **INV-CKM-7 (idempotent re-runs).** Seed, ingestion, and linking are idempotent: re-running against unchanged sources produces no new rows (stable natural keys), so partial failures are always safe to retry from the top.

Partial-failure walk: seed applied but ingestion fails → registry exists with zero evidence; assessments render as "no evidence" (honest). Ingestion commits but linker fails → artifacts visible as unlinked backlog (CKM-09 projects an "unlinked artifacts" count); retry is idempotent (INV-CKM-7). Assessment lags evidence → INV-CKM-5 staleness surfaces it. Confirmation receipt written but graph rebuilt → receipt re-applies on rebuild (INV-CKM-4).

## Acceptance criteria (capability level)

- [x] The CEG exists in the BuilderOps store, seeded from SBS + Capability Contract Model, populated with evidence from repo + GitHub sources, and rebuildable from scratch. Verify: `tests/builderops/ckm/test_rebuild_roundtrip.py::test_drop_and_rebuild_reproduces_graph`
- [x] Every capability has a seven-dimension assessment where every dimension cites its evidence, with candidate/confirmed share visible. Verify: `tests/builderops/ckm/test_assessment_engine.py::test_every_dimension_cites_evidence`
- [x] Gap and missing-evidence findings are generated and specific (capability + dimension + citation). Verify: `tests/builderops/ckm/test_gap_detection.py::test_findings_name_capability_dimension_and_citation`
- [x] Projections + CLI + HTML overview exist, self-identify as projections, and carry watermarks. Verify: `tests/builderops/ckm/test_projections.py::test_all_egress_self_identifies_with_watermark` and `tests/builderops/ckm/test_overview_html.py::test_projection_footer_always_present`
- [x] The orthogonality contract holds on the live path. Verify: `tests/builderops/ckm/test_evidence_kind_orthogonality.py::test_ckm_never_touches_runtime_evidence_role`
- [ ] Owner has viewed the Development Overview against the real repo and the parent issue records the validation receipt. Verify: parent feature issue validation comment (operator receipt)

## Relationship to GitHub issues

Parent feature issue: [#3138](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3138) — the live validation hub (blocked, not directly picked up); draft archived in [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). Children: CKM-01 #3139, CKM-02 #3140, CKM-03 #3141, CKM-04 #3142, CKM-05 #3143, CKM-06 #3144, CKM-07 #3145, CKM-08 #3146, CKM-09 #3147, CKM-10 #3148. The spec is authoritative; issues track backlog state.

## Verification path

Each task ships its own tests under `tests/builderops/ckm/` (named in each task's ACs) and passes the standard `not pg` suite. No task requires the integrated-runtime UAT (builder-plane only, no vault/hot-path surface).

## Validation / acceptance path

After CKM-09/CKM-10 merge: run the full pipeline against the live repo, attach the generated overview + projections to the parent issue as the validation receipt, owner eyeballs the capability map for sanity (grain, obvious mis-associations). Owner-doc promotion (README/DOCS_INDEX rows claiming the CKM as a supported builder capability, plus a `docs/builderops/` owner doc) happens once acceptance is recorded — not before.
