---
name: Mist Ladder Subtractive
description: Make the re-entry mist ladder genuinely gradual by rendering the orientation panels only from full_mist upward, de-duplicated and arranged beneath the re-entry card, so short gaps read as continuity and the card carries the orienting load.
task_id: CUIDR-06
source_anchor: companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt :: 02 J4; 04 A1
parent_capability: Companion UI Deep-Review Remediation
prerequisites: [CUIDR-01, CUIDR-03, CUIDR-04]
depends_on: [CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md, RAIL_AMBIENT_UNTIL_ACTIVE.md, EDGE_JOB_AND_REACHABILITY.md]
can_parallelize_with: [Governed Receipt First Class, Blocked Recourse and Lane Labeling]
---

# Mist Ladder Subtractive

## Purpose

The re-entry mist ladder is the signature feature of the Companion UI — the mechanism that
recovers your thread in proportion to how long you were away. Today it does not grade. The
maximum orientation load is the floor: `no_mist` (~30 s) and `thread_fade` (~5 min) are
pixel-identical, and both already render the full Re-entry snapshot — leave point, three open
loops, two notable changes, and governance summary tiles. The thing that should be absent at
short gaps is always present; the re-entry card, which should do the heaviest lifting at the
highest rungs, arrives on top of the same dashboard, repeating data the panels below it already
state. Calm, proportional re-entry has become a re-entry console.

This task reverses that. It makes the ladder subtractive: short gaps show little to nothing,
and the orientation panels appear only where the gap genuinely warrants them — from `full_mist`
upward, arranged beneath the card and stripped of every datum the card already names. It also
fixes the layout defect at `long_mist` (D4: the whisper column's "DOING" text overlaps the
card's ⓘ glyph) and removes the governance summary tiles from the orientation surface at every
rung (they belong behind the System Map, per CUIDR-04).

**Constraint (non-negotiable):** the runtime declares the mist rung and the snapshot data. The
UI renders proportionally to what is declared. No entry-state, rung, staleness, or snapshot
classification moves into the client — this boundary is test-enforced and is the point of the
system.

## What This Task Does

### `no_mist` (~30 s)

Renders as a near-uninterrupted session. No orientation overlay, no snapshot panels, no
re-entry card. At most: a single quiet resume line echoing the leave point (e.g.
"Back — you were in Midgård"), rendered as ambient copy subordinate to the active note. No
open-loop counts, no change counts, no governance tiles.

### `thread_fade` (~5 min)

Renders the peripheral rail cue only: the rail's fractional-opacity fade (already declared via
`data-reentry-fade`) signals the thread is cooling without interrupting the reading surface.
No orientation panels, no re-entry card, no snapshot. Visually distinguishable from `no_mist`
by the rail fade alone; nothing else changes.

### `soft_mist` (~20–30 min)

Renders residual ambient cues: the caret-echo cue ("Where you stopped") and any marginalia
the runtime declares. No re-entry card, no snapshot panels, no open-loop/change counts. The
ambient layer is intentionally sparse — one locating signal, not an orientation dashboard.

### `full_mist` (~1 h – 1 day)

Introduces the re-entry card. The card's four-question structure —
*what was I doing · where did momentum stop · what remains unresolved · what changed since* —
plus the WARM/DORMANT badge and the Resume / Start-fresh pair carries the orienting load.
Below the card, orientation panels may appear for open loops and notable changes — but only
data not already stated in the card. The card names leave point, open-loop count, and change
count; the panels below it enumerate the items without repeating those counts as headlines.
No governance/telemetry tiles at any rung.

### `long_mist` (~7 d +)

Adds the delta strip (`data-region="delta-strip"`) and the right-margin whisper column
(`data-region="whisper-column"`) — both suppressed in narrow mode. The whisper column must
not overlap the card's ⓘ glyph: the column's `doing` slot is positioned with sufficient
right-side clearance from the card's info icon so "DOING" text does not collide (D4 fix).
The orientation panels remain de-duplicated against the card: no datum stated in the card
appears again as a panel headline.

### Off-nominal rungs (preserve as-is)

`degraded` (E8) and `stale` (E9) are exemplary and must not be modified. The degraded rung
renders an amber partial-orientation notice and suppresses Resume. The stale rung renders
"Source changed since this was captured. Nothing was mutated." with Resume correctly replaced
by "Open the current artifact state." The only repair in scope for off-nominal rungs is enum
leakage (raw `resurfacing_source_unavailable` chip) — consumed from CUIDR-01's humanising
map.

