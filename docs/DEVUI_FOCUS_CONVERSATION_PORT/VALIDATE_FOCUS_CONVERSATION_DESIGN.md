---
name: Validate Focus and Conversation Design
description: Produce the governed Yggdrasil visual and interaction handoff for Focus, external conversation, and exact command preview.
task_id: FCP-02
github_issue: 4695
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Information architecture and hard boundary"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-01]
depends_on: [COMPOSE_SUBJECT_CENTRED_FOCUS.md]
can_parallelize_with: []
recommended_capability: "Codex Terra / medium plus governed Yggdrasil design handoff"
capability_rationale: "Design normalization is bounded but must preserve exact authority and degraded-state semantics."
---

# Validate Focus and Conversation Design

## Purpose

Turn the information behavior into an accepted Yggdrasil handoff before visual implementation.

## What This Task Does

- Uses the existing Yggdrasil tokens/components and the governed design-handoff chain.
- Designs the stable subject header, progressive Focus evidence, external Conversation Port, context
  pack preview, typed command preview, Start/Hold confirmation, receipt, and ambiguous result.
- Proves that Builder System Control is a separate route/context, not a Focus tab or provider view.
- Covers desktop, narrow, 200% zoom, keyboard, screen-reader naming, many-at-once, stale, unavailable,
  unread, unsupported, unlinked, missing, measured-empty, refused, and ambiguous states.
- Normalizes the accepted handoff into a durable component/interaction specification and receipt.

## Concretely

The handoff shows one Issue/capability header from Focus through pack preview, external handoff,
command preview, Hold/Start, and receipt. A separate Builder System Control entry visibly changes
the header to system scope and restores the previous Focus subject on return.

## Why This Matters

The authority boundary is partly interaction design: an ambiguous or visually merged read/action
surface can cause the owner to mistake provider prose for an executable or completed workflow.

## Acceptance Criteria

- [ ] A governed handoff package and normalized specification preserve all FCP invariants and use the
      live Yggdrasil design system without introducing an unapproved component vocabulary.
  - Verify: runtime receipt: yggdrasil-design-handoff.v1
- [ ] Conversation is visibly external/provenance-only, and source links/read-only analysis are
      visually distinct from the authority-bearing Start action.
  - Verify: runtime receipt: focus-conversation-command-preview.v1
- [ ] The design distinguishes every required source state without color-only meaning or false
      empty/healthy presentation.
  - Verify: runtime receipt: focus-source-state-matrix.v1
- [ ] Keyboard, focus order, screen-reader names, narrow, and 200% zoom preserve subject identity,
      evidence order, preview scope, and Start/Hold parity.
  - Verify: runtime receipt: focus-accessibility.v1
- [ ] Builder System Control has a distinct system-scope header and navigation return path; no
      control-lens claims leak into the Focus subject.
  - Verify: runtime receipt: focus-builder-system-boundary.v1

## How to Verify (Pre-Merge)

- Validate the handoff package and normalized spec through the governed Yggdrasil workflow.
- Walk every named scenario and source-state fixture against the FCP invariants.
- Record keyboard, narrow, 200% zoom, screen-reader naming, and degraded-state evidence.
- Run `git diff --check` on the normalized repository artifacts.

## Out of Scope

- Frontend or backend implementation.
- External-provider automation when the governed design environment is unavailable.
- Builder System Control content design beyond the boundary/navigation proof.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `companion-ui/prompts/claude-design/README.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`
- `companion-ui/companion-app/colors_and_type.css`

## Related GitHub Issues

Filed as blocked child [#4695](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4695); it remains
blocked after spec merge until FCP-01 fixtures and live governed design-handoff access are available.
