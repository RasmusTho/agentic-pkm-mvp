# Design Handoff — Canvas Suggestion Flow

**Date:** 2026-05-11
**Status:** Design handoff v1 · ready for implementation

## What this is

A narrow, implementation-ready interaction spec for the Canvas Suggestion Flow in the Companion UI. Covers the moment Hugin proposes a change to the active note, the user previews it, and the system either co-authors the body in place or routes the intent into the governed pipeline.

Produced in Claude Design (claude.ai/design) using repo context as constraints.

## Files

- `Canvas Suggestion Flow.html` — full 14-section spec with state gallery and live interactive demo. Open in a browser.
- `colors_and_type.css` — Yggdrasil design tokens (same as the cognitive-temporal handoff).

## Implementation scope

Two lanes, one state machine:

1. **Body-edit lane** — user-present co-authoring of the active note's body. Apply in place via `canvas_writer`. No governance receipt.
2. **Governance-bearing lane** — frontmatter, maturity, cross-note ops, lifecycle. Cannot be applied from chat. Queued via `GovernanceRouter`; returns a receipt.

Eight UI states: `idle`, `thinking`, `suggestion-staged:body`, `suggestion-staged:gov`, `apply-pending`, `governance-pending`, `applied`, `discarded`, `blocked`.

## Key contracts (from §13)

See `Canvas Suggestion Flow.html §13` for the full design-vs-contract split. High-signal contracts:

- **State enum + transitions** — implementations must enumerate exactly these states.
- **Two-lane split** — body vs governance must surface distinctly; UI never re-classifies.
- **No Apply on governance card** — hard rule enforcing gated-execution invariant.
- **Apply ≠ governance event** — body edits do not generate Panel receipts.
- **Composer disabled outside `idle`** — prevents send-race with in-flight proposals.
- **Keyboard shortcuts A/Q/D/I/E** — bound only during `suggestion-staged:*` states.
- **Portrait bottom sheet** — 3 snap points; auto-snap to `half` on proposal; never auto-full.

## Related implementation

See `companion-ui/companion-app/canvas_suggestion_flow.html` for the staged prototype.

## Related docs

- `companion-ui/docs/OVERLAY_GRAMMAR.md`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`
- `docs/CANVAS_CHAT_SURFACE/` (full backend contract)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/`
