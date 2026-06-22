---
name: Overlay Modal Frame Spec
description: One modal-frame spec — fixed positions, header-furniture order, one scrim, one dismiss/Esc/focus-trap grammar — shared by every overlay.
task_id: CUIDR-02
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 03 Overlay-grammar consistency; 04 B4
parent_capability: Companion UI Deep-Review Remediation
prerequisites: []
depends_on: []
can_parallelize_with: [Calm Degraded Grammar and Enum Map, Rail Ambient Until Active, Edge Job and Reachability, Front Door and Copy Hygiene]
---

# Overlay Modal Frame Spec

## Purpose

Every overlay that mounts on the shared overlay host must look and behave the same way. Today they
do not: the dismiss gesture differs, header furniture varies, and no single component owns the
frame. This spec defines the one frame all overlays must use so that the user builds exactly one
mental model for opening, reading, and closing any overlay in the system.

## What This Task Does

- Defines a single overlay-frame component (or rendering contract) that every overlay passes
  through. The component owns: position, header furniture, scrim, dismiss grammar, and focus trap.
- Audits the six current overlay positions and assigns each to one of the two declared frame
  positions (`center` or `right-drawer`).
- Standardises the header furniture order to: **title · status-pill · ⓘ · close** — left to right
  — with each slot present only when the overlay provides content for it.
- Establishes one scrim (a single rendered `data-testid="workspace-overlay-scrim"` element already
  wired in the host) and one dismiss grammar: clicking the scrim, pressing `Esc`, or activating the
  close button all route through `overlayHost.dismiss()`.
- Requires a focus trap while the overlay is open: keyboard focus cycles within the open overlay
  and does not leak to the document behind it.
- Notes the D4 "stray white inputs" issue (rail textarea and settings time inputs rendering white
  against the dark theme) as an overlay-chrome consistency concern. The input-styling fix itself
  is scoped to the Front Door and Copy Hygiene task (CUIDR-05); this task records the symptom
  and ensures the frame's chrome (header, scrim, container background) does not introduce further
  white-on-dark mismatches.

## Concretely

The following overlays are in scope. Each row names the overlay, its current ad-hoc position, the
frame position it adopts, and any notable header-furniture delta.

| Overlay | Current position | Frame position | Header furniture today | Normalised to |
|---------|-----------------|----------------|----------------------|---------------|
| ⌘K Panel palette (`cmd`) | Large centered panel | `center` | Panel ≠ Chat callout; no close button in header | title (`Panel`) · — · — · × |
| Capture modal (`capture`) | Medium centered modal | `center` | ⓘ + × in header | title (`Capture`) · — · ⓘ · × |
| Receipts history (`receipts`) | Small top-anchored card | `center` | Varies | title (`Receipts`) · — · — · × |
| Settings (`settings`) | Right drawer | `right-drawer` | Section labels; no unified header | title (`Settings`) · read-only-pill · — · × |
| Memory review (`memory`) | Right drawer | `right-drawer` | Provenance guard; no unified header | title (`Memory`) · status-pill · ⓘ · × |
| System Map (`map`) | Large centered modal | `center` | Title present; no close button in fixed position | title (`System Map`) · — · — · × |

**Frame positions defined:**

- `center` — the overlay renders as a panel centered in the viewport, above the scrim. Width is
  size-classified (`sm` / `md` / `lg`) and declared per overlay; the palette uses `lg`, capture
  uses `md`, receipts and system map use `lg`. The position is fixed; the overlay does not scroll
  the document behind it.
- `right-drawer` — the overlay slides in from the right edge, occupying a fixed-width column above
  the scrim. Settings and memory review use this position. Width is fixed at the drawer canonical
  width (already established by the shipped settings and memory drawers).

**Header furniture slots:**

