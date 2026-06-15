---
name: Render Commitments In Panel UI
description: Render active commitments in the Panel/Companion UI, visually distinguishing next-action from review-cycle, read-only
task_id: COMMITMENT-SURFACING-03
source_anchor: app/api/routes/companion.py :: WorkspaceStateResponse
parent_capability: Commitment Surfacing
prerequisites: [COMMITMENT-SURFACING-02]
depends_on: [EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md]
can_parallelize_with: []
---

State: Specification for the read-only Panel/Companion UI render. Slice 3 of the COMMITMENT_SURFACING capability (parent #1960). Depends on slice 2. Code-affecting (companion UI).

# Render Commitments In Panel UI

## Purpose

With commitments durably persisted (slice 1) and exposed read-only through the companion route (slice 2), the human must actually *see* them. This task renders active commitments in the Panel/Companion UI workspace, **visually distinguishing next-action from review-cycle** so the user can tell "what is mine to do next" apart from "what returns to me for review". It is the final slice that delivers the human-facing surface and leaves the capability ready for end-to-end validation on #1960.

## What This Task Does

- Renders the commitment surface from the workspace-state API field (slice 2) in the Panel/Companion UI workspace, following the existing read-only companion render patterns (the orientation / resurface / vault-browser panels).
- Visually distinguishes commitment families: next-action (and the actionable next/waiting kinds) versus review-cycle (review_return). The distinction is observable in the rendered output (distinct grouping, label, or styling marker), not merely present in the data.
- Renders read-only: no mutation affordance (no buttons that transition or close a commitment); the surface is a projection of the durable source. Any future transition action would route through the governed Panel confirmation path, which is out of scope here.
- Degrades honestly: when the API reports a degraded commitment read (cross-task invariant CI-2), the UI shows a degraded/unavailable state rather than rendering a confident empty surface.

## Concretely

When the workspace renders with the API returning a next_action commitment and a review_return commitment, the Companion UI shows them in visually distinct regions/treatments — e.g. a "Next" grouping for next_action/waiting and a "Review" grouping for review_return — each item read-only (summary + target reference, no transition control). When the API field is absent (older payload) or degraded, the UI degrades to not-shown / unavailable rather than crashing or implying the user has zero commitments.

## Why This Matters

The render is where the capability becomes real for the human; everything upstream exists to make this surface trustworthy. Collapsing next-action and review-cycle into one undifferentiated list would defeat the commitment-layer distinction (`COMMITMENT_LAYER_CONTRACT.md`: Next Action and Review Cycle are distinct semantic kinds) — the user could no longer tell "do this now" from "re-orient on this". Read-only rendering preserves the governed-transition constraint; honest degradation preserves the no-fabricated-absence invariant.

## Acceptance Criteria

- [ ] The Panel/Companion UI renders active commitments from the workspace-state API field, read-only (no mutation affordance).
  - Verify: `tests/companion_ui/test_commitment_surface.py::test_commitments_render_read_only`
- [ ] Next-action and review-cycle commitments are visually distinguished in the rendered surface (distinct grouping/label/marker observable in the render output).
  - Verify: `tests/companion_ui/test_commitment_surface.py::test_next_action_distinguished_from_review_cycle`
- [ ] When the commitment field is absent or the API reports a degraded read, the UI degrades to not-shown / unavailable rather than rendering a confident empty surface or crashing.
  - Verify: `tests/companion_ui/test_commitment_surface.py::test_degraded_or_absent_commitments_render_safely`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_commitment_surface.py` — runs the render, distinction, and degraded-render assertions.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api tests/companion_ui -k commitment` — broader commitment-surfacing sweep (matches #1960's Suggested Validation).
- `ruff check app tests` and `mypy app` (code-affecting change).
- If the companion UI renders via the pure `render_index_html` path, render to static HTML and visually confirm the next-action vs review-cycle distinction (per the companion UI local UAT pattern).

## Out of Scope

- Commitment execution; reminders/notifications; CRE reach-out.
- Changing commitment-vs-execution-plan semantics.
- Any commitment mutation / state-transition affordance (transitions remain governed; a future transition action would route through the Panel confirmation path).
- The durable persistence/query path (slice 1) and the route exposure (slice 2).

## Related Docs

- `docs/COMMITMENT_SURFACING/README.md`
- `docs/COMMITMENT_SURFACING/EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `app/api/routes/companion.py`
- `tests/companion_ui/` (existing read-only companion render tests as patterns)

## Related GitHub Issues

Implements COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI. Parent: #1960. Slice 3 — depends on slice 2 (EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE) and is the final slice; its delivery readies the capability for end-to-end validation on #1960. Created `agent:blocked` until slice 2 merges, `prio:med`, `area:companion-ui`, `panel`. Use the acceptance criteria above as the issue contract.
