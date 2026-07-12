---
name: Calendar Stream Adapter
description: Read-only calendar stream (CalDAV/ICS) registered as a fusion source — the strongest cheap signal for time, protagonist, and goal
task_id: ERE-09
source_anchor: docs/research/EPISODE_RESOLUTION_ENGINE.md :: Suggested build order (step 2)
parent_capability: Episode Resolution Engine
prerequisites: [ERE-01, ERE-04]
depends_on: [STREAM_REGISTRY_AND_SIGNAL_CONTRACT.md, TWO_STREAM_SEGMENTATION_CORE.md]
can_parallelize_with: []
---

# Calendar Stream Adapter

## Purpose

Calendar is build-order step 2 — the strongest cheap external signal: a calendar block gives time bounds, attendees (protagonist), location text (space), and title/context (goal) in one record. Today calendar exists nowhere in the system (no fabric class, no adapter, no topic); this task brings it in as a *registered stream*, proving the ERE-01 claim that a new source is a registry entry + adapter, not an engine change.

## What This Task Does

1. **Transport (decided here, within existing posture)**: read-only **CalDAV against iCloud** (app-specific password) with an ICS-file fallback for degraded/offline operation. Credentials and calendar selection live in the **private-bindings constituent** (operator-bound configuration — endpoints/credentials are exactly its charter), never in repo or vault. This conforms to the established egress posture (system is not local-only; Gemini-embedding precedent) — read-only external fetch, no data leaves the system. The `calendar-query` REPORT is bounded to a fixed window around "now" — `_CALDAV_TIME_RANGE_PAST` (7 days back) / `_CALDAV_TIME_RANGE_FUTURE` (60 days forward) in `app/episodes/calendar_stream.py` — both to cap the fetch (there is no durable read-position cursor; every tick re-reads the calendar's current item set) and because it doubles as the required `<C:expand>` window: the REPORT requests server-side recurrence expansion so a recurring master VEVENT comes back as one distinct occurrence per instance (its own RECURRENCE-ID/DTSTART) instead of a single unexpanded master that would otherwise emit exactly once, ever.
2. **Adapter**: a poller (watcher-tick cadence class: sparse) normalizing calendar entries into the ERE-01 signal contract — `observed_at_start/end` from event times (TZID-qualified local times are resolved via `zoneinfo` to the correct UTC instant; a genuinely floating time with no `Z`/no resolvable TZID degrades the `time` dimension's confidence rather than being silently asserted as UTC), `dimensions_fed: {time: high, protagonist: medium, space: medium, goal: medium}`, attendees resolved *provisionally* against the shared entity register (three-state resolution, HEIM-6-honest: calendar attendee strings are never silently upgraded to canonical identities). Provenance ref / signal_id (`app.episodes.calendar_stream.calendar_signal_id`, review round 2, findings 1+2): a non-recurring event is `uid:etag` (unchanged since v1 — one CalDAV resource, one occurrence, so its own etag correctly is its change signal); one occurrence of a server-expanded recurring series is `uid:occurrence_key:content_token`, where IDENTITY (`occurrence_key`) is this occurrence's own RECURRENCE-ID (falling back to its own DTSTART) — canonical and **window-independent**, never gated on how many sibling occurrences happen to also fall inside this tick's expand/time-range window (finding 1) — and CHANGE detection (`content_token`) is a hash of this occurrence's own DTSTART/DTEND/SUMMARY/SEQUENCE/LAST-MODIFIED, never the shared resource etag, since editing one occurrence must not re-emit its unmodified siblings as "new" evidence (finding 2).
3. **Registry activation**: flips the `calendar` registry entry `planned → live`; scope classification per calendar (a named calendar maps to a scope in the registry entry — e.g. work calendar → work scope), so cross-scope discipline (ERE-08) applies from the first signal.
4. **Fusion effect**: segmentation (ERE-04) consumes calendar signals like any registered stream — no segmenter change; a calendar block overlapping voice+vault signals strengthens boundary confidence and feeds protagonist/goal dimensions the two-stream core lacked.
5. **Fail-soft**: calendar unreachable → adapter reports degraded in the tick summary and the engine continues on remaining streams (a missing stream never stalls segmentation).

## Concretely

```
$ python -m app.cli episodes streams --json | jq '.streams[] | select(.stream_id=="calendar")'
{"stream_id": "calendar", "status": "live", "transport": "caldav_poll", "cadence": "sparse", ...}
$ python -m app.cli episodes tick --json
{"consumed": {"calendar": 3, ...}, "degraded": []}
```

## Why This Matters

Without calendar, protagonist and goal come only from ASR attribution and note-touch heuristics — the fusion table's weak column. Calendar is also the test of the registry architecture: if adding it requires touching the segmenter, ERE-01's central claim failed and that failure must surface here, not at stream #7.

## Acceptance Criteria

- [ ] AC1: CalDAV/ICS entries normalize to schema-valid signals (bitemporal, per-dimension confidence, provenance UID). Verify: `tests/episodes/test_calendar_adapter.py::test_calendar_entries_normalize_to_signal_contract`
- [ ] AC2: attendee resolution is three-state and never silently canonical (unknown attendee → `unresolved`, no register mutation). Verify: `tests/episodes/test_calendar_adapter.py::test_attendees_resolved_provisionally_heim6`
- [ ] AC3 (enforcement): the segmenter consumes calendar signals **without any segmenter code change** — the adapter registers via the ERE-01 registry and the existing entrypoint picks it up (asserted by running the ERE-04 fixture with calendar added and observing improved boundary confidence). Verify: `tests/episodes/test_calendar_adapter.py::test_calendar_joins_fusion_via_registry_only`
- [ ] AC4: credentials/config resolve from private-bindings paths only; no credential material in repo, vault, or logs (fail-loud if unconfigured while registry says live). Verify: `tests/episodes/test_calendar_adapter.py::test_credentials_from_private_bindings_fail_loud`
- [ ] AC5: unreachable calendar degrades softly — tick completes on remaining streams, degradation reported. Verify: `tests/episodes/test_calendar_adapter.py::test_unreachable_calendar_degrades_softly`
- [ ] AC6: per-calendar scope mapping enforced — a work-calendar signal never enters a private-scope segment partition (ERE-08 discipline). Verify: `tests/episodes/test_calendar_adapter.py::test_calendar_scope_mapping_respected`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/episodes/test_calendar_adapter.py     # against ICS fixtures; live CalDAV receipt on mac mini
pytest -q -m "not pg"
```

Live-CalDAV verification is a mac-mini test-channel receipt (laptop is not the runtime env), folded into promote-to-test per house practice.

## Out of Scope

Calendar *write* of any kind; inviting the engine into scheduling; location stream (ERE-10); Google/Exchange backends (registry makes them later adapters); attendee auto-canonicalization.

## Related Docs

- Research doc §fusion table + §build order; ERE-01 registry contract
- `docs/architecture/ECOSYSTEM_STRUCTURE_PROPOSAL.md` (private-bindings constituent C3)
- `docs/HEIMDAL/FABLE_COMPANION.md` (three-state resolution precedent)

## Related GitHub Issues

One issue: `[Episode Resolution Engine] calendar-stream: read-only CalDAV/ICS adapter as a registered fusion source`. Blocked until ERE-01 + ERE-04 merge.
