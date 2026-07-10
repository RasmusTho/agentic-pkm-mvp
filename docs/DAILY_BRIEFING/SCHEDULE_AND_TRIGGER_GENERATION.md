---
name: Schedule And Trigger Generation
description: Morning scheduled generation of the briefing plus an on-first-contact-of-day fallback; idempotent per day across both trigger paths
task_id: BRIEF-02
source_anchor: docs/research/yggdrasil-closed-loops-ideation.md :: Priority recommendation
parent_capability: Daily Briefing
prerequisites: [BRIEF-01]
depends_on: [COMPOSE_BRIEFING_ARTIFACT.md]
can_parallelize_with: [RENDER_BRIEFING_AUDIO, SURFACE_DAY_START_CARD]
---

# Schedule And Trigger Generation

## Purpose

BRIEF-01 can compose a briefing, but nothing decides *when*. This task adds the two trigger paths that guarantee the owner has a briefing waiting for him every day without asking for it: a morning scheduled tick, and an on-first-contact-of-day fallback for when the scheduled tick was missed (the runtime was down through the morning window, the watcher was disabled, etc.). Both paths must agree on one invariant: **exactly one generation per day**, never zero (silently) and never more than one (visibly, from the owner's perspective — a manual regenerate is a separate, explicit action, not this guard's concern).

## What This Task Does

