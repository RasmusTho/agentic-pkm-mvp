# Implementation contracts — Cold-start entry threshold

This is an **interaction contract limited to the `cold_start` / `no_vault` surface**. It amends, and must be read against, `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`. Where this package references runtime fields it does not declare them; field/schema changes go through owner-doc PRs (see `authority-boundaries.md`).

## State enum — UNCHANGED

The five states (`boot` / `no_vault` / `cold_start` / `orienting` / `shell_active`), the re-entry shape ladder, the `degraded`/`stale` cross-flag rules, and the allowed transition set are unchanged from `SYSTEM_ENTRY_POINT_SPEC.md`. This package only changes **what `cold_start` and `no_vault` render**.

`resolve_entry_state()` is unchanged. `cold_start` ← `leave_point.status == "absent"` (first contact) or cold trajectory (> 14 d). `degraded`/`stale` never decorate `cold_start`/`no_vault` (`EntryStateResolution.__post_init__`, `entry_state.py:94-114`).

## `cold_start` render contract (NEW)

Branch the body of `_render_orientation_index_html` on `entry_resolution.state`. For `cold_start`, **omit** the header band (`serve_dev_page.py:6377`), the telemetry meta row, and the orientation grid (`:6392-6408`); render the threshold instead. The full header + grid path is kept only for `orienting` / `shell_active`.

Top to bottom, the `cold_start` threshold renders:

1. **Vault chip** — status dot + `scope.vault_id` (server-declared, read-only). Echoes the topbar chip.
2. **Eyebrow + headline** — `leave_point.status == "absent"` → eyebrow "First contact", headline "Nothing is open yet."; cold trajectory (> 14 d) → eyebrow "Returning after a while", headline "Re-entry is through the vault." No mist, card, count, tint, or gravity-well in either variant.
3. **Verb-line** (`data-region="cold-start-verbs"`) — one inline sentence of text-weight affordances, **never** a button/card grid:
   - `Find a note` → `data-intent="vault.open"` → `vaultBrowser.focus()` (the declared `cold_start → shell_active` path)
   - `Jot something down` → `data-intent="capture.open"` → `overlayHost.mount('capture')`
   - `See the map` → `data-intent="map.open"` → `overlayHost.mount('map')` (the only opener; pull-only)
   - **No "Reorient" verb** — no trajectory exists to reorient into.
4. **Inline capture field** — a single unadorned line "Leave a note for future-you…" that on focus / `⌘N` mounts the shipped governed `capture` occupant verbatim. The caret is the one element allowed warmth (single-saturated-element rule); doors stay monochrome until hover.
5. **Provenance line** — one mono line in `fg-3`: `leave_point: absent · read-only · server-declared`.
6. **(Optional, operator-adopted) Recents-anchor** — if the runtime declares a most-recently-edited target on the cold payload, the Find verb carries a labeled sub-affordance "Open your most recent note" routing via `/workspace?note_path=…`. Omitted when the field is absent.

No `<details>` overflow, no "+N more", no zeroed collection anywhere on the surface.

### Region marker

`data-region="cold-start-threshold"` (container) and `data-region="cold-start-verbs"` (verb-line) are **renderer-convention structural regions**, not overlay occupants — they are NOT registered with `overlay_host`, carry no continuity claim, and are suppressed under reduced-content/print so the base style stays the calm threshold. Adding new `data-region` values is already permitted by the spec; no existing attribute is renamed.

## `no_vault` render contract (CORRECTION + restyle)

A routing correction every source design direction missed:

- **Primary path** — when `orientation is None` and `error` is set, `render_index_html` falls through `_render_error_section` (`:7208`) → `_render_vault_unreachable_state` (`:4884`), which **already ships** Retry (`data-intent="entry.retry"`, the declared `no_vault → boot` transition) + System map (`map.open`) with the sanctioned destructive runtime-health treatment and inert map nodes (`available_routes=()`). Delta = **copy restyle only** to the quiet register ("The runtime is unreachable. Nothing was lost."). Confirm **no** Find and **no** Jot verb: capture has no honest landing for an offline write at boot ("never claim a write it cannot back"). The alarm color stays confined to this one state.
- **Second path** — `orientation_error` set with a non-`None` orientation (the synthetic `_orientation_unavailable_frame` inside `_render_orientation_index_html`) must **also** branch to the threshold-minus-capture treatment: suppress the inline capture field when `entry_resolution.state == "no_vault"`, and render no re-entry overlay / no grid.

## Intent vocabulary delta

| Intent | Status | Change |
|---|---|---|
| `vault.open` | shipped | reused on `cold_start` verb-line; no change |
| `capture.open` | shipped | **proposed spec edit:** widen the `SYSTEM_ENTRY_POINT_SPEC.md` Surface column from `shell (⌘K) / map` to `shell (⌘K) / entry / map`. The intent string is unchanged (zero new intents); only its declared origin surface widens to `entry`. (Operator decision Q2 = adopt.) |
| `map.open` | shipped | reused on `cold_start` verb-line; pull-only; no change |
| `entry.retry` | shipped | reused on `no_vault`; no change |

No new entry/shell-composition intent is introduced.

## Proposed runtime contract field (recents-anchor) — Core Runtime

Operator-adopted (Q1). The runtime MAY emit a server-declared most-recently-edited target on the cold / first-contact orientation payload — a **Find / recency projection**, explicitly **NOT** a `leave_point` and **NOT** a continuity claim. Constraints:

- Declared by the runtime on the orientation payload (owner-doc: `WORKSPACE_ORIENTATION_CONTRACT.md`). It must **not** be a UI-side filesystem `mtime` probe — that would violate "no direct vault I/O from the UI" and re-open the host-vs-container mount hazard (#2141).
- Deterministic tiebreak (path sort) on the runtime side.
- The UI renders it as a labeled Find sub-affordance, routes via the existing `/workspace?note_path=` path, never auto-opens, and omits it when absent.

## Proposed `SYSTEM_ENTRY_POINT_SPEC.md` amendments (proposals — applied via reviewed PRs)

1. **State-enum, `cold_start` row (~line 70):** add a normative clarification that `cold_start` renders the intent-declaration threshold (vault chip + honest headline + verb-line + inline governed capture + provenance line) and explicitly does NOT render the orientation grid or any re-entry overlay; the orientation grid is gated to `state in ('orienting','shell_active')`. No state added or removed.
2. **Intent vocabulary, `capture.open` row (~line 176):** widen Surface to `shell (⌘K) / entry / map`.
3. **Data-attribute vocabulary (~line 116):** normalize `data-region="cold-start-threshold"` / `cold-start-verbs` as non-overlay structural regions carrying no continuity claim.
4. **Resolved questions (only if recents-anchor adopted):** declare the server-declared most-recently-edited Find/recency projection field and its render rules; cite the corresponding `WORKSPACE_ORIENTATION_CONTRACT.md` field.
