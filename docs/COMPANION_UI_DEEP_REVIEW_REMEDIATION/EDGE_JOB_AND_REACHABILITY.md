---
name: Edge Job and Reachability
description: Fix topbar clipping and narrow-edge collisions; move operator telemetry off the shell surface.
task_id: CUIDR-04
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 03 Reachability + Responsive integrity; 04 B2/B3/C1
parent_capability: Companion UI Deep-Review Remediation
prerequisites: []
depends_on: []
can_parallelize_with: [Calm Degraded Grammar and Enum Map, Overlay Modal Frame Spec, Rail Ambient Until Active, Front Door and Copy Hygiene]
---

# Edge Job and Reachability

## Purpose

The topbar currently carries two incompatible burdens: it is an operator-telemetry strip and a
surface-launcher cluster. Neither job survives at real viewport widths — launchers clip off-screen
at ≤1440 px and the operator telemetry violates the anti-dashboard posture it sits on. At 430 px
the identity string overflows without truncation and the bottom edge becomes a collision of
independently-positioned elements fighting for one corner. This task resolves both edges through
a deliberate design decision, not a CSS patch.

## What This Task Does

Three related review findings are folded into a single bounded unit because they share one root
cause — the topbar's job is undefined:

- **B2 (Reachability — Broken):** At ≤1440 px the topbar clips its own surface-launch icons
  off-screen and the rail header overlaps the icon cluster. Only ⌘K and ⌘N have keyboard
  fallbacks, so several entry points are unreachable by pointer and discoverability quietly
  collapses onto the System Map alone.

- **B3 (Responsive integrity — Friction):** At 430 px the identity/status string runs off-screen
  with no wrap or truncation. The bottom edge collides — the "Edit note body" hint, the
  Outline/Panel sheet triggers, and the floating Operator/Help pills occupy the same corner
  without a shared container.

- **C1 (Cognitive load — Operator telemetry on an anti-dashboard surface):** The topbar renders
  `N RECOVERY`, `ok Online`, `as-of 21:08`, and the amber ⚠ Operator pill on the primary
  reading surface. That is diagnostic data for operators; it does not belong on the front edge.

The settled design decision that bounds all three: **the top edge keeps IDENTITY + ONE primary
action (Capture, ⌘N — the most-used launcher); ALL other surface launchers route into one
resilient, never-clipping command/overflow surface.** That overflow surface is the **System Map
overlay** — the real surface index — not the `cmd` Panel palette. (Codex review of this spec PR
flagged the seam: the shipped `cmd.open` contract — `docs/SYSTEM_ENTRY_POINT/
PANEL_COMMAND_PALETTE.md`, `tests/companion_ui/test_panel_command_palette.py` — defines `cmd` as a
*presentation of the Panel rail's server-declared proposals* (`data-presentation-of="panel-rail"`),
not a general launcher; broadening it fails closed. The displaced launchers therefore route to the
System Map, which already indexes every surface.) Operator telemetry moves off the shell surface
entirely — reachable only via the System Map / operator layer.

## Concretely

**What stays on the top edge:**

| Element | Treatment |
|---|---|
| Wordmark / identity | Preserved; `data-region="workspace-header"` unchanged |
| Document-anchor pill | Preserved; truncates with ellipsis when needed |
| Vault-status dot | Preserved; coarse posture only (ok / degraded / blocked / unavailable) |
| Capture affordance (⌘N) | Preserved; the single primary launcher on the bar |
| Posture pill | Preserved; rendering-only, server-declared |

**What moves off the top edge:**

| Element | Destination |
|---|---|
| `N RECOVERY` recovery counter | System Map / operator layer only |
| `ok Online` runtime status text | System Map / operator layer only |
| `as-of HH:MM` freshness timestamp | System Map / operator layer only |
| ⚠ Operator pill | System Map / operator layer only |
| All non-Capture surface-launch icons (vault, map, memory, receipts, settings) | Routed into the **System Map overlay** (the never-clipping surface index); its single opener lives in the composed bottom bar (`map.open`). NOT the `cmd` Panel palette. |
| Help launcher | Composed bottom bar (the Help control), alongside the System Map opener |
| Vault-settings launcher | Identity-adjacent, kept beside the vault chip (vault config, not a launcher) |

