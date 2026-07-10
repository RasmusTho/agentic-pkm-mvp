---
name: Enrich With Calendar Episodes
description: Add a today's-calendar/episodes section to the composed briefing once the ERE calendar stream and episode note store are live — BLOCKED on an external prerequisite
task_id: BRIEF-05
source_anchor: docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md :: What This Task Does
parent_capability: Daily Briefing
prerequisites: [BRIEF-01]
depends_on: [COMPOSE_BRIEFING_ARTIFACT.md]
can_parallelize_with: []
---

# Enrich With Calendar Episodes

**BLOCKED** — this task cannot start until the Episode Resolution Engine's calendar stream adapter (`docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md`, task id ERE-09, GitHub **#3184**, currently `agent:blocked` on ERE-01/ERE-04) is live, and until the Episode Note Store (`docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md`, ERE-02) exists to read from. Neither is delivered as of this spec (2026-07-07). This task file exists so the fourth briefing section is designed and ready to pick up the moment its external prerequisite clears — it is not ready work today.

## Purpose

The ideation capture (`docs/research/yggdrasil-closed-loops-ideation.md` :: 1. Daily briefing) names calendar as an enabling substrate "arriving via ERE-09." Once it lands, a day-start briefing without today's calendar/episode context is missing the single strongest cheap signal for "what today actually is" (a calendar block gives time, attendees, location, and title in one record — `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md :: Why This Matters`). This task adds that as a fourth briefing section, once it can.

## What This Task Does

1. Adds a fourth section to BRIEF-01's composer: **today's calendar / episodes**, reading:
   - the ERE-09 registered `calendar` stream (once its status flips `planned → live`) for today's calendar entries, and
   - the ERE-02 episode-note projection for episodes bounded within today (open or closed).
2. Each item in this section carries a provenance reference back to its source: the calendar item's UID/etag for calendar entries, the episode note's `episode_id` for episodes — following the exact provenance discipline BRIEF-01 established for its other three sections.
3. **Adds no new episode or calendar logic of its own.** This task is a consumer of ERE-09's and ERE-02's already-existing read interfaces, exactly as ERE-09 itself was designed to prove that a new stream is "a registry entry + adapter, not an engine change" — this task is the analogous proof for the briefing composer: a new *section* is a new read, not a new engine.
4. **Same fail-legible discipline as BRIEF-01**: if the calendar/episode read degrades (stream unreachable, projection read fails), the section is explicitly named missing, exactly like BRIEF-01's other three sources — this task does not introduce a second degrade convention.

## Concretely

```python
from app.briefing.compose import compose_briefing

receipt = compose_briefing(vault_context=ctx, for_date=date.today())
note = load_briefing(vault_context=ctx, for_date=date.today())
assert note.sections["calendar_episodes"][0].provenance_ref  # calendar UID or episode_id
```

When the calendar stream is unreachable on a given day:

```python
note = load_briefing(vault_context=ctx, for_date=date.today())
assert "calendar_episodes" in note.degraded_sections
```

## Why This Matters

Without this section, the briefing tells the owner what is open (commitments), what is relevant (CRE picks), and what was decided (receipts) — but not what the day itself *is*. Calendar/episode context is what turns "here is what's outstanding" into "here is what's outstanding, given what today looks like." Deferring this task rather than stubbing it with ad hoc calendar-reading logic keeps the briefing composer honest about what substrate actually exists today, per this repo's standing discipline against building ahead of a declared, ratified prerequisite.

## Acceptance Criteria

- [ ] AC1: when the calendar stream (ERE-09) is live, the composed briefing includes a calendar/episodes section listing today's bounded calendar entries and episodes, each with a resolvable provenance reference. Verify: `tests/briefing/test_briefing_calendar_section.py::test_briefing_includes_todays_calendar_episodes_when_stream_live`
- [ ] AC2: the same fail-legible degrade discipline as BRIEF-01 applies — an unreachable or degraded calendar/episode read names the missing section explicitly rather than silently omitting it. Verify: `tests/briefing/test_briefing_calendar_section.py::test_degraded_calendar_stream_names_missing_section`
- [ ] AC3 (enforcement): this task introduces no new episode-segmentation or calendar-adapter logic — it reads only the existing ERE-09 registered-stream interface and the existing ERE-02 episode-note projection, asserted by exercising the section against ERE's own fixtures without any Daily-Briefing-side calendar/episode code. Verify: `tests/briefing/test_briefing_calendar_section.py::test_calendar_section_reads_existing_ere_interfaces_only`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/briefing/test_briefing_calendar_section.py
pytest -q -m "not pg"
```

Do not begin implementation before confirming ERE-09 and ERE-02 are merged to `main` — re-check `gh issue view 3184` and the ERE-02 issue status before starting, since both may have moved since this spec was drafted.

## Out of Scope

Any change to the ERE calendar adapter (`CALENDAR_STREAM_ADAPTER.md`), the episode note store/projection, or episode segmentation itself — this task is read-only against those interfaces. Location-stream enrichment (ERE-10, itself a declared-posture-only, no-issue-yet future state). Scheduling, audio, or UI changes (owned by BRIEF-02/03/04).

## Related Docs

- `docs/DAILY_BRIEFING/README.md` (capability spec — this section's place in the sources-consumed table)
- `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` (the composer this task extends)
- `docs/EPISODE_RESOLUTION_ENGINE/CALENDAR_STREAM_ADAPTER.md` (ERE-09, the blocking external prerequisite)
- `docs/EPISODE_RESOLUTION_ENGINE/EPISODE_NOTE_STORE_AND_PROJECTION.md` (ERE-02, the episode-note projection this task reads)
- `docs/EPISODE_RESOLUTION_ENGINE/README.md` (ERE capability spec and execution order)

## Related GitHub Issues

One issue: `[Daily Briefing] enrich-with-calendar-episodes: today's-calendar/episodes section once ERE-09 lands`. `agent:blocked` — do not create as `agent:ready` until ERE-09 (GitHub #3184) and ERE-02 both merge to `main`; re-verify their state at filing time and again immediately before pickup.
