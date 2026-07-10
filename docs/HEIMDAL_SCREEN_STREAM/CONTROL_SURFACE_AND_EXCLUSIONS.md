---
name: Control Surface and Exclusions
description: The operator control surface — pause/resume with always-visible state, per-app and per-scope exclusions, and retention tunables — settings-governed per the Settings Spine, with a durable receipt for every control change
task_id: SCREEN-06
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: Owner ruling (pause + exclusion controls, derive-and-discard)
parent_capability: Heimdal Screen Stream
prerequisites: [SCREEN-01, SCREEN-03]
depends_on: [DEFINE_SCREEN_OBSERVATION_CONTRACT.md, BUILD_MACOS_OBSERVER_CLIENT.md]
can_parallelize_with: [PROJECT_TIME_SPEND_ANALYSIS]
---

# Control Surface and Exclusions

## Purpose

The owner ruling that approved always-on desktop screen observation came **with** conditions: pause and
app/scope exclusion controls, and a derive-and-discard raw posture. This task builds the operator
control surface that makes those conditions real and legible: pause/resume with **always-visible
state**, per-app and per-scope exclusions, and the retention tunables — all **settings-governed** per
the Settings Spine, with a **durable receipt for every control change**. It is the governed settings +
receipt half behind the capture-loop behavior SCREEN-03 enforces.

## What This Task Does

1. **Pause/resume with visible state (INV-SCREEN-C).** A control to pause and resume observation, whose
   current state (**observing / paused**) is **always visible at a glance** — the owner must never have
   to wonder whether they are being observed. Pause is durable (SCREEN-03 Restart posture); this task
   owns the state as a governed setting and its visible surface. Pause is the standing-grant revocation
   in miniature: paused = the `screen_always_on` consent is not active.
2. **Per-app and per-scope exclusions (INV-SCREEN-D).** An editable exclusion list: exclude by app
   (bundle id) and by scope. The list is honored **at capture** (SCREEN-03) — this task owns the
   list as a governed setting; the client reads it. A **scope→app mapping** lets the owner declare, e.g.,
   "everything in my banking app is `private` and excluded" once.
3. **Retention tunables.** The `screen_frame_retention_minutes` buffer bound, the
   `screen_capture_cadence_seconds`, `screen_client_buffer_max`, and `screen_coalesce_*` sensitivity —
   all declared once in the registry (SETTINGS_SPINE SINGLE_DEFAULT_REGISTRY posture), markdown-first,
   fail-loud on invalid (degrade to last-valid + visible degraded state, never silently to a code
   default — the F1 failure mode the Settings Spine exists to remove).
4. **Receipt for every control change (SETTINGS_SPINE RECEIPT_EVERY_SETTINGS_WRITE).** Every
   pause/resume, exclusion edit, and retention-tunable change emits a **durable actor-tagged receipt**
   (who / what / when / old→new). The owner can always answer "when did I pause, what did I exclude,
   when did the retention bound change?" — the audit trail the always-on posture needs.
5. **Settings-governed (Settings Spine).** These are vault-scoped settings resolved through the one
   spine; a change edited as markdown takes effect in the running client/host without a manual CLI step
   (SET-1 ingestion), and rebinds on vault selection (SET-7). No bespoke settings store.

## Concretely

```
$ python -m app.cli heimdal screen-control status
observing: on   paused_since: -   excluded_apps: [com.apple.Passwords, com.bank.app]   excluded_scopes: [private]
$ python -m app.cli heimdal screen-control pause
paused. receipt: heimdal_screen_control_receipt/2026-07-07T14:22Z (actor=operator, pause on->PAUSED)
$ python -m app.cli heimdal screen-control exclude-app com.some.app
excluded com.some.app. receipt: ... (actor=operator, exclusions +com.some.app)
```

## Why This Matters

These controls are the terms on which the owner approved always-on observation — they are not optional
polish. If pause state is invisible, the owner cannot trust the system; if an exclusion edit is not
honored at capture, a sensitive app leaks; if a retention change is silent, the privacy lever has no
audit trail. Receipting every change is what makes the always-on posture accountable rather than opaque.

## Acceptance Criteria

- [ ] AC1 (enforcement): every control change (pause/resume, exclusion add/remove, retention-tunable
      edit) emits exactly one durable actor-tagged receipt — asserted at each writer's production call
      site, not on a receipt helper in isolation. Verify: `tests/heimdal/test_screen_control_receipts.py::test_every_control_change_receipted` (asserts the receipt is written from the pause/exclusion/tunable write paths)
- [ ] AC2: the exclusion list and pause state are governed settings the client reads; a markdown edit
      takes effect without a manual CLI step (rides SET-1 ingestion) or reports degraded state. Verify: `tests/heimdal/test_screen_control_settings.py::test_control_settings_ingested_live`
- [ ] AC3: pause/observing state is queryable and always reflects the true capture state (no drift
      between the visible state and the client's actual behavior). Verify: `tests/heimdal/test_screen_control_settings.py::test_visible_state_matches_capture_behavior`
- [ ] AC4: an invalid retention/cadence value degrades loudly to last-valid with a visible degraded
      state, never silently to a code default. Verify: `tests/heimdal/test_screen_control_settings.py::test_invalid_tunable_degrades_loud_not_silent`
- [ ] AC5 (non-behavioral): the screen-stream tunables are declared once in the single default registry
      (no duplicated literals). Verify: doc writeback at `docs/HEIMDAL_SCREEN_STREAM/README.md :: Provisional constants` + `tests/settings/test_provider_census.py`-style single-source assertion for the screen tunables

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/heimdal/test_screen_control_receipts.py tests/heimdal/test_screen_control_settings.py
pytest -q -m "not pg"
RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q -m "not pg" tests/uat   # settings ingestion touches the vault/watcher hot path
```

## Out of Scope

The capture-time enforcement of pause/exclusion (SCREEN-03 — this task provides the governed list/state
it enforces); the schema/endpoint (SCREEN-01); derivation (SCREEN-02); time-spend (SCREEN-05); ERE
(SCREEN-04). No third-party consent machinery (single-operator). No new settings substrate — reuse the
Settings Spine.

## Restart / Durability Posture

Pause state and the exclusion list are **durable governed settings** (vault-scoped markdown + resolved
bundle): they survive a restart of the client and the host. The pause state's durability is the
load-bearing one — a restart must never resume observation the owner had paused (SCREEN-03 defaults to
paused on ambiguous restart; this task keeps the durable source of that state). A lost in-memory
resolved bundle re-resolves from the markdown source on restart (Settings Spine reload path), so no
control state is lost.

## Related Docs

- `docs/SETTINGS_SPINE/README.md` (one spine, ingestion SET-1, receipt-every-write SET-3, single default registry SET-4, rebind-on-selection SET-7)
- `docs/SETTINGS_SPINE/RECEIPT_EVERY_SETTINGS_WRITE.md`, `docs/SETTINGS_SPINE/WIRE_SETTINGS_INGESTION.md`
- `docs/HEIMDAL/OWNER_DECISIONS.md` D-CONSENT (pause = standing-grant revocation lineage)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-C, INV-SCREEN-D) + `:: Provisional constants`

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] control-surface-and-exclusions: visible pause + app/scope exclusions + retention tunables, receipted`. Blocked until SCREEN-01 and SCREEN-03 merge (∥ SCREEN-05). **Sonnet-tier** (settings-governed control surface + receipts over the existing Settings Spine). The client-side half of pause/exclusion enforcement may transfer to Bifrost with SCREEN-03. See scratchpad draft.
