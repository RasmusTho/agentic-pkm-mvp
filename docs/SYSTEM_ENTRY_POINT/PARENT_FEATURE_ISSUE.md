State: Filed. The parent feature issue exists as **#1782** (`[SystemEntryPoint] feature: unified shell + system entry point (validation hub)`), filed 2026-06-10 after the spec PR (#1777) merged. **The GitHub issue is now the authoritative backlog/validation surface**; this file is the archived pre-filing draft plus the filing record. Validation receipts, acceptance progress, and lifecycle state live on #1782, not here.

# Parent Feature Issue: System Entry Point and Unified Shell

Filed as: #1782 — `[SystemEntryPoint] feature: unified shell + system entry point (validation hub)`

Initial state as filed: `Status=Backlog`, label `agent:blocked` (validation hub, not a direct pickup issue). Child issues: #1783–#1795; parked Q15–Q16 decision issue: #1796 (`agent:needs-human`). See `README.md §Relationship to GitHub Issues` for the per-task issue map.

---

## Context

The 2026-06-09 `system-entry-point` design handoff passed Crossing B and was normalized into `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` per `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`. The spec declares the entry-point state model, the latency-ladder re-entry treatment, the data-attribute/intent vocabularies, and the surface composition over the shipped adaptive 3-column workspace (#1395). This parent issue is the live validation hub for the implementation breakdown in `docs/SYSTEM_ENTRY_POINT/`.

## Scope

The capability outcome (not one PR): the Companion UI declares its entry state server-side; re-entry follows the latency ladder; a unified topbar and shared overlay host enforce dismiss-to-anchor with no route reset; the ⌘K Panel palette, system map, guidance layer, settings drawer, capture modal, memory review drawer, and receipts history ship as composed surfaces; and a fixture-driven state gallery proves the composition.

## Source Anchors

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Entry-point state model (NORMATIVE)`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Overlay-grammar rule (NORMATIVE)`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Surface composition (NORMATIVE table)`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Resolved questions`
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Validation expectations`
- `docs/SYSTEM_ENTRY_POINT/README.md :: Flat Execution Order`

## Constraints

- Server declares; UI renders. No UI-derived entry state, authority class, trajectory state, or cognitive mode.
- Gated execution preserved: durable mutations only through policy → validation → event pipeline → deterministic writer; body-edit lane stays the `CANVAS_SUGGESTION_FLOW.md` exception with no governance receipt.
- Chat ≠ Panel. No task implements a chat surface; the rail slot's occupant is owned by `docs/CANVAS_CHAT_SURFACE/README.md`.
- The shipped 3-column adaptive workspace (#1395) is composed, not replaced.
- No notification, badge, urgency, or push semantics anywhere in the capability.
- Context lane / place band remain parked (Q15–Q16); the reserved intents must not be implemented.
- Owner contracts win over this breakdown wherever they appear to disagree.

## Acceptance Criteria

- [ ] Entry-state machine delivered: five states, shape sub-attribute, cross-flags, transition rejection.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_undeclared_transitions_are_rejected`
- [ ] Re-entry treatment delivered per the latency ladder with the display budget and no cold/no-vault overlay.
  Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_soft_mist_renders_no_card` and `tests/companion_ui/test_entry_state_machine.py::test_cold_start_shows_no_reentry_overlay`
- [ ] Overlay host enforces dismiss-to-anchor with no route reset across all shipped overlays.
  Verify: `tests/companion_ui/test_overlay_host.py::test_overlay_dismiss_returns_to_anchor_without_route_reset`
- [ ] ⌘K palette presents existing Panel proposals with governed confirm and guard-held blocked flow.
  Verify: `tests/companion_ui/test_panel_command_palette.py::test_palette_confirm_routes_through_panel_confirm`
- [ ] System map, guidance layer, settings drawer, capture, memory review drawer, and receipts history delivered per their task specs.
  Verify: each child issue's delivery receipt posted on this parent issue
- [ ] State-gallery validation passes across the fixture matrix and the parent-closure handoff is executed.
  Verify: `tests/companion_ui/test_entry_state_gallery.py::test_state_gallery_renders_all_declared_states` + closing receipt on this issue

## Out of Scope

- Context lane (time) and place band (parked; separate gated `agent:needs-human` issue holds Q15–Q16).
- Chat surface implementation (canvas-chat lane).
- New Panel actions or governance semantics.
- Production hosting/packaging decisions.

## Suggested Validation

Per-child: the `How to Verify (Pre-Merge)` block of each task spec. Capability-level: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/` green, plus a live dev-shell walkthrough of the state gallery scenarios (cold, returning 2h, returning 5d, degraded, no-vault, narrow).

## Source Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`
- `docs/SYSTEM_ENTRY_POINT/README.md` (+ task files)
- `companion-ui/design_handoff/2026-06-09-system-entry-point/` (design source, guidance only)

## Implementation Tasks

See `docs/SYSTEM_ENTRY_POINT/README.md` for the task list, flat execution order, and parallelization map. Task files: ENTRY_STATE_MACHINE, REENTRY_ORIENTATION_TREATMENT, UNIFIED_TOPBAR_AND_OVERLAY_HOST, PANEL_COMMAND_PALETTE, SYSTEM_MAP_OVERLAY, GUIDANCE_LAYER, SETTINGS_DRAWER, CAPTURE_TO_VAULT_INBOX (two issues), MEMORY_REVIEW_DRAWER (two issues), RECEIPTS_HISTORY_SURFACE, STATE_GALLERY_VALIDATION.

## Verification Path

Every child AC carries an inline `Verify:` target (test pointer or doc/receipt target). Child PRs are the task verification receipts.

## Validation / Acceptance Path

This issue is the validation hub: each child posts a short validation receipt here after merge; the final child (SEP-11) executes the parent-closure handoff — final receipt, owner-doc/status writeback, and truthful state updates to this draft and the directory README — before this issue closes.
