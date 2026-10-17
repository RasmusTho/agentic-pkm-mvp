---
name: Control Surface and Exclusions
description: The operator control surface — governed pause/resume state consumed by the native client's visible capture status, per-app and per-scope exclusions, and retention tunables — settings-governed per the Settings Spine, with a durable receipt for every control change
task_id: SCREEN-06
source_anchor: docs/HEIMDAL_SCREEN_STREAM/README.md :: Owner ruling (pause + exclusion controls, derive-and-discard)
parent_capability: Heimdal Screen Stream
prerequisites: [SCREEN-01]
depends_on: [DEFINE_SCREEN_OBSERVATION_CONTRACT.md]
can_parallelize_with: [DERIVE_ACTIVITY_OBSERVATIONS.md]
---

# Control Surface and Exclusions

## Purpose

The owner ruling that approved always-on desktop screen observation came **with** conditions: pause and
app/scope exclusion controls, and a derive-and-discard raw posture. This task builds the operator
control surface that makes those conditions real and legible: durable pause/resume state, per-app and
per-scope exclusions, and retention tunables — all **settings-governed** per the Settings Spine, with a
**durable receipt for every control change**. This task provides the governed settings + receipt half
behind the capture-loop behavior SCREEN-03 enforces; SCREEN-03 renders the client's actual capture
status for the operator.

## What This Task Does

1. **Governed pause/resume state (INV-SCREEN-C).** A durable, queryable control to pause and resume
   observation. SCREEN-03 owns the operator-visible status of the actual capture loop; this task owns
   the governed setting and must not claim that a resumed setting means an external client is
   observing. Pause revokes the active `screen_always_on` standing grants through the canonical
   consent ledger. A subsequent resume setting never re-grants consent: capture stays refused until
   a separate explicit grant exists.
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
   spine; a Markdown edit reaches the host's accepted control projection through SET-1 ingestion
   without a manual CLI step, and rebinds on vault selection (SET-7). SCREEN-03 consumes that
   projection. No bespoke settings store.

## Concretely

```http
GET /api/heimdal/screen/control?app_id=com.example.Editor&scopes=work

PUT /api/heimdal/screen/control
Content-Type: application/json

{"key":"screen_paused","value":true}
```

Both screen endpoints use the existing server-derived authentication subject. A write additionally
requires shared-settings role permission and WriteGuard admission; scoped read-context credentials
cannot select the compatibility vault for mutation. The existing
`POST /api/companion/vault/settings` writer applies the same authentication to screen keys. The
actor is never supplied by the request body.

These are carrier-free compatibility endpoints. Until the screen-control projections are
binding-aware, requests carrying either `X-Active-Context-Session` or `X-Active-Context-Override`
are refused: GET returns `409 capability_not_ready` (`mvr05b4_binding_aware_read`) and PUT returns
`409 capability_not_ready` (`mvr05c_scoped_write`). Neither endpoint falls back to the current
compatibility vault for a scoped request.

The response exposes accepted `controls`, `requested_state` (`paused` or `resume_requested`),
effective `state` (`paused`, `ready`, or `degraded`), `settings_state`, visible `errors`, and
`capture_state=unknown_external_client`. `capture_permitted` requires a nonempty app ID, active
consent, accepted resumed controls, and no app/scope exclusion. `ready` reports the general host
gates; `capture_permitted` applies the queried app/scope exclusions. Neither observes the client's
loop. A successful change returns its durable receipt; an unchanged
value returns no new receipt. This slice does not add a screen-control CLI.

The source is `<vault>/settings/screen_control.md`. The API, Companion writer, direct
`SettingsService.update_setting` caller, and live watcher use the existing acceptance seam. Local
service writers serialize control updates, preserve the original Markdown version with filesystem
version-CAS, and accept only the bytes produced by the requested write. Pause then revokes every
active screen-scope grant through `consent_ledger.revoke_consent` before settings acceptance. The
canonical grant fence denies later raw admission; the same call erases the grant's hot/cold raw
copies through HAR-05's receipted erasure path. Already published observations are not retracted by
this control. Other capture lanes' grants are unchanged.

