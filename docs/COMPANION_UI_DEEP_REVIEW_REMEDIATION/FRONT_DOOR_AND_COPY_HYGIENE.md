---
name: Front Door and Copy Hygiene
description: Style the vault picker to the design system, make entry-screen actions ranked affordances, and strip internal issue numbers from the System Map.
task_id: CUIDR-05
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 02 J1 + J7; 04 D1/D2/C4/D4
parent_capability: Companion UI Deep-Review Remediation
prerequisites: []
depends_on: []
can_parallelize_with: [Calm Degraded Grammar and Enum Map, Overlay Modal Frame Spec, Rail Ambient Until Active, Edge Job and Reachability]
---

# Front Door and Copy Hygiene

## Purpose

The vault picker is the literal front door of the product. It currently renders as unstyled default-browser markup — system fonts, raw form controls, a bare "Open Niflheim" button, "unknown / unknown" recent-vault rows — making it look like a different application. The entry screen's action row uses browser-default blue underlined links that read as fine print rather than primary affordances. The System Map leaks internal issue references into user-facing copy. And several inputs (rail textarea, settings time fields) render white against the dark theme.

This task fixes all four of these together because they are independent, presentation-only, and require no new runtime contracts. Each is a targeted styling or copy change; none moves any classification or data decision to the client.

## What This Task Does

- **D1 — Style the vault picker (E11) to the design system.** Replace every default-browser form control, font, and colour in the `vault_selection_required` surface with design-system equivalents: dark-palette background, `--font-ui` / `--font-body` typography, styled input fields, button using the primary button class, recent-vault rows using the standard list-item treatment.
- **D2 — Make entry-screen actions real ranked affordances.** The `cold_start` / `no_vault` action row ("Find a note · Jot something down · See the map") currently renders as inline browser-blue underlined links. Replace with one primary button and two secondary buttons, all on-palette and at a size/weight that reads as the primary way in.
- **C4 — Strip internal issue numbers from the System Map.** The `system_map_overlay` module renders surface entries that currently embed bare internal references (`#1783`, `SEP-04`, `#1716+`). Remove them. Each surface entry must stand as: surface name + how to reach it + how it returns. If any context note is genuinely useful to an operator, it belongs only in the operator/guidance layer, not the user-facing map copy.
- **D4 (white-input nit) — Bring stray white inputs onto the dark palette.** The rail textarea and settings time inputs currently render with default white chrome. Apply `background: var(--color-input-bg)` / `color: var(--color-input-fg)` (or the equivalent design-system variables) across all three input classes so no input stands out against the dark theme.

## Concretely

The affected render surfaces and their source modules:

| Surface | Capture ref | Source module (approximate) |
|---------|-------------|----------------------------|
| Vault picker | E11 | `companion_ui/workspace/serve_dev_page.py` — `vault_selection_required` branch |
| Entry action row | E1, E2 | `companion_ui/workspace/serve_dev_page.py` — `cold_start` / `no_vault` orientation render |
| System Map copy | O7 | `companion_ui/workspace/system_map_overlay.py` — `MAP_SURFACES` node definitions |
| Rail textarea | S2 rail | Right-rail panel markup (CSS or inline style) |
| Settings time inputs | O4 | `companion_ui/workspace/settings_drawer.py` — quiet-hours time inputs |

All changes are in the presentation layer (HTML/CSS/copy strings). No routing logic, no entry-state machine changes, no data contracts.

## Why This Matters

The vault picker is the first screen a user with no vault bound will ever see; if it looks broken the trust cost is immediate and irreversible. The entry-screen action row is the only navigation affordance on cold contact — the review's Axis B verdict for J1 is "Broken" specifically because of these two items. The System Map issue-number leakage breaks the copy contract that the map is an honest identity-and-routing index, not a changelog. The white inputs are a small but persistent signal that the dark theme is incomplete.

None of these are core-loop changes, but together they remove the four most immediately obvious "different application" signals from the surfaces a user sees first (J1) and returns to for orientation (J7).

## Acceptance Criteria

**D1 — Vault picker styled to design system**

The vault picker uses the design system's fonts, colours, controls, and spacing — indistinguishable in family from the rest of the app; no default-browser form styling remains.

- Verify: `tests/companion_ui/test_workspace_no_vault_picker.py` — render `vault_selection_required` fixture and assert `class="btn btn--primary"` (or equivalent DS class) on the configured-vault open button; assert no `<input type="text">` or `<select>` without the DS input class; assert no `font-family: serif` in inline styles. (New assertions acceptable alongside existing tests.)
- Static capture: E11 diff before/after.

