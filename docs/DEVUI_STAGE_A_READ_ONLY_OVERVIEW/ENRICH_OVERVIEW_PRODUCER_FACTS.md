---
name: Enrich Overview Producer Facts
description: Transport only accepted source-owned owner-attention and ready-to-try facts through the current Cockpit/composition producer chain.
task_id: ARO-02
github_issue: 4743
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-01]
depends_on: [AUTHORIZE_OVERVIEW_SOURCE_FACTS.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Cross-source producer wiring must preserve authority, linkage, freshness, and hostile no-inference behavior."
execution_context: fresh_issue_agent
issue_local_helper_budget: 1
context_cost_estimate: high
complexity: high
verification_difficulty: high
defect_blast_radius: high
review_gate: independent semantic review plus exact-head CI
---

# Enrich Overview Producer Facts

## Purpose

Carry only authorized producer facts into the delivered Overview composer.

## Context

Parent: #4741

Expose explicit Overview candidates from the existing read producer chain only after ARO-01 names
their canonical source facts. Missing or unsupported facts remain withdrawals.

## What This Task Does

- Carries accepted source-owned category/governing-source/subject/evidence fields for **Needs you**.
- Carries accepted receipt-backed `ready_to_try`/subject/evidence fields for **Ready to try**.
- Supplies candidates to the delivered composer at the production composition call site.
- Preserves Now and every degraded/withdrawn state without source or lifecycle inference.

## Concretely

An exact category/source/linkage tuple may produce a Needs-you candidate; an `agent:needs-human`
label without that tuple produces no candidate. The same rule applies to explicit ready-to-try
receipts versus generic terminal delivery facts.

## Why This Matters

This is the last source boundary before server classification, so inference here would be rendered
as owner truth everywhere downstream.

## Scope

- Modify only the current source-to-composition chain named under Constraints.
- Add production-call-site and hostile-input tests for both admitted and withdrawn facts.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A — see: coherent read-only devUI`

## SBS Impact

- Primary subsystem: Builder System / BuilderOps producer plane
- Secondary subsystem(s): devUI composition and Cockpit registry
- Write class: read-projection producer enrichment
- Authority impact: none; transports only ARO-01-owned facts
- Persistence impact: no new persistence
- Derived/rebuildable impact: adds per-read Overview candidates
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: no new retrieval
- Sync/deployment impact: local BuilderOps/API process only
- External boundary impact: existing GitHub read boundary only if authorized by ARO-01
- New or changed contract: explicit Overview candidate fields in current producer chain
- Owner-doc impact: none after ARO-01
- Transition debt impact: removes label/delivery-state inference pressure
- Fitness rule impact: hostile no-inference and cross-field producer tests

## Constraints

Allowed production files are `app/builderops/sync_github.py`,
`app/builderops/cockpit_registry.py`, and `app/builderops/devui_composition.py`; allowed tests are
their existing focused test modules. If ARO-01 selects a source that cannot be transported inside
this boundary, this child remains blocked and must be superseded by a new breakdown.

## Acceptance Criteria

- [ ] Only ARO-01-authorized fields enter Overview candidates at the production call site.
  - Verify: `tests/builderops/test_devui_composition.py :: test_overview_candidates_preserve_authorized_source_facts`
- [ ] A supported owner category carries exact governing source, subject linkage, and actionable
      evidence; missing/unknown/degraded fields withdraw it.
  - Verify: `tests/builderops/test_cockpit_registry.py :: test_overview_owner_question_requires_explicit_canonical_category`
- [ ] `ready_to_try` requires the exact authorized receipt type/source and linked actionable
      evidence; merge/done/closure/delivery alone never produces it.
  - Verify: `tests/builderops/test_devui_composition.py :: test_overview_ready_to_try_never_follows_terminal_delivery_state`
- [ ] Provider prose, labels alone, timestamps, and textual similarity never synthesize either zone.
  - Verify: `tests/builderops/test_devui_composition.py :: test_overview_candidates_reject_inferred_source_facts`
- [ ] The delivered pure composer remains unchanged and the production result preserves its
      withdrawals and independent evidence axes.
  - Verify: `tests/builderops/test_devui_overview.py :: test_overview_production_inputs_preserve_withdrawals`

## How to Verify (Pre-Merge)

- Run the five named tests plus the full Cockpit registry, composition, and Overview test modules.
- Run `git diff --check`; prove the diff stays inside Exact Code Ownership.

## Suggested Validation

- Execute the full focused producer/composer suites at the PR head.

## Out of Scope

- Selecting or creating source authority; changing the Overview composer; route/UI work.
- New persistence, cache, lifecycle state, inferred correlation, or delivery-readiness semantics.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/BUILDEROPS_COCKPIT/REGISTRY_READ_TIME_JOIN.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`

## Applies learning (optional)

- Phase 1 audit informs hostile cases only; its task list is advisory.

## Related GitHub Issues

Filed as blocked child [#4743](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4743); it becomes
eligible for strict readiness validation only after #4742's accepted source-authority receipt is
live and transportable inside the exact code boundary.
