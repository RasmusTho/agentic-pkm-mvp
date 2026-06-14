---
name: System Entry Point Specification
description: Implementation breakdown for the Companion UI system entry point and unified-shell composition normalized in SYSTEM_ENTRY_POINT_SPEC.md
type: specification
authority: Source specification for the system-entry-point implementation issues; composition semantics owned by companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md
source_of_truth: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md
related_docs:
  - companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md
  - companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md
  - companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md
  - companion-ui/docs/CONTINUITY_AND_DECAY.md
  - companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
  - docs/CANVAS_CHAT_SURFACE/README.md
---

State: Capability delivered. All twelve implementation children (#1783–#1794) merged; the final child (#1795, SEP-11) shipped the fixture-driven state-gallery validation harness (`tests/companion_ui/test_entry_state_gallery.py`) and executed the parent-closure handoff. Epic #1782 closure is performed by the delivery coordinator on the #1795 validation receipt. The parked Q15–Q16 decision issue (#1796, `agent:needs-human`) remains open. GitHub is the authoritative backlog surface; see §Relationship to GitHub Issues for the per-task delivery map (PARENT_FEATURE_ISSUE.md keeps the filing record).

# System Entry Point Specification

This directory specifies the bounded implementation work for the Companion UI **system entry point and unified shell**, as normalized in `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` from the `2026-06-09-system-entry-point` design handoff (Crossing B → normalized spec → issues, per `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`).

## Capability Boundary

The capability is: a declared entry-point state machine over the existing orientation/workspace renderer branch, the latency-ladder re-entry treatment, a unified topbar + shared overlay host on the shipped adaptive 3-column workspace (#1395), and the new subordinate surfaces the spec defines (⌘K Panel palette, system map, guidance layer, settings drawer, capture, memory review drawer, receipts history), validated by a fixture-driven state gallery.

The boundary explicitly **composes** shipped surfaces; it does not rebuild them. Server declares; UI renders. Gated execution and Chat ≠ Panel authority separation are preserved throughout. The chat rail is a **slot** only — its occupant is owned by the canvas-chat lane (`docs/CANVAS_CHAT_SURFACE/README.md`), and no task in this directory implements a chat surface.

## Task List

1. [ENTRY_STATE_MACHINE.md](ENTRY_STATE_MACHINE.md) — SEP-01, server-side entry-state resolution wrapping the existing renderer branch. Foundation.
2. [REENTRY_ORIENTATION_TREATMENT.md](REENTRY_ORIENTATION_TREATMENT.md) — SEP-02, latency-ladder re-entry shapes on the orientation surface.
3. [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md](UNIFIED_TOPBAR_AND_OVERLAY_HOST.md) — SEP-03, topbar consolidation + shared overlay host + keyboard map.
4. [PANEL_COMMAND_PALETTE.md](PANEL_COMMAND_PALETTE.md) — SEP-04, ⌘K presentation of existing Panel proposals.
5. [SYSTEM_MAP_OVERLAY.md](SYSTEM_MAP_OVERLAY.md) — SEP-05, user-facing system map overlay.
6. [GUIDANCE_LAYER.md](GUIDANCE_LAYER.md) — SEP-06, opt-in `data-guidance` explanatory layer.
7. [SETTINGS_DRAWER.md](SETTINGS_DRAWER.md) — SEP-07, Local UI settings drawer consolidating shipped display preferences (#1675) plus listening preferences.
8. [CAPTURE_TO_VAULT_INBOX.md](CAPTURE_TO_VAULT_INBOX.md) — SEP-08, governed capture endpoint + capture modal UI (may map to two issues).
9. [MEMORY_REVIEW_DRAWER.md](MEMORY_REVIEW_DRAWER.md) — SEP-09, review-queue endpoints + right-drawer review UI (may map to two issues).
10. [RECEIPTS_HISTORY_SURFACE.md](RECEIPTS_HISTORY_SURFACE.md) — SEP-10, read-only receipts history modal.
11. [STATE_GALLERY_VALIDATION.md](STATE_GALLERY_VALIDATION.md) — SEP-11, fixture-driven state-gallery validation harness; final child with parent-closure handoff.

## Flat Execution Order

1. **SEP-01 ENTRY_STATE_MACHINE** — everything else keys off `data-entry-state` and the transition-rejection rule; no overlay or re-entry work can be asserted against entry states that are not yet declared.
2. **SEP-03 UNIFIED_TOPBAR_AND_OVERLAY_HOST** — the shared overlay host (Esc / dismiss-to-anchor / no route reset) is the substrate every new overlay surface mounts on; the keyboard map lands here.
3. **SEP-02 REENTRY_ORIENTATION_TREATMENT** — needs SEP-01's `orienting` state and shape attribute; independent of the overlay host, so it can run in parallel with SEP-03.
4. **SEP-08a / SEP-09a (runtime halves of CAPTURE_TO_VAULT_INBOX and MEMORY_REVIEW_DRAWER)** — governed endpoints have no UI dependency and can start any time after the spec merges, in parallel with SEP-02/SEP-03.
5. **SEP-04 PANEL_COMMAND_PALETTE** — mounts on the overlay host; reuses `POST /api/panel/confirm`.
6. **SEP-05 SYSTEM_MAP_OVERLAY** — mounts on the overlay host; routes to surfaces as they exist (nodes for not-yet-shipped surfaces declare their status truthfully).
7. **SEP-07 SETTINGS_DRAWER** — mounts on the overlay host; consolidates shipped display preferences.
8. **SEP-10 RECEIPTS_HISTORY_SURFACE** — mounts on the overlay host; read-only over existing receipt projections.
9. **SEP-08b CAPTURE modal UI** — needs the overlay host (⌘N) and the SEP-08a endpoint.
10. **SEP-09b MEMORY REVIEW drawer UI** — needs the overlay host and the SEP-09a endpoints.
11. **SEP-06 GUIDANCE_LAYER** — cross-cutting callouts over shell + overlays; scheduled late so the callouts cover the real overlay set, though it can begin any time after SEP-03.
12. **SEP-11 STATE_GALLERY_VALIDATION** — final child; renders the spec's state gallery against fixtures across everything above and carries the parent-closure handoff.

### Parallelization map

- After SEP-01: SEP-02 ∥ SEP-03 ∥ SEP-08a ∥ SEP-09a.
- After SEP-03: SEP-04 ∥ SEP-05 ∥ SEP-06 ∥ SEP-07 ∥ SEP-10 ∥ SEP-08b (once SEP-08a lands) ∥ SEP-09b (once SEP-09a lands).
- SEP-11 is strictly last.

## Capability-Level Acceptance Criteria

All capability-level criteria are satisfied as of the #1795 state-gallery closure:

- [x] The shell root declares `data-entry-state` for exactly the five spec states, and undeclared transitions are rejected.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_undeclared_transitions_are_rejected`
- [x] Cold start (first contact and >14d) and `no_vault` render no re-entry overlay.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_cold_start_shows_no_reentry_overlay`
- [x] Every overlay dismisses back to the document anchor with no route reset and no loss of staged suggestions or open-loop counts.
  Verify: `tests/companion_ui/test_overlay_host.py::test_overlay_dismiss_returns_to_anchor_without_route_reset`
- [x] Governed intents surface receipts; body edits do not (receipt asymmetry).
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_governed_vs_body_edit_receipt_asymmetry`
- [x] The orientation display budget keeps visible items at or below the server caps with the spec's default scarce subset.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_display_budget_caps_visible_items`
- [x] The full state gallery renders from fixtures with no UI-derived authority classification.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_state_gallery_renders_all_declared_states` and `::test_no_ui_derived_authority`

## Verification Path

Task-level verification follows each task file's `How to Verify (Pre-Merge)` section; every AC names its test or receipt target inline. Parent-level verification lives on the GitHub parent feature issue (#1782) as child delivery receipts.

## Validation / Acceptance Path

The parent feature issue (#1782; pre-filing draft archived in [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md)) was the live validation hub: each child PR posted a validation receipt to the parent before the next dependent child was picked up. Owner-doc promotion (the `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` shipped-vs-new audit and the `docs/STATUS.md` delivery record) executed with the final child (SEP-11, #1795) as its parent-closure handoff. Epic #1782 is closed by the delivery coordinator on the #1795 validation receipt.

## Relationship to GitHub Issues

The issue tree was filed 2026-06-10 per `.codex/skills/feature-breakdown/SKILL.md`. SEP-08 and SEP-09 each map to two issues (runtime endpoint + UI surface), per their task files' split-dependency notes. GitHub is the authoritative backlog state; the table below is the filing and delivery record.

| Task spec | Issue | Delivery |
|---|---|---|
| Parent feature issue (validation hub) | #1782 | open until the coordinator closes it on the #1795 validation receipt |
| SEP-01 [ENTRY_STATE_MACHINE.md](ENTRY_STATE_MACHINE.md) | #1783 | delivered — PR #1800 |
| SEP-02 [REENTRY_ORIENTATION_TREATMENT.md](REENTRY_ORIENTATION_TREATMENT.md) | #1784 | delivered — PR #1801 |
| SEP-03 [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md](UNIFIED_TOPBAR_AND_OVERLAY_HOST.md) | #1785 | delivered — PR #1802 |
| SEP-04 [PANEL_COMMAND_PALETTE.md](PANEL_COMMAND_PALETTE.md) | #1786 | delivered — PR #1817 |
| SEP-05 [SYSTEM_MAP_OVERLAY.md](SYSTEM_MAP_OVERLAY.md) | #1787 | delivered — PR #1846 |
| SEP-06 [GUIDANCE_LAYER.md](GUIDANCE_LAYER.md) | #1788 | delivered — PR #1847 |
| SEP-07 [SETTINGS_DRAWER.md](SETTINGS_DRAWER.md) | #1789 | delivered — PR #1834 |
| SEP-08a [CAPTURE_TO_VAULT_INBOX.md](CAPTURE_TO_VAULT_INBOX.md) (runtime endpoint) | #1790 | delivered — PR #1799 |
| SEP-08b [CAPTURE_TO_VAULT_INBOX.md](CAPTURE_TO_VAULT_INBOX.md) (capture modal UI) | #1791 | delivered — PR #1816 |
| SEP-09a [MEMORY_REVIEW_DRAWER.md](MEMORY_REVIEW_DRAWER.md) (runtime endpoints) | #1792 | delivered — PR #1798 |
| SEP-09b [MEMORY_REVIEW_DRAWER.md](MEMORY_REVIEW_DRAWER.md) (review drawer UI) | #1793 | delivered — PR #1818 |
| SEP-10 [RECEIPTS_HISTORY_SURFACE.md](RECEIPTS_HISTORY_SURFACE.md) | #1794 | delivered — PR #1833 |
| SEP-11 [STATE_GALLERY_VALIDATION.md](STATE_GALLERY_VALIDATION.md) | #1795 | delivered by this slice's PR (state-gallery harness + parent-closure handoff) |
| Parked context lane / place band decision (Q15–Q16) | #1796 | open — `agent:needs-human`, prio:low (decision issue, not implementation) |

## Parked

The **context lane (time)** and **place band** from the design package are explicitly parked pending Q15–Q16 (no owner doc grounds a calendar or location source; see `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Resolved questions`). No task in this directory implements them, and the reserved intents `context.open` / `location.enable` must not be emitted. The gated backlog issue holding the Q15–Q16 decisions is filed as #1796 (`agent:needs-human`); it is not an implementation task and must not be made `agent:ready` until a human resolves the source and privacy posture.
