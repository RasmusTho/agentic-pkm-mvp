---
name: Surface Day Start Card
description: Companion-UI day-start card surfacing the generated briefing (listen + read), pure visual interaction, zero typing required, read-only
task_id: BRIEF-04
source_anchor: docs/HUMAN-FLOWS.md :: 0
parent_capability: Daily Briefing
prerequisites: [BRIEF-01]
depends_on: [COMPOSE_BRIEFING_ARTIFACT.md]
can_parallelize_with: [SCHEDULE_AND_TRIGGER_GENERATION, RENDER_BRIEFING_AUDIO]
---

# Surface Day Start Card

## Purpose

A briefing note the owner never sees is not a briefing. This task renders one day-start card in the Companion UI that surfaces today's generated briefing — listen and read — as a single glanceable, zero-typing surface, following the existing read-only companion-render pattern (`app/relevance/now_surface.py`'s glance surface, `RENDER_COMMITMENTS_IN_PANEL_UI`'s read-only projection precedent).

## What This Task Does

- Adds a read-only projection of today's briefing note (BRIEF-01's dated vault note) to the companion workspace, following the existing glance-surface pattern: a small server-side read function (sibling to `app/relevance/now_surface.py::collect_now_moments`) that loads `<system_dir>/briefings/<today>.md` and returns a view-model the UI renders.
- Renders **one card**: date, a short preview/summary, and two affordances — **listen** (wired from BRIEF-03; degrades to absent/disabled if BRIEF-03 has not yet merged or TTS is unavailable) and **read/expand** (shows the full composed briefing, including each item's provenance so the owner can trace any line back to its source commitment/moment/receipt).
- **Zero typing**: every action on the card (listen, expand/read, dismiss/collapse) is a tap/click affordance; the card introduces no text input of any kind.
- **Read-only**: no affordance may mutate a commitment, a decision receipt, or (in the future) an episode from the card. The card is a pure projection of the durable briefing note — matching the read-only discipline `RENDER_COMMITMENTS_IN_PANEL_UI` established for the same class of surface.
- **Three honest states, not two:** the card must visually distinguish (a) *not yet generated* (no note exists for today — BRIEF-02 has not fired yet, or is degraded), (b) *generated with a named degraded section* (BRIEF-01's fail-legible marker is present), and (c) *generated in full*. Collapsing (a) and (b) into a blank/empty card, or collapsing (b) and (c) into an undifferentiated "briefing available" state, both violate the fail-legible invariant this capability's README names.

## Concretely

When today's briefing exists and is complete: the card shows the date, a preview line, a "Listen" button (if BRIEF-03 has shipped and TTS is available), and a "Read" affordance that expands to the full briefing with provenance links per item.

When today's briefing does not exist yet: the card shows an explicit "Today's briefing isn't ready yet" state — not a blank region, not yesterday's briefing relabeled as today's.

When today's briefing exists but has a named degraded section (e.g. decision receipts could not be read): the card renders normally but visibly marks the degraded section (e.g. "Decision receipts: unavailable today") rather than silently omitting it.

## Why This Matters

This card is where the capability becomes real for the owner — everything upstream (composition, scheduling, audio) exists only to make this surface trustworthy and worth a glance. If the card could not tell "not yet generated" apart from "generated but incomplete," the owner would eventually stop trusting the surface to tell him the truth about its own completeness — the same class of trust failure `COMMITMENT_SURFACING`'s CI-2 ("no flicker / no fabricated absence") protects against, applied here to a three-state distinction instead of two.

## Acceptance Criteria

- [ ] AC1: the companion UI renders one day-start card surfacing today's generated briefing, read-only, with listen and read affordances, when a complete briefing note exists for today. Verify: `tests/companion_ui/test_day_start_card.py::test_day_start_card_renders_todays_briefing`
- [ ] AC2: the card requires zero typing to operate — every action (listen, expand/read, dismiss) is a tap/click affordance with no text-input element. Verify: `tests/companion_ui/test_day_start_card.py::test_day_start_card_has_no_text_input_affordances`
- [ ] AC3: when no briefing note exists yet for today, the card shows an explicit "not yet generated" state rather than an empty/blank card or a stale prior day presented as current. Verify: `tests/companion_ui/test_day_start_card.py::test_missing_todays_briefing_shows_pending_state_not_blank`
- [ ] AC4: when today's briefing exists but carries a named degraded section, the card visibly marks the degraded section and is visually distinct from both the "not yet generated" state and the fully-generated state. Verify: `tests/companion_ui/test_day_start_card.py::test_degraded_briefing_distinguished_from_pending_and_full`
- [ ] AC5: the card is strictly read-only — no affordance mutates the briefing note, or any commitment/decision-receipt/episode it references. Verify: `tests/companion_ui/test_day_start_card.py::test_day_start_card_is_read_only`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/companion_ui/test_day_start_card.py
pytest -q tests/companion_ui -k briefing
```

If the companion UI renders via the pure `render_index_html` path, render to static HTML and visually confirm the three-state distinction (per the companion UI local UAT pattern).

## Out of Scope

Any push/notification delivery of the card; "dismiss permanently" semantics beyond a simple UI collapse for the current session; editing or deleting the briefing note from the card; the listen affordance's own TTS wiring (BRIEF-03 owns that; this task only hosts the affordance and degrades gracefully in its absence); the calendar/episodes section content (BRIEF-05).

## Restart / Durability Posture

The card is a pure read projection of the durable briefing note (BRIEF-01) — it carries no non-durable state of its own. A process restart mid-day changes nothing about what the card shows: it re-reads today's note (or its absence) fresh on the next render, identically to before the restart. There is no in-memory "card state" to lose.

## Related Docs

- `docs/DAILY_BRIEFING/README.md` (capability spec, cross-task invariants — "fail-legible partial generation")
- `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` (the note this card projects)
- `docs/DAILY_BRIEFING/RENDER_BRIEFING_AUDIO.md` (the listen affordance this card hosts)
- `app/relevance/now_surface.py` (existing glance-surface read-projection pattern)
- `docs/COMMITMENT_SURFACING/RENDER_COMMITMENTS_IN_PANEL_UI.md` (read-only render precedent, CI-2 no-fabricated-absence invariant)
- `docs/HUMAN-FLOWS.md` §0 (zero-typing, visual-pick interface posture)

## Related GitHub Issues

One issue: `[Daily Briefing] surface-day-start-card: zero-typing listen + read card for today's briefing`. `agent:blocked` until BRIEF-01 merges. Not blocked on BRIEF-03 (degrades gracefully if the listen affordance is not yet wired).
