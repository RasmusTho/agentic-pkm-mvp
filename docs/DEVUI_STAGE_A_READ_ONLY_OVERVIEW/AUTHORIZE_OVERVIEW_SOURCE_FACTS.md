---
name: Authorize Overview Source Facts
description: Decide which existing sources canonically own Overview owner-attention and ready-to-try facts and how those facts are serialized.
task_id: ARO-01
github_issue: 4742
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: []
depends_on: []
can_parallelize_with: []
recommended_capability: "Owner decision with Codex Sol / high decision-brief support"
capability_rationale: "This changes a Builder System source-authority boundary; an agent may prepare evidence but cannot select the authority."
execution_context: inline_deterministic
issue_local_helper_budget: 0
context_cost_estimate: medium
complexity: medium
verification_difficulty: high
defect_blast_radius: high
review_gate: owner decision receipt plus docs-authoring review
---

# Authorize Overview Source Facts

## Purpose

Resolve the one authority question that prevents honest producer enrichment.

## Context

Parent: #4741

Record the exact owner decision that makes producer enrichment semantically possible, or decide
that no current source owns one or both facts and keep those zones withdrawn.

## What This Task Does

- Names the canonical existing source and serialized field for the four already-governed
  owner-authority categories, including governing-source reference, stable subject linkage, and
  evidence-state fields.
- Names the canonical receipt type/source that explicitly owns `ready_to_try`, including linkage,
  availability, and freshness rules.
- Decides whether the bounded GitHub → Cockpit → `devui.composition.v1` chain may transport those
  facts without gaining authority.
- Amends only the owning Builder System source/owner contract and records a decision receipt.

## Concretely

The accepted decision names the exact source field and receipt contract, or explicitly records
that the fact has no current owner and the affected Overview zone stays withdrawn.

## Why This Matters

Without a named source owner, producer code would turn labels or delivery outcomes into new policy.

## Scope

- Produce the bounded source-authority contract and receipt only.
- Leave all runtime implementation to ARO-02 and later children.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md :: Human exception routing`

## SBS Impact

- Primary subsystem: Builder System governance
- Secondary subsystem(s): devUI and the selected existing source owner
- Write class: governance/source-contract decision only
- Authority impact: names an existing canonical fact owner or explicitly records no owner
- Persistence impact: no runtime persistence
- Derived/rebuildable impact: enables or withdraws a derived Overview classification
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: none
- Sync/deployment impact: none
- External boundary impact: explicit owner decision receipt
- New or changed contract: source serialization for owner category and `ready_to_try`
- Owner-doc impact: bounded amendment to `docs/DEVUI.md` and selected source owner
- Transition debt impact: removes unsafe label/terminal-state inference
- Fitness rule impact: docs/architecture assertion for source identity and withdrawal

## Constraints

This decision may edit `docs/DEVUI.md` plus the selected existing source-owner document. It does
not edit application code. If no current source is selected, it records withdrawal semantics and
ARO-02 remains blocked or is superseded.

## Acceptance Criteria

- [ ] The accepted contract names one canonical source and serialization for each admitted fact,
      or explicitly states that no current source owns it.
  - Verify: doc writeback at `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- [ ] The contract carries category/receipt identity, governing source, subject linkage, evidence
      availability/freshness/completeness/cardinality/linkage, and withdrawal rules.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py :: test_overview_source_authority_contract_is_explicit`
- [ ] `agent:needs-human`, done, merge, Issue closure, availability, delivery, and a generic
      terminal receipt are explicitly rejected as substitutes.
  - Verify: doc writeback at `docs/DEVUI.md :: DEVUI-OVERVIEW-BOUNDARY — server-declared read model`
- [ ] The decision states whether the current producer chain can transport the facts without an
      authority or persistence change.
  - Verify: runtime receipt: devui-overview-source-authority-decision.v1

## How to Verify (Pre-Merge)

- Run the named architecture test, `python3 scripts/docs_guard.py`, and `git diff --check`.
- Review the decision against the four owner categories and independent delivery-fact rule.
- Post the exact accepted doc SHA and decision receipt to the parent.

## Suggested Validation

- Execute every Verify target above and inspect the exact owner-decision receipt.

## Out of Scope

- Producer, composer, route, navigation, visual, browser, or command code.
- Creation of a new task store, readiness state, or devUI-owned authority.
- Treating the requested decision as already decided by this task spec.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DEVUI.md`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`

## Applies learning (optional)

- None; the blocker follows the live owner contract and code audit.

## Related GitHub Issues

Filed as `agent:needs-human` child [#4742](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4742)
of blocked parent #4741; never `agent:ready` before the owner decision is recorded.
