---
name: Device Registration And Consent Surface
description: JC on the capture side — first-run creation of this device's `_heimdal/devices/{device_id}.md` note bound to the standing self-record grant, and a truthful consent/registration display.
task_id: HCAP-04
source_anchor: docs/contracts/MIMER_CLIENT_CONTRACT.md :: §5 Direct-filesystem write transport
parent_capability: Heimdal Capture Client
prerequisites: [HCAP-01]
depends_on: [HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING]
can_parallelize_with: [DISCRETE_RECORD_WITH_BACKGROUND_AUDIO, DELIVER_RECORDINGS_TO_WATCHED_FOLDER]
---

# Device Registration And Consent Surface

Target repo: **`RasmusTho/bifrost`** (Swift; hub repo holds only this spec).
**Vault-write gate applies:** blocked until bifrost#4 and bifrost#5 are merged (README :: Gates).

## Purpose

Heimdal admits captures from registered, consent-bound devices. The device registry is markdown:
one durable-slice note per device at `_heimdal/devices/{device_id}.md` (human-editable
`device_id`/`label`/`consent_grant_ref`; agent-authored `capture_gap_log`/`last_known_snapshot`).
This task makes the phone a first-class registered device and gives JC its capture-side surface —
truthfully (INV-B3-3).

## What This Task Does

- **Device identity:** generate a stable `device_id` on first run (UUID persisted locally;
  `identifierForVendor` acceptable seed), with a human `label` defaulting to the device name.
- **First-run registration:** if `_heimdal/devices/{device_id}.md` does not exist in the selected
  vault, create it via the coordinated, provenance-tagged write seam (post-bifrost#4/#5
  `VaultFileStore`) with frontmatter: `device_id`, `label`, `consent_grant_ref` referencing the
  standing self-record grant as mirrored in `_heimdal/consent.md` (read the grant ref from the
  consent note's `grants`; if the consent note is missing/empty, the surface says so and offers
  registration with the ref left for the hub/human to bind — never a fabricated grant ref).
- **JC surface:** shows the standing grant (scope, granted_at, from the consent note — read-only,
  same note `ConsentLensView` reads), this device's registration state (note exists / fields),
  and an explicit statement of what capture means under Posture A (single-party, discrete,
  press-to-record).
- Registration state feeds the record surface: unregistered → record still works (hub adjudicates
  admission; INV-B3-3) but the surface carries a visible "not registered — captures may be
  refused" state.

## Concretely

Fixture vault with a seeded `consent.md`: first entry into the Heimdal area → "Register this
device" → `_heimdal/devices/<uuid>.md` appears with the three human fields + provenance block;
JC surface shows grant + registered. Fixture without consent grants: surface shows "no standing
grant found" and the unregistered warning; no note fields are invented.

## Why This Matters

Consent is Heimdal's spine (HEIM-3): captures are admitted against a grant, and the device note is
the identity the gap-log and health snapshot (HCAP-05) hang off. A client that fabricated grant
bindings would corrupt the consent chain at its root.

## Acceptance Criteria

- [ ] First-run registration creates the device note with exactly the durable-slice human fields
  + provenance, via `readModifyWrite`/create on the coordinated seam. `Verify:` bifrost
  `Yggdrasil/YggdrasilTests/DeviceRegistrationTests.swift::testFirstRunCreatesDeviceNoteWithProvenance`
  (new; temp vault).
- [ ] Existing device note is never overwritten wholesale — re-registration is a no-op or a
  field-preserving merge. `Verify:` bifrost
  `DeviceRegistrationTests.swift::testExistingNotePreservedOnRelaunch` (new).
- [ ] Missing/empty consent note → truthful empty-state; no fabricated `consent_grant_ref`.
  `Verify:` bifrost `DeviceRegistrationTests.swift::testNoGrantMeansNoFabricatedRef` (new).
- [ ] JC surface renders grant + registration state from the notes (read-only for consent).
  `Verify:` bifrost `Yggdrasil/YggdrasilUITests/HeimdalShellUITests.swift::testConsentSurfaceStates`
  (new; fixture-driven).

## How to Verify (Pre-Merge)

- bifrost CI green; `swiftlint --strict` clean. Pre-merge gate check in the PR body: bifrost#4 and
  #5 merged.

## Out of Scope

- Granting/revoking consent (owner-reserved via the hub's ledger; the client only reads the
  mirror). Hub-side admission behavior. Gap-log/snapshot writes (HCAP-05). Posture-B consent
  fields (dormant by design).

## Related Docs

- `docs/HEIMDAL_CAPTURE_CLIENT/README.md` (INV-B3-3/-B3-4; Gates)
- Hub: `app/heimdal/settings_notes.py` (device + consent note specs — the shapes to conform to,
  published form tracked by hub #3131)
- bifrost: `Yggdrasil/Yggdrasil/Mimer/Lenses/ConsentLensView.swift` (the consent-note read
  pattern)

## Related GitHub Issues

One implementation issue in `RasmusTho/bifrost` (`type:task`, `agent:blocked` — gate list: HCAP-01
issue + bifrost#4 + bifrost#5), linking hub #3026 and this spec file. TCD hint: Sonnet / medium
effort — note I/O with strict truthfulness rules; shapes already exist in `YggdrasilCore`.
