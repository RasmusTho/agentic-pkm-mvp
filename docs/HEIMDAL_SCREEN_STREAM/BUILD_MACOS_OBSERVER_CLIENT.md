---
name: Build macOS Observer Client
description: The reference macOS desktop observer — screen-capture cadence, frontmost-app metadata, pause control, per-app exclusion list, durable offline buffer — that ships raw capture bundles per the SCREEN-01 contract; default home is the Bifrost repo
task_id: SCREEN-03
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: Topology (the observer is a native/local client)
parent_capability: Heimdal Screen Stream
prerequisites: [SCREEN-01]
depends_on: [DEFINE_SCREEN_OBSERVATION_CONTRACT.md]
can_parallelize_with: [DERIVE_ACTIVITY_OBSERVATIONS]
---

# Build macOS Observer Client

## Purpose

The reference desktop observer that actually captures the owner's screen state and ships it to the host
per the SCREEN-01 contract. It is the only component that touches the screen — the ingress boundary,
the screen analog of the voice-memo capture adapter. This task specifies its **behavior**, not its UI
widget (menu-bar app vs launchd daemon is an implementation choice for the Bifrost stack).

**Client home = Bifrost (ADR-0050).** A native macOS client is a constituent-surface client; per
ADR-0050 its home is the governed **Bifrost** repo (topology C), built by the Builder System under
ecosystem governance in the Swift/iOS toolchain. **This issue may be transferred to the `bifrost`
repo** and delivered there; it is specified here because the capability spec lives here and the client
builds against this repo's SCREEN-01 host contract. If delivered in Bifrost, its verification runs in
the Bifrost CI (Swift build + test + lint per ADR-0050 §1), and its validation receipt is still posted
to this capability's parent feature issue (single tracking source until Bifrost has its own board).

## What This Task Does

1. **Capture cadence.** Sample the screen every `screen_capture_cadence_seconds` (provisional constant,
   SCREEN-06-governed). **Idle-adaptive**: a locked, screensaver-active, or user-idle screen is **not
   sampled** (no point observing a screen the owner is not at — this is what "while at computer" means).
2. **Frontmost-app metadata.** With each sample, capture the frontmost application (bundle id + name)
   and window title (subject to exclusion/redaction), plus active/idle state. This is local context
   provider #1 (SCREEN-02 consumes it).
3. **Pause control (INV-SCREEN-C).** A visible pause/resume. **Paused = no sampling, no buffering, no
   shipping** — the client does not capture at all while paused. Pause state is **durable** (survives
   restart, see Restart posture). The current state (observing / paused) is always visible at a glance
   (the SCREEN-06 control surface owns the visible-state guarantee; this task honors it in the capture
   loop).
4. **Per-app exclusion list (INV-SCREEN-D).** Before sampling, check the frontmost app (and its scope,
   SCREEN-06) against the exclusion list. **An excluded app's pixels are never captured** — not
   sampled, not buffered, not shipped. Exclusion is enforced **at capture**, upstream of everything;
   there is no path by which an excluded app's frame reaches the host to be redacted there.
5. **Durable offline buffer + backfill (INV-SCREEN-F).** When the host is unreachable, buffer raw
   bundles in a **bounded, durable** local queue (`screen_client_buffer_max`); on reconnect, backfill
   in order. Each bundle carries its `content_identity`, so a re-shipped bundle after a lost ack dedups
   host-side (no duplicate observation). When the buffer is full while offline, the **oldest** bundles
   age out (bounded loss, locally counted/legible — never unbounded growth that fills the disk).
6. **Ship per SCREEN-01.** POST `raw_capture_bundle`s to the host capture endpoint over the
   loopback (co-located) or Tailscale-local (cross-machine) transport; register as a sensor on first
   run; release a buffered bundle only on a durable host ack.

## Concretely

```
# observer status (menu-bar or CLI surface)
observing: on   machine: rasmus-macbook   cadence: 45s   buffered: 0   excluded apps: 3   scope: work
# host unreachable -> buffering, still bounded
observing: on   host: unreachable   buffered: 128/500 (oldest aging out)   backfill: pending
# paused -> total stop
observing: PAUSED   machine: rasmus-macbook   buffered: 0   (no capture, no buffering, no shipping)
```

## Why This Matters

This is the component the owner sees and trusts. If pause is not durable, the owner can be observed
without knowing after a restart. If exclusion is enforced host-side instead of at capture, a sensitive
app's pixels have already left the machine before anything redacts them. If the offline buffer is
unbounded, an offline laptop fills its disk; if backfill is not idempotent, a reconnect duplicates a
day of observations.

