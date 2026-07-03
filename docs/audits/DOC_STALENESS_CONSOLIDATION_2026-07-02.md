State: Audit report (point-in-time docs-staleness consolidation audit, 2026-07-02; advisory, not normative).
Doc role: Reference (advisory audit snapshot)
Authority: Advisory only; subordinate to docs/DOCS_INDEX.md and owner contracts. Corrections applied via the PR that lands this doc; residual/deferred items tracked below.

# Doc Staleness Consolidation — Audit (2026-07-02)

**Status:** Audit / evidence-based review. Corrections are applied in the same delivery wave as this report.
**Scope:** The active `docs/` tree — roughly 783 tracked Markdown files — audited via 21 evidence
clusters (delivery-writeback drift, duplicate index rows, structural bloat, archive candidates, and
cross-repo mechanical staleness) with adversarial verification against `main` before any correction
landed.
**Source anchors:** each corrected doc is cited by path in [What was fixed](#what-was-fixed); each
deferred item carries its own follow-up pointer in [Deferred](#deferred).

---

## TL;DR

The dominant failure mode is **delivery-writeback drift**: roughly 20 owner docs and specification
directories kept describing capabilities as "forward line / not yet shipped" or issues as "open /
blocked" long after the governing GitHub issues closed and the code landed (Contextual Relevance
Engine, Dispatcher Agent Adoption, Observability Stabilization, Telemetry Relocation, Orchestrator
A2A Routing, Scope/Sphere/Situated Identity, Commitment Surfacing, Agent Memory, Release Channels,
and others). A second, narrower drift pattern is **stale SoT epic framing**: `docs/STATUS.md` and
`docs/ROADMAP.md` both described epic #1874 (Integrated Runtime v1) as open long after it closed
2026-06-12. `docs/DOCS_INDEX.md` itself carried duplicate rows for the same path with divergent status
(`docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md`, `docs/plans/MAJOR_ROADMAP_RESET_2026_06_04.md`,
`docs/plans/SPHERE_CONTEXT_ENABLEMENT_PREP.md`, `docs/runbooks/RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md`)
and was missing a row for the shipped ADR-0040.

`docs/INTEGRATED_RUNTIME_V1/` (a self-declared non-authoritative planning package, superseded by the
now-closed #1874) was archived to `docs/archive/INTEGRATED_RUNTIME_V1/` with a redirect stub left at
the old path.

An index-structure bloat measurement found `docs/DOCS_INDEX.md` carrying 479 table rows with an
average Notes-cell length of ~405 characters; two sections alone (`Core SoT Docs` and `v6.0 Capability
Specifications`) account for roughly 64% of the file's total bulk. This is a maintainability signal,
not a correctness defect, and is deferred to a follow-up slimming pass rather than corrected here.

Adjacent findings outside `docs/`: a handful of stray root-level files were removed by a prior
companion-repair PR (already resolved, recorded here for completeness); the Companion UI capability
index has a coverage gap (17 of 54 relevant files indexed); and `.codex/` carried three small
mechanical staleness issues (fixed as part of this pass where in scope).

---

## Method

Evidence was gathered by re-grepping every flagged claim directly against the working tree immediately
before editing it (not against the original audit snapshot), so any claim already corrected by a
sibling agent or an intervening PR was skipped and recorded as already-fixed rather than re-applied.
Closure facts for GitHub issues cited in corrections were cross-checked against `docs/STATUS.md`,
`docs/DOCS_INDEX.md`, and owner docs that already carried the delivered-reality framing (e.g.
`docs/AGENT_ISSUE_DISPATCHER.md` for the dispatcher adoption facts), with a small number of direct
GitHub REST reads reserved for facts that could not be confirmed from in-repo evidence alone. No
runtime code changed; every correction is a docs-only surgical edit that preserves each doc's existing
header conventions and spec-body content.

---

## What was fixed

- **`docs/STATUS.md`, `docs/ROADMAP.md`** — Integrated Runtime v1 (#1874) reframed from "open/active" to
  closed/delivered (closed 2026-06-12, PRs #1882-#1888); local test-bootstrap path reframed from "not
  fully self-contained" to delivered (#331-#336 closed, `make test-bootstrap` shipped).
- **`docs/INTEGRATED_RUNTIME_V1/` → `docs/archive/INTEGRATED_RUNTIME_V1/`** — archived (git mv, 4 files);
  redirect stub left at the old `README.md` path; `docs/DOCS_INDEX.md` row updated; internal
  cross-references repointed.
- **`docs/DOCS_INDEX.md`** — added the missing ADR-0040 row; reconciled duplicate rows for
  `ONTOLOGY_ALIGNMENT_PLAN.md`, `MAJOR_ROADMAP_RESET_2026_06_04.md`, `SPHERE_CONTEXT_ENABLEMENT_PREP.md`,
  and `RUNBOOK_AGENTOPS_INCIDENT_TRIAGE.md` down to one row each; swept stale #2510-pending phrasing on
  the `RECALL_RUNTIME_ACTIVATION`, `VAULT_OPTIONAL_RUNTIME`, and `COMMITMENT_SURFACING` rows (#2510 is
  closed); extended the `AGENT_MEMORY/README.md` row's note to cover the un-indexed sibling spec
  `DEFINE_MEMORY_LIFECYCLE_ARCHIVE_AND_FORGET.md`.
- **Delivery-writeback corrections** (State lines / issue-status footers rewritten to delivered
  reality, spec bodies unchanged): `docs/CONTEXTUAL_RELEVANCE_ENGINE/README.md` and its four task
  specs; `docs/CONCEPTS/MOMENT_ARTIFACT_CONTRACT.md`, `RELEVANCE_EVALUATOR_CONTRACT.md`,
  `REACHOUT_AND_SCARCITY_GATE_CONTRACT.md`; `docs/DISPATCHER_AGENT_ADOPTION/README.md` (all seven
  acceptance boxes checked with cited evidence); `docs/LOCAL_TEST_BOOTSTRAP/README.md`;
  `docs/EMBEDDING_RELIABILITY/README.md` + `PARENT_FEATURE_ISSUE.md` (children closed, parent #2292
  precisely stated as still open); `docs/OBSERVABILITY_STABILIZATION/README.md` +
  `PARENT_FEATURE_ISSUE.md` (all 11 children closed, parent #2597 open-by-design noted);
  `docs/TELEMETRY_RELOCATION/README.md`; `docs/ORCHESTRATOR_A2A_ROUTING/README.md` (parent #359 closed,
  directory retained per its cross-link from `docs/tracks/TRACK_AGENTOPS_A2A_MCP.md`);
  `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md` (implementation delivered, owner-doc promotion now
  tracked by #2825); `docs/COMMITMENT_SURFACING/PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md` +
  `EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md`; `docs/AGENT_MEMORY/PARENT_FEATURE_ISSUE.md` +
  `ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`; `docs/RELEASE_CHANNELS/README.md` (resolver layer #594
  closed).
- **Other current-state corrections**: `docs/runbooks/E2E_ALPHA.md` (added the Legacy caveat for
  `make alpha-up` pointing at `RUNBOOK_STARTUP_FULL_SYSTEM.md`); `docs/architecture/IMPORT_BOUNDARY_INVENTORY.md`
  (import-linter CI flipped from non-blocking to blocking via #2481); `docs/plans/DRAFT_EXPANSION_ACTIVATION_GATE.md`
  (corrected the "not wired into DOCS_INDEX" claim and the #2022 progress undersell);
  `docs/plans/ONTOLOGY_ALIGNMENT_PLAN.md`, `ONTOLOGY_EXECUTION_COORDINATION.md`,
  `ONTOLOGY_STATUS_NEXT_DECISIONS.md` (marked concluded/historical; two live inbound pointers in
  `docs/DOCS_INDEX.md` and `docs/AGENTS.md` reworded); `docs/plans/V56_FORWARD_LINE.md` and
  `docs/AGENTS.md` (backfilled the standard `Doc role:`/`Authority:` header block); `docs/INVENTORY.md`
  (EMBED_DIM row cross-referenced to `docs/EMBEDDINGS.md`).

## Deferred

- **`docs/DOCS_INDEX.md` slimming** — the 479-row / ~405-char-average-Notes structural bloat measured in
  this audit is a follow-up issue, not corrected here (correctness rows were fixed; structural
  reorganization was not).
- **Row-adds for `schemas/README.md` and `ops/host-setup/README.md`** — both files exist and are
  un-indexed; deferred to a Wave B index-authority pass rather than added ad hoc in this PR.
- **Archive candidates gated on open parents** — directories whose validation hubs remain open by
  design (#2597 Observability Stabilization, #2292 Embedding Reliability, #2443) are left in place
  rather than archived, since their parents are not yet closed.
- **BuilderOps projection regen** — the generated `docs/generated/builderops/*` projections are
  operational artifacts regenerated from the BuilderOps Vault, not something this docs-authoring pass
  edits directly.
- **`design_handoff/` (23MB)** — grandfathered; out of scope for a docs-staleness pass.
- **Companion UI capability index gap (17/54)** — flagged, not remediated here; belongs to a Companion
  UI-specific indexing pass.

## Residual uncertainty

This audit corrects the claims that were checked; it does not re-verify every row of
`docs/DOCS_INDEX.md`, and other stale delivery-writeback drift of the same shape may remain
undiscovered outside the 21 evidence clusters this pass covered. Treat this report as a snapshot of
what was found and fixed on 2026-07-02, not an exhaustive staleness sweep.
