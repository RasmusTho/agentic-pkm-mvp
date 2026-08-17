---
name: Validate Connected Overview and Focus Yggdrasil Evidence
description: Produce and accept one governed Yggdrasil evidence package for the stable connected Overview to Focus to return journey.
task_id: ARO-05
github_issue: 4746
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: ["#4834 stable source-owned Now fixtures", "#4768 delivered Focus API fixtures"]
depends_on: [EXPOSE_LOCAL_OVERVIEW_GET_ROUTE.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / high plus governed Yggdrasil design evidence"
capability_rationale: "The semantic fixtures are fixed; exact shipped reuse may use constrained provenance, while every novel or uncertain delta requires the live handoff."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: high
complexity: high
verification_difficulty: high
defect_blast_radius: medium
review_gate: governed evidence acceptance and independent authority review
---

# Validate Connected Overview and Focus Yggdrasil Evidence

## Purpose

Accept one governed visual treatment over stable, source-honest Overview and Focus fixtures.

## Context

Parent: #4741

Turn the merged #4834 source-owned **Now** fixture and delivered #4768 Focus API fixture into
accepted connected Overview → Focus → return guidance without changing server semantics or
claiming runtime implementation. #4834 is still open and blocked, so this task remains blocked.

## Scope

- Re-read the merged #4834 source-owned **Now** fixture and delivered #4768 Focus API fixture.
- Classify the complete connected visual scope through the canonical Yggdrasil classifier.
- For exact shipped Cockpit pattern/token reuse, produce and independently review
  `yggdrasil-constrained-reuse.v1` without design generation or a live-selection claim.
- For novel, mixed, unknown, extension, or out-of-envelope scope, run the fail-closed live
  Yggdrasil system/token preflight and produce `yggdrasil-design-handoff.v1`.
- Normalize the accepted route's guidance without changing server semantics.

## What This Task Does

- Accepts one of exactly two truthful evidence routes: either `yggdrasil-constrained-reuse.v1` or
  `yggdrasil-design-handoff.v1`.
- Produces and validates the complete connected state/accessibility matrix.
- Records accepted guidance without touching production code. Any proposed extension is novel and
  must use the live route.

## Concretely

The accepted evidence renders the same server-declared subject across Overview, visual Focus, and
return, including normal, withdrawal, measured-empty, partial, stale, missing, refused,
unsupported, unlinked, timeout, HTTP-error, narrow, keyboard, print, and JavaScript-off states,
while retaining exact selector identity, evidence axes, and limitation language.

## Why This Matters

Visual hierarchy can accidentally turn degraded evidence into confidence or provider data into policy.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI.md :: Visual composition hypothesis (pre-handoff)`
- `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md :: Design-work classifier`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Visual-work classification`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Exact shipped-pattern reuse`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate`

## SBS Impact

- Primary subsystem: Builder System / devUI visual boundary
- Secondary subsystem(s): constrained reuse provenance; governed external design handoff; Focus
- Write class: design guidance and normalized specification only
- Authority impact: none; design cannot change source or runtime authority
- Persistence impact: design package/receipt only, no runtime state
- Derived/rebuildable impact: visual guidance over fixed derived fixtures
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: targeted fixture and component evidence only
- Sync/deployment impact: none
- External boundary impact: none for exact constrained reuse; governed live Yggdrasil access for
  novel, mixed, unknown, extension, or out-of-envelope work
- New or changed contract: accepted visual/interaction treatment only
- Owner-doc impact: normalized capability spec may record accepted guidance
- Transition debt impact: prevents generic or semantically drifting shell design
- Fitness rule impact: exact-provenance or live-token-parity route plus complete state evidence

## Constraints

This task owns one dated supporting evidence package and its normalized acceptance receipt. It
edits no production application code. Exact shipped reuse does not run or claim the live
system/token preflight: every decision instead maps to content-addressed shipped patterns and
accepted token declarations, zero novel language, no egress, complete state/accessibility evidence,
and an author-independent review. Any missing mapping, uncertain decision, extension, or final
delta outside that envelope reclassifies the complete scope as mixed, unknown, or novel and uses
the live gate. Accepted guidance is normalized back into this capability specification before the
connected shell implementation in #4836.

## Acceptance Criteria

- [ ] The complete scope is classified before work begins. Exact shipped reuse accepts an
      independently reviewed `yggdrasil-constrained-reuse.v1`; every novel, mixed, unknown,
      extension, or out-of-envelope scope accepts only `yggdrasil-design-handoff.v1` after exact
      live **Yggdrasil Design System** selection and byte-for-byte token parity.
  - Verify: runtime receipt: devui-connected-design-evidence.v1
- [ ] The accepted evidence binds the merged #4834 source-owned Now subject and delivered #4768
      Focus API subject byte-identically across Overview, visual Focus, and return without using
      #4745 fixtures.
  - Verify: runtime receipt: devui-connected-subject-authority-boundary.v1
- [ ] Guidance freezes zone, item, evidence, root, and Focus selector identity; transport-only
      `loading|loaded|error`; and verbatim server axes across normal, withdrawal, measured-empty,
      partial, stale, missing, refused, unsupported, unlinked, timeout, and HTTP-error states.
  - Verify: runtime receipt: devui-connected-state-selector-matrix.v1
- [ ] Desktop, narrow, 200% zoom, keyboard, screen-reader naming, print, JavaScript-off, hostile
      strings/hrefs, many-at-once, Focus return/context, and semantic main/section/status/alert
      behavior are accepted.
  - Verify: runtime receipt: devui-connected-accessibility-interaction-matrix.v1
- [ ] Accepted assets use a hash-bound no-egress local-system-font normalization, prove zero
      cross-origin requests, and make no CSP relaxation.
  - Verify: runtime receipt: devui-yggdrasil-no-egress-normalization.v1
- [ ] The normalized contract leaves producer/API/authority semantics server-owned and names #4833
      exact-ref browser proof as the implementation verification route for #4836.
  - Verify: runtime receipt: devui-connected-design-normalization.v1

## How to Verify (Pre-Merge)

- Re-read merged #4834 and delivered #4768 before capture, then classify the entire connected scope.
- On exact reuse, validate every required source/token/decision/transformation/artifact/evidence
  hash in `yggdrasil-constrained-reuse.v1`, including independent review of the exact payload hash.
- On the live route, execute the canonical selection/token-parity preflight and record a genuine
  `yggdrasil-design-handoff.v1`. Repository provenance never substitutes for live selection.
- Walk the complete connected state matrix and record exact evidence.
- Run `git diff --check` on normalized repository artifacts.

## Suggested Validation

- Validate the applicable complete receipt and connected state matrix before accepting normalization.

## Out of Scope

- Frontend/backend implementation, #4834 producer code, API/navigation changes, design-system
  extensions on the constrained route, deployment, promotion, or owner pilot.

## Related Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `companion-ui/prompts/claude-design/README.md`

## Source Docs

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

## Applies learning (optional)

- None; both accepted evidence routes remain governed and fail closed.

## Related GitHub Issues

Filed as blocked child [#4746](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4746). Its exact
serial prerequisites are merged stable #4834 source-owned Now fixtures plus delivered #4768 Focus
API fixtures. #4745 is not a prerequisite and supplies no fixture; it remains a preserved
supersession candidate until #4836 delivers equivalent behavior. #4838 establishes the
constrained-reuse authority but produces no #4746 receipt. #4836 consumes the accepted connected
evidence, and #4833 owns the later exact-ref browser proof.
