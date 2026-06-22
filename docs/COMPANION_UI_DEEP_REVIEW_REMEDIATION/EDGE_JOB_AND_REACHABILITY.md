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
resilient, never-clipping command/overflow surface** (the existing `cmd` overlay, ⌘K). Operator
telemetry moves off the shell surface entirely — reachable only via the System Map / operator
layer.

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
| All non-Capture surface-launch icons (vault, map, memory, receipts, settings, help) | Routed into the `cmd` overlay (⌘K); the overflow surface is never-clipping |

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
top edge, or reachable through the `cmd` overlay (⌘K), which never clips.
No launch icon sits behind the rail or off the viewport edge at either width.

> Verify: static — render the shell at 1280 and 1440 px viewport widths via
> `render_index_html`; for each launcher in `SHIPPED_TOPBAR_SURFACES` assert either
> (a) `data-surface="{surface}"` is present inside the `data-region="surface-icons"` nav
> and is not positioned beyond the viewport edge, or (b) the surface is reachable via the
> `cmd` overlay and `data-surface="{surface}"` is absent from the topbar nav. Assert
> `data-surface="capture"` remains on the topbar at both widths.

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
> appear on the shell surface; assert the operator layer carries them.

## How to Verify (Pre-Merge)

1. **B2 pointer-hit-test** — `tests/companion_ui/test_topbar_edge_job.py::test_launchers_reachable_at_1280_and_1440`. Renders the shell fixture at both widths, walks `SHIPPED_TOPBAR_SURFACES`, and asserts each is either on the topbar or in the `cmd` overlay surface registry. Capture is always on the topbar; vault/map/memory/receipts/settings/help are always off it.

2. **B3 narrow-shell capture** — `tests/companion_ui/test_topbar_edge_job.py::test_narrow_shell_composed_edges_at_430`. Renders at 430 px; asserts truncation CSS on the identity region; asserts a single bottom-bar container; asserts no stray fixed-position bottom elements.

3. **C1 telemetry scan** — `tests/companion_ui/test_topbar_edge_job.py::test_operator_telemetry_absent_from_shell`. Iterates entry-state fixtures; asserts the operator testids and runtime-pill intents are absent from the shell render; asserts they appear in the operator/System Map layer render.

All three are static (no live runtime required). A Playwright live UAT confirming pointer hit-tests at real viewport widths is a stretch goal, not a merge gate for this task.

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
  `SHIPPED_TOPBAR_SURFACES`, `KEYBOARD_MAP`, `INTENT_OVERLAY_TARGETS`; the `cmd` overlay
  is already declared and shipped; this task removes icons from the topbar nav and confirms
  they remain reachable via `cmd.open`
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/OVERLAY_MODAL_FRAME_SPEC.md` — CUIDR-05,
  the frame contract for the `cmd` overlay that absorbs the displaced launchers
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` — CUIDR-03,
  the rail-collapse task that reclaims width; B2's overlap finding (rail header covers topbar
  icon cluster) is fixed by that task reducing rail extent, reinforced by this task moving
  icons out of the crowded topbar nav

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] edge-job-and-reachability; Wave 1; agent:ready.
