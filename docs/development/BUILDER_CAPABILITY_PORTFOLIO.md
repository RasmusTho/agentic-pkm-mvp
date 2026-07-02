State: Advisory proposal (2026-07-02). Builder System capability portfolio — proposes candidate builder capabilities with build-vs-defer recommendations; nothing here is built or ratified by this doc. Owner triage decides which entries become issues. Not Product/Runtime truth.

# Builder Capability Portfolio

Proposal doc from RESEARCH-05 (#2783, child of #2778): builder-side capabilities that do **not**
exist today, each with a trigger, cost/benefit sketch, TCD placement per
`AGENTS.md :: Total Cost of Development`, and a build-vs-defer recommendation grounded in what the
repo already has. The companion deliverable — the repeatable research workflow itself — is
`.codex/skills/architecture-research/SKILL.md`.

Evaluation frame: a capability is worth building when it converts recurring human/coordinator time
or recurring defect classes into deterministic or cheap-model machinery (TCD decision rule), and
worth deferring when its substrate does not exist yet or existing machinery already covers the
same failure class.

## Summary

| Capability | Recommendation | Why (one line) |
| --- | --- | --- |
| 1. Architectural regression detection | **Defer** | Comparison substrate (typed transitions, schema registry) lands with the Correctness Kernel first |
| 2. Semantic diffing | **Build small** (review-lens), defer tooling | Prompt-level lens on the existing local review gate is nearly free; dedicated tooling is not |
| 3. Invariant synthesis | **Built** (as skill phase), defer automation | Delivered as `architecture-research` Phase 4; standalone automation has no added trigger yet |
| 4. Eval-case generation from failures | **Defer** until KERNEL-15 ships | Generalizing a pattern before its first instance exists is speculation |
| 5. Documentation reconciliation | **Build** | Known recurring defect class (stale doc claims), cheap to run, no missing substrate |
| 6. Specification repair | **Build small** (deterministic checker) | Anchor rot is machine-checkable; repeated anchor-drift learnings justify it |

## 1. Architectural regression detection

Diff a PR's effect against the formal model's allowed state transitions — does this change add a
store writer, a new untyped LLM boundary, an event topic without schema, a bypass around
WriteGuard?

- **Trigger:** every PR touching `app/` (as a CI lens), or on demand before merge of high-risk
  slices.
- **Exists today:** the static fitness suite — `tests/architecture/` (import boundaries per
  ADR-0013, SBS fitness rules, component boundaries, deprecated-store-caller checks), the
  `import-linter` workflow, and the 36-invariant registry (`docs/testing/invariant-tests.md`)
  enforced from `tests/invariants/`. These check *structure*, not *transition deltas*: they catch
  a forbidden import, not "this PR added a second writer for a table" as a diff-level statement.
- **Cost/benefit:** high benefit in principle (the audit's CW-1/CW-4 classes are exactly
  unnoticed regressions), but the comparison target — typed event topics, registered schemas, a
  single-writer register — is what the Runtime Correctness Kernel (KERNEL-03/08, I-S1/I-E5) is
  building now. Built today it would diff against an unconstrained baseline and mostly restate
  the existing static gates. Build cost: medium-high (needs a durable model of "allowed
  transitions" to diff against).
- **TCD placement:** integrate/verify stage; deterministic where possible, Sonnet/high for the
  semantic delta summary.
- **Recommendation: Defer.** Revisit after KERNEL-08 (topic schema registry) and KERNEL-03
  (single store generation) land — at that point the registry and writer map *are* the transition
  model and the capability becomes a cheap diff over declared state.

## 2. Semantic diffing

Summarize a PR as contract-level deltas instead of line deltas: schemas touched, event topics
added/changed, invariants exercised, authority classes crossed, owner docs implicated.

- **Trigger:** review time on Tier 2+ PRs; especially multi-file slices where line diffs hide the
  contract change.
- **Exists today:** the local code-review gate (Codex/Claude review before merge), `pr-contract`
  surface checks, and the post-merge-owner-doc skill (which already reads diffs and decides doc
  impact — a manual semantic diff).
- **Cost/benefit:** the benefit is reviewer/coordinator time (the dominant TCD term) and fewer
  missed owner-doc writebacks. A *prompt-level lens* — instructing the existing review gate to
  lead with contract deltas — costs one skill/prompt edit. A dedicated tool (AST/schema diffing)
  costs real build+maintenance and duplicates what the review model already infers.
- **TCD placement:** integrate/verify stage; Sonnet/medium as part of the existing review pass —
  no extra model run.
- **Recommendation: Build small.** Add a contract-delta lead-in to the local review gate's
  instructions; defer any standalone semantic-diff tooling until the lens demonstrably misses
  classes of change.

## 3. Invariant synthesis

Turn observed system behavior and weaknesses into named, enforcement-categorized invariants
(MUST / GATE / DOCTOR) — RESEARCH-03's method as a repeatable capability.

- **Trigger:** during an architecture research pass; after an incident whose class has no named
  invariant.
- **Exists today:** the invariant registry (`docs/testing/invariant-tests.md`, 36 invariants,
  enforced from `tests/invariants/`) and, as of this PR, the method itself encoded as
  `architecture-research` Phase 4 (extraction rules, enforcement categories, minimal-kernel
  discipline, extend-don't-fork registry rule).
- **Cost/benefit:** the marginal capability beyond the skill phase would be *standalone*
  synthesis (e.g. a scheduled pass proposing invariants from incident streams). Incident volume
  today is too low to feed it; the audit produced its nine-invariant kernel in one coordinated
  pass without needing standing machinery.
- **TCD placement:** decompose/plan stage; Opus/xhigh-tier (it is exactly the
  architecture/high-defect-cost case).
- **Recommendation: Built as a skill phase; defer standalone automation.** The repeatable form
  ships in `architecture-research/SKILL.md`; no separate capability issue is warranted now.

## 4. Eval-case generation from failures

Convert failures into permanent regression material automatically — generalizing KERNEL-15's
failure-to-eval capture loop (runtime dead-letters and UNKNOWN classifications drafted as eval
cases) to the builder plane: CI failures, review-gate catches, and reverted slices drafted as
governance-test or golden-set candidates.

- **Trigger:** any dead-letter/UNKNOWN (runtime plane, KERNEL-15); any repeated CI failure class
  or review-gate catch (builder plane, the proposed generalization).
- **Exists today:** the KERNEL-15 spec
  (`docs/RUNTIME_CORRECTNESS_KERNEL/FAILURE_TO_EVAL_CAPTURE_LOOP.md`, issue #2777, not yet
  implemented) for the runtime plane; on the builder plane, the learning-signal machinery
  (`capture-learning` → BuilderOps `LearningSignal` → `learning-retrospective` →
  `learning-to-issue`) already captures divergences — but as prose signals, not executable cases.
- **Cost/benefit:** the runtime half is already specced and issued; duplicating it here would
  violate reconcile-don't-duplicate. The builder-plane generalization is attractive (Codex review
  caught a real prod-path bug on every slice of the observability epic — those catches are
  currently only prose learnings) but its right shape depends on how KERNEL-15's review-queue +
  draft-case pattern actually works in practice.
- **TCD placement:** retrospect stage; Haiku/Sonnet-low for drafting, human/agent adjudication as
  the gate (matching KERNEL-15's human-confirmed queue).
- **Recommendation: Defer until KERNEL-15 ships,** then evaluate extending its capture pattern to
  builder-plane signals via a `learning-retrospective` extension rather than new machinery.

## 5. Documentation reconciliation

Scheduled doc-vs-code divergence sweeps: verify that owner-doc claims still match code reality,
with `file:line` evidence — generalizing RESEARCH-01's Divergences method (each divergence carries
both a doc anchor and a code anchor).

- **Trigger:** cadence (e.g. monthly per owner-doc cluster) or before an epic is planned against a
  doc cluster.
- **Exists today:** `temporal-doc-governance` (freshness of time-sensitive docs),
  `backlog-reconciliation-drift-audit` (GitHub-state drift), `scripts/docs_guard.py` and
  `tests/architecture/test_docs_index.py` (structural/index conformance), BuilderOps
  `DocsFreshnessRecord`. None of these check *claims against code*: the 2026-07-02 audit found a
  stale "#2025 pending" authority claim in a concept contract that every structural check passed.
- **Cost/benefit:** doc-staleness is a proven recurring defect class in this repo (stale spec
  pointers, roadmap wording that still reads as pending, "not yet implemented" over shipped
  code), and each instance costs agent misrouting or duplicate work. Run cost is low: it is the
  explorer-brief format from `architecture-research` Phase 1 pointed at one doc cluster —
  Sonnet-tier, read-only, output = divergence list routed to `docs-authoring` or
  `issue-maintenance-change-control`. No missing substrate.
- **TCD placement:** its own maintenance lane; Sonnet/medium explorers, findings adjudicated by
  the coordinator or routed directly when unambiguous.
- **Recommendation: Build.** Cheapest of the six relative to demonstrated recurring cost. Shape:
  extend `temporal-doc-governance` with a claims-vs-code sweep mode reusing the
  `architecture-research` evidence-brief contract, rather than a new skill.

## 6. Specification repair

Detect stale anchors in specification directories: task-file `source_anchor` frontmatter,
`file:line` references, and issue links that no longer resolve after the code or docs moved.

- **Trigger:** cadence over `docs/*/` spec directories with open child issues; before an agent
  picks up a spec-derived issue.
- **Exists today:** consumption-time handling only — `issue-to-code`'s source-anchor resolution
  rules (continue through anchor drift, report it) and DOCS_INDEX anchor checking
  (`tests/architecture/test_docs_index.py :: test_no_broken_intra_repo_anchors`, DOCS_INDEX links
  only). Spec-directory anchors rot silently until an implementing agent trips on them; anchor
  drift is a repeat LearningSignal theme.
- **Cost/benefit:** detection is almost fully deterministic (path exists, anchor heading exists,
  issue state matches the header claim) — a script, not a model. Repair stays with existing lanes
  (`issue-maintenance-change-control` / `docs-authoring`). Build cost: small script + optional
  non-blocking CI report; benefit: agents stop discovering rot mid-implementation.
- **TCD placement:** deterministic (no model) for detection; repair routed per existing skills.
- **Recommendation: Build small.** A deterministic checker extending the existing
  `test_docs_index.py` pattern to spec-directory frontmatter and intra-doc anchors, reported
  non-blocking first (matching the import-boundary gate's rollout posture).

## Relationship to existing machinery

Cited current-state substrate (what the recommendations are grounded in):

- Index doctor: `app/index/doctor.py` + `app/cli/index_doctor.py` — the repo's exemplar of the
  DOCTOR enforcement category (read-only detection, explicit repair), extended by #2753.
- Invariant registry: `docs/testing/invariant-tests.md` + `tests/invariants/`.
- Runtime Correctness Kernel: `docs/RUNTIME_CORRECTNESS_KERNEL/` (#2762–#2777), esp. KERNEL-15
  (`FAILURE_TO_EVAL_CAPTURE_LOOP.md`).
- Learning-signal machinery: `capture-learning`, `learning-retrospective`, `learning-to-issue`
  skills + BuilderOps `LearningSignal` records.
- Architecture fitness gates: `tests/architecture/`, `import-linter` workflow, ADR-0013.

## Next step

Owner triage: each **Build** / **Build small** entry becomes its own bounded issue
(`docs-to-issue` from this doc) only after triage; nothing here authorizes implementation.