## Acceptance Criteria

- [ ] AC1: the observer samples at cadence and does **not** sample when the screen is locked / idle /
      screensavered. Verify: `tests/heimdal/test_screen_client_capture.py::test_no_sample_when_idle_or_locked` (Bifrost: `ScreenObserverCaptureTests.testNoSampleWhenIdle`)
- [ ] AC2 (enforcement): an excluded app being frontmost means **no capture** — asserted at the capture
      entrypoint, before any buffer write or network call. Verify: `tests/heimdal/test_screen_exclusion.py::test_excluded_app_never_captured` (asserts the exclusion check gates the capture call site, not a host-side filter)
- [ ] AC3 (enforcement): pause stops sampling, buffering, and shipping entirely; resume restores
      capture. Verify: `tests/heimdal/test_screen_pause.py::test_pause_is_durable_and_total` (asserts the capture loop no-ops while paused and the buffer does not grow)
- [ ] AC4: the offline buffer is bounded and durable; a full buffer ages out oldest bundles with a
      local count, never grows unbounded. Verify: `tests/heimdal/test_screen_client_buffer.py::test_buffer_bounded_and_durable`
- [ ] AC5: backfill after reconnect does not duplicate observations (re-shipped bundle dedups on
      `content_identity` host-side). Verify: `tests/heimdal/test_screen_client_buffer.py::test_backfill_idempotent_no_duplicates`
- [ ] AC6: the client ships conforming `raw_capture_bundle`s and registers as a sensor before its first
      admit. Verify: `tests/heimdal/test_screen_client_capture.py::test_ships_conforming_bundle_and_registers_sensor`

## How to Verify (Pre-Merge)

```
# if delivered in this repo (host-side reference/simulator of the client contract):
pytest -q tests/heimdal/test_screen_client_capture.py tests/heimdal/test_screen_exclusion.py tests/heimdal/test_screen_pause.py tests/heimdal/test_screen_client_buffer.py
pytest -q -m "not pg"
# if delivered in Bifrost: Swift build + test + lint (ADR-0050 §1), same AC names as XCTest cases;
# validation receipt still posted to this capability's parent issue.
```

## Out of Scope

The host schema/endpoint (SCREEN-01); host-side derivation (SCREEN-02); the on-device `derived_observation`
producer (declared future — this client ships raw bundles); ERE registration (SCREEN-04); time-spend
(SCREEN-05); the settings/receipt plumbing behind pause/exclusion/retention tunables (SCREEN-06 owns the
governed settings surface; this task consumes it). No keylogging / input capture / clipboard / video —
still frames + app metadata only.

## Restart / Durability Posture

Two durability-sensitive surfaces this task owns:

- **Offline buffer.** Durable across client restart (bounded on-disk queue, not in-memory): bundles
  captured while offline survive a client crash/restart and backfill when the host returns. Bounded by
  `screen_client_buffer_max`; on overflow the **oldest** bundles are dropped with a local count (loss
  is legible, disk is protected). The user experience on restart: buffered-but-unsent bundles resume
  backfilling; nothing silently vanishes without the count reflecting it.
- **Pause state.** Durable across client restart. A client paused when it crashed comes back **PAUSED**,
  never observing. The trust consequence of getting this wrong is severe: a pause that resets to
  "observing" on restart means the owner is captured without realizing — so the default on ambiguous
  restart state is **paused**, fail-safe toward not-observing.

## Related Docs

- `docs/adr/ADR-0050-cross-repo-governance-and-bifrost-client-repo.md` (client home; Builder-System-in-Bifrost)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` (the host-contract-for-a-Bifrost-client precedent) + SCREEN-01 (this capability's host contract)
- `docs/HEIMDAL/FABLE_COMPANION.md` §11#5 (the voice-memo capture adapter this mirrors — the ingress boundary, delete/discard discipline)
- `docs/SECURITY_TRUST_BOUNDARIES.md` (LAN/Tailscale environment boundary — explicit + proportionate)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-C, INV-SCREEN-D, INV-SCREEN-F)

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] macos-observer-client: cadence + metadata + pause + exclusions + durable offline buffer`. Ready after SCREEN-01 merges (∥ SCREEN-02). **May transfer to the `bifrost` repo.** External-boundary/client work; likely **opus-tier** (durable buffer + pause fail-safe + capture-time exclusion are correctness-critical at an external boundary). See scratchpad draft.