**Presentation only.** The telemetry VALUES continue to come from the runtime payload;
this task changes WHERE they render (operator layer, not the front edge). The server-side
posture and classification boundary is unchanged.

**Composed top bar at 430 px:**

The identity/status string uses `text-overflow: ellipsis; white-space: nowrap; overflow: hidden`
with a minimum guaranteed width, so it never runs off-screen. A single affordance (e.g. a
truncation indicator or the vault-status dot itself) signals that more context exists without
requiring a visible overflow. The full string is reachable via the `cmd` overlay or the System Map.

**Composed bottom bar at 430 px:**

The bottom edge consolidates into one composed bar with a defined stacking order:

1. Sheet trigger controls (Outline / Panel) — leftmost, primary affordance group
2. "Edit note body" contextual hint — center, secondary
3. Help control — rightmost, tertiary

The floating Operator pill is removed from the bottom edge and routed to the operator layer. No
independently-positioned fixed elements remain at the bottom edge.

## Why This Matters

Reachability is a correctness property, not a polish concern. When launchers clip and the
only reliable fallback is ⌘K/⌘N, the surface is effectively keyboard-only — undiscoverable
to pointer users. At 430 px an overflowing identity string and a four-element bottom collision
signal a shell that has not been designed at that width, not merely a visual imperfection.

The telemetry relocation (C1) is the highest-leverage change for the anti-dashboard posture:
every surface the user touches front-loads operator diagnostic noise that belongs one level
deeper. Removing it from the shell does not reduce access — it moves it to the correct layer
where operators expect it.

## Acceptance Criteria

**B2** — At 1280 px and 1440 px every surface launcher is either visible and clickable on the
top edge, or reachable through the **System Map overlay** (a never-clipping surface index).
No launch icon sits behind the rail or off the viewport edge at either width.

> Verify: static — render the shell via `render_index_html`; assert
> `SHIPPED_TOPBAR_SURFACES == ("capture",)` and that `data-surface="capture"` is present in the
> `data-region="surface-icons"` nav. For each surface in `OVERFLOW_TOPBAR_SURFACES`
> (vault/map/memory/receipts/settings/help) assert `data-surface="{surface}"` is absent from the
> topbar nav; vault/map/memory/receipts/settings each carry a `data-surface-id="{surface}"` node in
> the System Map overlay, and help is reachable via the composed bottom bar
> (`data-testid="workspace-help-toggle"`). The render is width-independent server markup, so the
> 1280/1440 contract holds structurally — a launcher reachable only via the never-clipping System
> Map cannot clip off the topbar at any width.

**B3** — At 430 px the status string carries `text-overflow: ellipsis` (or equivalent
truncation CSS), the identity region never overflows the viewport, and all bottom-edge
controls (`data-region="bottom-bar"` or equivalent) occupy a single composed container
with no independently-positioned siblings at `position: fixed; bottom: ...`.

> Verify: static — render at 430 px viewport width; assert the topbar identity region
> contains truncation CSS; assert a single `data-region="bottom-bar"` element exists;
> assert no `position: fixed` element with `bottom` sits outside that container.

**C1** — No operator or diagnostic telemetry renders on the shell or orientation surfaces.
Specifically: no element carrying `data-testid="workspace-runtime-pill"`,
`data-testid="workspace-freshness"`, `data-testid="workspace-quick-open"` (as a
front-edge affordance), or `data-intent="operator.open"` appears in any entry-state
render outside the operator/System Map overlay.

> Verify: static — scan renders across entry states (cold_start, no_mist, thread_fade,
> full_mist, long_mist, degraded) for the listed testids and data-intents; assert none
> appear on the shell/orientation front surface (the operator/System Map overlay region is
> excluded from the scan); assert the operator layer carries them. The detailed runtime
> telemetry is **relocated, not discarded**: it renders in the server-rendered
> `data-region="operator-telemetry"` / `data-layer="operator"` region (hidden from the reading
> surface) and is reachable via the System Map operator node (`operator.open`).

