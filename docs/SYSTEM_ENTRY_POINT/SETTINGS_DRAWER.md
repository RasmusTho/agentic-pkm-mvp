---
name: Settings Drawer
description: Local UI settings drawer consolidating shipped display preferences (#1675) plus listening preferences, with byte-unchanged guarantee, local-only badge, and reset-to-canonical
task_id: SEP-07
source_anchor: companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md :: Resolved Q19
parent_capability: system-entry-point
prerequisites: [SEP-03]
depends_on: [UNIFIED_TOPBAR_AND_OVERLAY_HOST.md]
can_parallelize_with: [PANEL_COMMAND_PALETTE.md, SYSTEM_MAP_OVERLAY.md, RECEIPTS_HISTORY_SURFACE.md, GUIDANCE_LAYER.md]
---

# Settings Drawer

## Purpose

Give the Local UI preferences one coherent home — a right drawer per the design — without changing their authority class: preferences re-render identical content, never touch the vault, and are always resettable.

## What This Task Does

- Mounts a Settings drawer on the overlay host (`settings.open`), consolidating:
  - **Display** preferences: the shipped #1675 controls (font size, line height, reading width, focus mode — `data-testid="display-pref-*"`) move into / are mirrored by the drawer. Issue #1675 is **delivered and closed**; this task builds on that shipped slice and must not re-implement or regress it.
  - **Listening** preferences per the #1641/#1643 contract lineage: modality and speed over the shipped TTS read-back, render-only.
  - **Companion behaviour**: the guidance-layer default (extends SEP-06's session-local toggle into a stored Local UI preference) and **quiet hours** — which dampen ambient salience presentation only and can never schedule, suppress, or batch notifications (spec §Resolved Q18; there are no notifications).
  - **Connection posture**: read-only display of the runtime/vault posture; the UI never selects or names a vault.
- Storage home: the `WORKSPACE_STATE_CONTRACT.md` local-state home as pinned by `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` — never vault Markdown/frontmatter, never a save/projection endpoint. (#1675 shipped `localStorage`; this task keeps that mechanism unless the local-state home dictates otherwise — reconcile, don't fork.)
- Guarantees: canonical Markdown hash **byte-unchanged** across any preference change; **`local-only render` badge** whenever a preference diverges from the canonical render; **reset-to-canonical** always available; per-surface overrides may layer on global defaults.

## Concretely

```text
settings.open → right drawer; Display / Listening / Behaviour / Connection sections
set font size lg → note re-renders; content_hash unchanged; local-only badge visible
settings.reset → canonical render restored; badge gone
quiet hours 22:00–07:00 → ambient cue intensity reduced in window; nothing else changes
```

## Why This Matters

Preferences are the easiest place for authority creep: one preference write that reaches the vault or a save endpoint breaks the byte-unchanged contract and turns Local UI into hidden semantic state.

## Acceptance Criteria

- [ ] The drawer renders Display, Listening, Behaviour, and Connection sections; the shipped #1675 display controls keep working unregressed.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_drawer_sections_render_and_display_prefs_work` and `tests/companion_ui/test_display_preferences.py` (existing suite stays green)
- [ ] Any preference change leaves the canonical Markdown/content hash byte-unchanged.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_preferences_leave_canonical_hash_byte_unchanged`
- [ ] No preference change calls a save/projection endpoint or reaches the vault.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_no_preference_write_reaches_save_or_vault`
- [ ] A `local-only render` badge appears whenever a preference diverges and disappears on reset-to-canonical.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_local_only_badge_on_divergence_and_reset`
- [ ] Quiet hours affect ambient salience presentation only — no notification, scheduler, or suppression machinery exists.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_quiet_hours_dampen_presentation_only`
- [ ] The connection section is read-only and never offers vault selection.
  Verify: `tests/companion_ui/test_settings_drawer.py::test_connection_posture_is_read_only`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_settings_drawer.py tests/companion_ui/test_display_preferences.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/companion_ui/test_tts_readback.py`
- `ruff check app tests`

## Out of Scope

- Re-implementing or relocating the delivered #1675 slice's semantics — only consolidating its presentation.
- Semantic transformations ("simplify", "summarize", "fix spelling") — separately governed flows per `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` RQ-9.
- Vault selection/binding (runtime-owned).
- TTS provider/endpoint changes (`LOCAL_FIRST_TTS_CONTRACT.md` owns that boundary).

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q18, §Resolved Q19
- `companion-ui/docs/DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (local-state home)
- `companion-ui/docs/LOCAL_FIRST_TTS_CONTRACT.md`

## Related GitHub Issues

Filed as **#1789** (`[SystemEntryPoint] settings-drawer: Local UI preference drawer`). Do not create a duplicate issue; use the filing record in `README.md §Relationship to GitHub Issues` for current pickup state and dependencies. Reference delivered #1675 (display preferences UI) and contract issues #1641/#1643 in Context; do not duplicate them.
