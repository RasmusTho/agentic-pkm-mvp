---
name: Entry State Machine
description: Server-side entry-state resolution wrapping the existing orientation/workspace renderer branch, with declared transitions and cross-flags
task_id: SEP-01
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Entry-point state model (NORMATIVE)
parent_capability: system-entry-point
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Entry State Machine

## Purpose

Make the entry-point state model explicit. Today `render_index_html()` hard-branches between an orientation page and the workspace page; nothing declares which entry state the shell is in, so re-entry shapes, overlay behavior, and validation have no stable selector to key off.

## What This Task Does

Adds server-side entry-state resolution in the Companion UI renderer (`companion-ui/companion-app/companion_ui/workspace/serve_dev_page.py`) that wraps — does not replace — the existing orientation/workspace branch:

- Resolves exactly the five spec states: `boot`, `no_vault`, `cold_start`, `orienting`, `shell_active`, from the signals named in the spec (`GET /api/companion/orientation` result, `leave_point.status`, note selection).
- Emits `data-entry-state` on the shell root, `data-reentry-shape` when `orienting`, and the `data-degraded` / `data-stale` cross-flags from `meta.degraded_reasons` and `leave_point.status`.
- Enforces the allowed-transition table: state resolution is a pure server-side function; an input combination outside the enumerated transitions resolves to the nearest declared state and is surfaced as a degraded reason, never as a new implicit state.
- `boot` is the server-render equivalent of "handshake in progress" — for the server-rendered page this is the state declared while the orientation fetch is unresolved (and the state any client-side retry returns to via `entry.retry`).

## Concretely

```text
GET /  (no note, leave_point.status=present, gap 5h)
  → page renders with <body … data-entry-state="orienting" data-reentry-shape="full_mist">

GET /  (orientation returns 503)
  → data-entry-state="no_vault"; retry affordance carries data-intent="entry.retry"

GET /?note_path=notes/foo.md
  → data-entry-state="shell_active"; existing 3-column workspace unchanged
```

## Why This Matters

Every other task in this capability (re-entry shapes, overlay host, state-gallery validation) asserts against `data-entry-state`. Without a declared, server-resolved state, the UI would re-derive entry posture locally — violating "server declares; UI renders" — and cold/no-vault overlay prohibitions would be unenforceable.

## Acceptance Criteria

- [ ] The shell root declares `data-entry-state` with exactly one of the five spec values in every render path (orientation page, workspace page, error page).
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_shell_root_declares_entry_state_in_all_render_paths`
- [ ] `leave_point.status: absent` resolves to `cold_start`; first contact and >14d cold trajectories render no re-entry overlay region.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_cold_start_shows_no_reentry_overlay`
- [ ] Orientation HTTP 503 resolves to `no_vault` with a retry affordance and no fabricated snapshot content.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_runtime_unavailable_resolves_to_no_vault`
- [ ] `orienting` carries `data-reentry-shape` derived from the latency-ladder gap, and `degraded` / `stale` render as cross-flag attributes, not separate states.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_orienting_carries_shape_and_cross_flags`
- [ ] Undeclared transitions are rejected: state resolution never emits a value outside the enum and surfaces out-of-contract inputs as degraded reasons.
  Verify: `tests/companion_ui/test_entry_state_machine.py::test_undeclared_transitions_are_rejected`
- [ ] The existing orientation and workspace pages render byte-compatible content apart from the new attributes (no behavior regression).
  Verify: `tests/companion_ui/test_workspace_layout.py` and `tests/companion_ui/test_reentry_orientation_surface.py` (existing suites stay green)

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_entry_state_machine.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_workspace_layout.py tests/companion_ui/test_reentry_orientation_surface.py`
- `ruff check app tests`

## Out of Scope

- Any change to `GET /api/companion/orientation` or `GET /api/companion/workspace` schemas.
- The re-entry mist visual treatment (SEP-02).
- The overlay host and keyboard map (SEP-03).
- Client-side routing or SPA conversion — the page remains server-rendered.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Entry-point state model
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
- `companion-ui/docs/CONTINUITY_AND_DECAY.md` (latency ladder)

## Related GitHub Issues

Create one issue: `[SystemEntryPoint] entry-state-machine: server-side entry-state resolution`. This is the foundation issue; it blocks SEP-02 and SEP-03.
