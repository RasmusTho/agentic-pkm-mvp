---
name: Validate the Overview Yggdrasil Design
description: Produce and accept the governed Yggdrasil handoff for the stable read-only Overview fixtures and navigation journey.
task_id: ARO-05
github_issue: 4746
source_anchor: "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate"
parent_capability: devUI Stage A Read-Only Overview
prerequisites: [ARO-03, ARO-04]
depends_on: [EXPOSE_LOCAL_OVERVIEW_GET_ROUTE.md, BIND_TYPED_OVERVIEW_NAVIGATION.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / high plus governed Yggdrasil design handoff"
capability_rationale: "The semantic fixtures are fixed; visual hierarchy, responsive behavior, and accessibility require governed design-system evidence."
execution_context: fresh_issue_agent
issue_local_helper_budget: 0
context_cost_estimate: high
complexity: high
verification_difficulty: high
defect_blast_radius: medium
review_gate: governed handoff acceptance and independent authority review
---

# Validate the Overview Yggdrasil Design

## Purpose

Accept a governed visual treatment over stable, source-honest Overview fixtures.

## Context

Parent: #4741

Turn the preserved ARO-01 withdrawal and stable route/navigation fixtures into accepted
visual/interaction guidance without changing server semantics or claiming runtime implementation.

## Scope

- Run the fail-closed Yggdrasil system/token preflight.
- Produce the state matrix from the preserved ARO-01 withdrawal and stable ARO-03/04 fixtures.
- Normalize accepted guidance into this capability boundary without changing server semantics.

## What This Task Does

- Runs the exact live design-system selection/token-parity gate.
- Produces and validates the complete state/accessibility matrix.
- Records accepted guidance and unresolved extensions without touching production code.

## Concretely

The handoff renders the same server-declared item across normal, degraded, narrow, keyboard, print,
and JavaScript-off states while retaining its exact evidence and limitation language.

## Why This Matters

Visual hierarchy can accidentally turn degraded evidence into confidence or provider data into policy.

## Source Anchors

- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Cross-task invariants`
- `docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md :: Authority-resolution gate`
- `docs/DEVUI.md :: ARO-01 source-authority resolution (2026-08-10)`
- `docs/DESIGN_PRINCIPLES.md :: Shared Visual Language`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate`

## SBS Impact

- Primary subsystem: Builder System / devUI visual boundary
- Secondary subsystem(s): external governed design handoff
- Write class: design guidance and normalized specification only
- Authority impact: none; design cannot change source or runtime authority
- Persistence impact: design package/receipt only, no runtime state
- Derived/rebuildable impact: visual guidance over fixed derived fixtures
- Human knowledge impact: none
- Memory impact: none
- Retrieval/context impact: targeted fixture and component evidence only
- Sync/deployment impact: none
- External boundary impact: governed Yggdrasil design-system access
- New or changed contract: accepted visual/interaction treatment only
- Owner-doc impact: normalized capability spec may record accepted guidance
- Transition debt impact: prevents generic or semantically drifting shell design
- Fitness rule impact: token parity and full visual-state receipt

## Constraints

This task owns one dated supporting design package and its normalized acceptance receipt under the
governed Yggdrasil handoff. It edits no production application code. For this Builder-only surface,
accepted guidance is normalized back into this capability specification before ARO-06.

## Acceptance Criteria

- [ ] The live system named exactly **Yggdrasil Design System** passes selection and byte-for-byte
      token parity against `companion-ui/companion-app/colors_and_type.css`.
  - Verify: runtime receipt: yggdrasil-design-handoff.v1
- [ ] The handoff uses the preserved ARO-01 withdrawal and stable ARO-03/04 fixtures and never
      changes zone eligibility, evidence axes, withdrawals, source authority, or typed-root
      separation.
  - Verify: runtime receipt: devui-overview-design-authority-boundary.v1
- [ ] State guidance covers desktop, narrow, 200% zoom, keyboard, screen-reader naming, print,
      JavaScript-off, many-at-once, complete-empty, partial, stale, missing, refused, and unlinked.
  - Verify: runtime receipt: devui-overview-design-state-matrix.v1
- [ ] The package names every reused primitive and keeps any extension explicit and unresolved
      until separately accepted.
  - Verify: runtime receipt: yggdrasil-design-handoff.v1
- [ ] The accepted normalization states exact shell behavior and leaves source semantics with the server.
  - Verify: runtime receipt: devui-overview-design-normalization.v1

## How to Verify (Pre-Merge)

- Before design generation or readiness, execute the canonical live selection and token-parity
  preflight in `.codex/skills/yggdrasil-design-handoff/SKILL.md`. The fresh execution receipt must
  record the then-resolved exact design-system name and ID, binding token source, SHA-256, and
  byte-for-byte parity. The design-system MCP is unavailable during this documentation repair, so
  no selection, parity, readiness, or generation is proven here.
- Walk the complete state matrix and record token SHA-256, component inputs, screenshots, and open questions.
- Run `git diff --check` on normalized repository artifacts.

### Narrow exact-reuse provenance route

When a bounded delivery needs to reuse the shipped token sheet without a new
design generation, the only admitted route is the checked-in
`config/builderops/devui_exact_reuse_declaration.json` evaluated by
`app.builderops.devui_exact_reuse_provenance`.  The declaration is read as a
regular blob from the exact committed candidate tree; its source is a regular
blob from an immutable commit reachable from that candidate.  The validator
hardcodes the approved Google/Bunny import literals and rejects all other
URLs, transforms, fallback families, or state matrices.  This route does not
replace the live Yggdrasil gate for generated, novel, mixed, unknown, or
out-of-envelope work.

## Suggested Validation

- Validate the complete handoff receipt and state matrix before accepting normalization.

## Out of Scope

- Frontend/backend implementation, source/route changes, design-system extensions, or design
  generation without a passing preflight.

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

- None; the governed handoff is a live dependency, not an advisory audit claim.

## Related GitHub Issues

Filed as blocked child [#4746](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4746) on stable
ARO-03/#4744 and ARO-04/#4745 fixtures plus live governed design access. ARO-01/#4742 preserves
the withdrawal that the handoff must render; ARO-02/#4743 is closed/superseded and supplies no
fixture.