1. **Scheduled trigger**: extends the existing watcher tick registry (`app/watcher/registry.py`, following the sparse-cadence pattern already used by `app/watcher/relevance_tick.py`) with a briefing tick that, once per configured morning window, checks whether today's briefing note already exists and — if not — calls BRIEF-01's composer.
2. **First-contact-of-day fallback**: hooks the existing companion entry-state resolution path (the `cold_start` / `orienting` resolution described in `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`) so that the first companion entry of a new calendar day, if no briefing note exists yet for today, triggers composition as a fallback — covering the case where the scheduled tick never ran.
3. **Idempotency across both paths**: a single per-day guard (backed by the durable presence of today's dated note, not an in-memory flag — see Restart / Durability Posture) ensures neither path double-fires: the scheduled tick checks "does today's note exist?" before composing, and so does the fallback; whichever path runs first wins, and the other becomes a no-op.
4. **Tunables — declared once, honestly provisional.** `BRIEFING_GENERATION_HOUR` (default morning local hour), `BRIEFING_TIMEZONE` (owner's configured zone), and `BRIEFING_ENABLED` (default on) are declared in exactly one module (`app/briefing/config.py`), matching the `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md` (SETTINGS-02) posture of "every behavior-shaping default declared once." SETTINGS-02 has not landed as of this task; these constants are **provisional** and the module docstring says so explicitly, naming the migration target once the Settings Spine registry exists. No call site outside this module re-declares its own default for these keys.
5. **Regenerability preserved**: an explicit manual regenerate action (operator CLI today; a future settings/UI action) can re-run BRIEF-01's composer for the current day even when today's note already exists — the once-per-day guard governs the *automatic* triggers only, and must not block a deliberate re-run.

## Concretely

```
$ python -m app.cli briefing tick --json
{"triggered": true, "reason": "scheduled_window", "date": "2026-07-08"}
$ python -m app.cli briefing tick --json   # same day, called again
{"triggered": false, "reason": "already_generated_today"}
```

Fallback path (scheduled tick never ran — system was off through the window):

```
GET /  (first companion entry of 2026-07-08, no briefing note exists for today)
→ entry-state resolution observes no today's briefing, triggers compose_briefing as a side effect,
  then resolves cold_start/orienting as normal
```

Manual regenerate (bypasses the automatic-trigger guard):

```
$ python -m app.cli briefing regenerate --date 2026-07-08
→ WriteReceipt(operation="briefing.write_note", locator=vault://<system_dir>/briefings/2026-07-08.md)
```

## Why This Matters

This is the seam where "one low-cognitive-load touchpoint per day, push not pull" either holds or breaks. If the scheduled tick is the only path, a single missed morning (machine asleep, watcher disabled) means the owner opens the companion UI to nothing — exactly the checking-panels behavior this capability exists to remove. If the two paths do not agree on idempotency, the owner could see two different "today's briefing" notes generated hours apart with different content, which is confusing at best and trust-eroding at worst.

## Acceptance Criteria

- [ ] AC1: on a scheduled tick during the configured morning window, if no briefing note exists for today, the composer runs exactly once. Verify: `tests/briefing/test_schedule_trigger.py::test_scheduled_tick_generates_once_per_day`
- [ ] AC2: if the scheduled tick never fires (process down through the entire window), the first companion entry of the day triggers composition as a fallback. Verify: `tests/briefing/test_schedule_trigger.py::test_first_contact_of_day_falls_back_when_schedule_missed`
- [ ] AC3 (enforcement): a second trigger on the same day — the scheduled tick firing twice, or the first-contact fallback racing the scheduled tick — never produces a second automatic composition; the idempotency guard is asserted at the production trigger call site (both the tick handler and the entry-state hook), not only in a shared helper tested in isolation. Verify: `tests/briefing/test_schedule_trigger.py::test_duplicate_trigger_same_day_is_idempotent_at_call_site`
- [ ] AC4: the three tunables (`BRIEFING_GENERATION_HOUR`, `BRIEFING_TIMEZONE`, `BRIEFING_ENABLED`) are declared exactly once in `app/briefing/config.py`, whose docstring names the Settings Spine `SINGLE_DEFAULT_REGISTRY` (SETTINGS-02) as the eventual home and states plainly that this is a provisional interim location. Verify: `tests/briefing/test_schedule_trigger.py::test_tunables_declared_once`
- [ ] AC5: an explicit manual regenerate call re-runs the composer for the current day even when today's note already exists, without being blocked by the automatic-trigger idempotency guard. Verify: `tests/briefing/test_schedule_trigger.py::test_manual_regenerate_bypasses_auto_trigger_guard`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/briefing/test_schedule_trigger.py
pytest -q -m "not pg"
```

Hot-path change (watcher tick registry + entry-state hook): run the full `not pg` suite per the sub-agent hot-path posture, and exercise `RUN_INTEGRATED_RUNTIME_UAT=1` if the entry-state hook change touches the vault/watcher runtime chain.

## Out of Scope

The composer itself (BRIEF-01); audio rendering (BRIEF-03); the companion-UI card (BRIEF-04); the calendar/episodes section (BRIEF-05); a full settings-UI surface for the tunables (they are code-level constants until the Settings Spine lands); spinning up additional watchers or multi-vault scheduling (out of scope here, same boundary the Settings Spine README draws around its own follow-up capability).

## Restart / Durability Posture

The "has today's briefing already been generated" check must read the **durable** state — the presence and date of the vault note itself (or an equivalently durable marker) — never an in-memory flag held only by the running process. This is the trust-critical detail of this task:

- **Survives restart:** whether today's briefing has been generated. A restart mid-morning, before or after either trigger has fired, must not cause a double-generation (if the note already exists, both paths still see it) or a missed generation (if the note does not exist yet, either trigger still fires on its next opportunity).
- **Does NOT survive restart, and must not be the source of the guard:** any in-process "already ran today" flag. If the idempotency guard were implemented as in-memory state, a restart between the scheduled tick and the fallback check would cause a duplicate generation, silently reintroducing the exact defect this task exists to prevent.
- **Trust consequence if this is not honored:** the owner would occasionally see two different "today" briefings hours apart (confusing), or none at all after a restart timed unluckily (defeats the "push, not pull" promise). Keying the guard off the durable note is the defense.

## Related Docs

- `docs/DAILY_BRIEFING/README.md` (capability spec, cross-task invariants — "one generation per day idempotency")
- `docs/DAILY_BRIEFING/COMPOSE_BRIEFING_ARTIFACT.md` (the composer this task triggers)
- `app/watcher/relevance_tick.py`, `app/watcher/registry.py` (existing sparse-cadence tick pattern)
- `docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md` (existing entry-state resolution seam the fallback hooks)
- `docs/SETTINGS_SPINE/README.md`, `docs/SETTINGS_SPINE/SINGLE_DEFAULT_REGISTRY.md` (the tunables posture this task honestly follows as provisional)

## Related GitHub Issues

One issue: `[Daily Briefing] schedule-and-trigger-generation: morning tick + first-contact-of-day fallback, idempotent per day`. `agent:blocked` until BRIEF-01 merges.