**D2 — Entry-screen actions are ranked on-palette affordances**

Entry-screen actions are ranked, on-palette affordances (one primary), not inline browser-blue links.

- Verify: `tests/companion_ui/test_workspace_entry_state.py` (or a new `test_entry_screen_action_row.py`) — render `cold_start` orientation and assert the action row contains exactly one element with `class` including `btn--primary` and two elements with `class` including `btn--secondary`; assert no `<a href` tags in the action row region.
- Static capture: E1 / E2 diff before/after.

**C4 — System Map carries no bare internal issue numbers**

The System Map carries no bare internal issue numbers in user-facing copy; each surface entry reads as identity + how-to-reach + how-it-returns.

- Verify: `tests/companion_ui/test_system_map_overlay.py` — add an assertion over the rendered overlay HTML that `re.search(r'#\d{3,}', overlay_html)` finds no match, and that no node's `status_note` or `reached`/`returns` fields in `MAP_SURFACES` contain a bare `#NNNN` pattern. (New assertion inline with existing `test_map_renders_composition_table_nodes`.)
- Static capture: O7 diff before/after.

**White-input AC — No input renders with default white chrome**

No input (vault picker fields, rail textarea, settings time inputs) renders with default white chrome against the dark theme.

- Verify: `tests/companion_ui/test_settings_drawer.py` — render the settings drawer and assert that every `<input type="time">` element's inline style or class references a design-system variable (e.g. `var(--color-input-bg)` or a DS class such as `input--dark`); assert no `background: #fff` or `background: white` inline.
- Static capture: O4 (time inputs), S2-rail (textarea) diffs before/after.

## How to Verify (Pre-Merge)

1. Run the existing companion-UI test suite (`pytest tests/companion_ui/ -x -q --not-pg`). No regressions.
2. Render E11, E1, E2, O7, O4 fixtures via `render_index_html` with appropriate payloads and inspect the HTML:
   - E11: vault picker — zero raw `<input>` / `<select>` without DS classes; primary button class on the configured-vault open action.
   - E1/E2: cold_start action row — one `btn--primary`, two `btn--secondary` (or whatever the DS tokens are); no `<a href` in the action row.
   - O7: system map overlay — `grep -E '#[0-9]{3,}'` returns nothing from the rendered user-facing node copy.
   - O4: settings drawer — time inputs carry DS input class or CSS variable; no white inline styles.
3. Scan rail textarea markup for `background: white` / `background: #fff` / absence of DS variable.
4. All four static ACs pass. No live UAT gate for this task (all presentation-only, no motion or round-trip behaviour added).

## Out of Scope

- The vault picker's *content* — which vaults are listed, the configured-vault root value, recent-vault entries — is entirely server-declared. This task changes only styling; the runtime contract for `vault_selection_required` is untouched.
- The System Map's routing logic, surface list, node statuses, and route intents are unchanged. Only the user-facing copy strings (`reached`, `returns`, `status_note`) may change to remove issue references.
- The entry-screen action set ("Find a note · Jot something down · See the map") is unchanged; only the affordance treatment changes.
- The `long_mist` whisper-column / info-glyph collision (also called out in D4) is scoped to `MIST_LADDER_SUBTRACTIVE`, not this task. That collision is part of the mist-ladder re-authoring work.
- The vault browser "Error: Failed to fetch" raw error string is scoped to `CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP` (D3).
- No new overlays, no new route intents, no new server endpoints.

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` — review source; J1 verdict (Axis B Broken), J7 verdict (Axis B Works / nit), recommendations D1, D2, C4, D4.
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/README.md` — capability overview, Wave 1 task table, cross-task invariants.
- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — entry-state machine; `vault_selection_required` state definition.
- `companion-ui/docs/SYSTEM_MAP_OVERLAY.md` — system map surface spec; pull-based, non-authoritative index contract.
- `tests/companion_ui/test_workspace_no_vault_picker.py` — existing vault-picker render contract.
- `tests/companion_ui/test_system_map_overlay.py` — existing system-map overlay contract (C4 assertions extend here).
- `tests/companion_ui/test_settings_drawer.py` — existing settings drawer contract (white-input assertions extend here).

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] front-door-and-copy-hygiene; Wave 1; agent:ready.