A concurrent source edit, failed revocation/erasure, or failed settings receipt returns a refusal
without accepting a stale pause. A durable revocation is never compensated by re-granting consent.
If erasure fails after the ledger append, that existing revocation row remains the recovery work
item. Pause retry reconciles screen-scope erasure before accepting the setting; the existing
scheduled retention reconciliation also retains its all-scope recovery. An explicit pause of an
already-paused setting still revokes active screen grants, with canonical actor-tagged revocation
rows but no duplicate settings-change receipt.
If one grant's revocation or erasure raises, the writer still attempts every remaining active
screen grant before returning failure. An erasure failure must not leave a later grant admitting
capture; no settings success receipt is written until the pending work is reconciled.

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
- [ ] AC3: the host status surface exposes the durably accepted pause/exclusion/tunable settings
      supplied to SCREEN-03, including visible degradation. It distinguishes requested/allowed
      observation from actual external-client capture state and never reports `observing` solely from a
      resume setting. Actual capture-loop and visible-indicator agreement is SCREEN-03/Bifrost #72 and
      the parent #3340 capability acceptance. Verify:
      `tests/heimdal/test_screen_control_settings.py::test_visible_state_matches_governed_controls`
- [ ] AC4: an invalid retention/cadence value degrades loudly to last-valid with a visible degraded
      state, never silently to a code default. Verify: `tests/heimdal/test_screen_control_settings.py::test_invalid_tunable_degrades_loud_not_silent`
- [ ] AC5 (non-behavioral): the screen-stream tunables are declared once in the single default registry
      (no duplicated literals). Verify: doc writeback at `docs/HEIMDAL_SCREEN_STREAM/README.md :: Provisional constants` + `tests/heimdal/test_screen_control_settings.py::test_screen_tunables_are_single_sourced`

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

Pause state and exclusions are **durable governed settings**: vault-scoped Markdown supplies desired
values, and the existing durable settings receipt history reconstructs accepted values for the
selected vault ID and local-instance ID. Restart and watcher replay retain accepted pause and do not
duplicate a receipt. A source edit that has not completed durable acceptance remains pending and
denies capture. Invalid replacements retain proven values with visible degradation; unavailable or
corrupt receipt history cannot authorize capture or irreversible retention cleanup. No selected vault or
a missing source file also denies capture. SCREEN-03 must still default to paused on ambiguous
client restart and render its actual loop state. Resuming the setting after a completed pause keeps
capture refused until a separate explicit consent grant; neither retry nor restart creates one.

New-vault initialization derives the canonical file from the single model declaration. An existing
legacy `_heimdal/settings.md` retention value is migration evidence only: an explicit canonical
Settings Spine write records that old value before the screen retention policy becomes active.
The old note is not rewritten. See `docs/SETTINGS.md :: Screen control settings`.

## Related Docs

- `docs/SETTINGS_SPINE/README.md` (one spine, ingestion SET-1, receipt-every-write SET-3, single default registry SET-4, rebind-on-selection SET-7)
- `docs/SETTINGS_SPINE/RECEIPT_EVERY_SETTINGS_WRITE.md`, `docs/SETTINGS_SPINE/WIRE_SETTINGS_INGESTION.md`
- `docs/HEIMDAL/OWNER_DECISIONS.md` D-CONSENT (pause = standing-grant revocation lineage)
- `docs/HEIMDAL_SCREEN_STREAM/README.md :: Cross-Task Invariants` (INV-SCREEN-C, INV-SCREEN-D) + `:: Provisional constants`

## Related GitHub Issues

One issue: `[Heimdal Screen Stream] control-surface-and-exclusions: visible pause + app/scope exclusions + retention tunables, receipted` (#3342). It depends on SCREEN-01 (#3343) and can proceed before SCREEN-03. SCREEN-06 exposes the governed controls and reports external capture state as unknown on its own; SCREEN-03's native implementation in [Bifrost #72](https://github.com/RasmusTho/bifrost/issues/72), with #3341 as the Heimdal validation pointer, renders actual capture status and enforces those controls. **Sonnet-tier** (settings-governed control surface + receipts over the existing Settings Spine). See scratchpad draft.