1. **title** — always present; the overlay's plain-language name (not a route or enum).
2. **status-pill** — present only when the overlay has an authority or read-only designation to
   display (e.g. settings' "Preferences re-render identical content. They never touch the vault").
   Absent otherwise; the slot does not render an empty placeholder.
3. **ⓘ** — present only when the overlay ships contextual guidance. The capture modal already has
   this; it is absent for palette and system map.
4. **close (×)** — always present; activates `overlayHost.dismiss()`.

## Why This Matters

The review (cross-cutting finding "Overlay-grammar consistency") identifies this as a `Friction`
pattern that spans every journey. The current ad-hoc frames mean the user must re-learn how to
dismiss each overlay, cannot rely on a consistent position for the close affordance, and gets
different scrim and focus-trap behaviour depending on which overlay they opened. The capture modal
is explicitly identified as the model the rest of the overlay layer should imitate (J3: "This is
the model the rest of the overlay layer should imitate"). This task makes that imitation
structural rather than incidental.

The frame also provides the downstream dependency cited in the capability README: the governed
receipt task (CUIDR-07) renders its link-to-history overlay through this frame; the frame must
exist before that task ships.

## Acceptance Criteria

**AC-B4 (from review §05):** Every overlay uses one of the defined frame positions with identical
header furniture order and scrim; all dismiss via the same gesture and Esc, and trap focus while
open.

- Verify: (static) render each overlay fixture via `render_index_html` and assert
  `data-overlay-frame-position` is one of `["center", "right-drawer"]`, that the header contains
  the four furniture slots in order (title → status-pill slot → ⓘ slot → close), and that
  `data-testid="workspace-overlay-scrim"` is present and wired to `overlayHost.dismiss()`. Test
  pointer: `tests/companion_ui/test_overlay_frame.py::test_all_overlays_use_declared_frame`
- Verify: (live) focus trap and Esc dismiss are exercised in live UAT against the running shell.
  Each overlay is opened; Tab must not reach the document behind it; Esc must dismiss and return
  focus to the document anchor. `[live]`

**AC-Frame (frame-definition):** A single overlay-frame component or rendering contract exists
and every overlay (palette, capture, receipts, settings, memory, system map) is rendered through
it — no overlay produces its own bespoke header, scrim, or dismiss wiring outside the frame.

- Verify: (static) `tests/companion_ui/test_overlay_frame.py::test_overlay_frame_component_is_sole_frame_source`
  — assert that the overlay-frame render path is the single code site that emits
  `data-overlay-frame-position`, the header furniture markup, and the scrim dismiss binding, and
  that no overlay module contains a duplicate scrim element or a standalone `overlayHost.dismiss()`
  binding outside the frame.

**D4 note (non-blocking, shared with CUIDR-05):** The rail textarea and settings time inputs
currently render with white chrome against the dark theme (`data-region="capture-input"` textarea,
O4 time inputs). This task must not introduce additional white-on-dark chrome in the frame's own
container or header. The input-token fix (making those inputs inherit the dark-theme palette) is
owned by CUIDR-05.

## How to Verify (Pre-Merge)

1. Render all six overlay fixtures (palette, capture, receipts, settings, memory, system map) by
   calling `render_index_html` with suitable field overrides in
   `tests/companion_ui/test_overlay_frame.py`.
2. Assert `data-overlay-frame-position` present and in `["center", "right-drawer"]` for each.
3. Assert header furniture order: a single `<header data-region="overlay-header">` containing
   children in the order `[title, status-pill?, info?, close]` — status-pill and info are
   conditionally present, title and close always present.
4. Assert `data-testid="workspace-overlay-scrim"` is present exactly once in the rendered HTML and
   its `onclick` (or `data-intent`) routes to `overlayHost.dismiss()`.
5. Assert no overlay-specific module emits a second scrim or a `dismiss()` binding outside the
   frame (grep for duplicate `workspace-overlay-scrim` and standalone dismiss bindings).
6. Confirm D4 non-regression: the frame's container background uses the dark-theme CSS variable,
   not a hardcoded `#fff` or `white`.
7. Live UAT (post-merge): open each overlay on the running shell; verify Tab cycles within the
   overlay; verify Esc dismisses and returns focus.

## Out of Scope

- Input-token styling for white inputs inside overlay content (rail textarea, settings time
  inputs) — owned by CUIDR-05 (Front Door and Copy Hygiene).
- Any change to what an overlay *classifies* or *decides* — overlays continue to render
  runtime-declared data only; no entry-state, authority, posture, staleness, or receipt value
  moves into the client.
- The governed receipt's link-to-history overlay content — that content is defined by CUIDR-07
  (Governed Receipt First Class). This task provides only the frame that CUIDR-07 mounts through.
- Any new overlay surface not already declared in `DECLARED_OVERLAYS` in
  `companion_ui/workspace/overlay_host.py`.

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` § 03
  Overlay-grammar consistency; § 04 B4
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` § Overlay-grammar rule (NORMATIVE)
- `companion-ui/docs/OVERLAY_GRAMMAR.md`
- `docs/SYSTEM_ENTRY_POINT/UNIFIED_TOPBAR_AND_OVERLAY_HOST.md`
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/README.md` § Cross-Task Invariants (invariant:
  "One overlay frame, one dismiss grammar (tasks 2, 7)")

## Related GitHub Issues

Maps to one child issue **[Companion UI Deep-Review] overlay-modal-frame**; Wave 1; `agent:ready`.