## Concretely

**Governance tiles removed from orientation surface:** the governance summary block
(`data-region="governance-summary"`, currently rendered at E3–E8) is removed from all
orientation rungs. This block (pending proposals / receipts / latest outcome) is operator
telemetry; it belongs behind the System Map. CUIDR-04 owns its removal; this task depends on
that removal being in place before merge (prerequisite gate).

**De-duplication contract:** at `full_mist` and `long_mist`, before rendering any orientation
panel, the renderer checks whether the datum (leave-point slug, open-loop count, change count)
is already present in the re-entry card payload. If it is, the panel does not repeat it as a
headline or summary line. Enumerations (the individual loop items, the individual change items)
may appear in the panels as they are distinct from the counts the card states.

**Whisper column / ⓘ clearance (D4):** the whisper column's CSS positions the column with a
minimum right-offset from the card edge sufficient to avoid the card's ⓘ info glyph (nominally
`right: calc(var(--card-info-glyph-width) + 0.75rem)` or equivalent from the design token).
The "DOING" whisper item must clear the ⓘ hit target at every viewport width where the whisper
column is not suppressed.

**No-telemetry contract:** no `data-region="governance-summary"` element, and no governance
or operator telemetry content (pending proposal counts, receipt counts, outcome labels), renders
on any orientation surface at any rung — including `no_mist` through `long_mist` and the
degraded/stale off-nominal rungs.

**Runtime declaration boundary:** the renderer reads `orientation.rung`, `orientation.snapshot`
(leave point, open loops, notable changes), `orientation.card` (four-question payload,
WARM/DORMANT badge, resume token), and `orientation.delta` (delta strip and whisper column
items). It renders proportionally. It does not compute or infer any of these values.

## Why This Matters

The review's J4 verdict is "Broken" on Axis A specifically because the mist ladder inverts its
own philosophy. The re-entry card is the strongest single artifact in the UI — its four-question
structure, WARM/DORMANT badge, and Resume/Start-fresh pair constitute a genuine thread-recovery
affordance. Today it is buried under a dashboard it was supposed to replace. Making the ladder
subtractive means the card carries more of the orienting load at the rungs where the user needs
it, and carries nothing at the rungs where they don't. The surface becomes proportional to the
gap; calm re-entry is the default rather than the exception.

## Acceptance Criteria

**A1 (static):** `no_mist` and `thread_fade` are visually distinguishable, and neither renders
the orientation panels; the snapshot panels appear only at `full_mist` and above, with no datum
(open-loop count, change count, leave point) repeated between the card and a panel.

Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_thread_fade_renders_no_card_and_no_peripheral_line` (confirms thread_fade is rail-fade only, no panels); render each rung fixture and diff — `no_mist` must carry no orientation overlay marker; `thread_fade` must carry only `data-reentry-fade`; `full_mist` and `long_mist` may carry snapshot panels but must not repeat counts stated in the card. New test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_mist_ladder_subtractive_no_panel_at_short_rungs`.

**A1 (live):** The re-entry card's resume action restores the prior caret/scroll position; the
entrance reads as proportional to the rung (heavier only at higher rungs).

Verify: `live` — requires runtime + motion; assert caret/scroll position is restored from the
leave-point token in the runtime payload, not a client-held value.