## How to Verify (Pre-Merge)

1. **B2 pointer-hit-test** — `tests/companion_ui/test_topbar_edge_job.py::test_launchers_reachable_at_1280_and_1440`. Asserts `SHIPPED_TOPBAR_SURFACES == ("capture",)` (Capture is the single topbar launcher), each `OVERFLOW_TOPBAR_SURFACES` launcher is absent from the topbar nav, vault/map/memory/receipts/settings carry a System Map node, and help is reachable via the composed bottom bar.

2. **B3 narrow-shell capture** — `tests/companion_ui/test_topbar_edge_job.py::test_narrow_shell_composed_edges_at_430`. Asserts truncation CSS (`text-overflow: ellipsis; white-space: nowrap; overflow: hidden`) on the identity region; a single `data-region="bottom-bar"` container; no stray fixed-position operator pill at the bottom edge.

3. **C1 telemetry scan** — `tests/companion_ui/test_topbar_edge_job.py::test_operator_telemetry_absent_from_shell`. Iterates entry-state fixtures with the operator layer stripped; asserts the operator testids and `operator.open` intent are absent from the front surface; asserts the relocated telemetry lives in the hidden operator-telemetry region and the System Map operator node carries `operator.open`.

All three are static (no live runtime required). A Playwright live UAT confirming pointer hit-tests at real viewport widths is a stretch goal, not a merge gate for this task — defer to the parent (#2443) live UAT pass.

## Out of Scope

- The `cmd` overlay's internal surface routing or its visual frame — governed by CUIDR-02
  (Overlay Modal Frame Spec).
- Bottom-sheet snap state or drag-handle behavior at 430 px — governed by the existing
  `test_converse_session_drawer_portrait.py` suite; this task only defines the composed bar
  container contract.
- The System Map's internal surface listing or copy — governed by CUIDR-01 (Front Door and
  Copy Hygiene).
- The orientation surface telemetry tiles (governance summary tiles on the re-entry rungs) —
  governed by CUIDR-06 (the mist-ladder task); the governance/telemetry tiles must be
  **removed** from the orientation render entirely, not relocated within it. This task and
  CUIDR-06 share the constraint that no telemetry surfaces on front-edge or orientation
  surfaces; coordinate the shell-layer boundary.
- Moving posture classification to the client — explicitly prohibited. Server remains
  authoritative.

## Related Docs

- `companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` — shell overlay grammar, keyboard map,
  data-attribute vocabulary (§Keyboard map, §Data-attribute vocabulary, §Resolved Q6)
- `companion-ui/companion-app/companion_ui/workspace/overlay_host.py` — `TOPBAR_SURFACES`,
  `SHIPPED_TOPBAR_SURFACES` (now `("capture",)`), `OVERFLOW_TOPBAR_SURFACES`, `KEYBOARD_MAP`,
  `INTENT_OVERLAY_TARGETS`; this task removes the launcher icons from the topbar nav and confirms
  they remain reachable via the System Map overlay (and the composed bottom bar for Help)
- `companion-ui/companion-app/companion_ui/workspace/system_map_overlay.py` — the never-clipping
  surface index that absorbs the displaced launchers; this task adds the `operator` node so the
  relocated operator/diagnostic telemetry is reachable from the map (`operator.open`)
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/OVERLAY_MODAL_FRAME_SPEC.md` — CUIDR-05,
  the modal-frame contract for overlays (the `cmd` palette stays a Panel-rail presentation; it is
  NOT broadened into a general launcher by this task)
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` — CUIDR-03,
  the rail-collapse task that reclaims width; B2's overlap finding (rail header covers topbar
  icon cluster) is fixed by that task reducing rail extent, reinforced by this task moving
  icons out of the crowded topbar nav

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] edge-job-and-reachability; Wave 1; agent:ready.
