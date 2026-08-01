State: ACCEPTED/DELIVERED Capability Knowledge Model (CKM / Kvasir) MVP, enacted by ADR-0057. Validation parent #3138 is closed after children #3139-#3148 and presentation refinement #3689; current-main acceptance and owner visual acceptance are recorded on the parent. This directory remains the MVP contract/history owner. Post-MVP structured access and measurement are owned by `docs/CKM_MEASUREMENT_AND_ACCESS/`. Builder System work (BuilderOps plane); not Product/Runtime truth.
Doc role: Specification directory (capability breakdown)
Authority: Owns the MVP task decomposition, execution order, cross-task invariants, and acceptance path for the CKM. Subordinate to ADR-0057 (decisions), ADR-0010 (BuilderOps authority), `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md` (grounding SRS), `docs/CAPABILITY_CONTRACT_MODEL.md` and `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (seed taxonomy owners).
Owner: BuilderOps governance
Temporal class: snapshot (accepted/closed contract and delivery history)
Review cadence: event-driven
Source of truth: mixed (this directory for task shape; ADR-0057 for decisions)
Last reviewed: 2026-08-01

# Capability Knowledge Model (CKM / Kvasir) — MVP Specification

The CKM is the Builder System subsystem that continuously constructs and maintains an evidence-backed model of the Yggdrasil platform: **Capability** as primary entity, every engineering artifact as typed **Evidence**, and an explainable seven-dimension **maturity assessment** per capability. Full rationale, prior art, and requirements: [DEVELOPMENT_KNOWLEDGE_MODEL.md](../research/DEVELOPMENT_KNOWLEDGE_MODEL.md). Decisions: [ADR-0057](../adr/ADR-0057-capability-knowledge-model-kvasir.md).

**Work classification (SBS operating model):** Builder System. Implementation home `app/builderops/ckm/`, tests `tests/builderops/ckm/`, store = existing BuilderOps SQLite substrate (OD-K4). No Product/Runtime subsystem is touched; the product repo is read-only input.

**MVP scope (OD-K1):** seed → ingest → link → assess → detect gaps → project. **Deferred:** drift detection (FR-8; waits for the Correctness Kernel registry), closed-loop writeback, predictive maturity, cross-repo federation.

**Amended 2026-07-27 (ADR-0057 A1) — what "closed-loop writeback" still defers.** The deferral continues to bind *the CKM*: no CKM component may file or edit an Issue, and the write-class restriction (`analytical`/`projection`/`receipt` only) is unchanged. What is no longer deferred is the *external* path — a builder agent may read CKM-surfaced gaps and drive delivery from them, holding exactly the authority Claude Code and Codex already hold, through the ordinary Issue contract, publication boundary, CI, and review gate. The distinction is the one ADR-0057 §7 always drew: action is an agent's decision outside the knowledge model, never a CKM effect. Drift detection, predictive maturity, and cross-repo federation stay deferred as written.

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

Post-MVP presentation refinement: [DEV_OVERVIEW_DIRECTION_A.md](DEV_OVERVIEW_DIRECTION_A.md) defines the CKM-11 redesign contract implemented by issue #3689. It preserves CKM-10's static, self-contained projection boundary; owner visual acceptance remains on parent #3138.

## Supported opt-in presentation successor

[CKM Cockpit Direction B](../CKM_COCKPIT_DIRECTION_B/README.md) is the bounded opt-in successor
to the same generated Development Overview. Independent parent
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080) accepted and closed the capability
on 2026-07-28 after completion issue
[#4222](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4222) and
[PR #4224](https://github.com/RasmusTho/agentic-pkm-mvp/pull/4224) supplied the protected
production-CLI proof. The supported surface is an opt-in local `ckm overview --cockpit` projection
with exact newest-pair O1b
comparison-or-refusal, one filtering-only inline script, inert drafts, and deterministic print.
It remains generated, local, deterministic, and non-authoritative: it creates no CKM, GitHub,
Product/Runtime, or network write authority. Direction A remains the script-free default; Direction
B is the supported opt-in cockpit mode. Exact acceptance and closure receipts are recorded on
[#4080](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102696743) and its
[terminal closure receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4080#issuecomment-5102745391).

## Adjacent Builder capability: design-agent integration (delivered, dormant)

[CKM Design-Agent Integration](../CKM_DESIGN_AGENT_INTEGRATION/README.md) is delivered and merged.
Its six child slices #4308–#4313 are closed with merged PRs on `main`, supplying the
provider-neutral design-run contracts, the exact three-adapter registry
(`claude-design-via-claude-code`, `codex`, `fable`) above the ADR-0064 model-access substrate, the
governed admission/approval/receipt lifecycle, the `builderops design-run` operator CLI, and the
read-only Direction B cockpit projection. It is Builder System machinery *around* the CKM, not a new
CKM authority class: INV-CKM-2 is unchanged, the design hub is not a Product/Runtime capability,
there is no provider ranking, recommendation, selection, or fallback, and no design result is
accepted repo or product truth.

**The capability ships dormant and fail-closed, and no design run can execute.** The host secret
contract declares no `builderops-design-run` consumer on any channel, so all three registered design
agents report `available=False` on `dev`, `test`, and `prod` — `codex` and `fable` with
`model_access_unavailable`, `claude-design-via-claude-code` with `interactive_subscription_only` —
and no credential is read on the availability path.

What the production acceptance matrix proves is *governance semantics*: exact admission and approval
hash binding, append-only causal receipts, one provider turn at most, no fallback, sanitized adapter
identity, Yggdrasil-gated visual deliverables, and handoffs labelled unaccepted Builder material. It
does not prove provider execution. Those governed-success rows run above a doubled model-access
resolver and turn-adapter port, and therefore also bypass production host-secret-contract
authorization; they demonstrate governance above a *successful resolution*, not that a real
credential grant would execute. Nothing in this repository establishes that design-agent runs work,
are available, are enabled, or have been proven end to end against a real provider.

`claude-design-via-claude-code` is never headless-available. That follows from INV-CDH-5A as an
invariant — not from configuration and not from the absent grant: the route is hard-refused inside
the adapter registry before any adapter lookup, and stays refused even when the other two routes
resolve. Its `interactive_subscription_only` string is an availability-**descriptor** code; at run
level that route yields the generic `adapter_unavailable`, the same code the dormant no-adapter case
yields, so no distinct run-level refusal code exists for it.

The `design_agent_profiles` entries in `docs/settings/models/providers.yaml` — including the `prod`
rows that name real frontier models and real credential identifiers — are ADR-0064 census
declarations, not provisioning. They do not make this an enabled production capability. Dormancy
rests on the absent `builderops-design-run` consumer in the host secret contract; enabling a run
would require a separate governed change to that contract.

Parent validation hub [#4131](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4131) governs
acceptance and closure for this capability; GitHub owns its current open/closed state and labels,
not this doc. The
[conditional acceptance receipt](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4131#issuecomment-5149608088)
authorized exactly this docs-only owner-doc promotion and, by itself, ticks no acceptance criterion;
the hub's closure criterion is a separate post-promotion fresh independent audit of the merged
promotion diff.

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

- [x] The CEG exists in the BuilderOps store, seeded from SBS + Capability Contract Model, populated with evidence from repo + GitHub sources, and rebuildable from scratch. Verify: `tests/builderops/ckm/test_store.py::test_upsert_idempotent_and_rebuild`; `tests/builderops/ckm/test_seed.py::test_seed_idempotent_and_incremental`
- [x] Every capability has a seven-dimension assessment where every dimension cites its evidence, with candidate/confirmed share visible. Verify: `tests/builderops/ckm/test_assessment_engine.py::test_every_dimension_cites_evidence`
- [x] Gap and missing-evidence findings are generated and specific (capability + dimension + citation). Verify: `tests/builderops/ckm/test_gap_detection.py::test_findings_name_capability_dimension_and_citation`
- [x] Projections + CLI + HTML overview exist, self-identify as projections, and carry watermarks. Verify: `tests/builderops/ckm/test_projections.py::test_all_egress_self_identifies_with_watermark`; `tests/builderops/ckm/test_overview_html.py::test_provenance_banner_precedes_map_and_footer_remains`
- [x] The orthogonality contract holds on the live path. Verify: `tests/builderops/ckm/test_evidence_kind_orthogonality.py::test_ckm_never_touches_runtime_evidence_role`
- [x] Owner has viewed the Development Overview against the real repo and the parent issue records the validation receipt. Verify: [owner visual acceptance receipt on #3138](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3138#issuecomment-4974008965)

## Relationship to GitHub issues

Accepted parent feature issue: [#3138](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3138), closed 2026-07-15 with a complete parent receipt; checked-in contract: [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). Delivered children: CKM-01 #3139, CKM-02 #3140, CKM-03 #3141, CKM-04 #3142, CKM-05 #3143, CKM-06 #3144, CKM-07 #3145, CKM-08 #3146, CKM-09 #3147, CKM-10 #3148, and presentation refinement CKM-11 #3689. Successor validation hub: #3775 with contract at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`.

## Verification path

Each task ships its own tests under `tests/builderops/ckm/` (named in each task's ACs) and passes the standard `not pg` suite. No task requires the integrated-runtime UAT (builder-plane only, no vault/hot-path surface).

## Validation / acceptance path

Acceptance completed: the full live pipeline and generated overview/projections were attached to #3138; CKM-11 #3689 then received explicit owner visual acceptance for desktop, expanded-row, 390×844, and 200%-zoom-equivalent states. Current-main reconciliation on 2026-07-15 re-ran the corrected parent acceptance ledger (10 passed) before closing #3138. This README and `docs/DOCS_INDEX.md` now state accepted MVP truth; successor access/measurement work makes no shipped claim until its own parent #3775 closes.