**D4-collision (static):** At `long_mist` the whisper column does not overlap the card's info
glyph.

Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_adds_delta_strip_and_whisper_column` (existing) extended to assert the whisper column element carries the correct clearance data-attribute or inline style; new test: `tests/companion_ui/test_reentry_orientation_treatment.py::test_long_mist_whisper_clears_info_glyph` — render the `long_mist` fixture at standard viewport, assert `data-region="whisper-column"` element does not overlap `data-reentry-info-glyph` bounding box (static — E7 fixture).

**No-telemetry-on-orientation AC:** no governance/telemetry tile renders on the orientation
surface at any rung (consistent with CUIDR-04).

Verify: `tests/companion_ui/test_reentry_orientation_treatment.py::test_no_governance_tiles_on_orientation_surface` — static; render all six rung fixtures (no_mist, thread_fade, soft_mist, full_mist, long_mist, degraded); assert `data-region="governance-summary"` is absent from every output.

## How to Verify (Pre-Merge)

1. Run the full orientation treatment suite:
   `pytest tests/companion_ui/test_reentry_orientation_treatment.py -v`
   Confirm all existing tests pass (no regressions to the off-nominal E8/E9 rungs).

2. Run the orientation surface suite:
   `pytest tests/companion_ui/test_reentry_orientation_surface.py -v`
   Confirm no regressions.

3. Static rung diff: render each fixture (no_mist, thread_fade, soft_mist, full_mist,
   long_mist) and confirm:
   - `no_mist`: no orientation overlay marker, no snapshot panels, at most one ambient resume
     line.
   - `thread_fade`: `data-reentry-fade` present; no card, no panels, no peripheral line —
     consistent with `test_thread_fade_renders_no_card_and_no_peripheral_line`.
   - `soft_mist`: caret-echo cue present; no card, no snapshot panels —
     consistent with `test_soft_mist_renders_no_card`.
   - `full_mist`: card present with four questions; snapshot panels present but no datum
     repeated from the card.
   - `long_mist`: card + delta strip + whisper column; whisper column clears ⓘ glyph; no
     governance tiles.

4. No-telemetry scan: grep the rendered HTML of all orientation fixtures for
   `governance-summary` — must return empty.

5. For the A1 live AC: with the runtime running, navigate away from a note, wait past the
   `full_mist` threshold, navigate back, and confirm the card renders with the correct
   WARM/DORMANT badge; click Resume and assert the scroll position is restored to the last
   known caret position.

## Out of Scope

- The off-nominal rung structure of `degraded` (E8) and `stale` (E9) — preserve exactly;
  the only permitted repair is routing `resurfacing_source_unavailable` through CUIDR-01's
  humanising map.
- Cold-start / long-absence threshold reconsideration (>14 days routes to `cold_start`) —
  deferred to the strategic E1 recommendation; this task does not change the classification
  boundary.
- The rail-vs-palette relationship — deferred to the E2 strategic recommendation.
- Animated transitions between rung states — deferred; this task requires the rendered state,
  not the motion.
- The `cold_start` surface (E1, E2) — owned by FRONT_DOOR_AND_COPY_HYGIENE.md and the
  strategic spec.
- Governance tiles in non-orientation surfaces (the System Map, the operator layer) — not in
  scope here; CUIDR-04 owns their relocation.

## Restart / Durability Posture

The mist rung, leave-point token, open-loop snapshot, and change snapshot are all
runtime-declared via the orientation API (`app/api/routes/orientation.py`,
`app/orientation/runtime.py`). None of this data is held in client state.

On restart, the server recomputes the rung from the leave-point cursor
(`app/orientation/leave_point_cursor.py`) and the bundle consumer
(`app/orientation/bundle_consumer.py`). The user sees the rung appropriate to the elapsed
time at the moment of re-entry — no stale client-side rung persists across page loads.

If the runtime is unreachable at re-entry, the degraded path (E8) is shown: the orientation
surface renders the amber partial-orientation banner
"Partial orientation · Runtime posture: degraded · Missing source." with Resume suppressed.
This is the existing `degraded` rung, already test-covered and must not be modified. The
user is never shown a blank surface or a raw error; the calm degraded grammar (CUIDR-01)
applies to any unavailable source within the orientation response.

## Related Docs

- `companion-ui/design_handoff/2026-06-22-companion-ui-deep-review/REVIEW_RESPONSE.txt` —
  J4 verdict (E3–E9 evidence; A1 recommendation; D4 collision finding)
- `app/orientation/runtime.py` — mist rung declaration; snapshot payload
- `app/orientation/leave_point_cursor.py` — leave-point token; cursor persistence
- `app/orientation/bundle_consumer.py` — bundle → orientation snapshot assembly
- `app/api/routes/orientation.py` — orientation API route; rung + snapshot response shape
- `tests/companion_ui/test_reentry_orientation_treatment.py` — primary test home for this task
- `tests/companion_ui/test_reentry_orientation_surface.py` — orientation surface contract
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP.md`
  (CUIDR-01) — humanising map this task consumes for enum token repair
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/RAIL_AMBIENT_UNTIL_ACTIVE.md` (CUIDR-03) —
  rail active state this task renders within
- `docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/EDGE_JOB_AND_REACHABILITY.md` (CUIDR-04) —
  governs removal of telemetry from the orientation surface; this task depends on that
  removal being complete before merge

## Related GitHub Issues

Maps to child issue [Companion UI Deep-Review] mist-ladder-subtractive; Wave 2;
agent:blocked until CUIDR-01 (CALM_DEGRADED_GRAMMAR_AND_ENUM_MAP), CUIDR-03
(RAIL_AMBIENT_UNTIL_ACTIVE), and CUIDR-04 (EDGE_JOB_AND_REACHABILITY) merge.
