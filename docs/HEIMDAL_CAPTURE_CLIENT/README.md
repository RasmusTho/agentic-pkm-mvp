State: Active specification (2026-07-07). Governs B3 (#3026) — the Heimdal-iPhone capture client + Apple Watch — broken down to slices a Sonnet-class agent can build from the slice text alone.
Doc role: Specification directory (feature-breakdown lane)
Authority: Specifies the B3 work. Subordinate to `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`, `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md`, `docs/adr/ADR-0056-mimer-client-contract-and-transports.md`, `docs/contracts/MIMER_CLIENT_CONTRACT.md`, and `docs/BIFROST/APP_TOPOLOGY_AND_PLATFORMS.md` (design-of-record; ADRs win on conflict — see "The ASR ruling" below, which exercises exactly that clause). Transport reasoning follows `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md`.
Owner: Architecture / product (Rasmus)

# Heimdal Capture Client (B3)

## Why this spec exists

B3 gives Heimdal its native capture surface: press-to-record on iPhone with true background
continuation (J0), the consent/identity surface (JC), the device-health panel (JD), and one-tap
record with haptic capture status on Apple Watch. Today capture runs on stock Voice Memos + a
Shortcut moving files into an iCloud folder the hub watches — functional (Model 1, "the durable
floor") but friction-heavy and metadata-poor.

Substrate facts this spec builds on (verified on hub `main` = `1ce3b013`):

- **Ingress is filesystem-only.** The capture watcher (`app/heimdal/capture_runtime.py`, which
  reads `HEIMDAL_CAPTURE_WATCH_DIR` and drives `app/heimdal/capture_adapter.py` on a tick) admits
  `.m4a/.wav/.caf/.aac`, refuses still-syncing files via a two-read stability guard (#3112),
  encrypts into the raw store idempotently by content hash, and deletes the source only after the
  confirmed write. **There is no HTTP route for audio** and this
  spec does not create one.
- **The hub transcribes.** ASR is the shared faster-whisper engine invoked inside Heimdal's trust
  boundary on the runtime host — local-only, fail-loud, no cloud fallback (ADR-0049 §3; the
  one-Whisper rule in `docs/HEIMDAL/FABLE_COMPANION.md`).
- **Consent + device identity are vault notes.** The standing `self_record` grant lives in the
  consent ledger (mirrored to `_heimdal/consent.md`); device identity/config is
  `_heimdal/devices/{device_id}.md` (durable slice: `device_id`, `label`, `consent_grant_ref`
  human-editable; `capture_gap_log`, `last_known_snapshot` agent-authored).
- **Watch constraint:** Tailscale does not run on watchOS and no sanctioned watchOS pattern
  exists for streaming mic audio (`CAPTURE_TRANSPORT_FEASIBILITY.md` Model 3, "do not build" +
  R-EXTERNAL). The sanctioned Watch path is file-based relay.

Changed since that snapshot:

- **Two standing `self_record` grants, not one (#4492).** The consent ledger now seeds one per
  self-record capture lane — `device+adapter:v1-voice-memo` (this spec's watched-folder lane) and
  `device+adapter:v1-media-ingress` (the governed media ingress lane) — so `basis: self_record` no
  longer identifies a unique grant. Select by `scope`. See
  `DEVICE_REGISTRATION_AND_CONSENT_SURFACE.md` for the binding rule.

## The ASR ruling (read before executing anything)

Issue #3026 as originally filed asked for "on-device ASR", and the design-of-record's §3 assigns
"the on-device ASR pipeline" to the Heimdal client. That conflicts with the **ratified** ADR-0049
§3 ruling (local-only ASR, no silent cloud fallback) as concretized by its joint source-of-truth
`docs/HEIMDAL/FABLE_COMPANION.md` §7.3/§9-j/§9-k: one shared ASR engine on the runtime host,
raw-evidence lineage (`raw_store` → gated reads → transcript with per-segment confidence),
diarization-based third-party withholding, fail-loud. The design-of-record's own authority header says
ADRs win on conflict. **Ruling encoded by this spec: the client captures and delivers audio; it
never transcribes.** Phone-side ASR would bypass the raw seam (no lineage, no diarization
withholding, a second ASR identity) — the same reason the Siri/App-Intents dictation channel is
classified as complementary-only. If the owner ever wants phone-side ASR it is a `reshape`
requiring an ADR, not a B3 slice. #3026's ACs are repaired to match this ruling.

Consequence for buildability: **no ML on the phone.** Every B3 slice is ordinary AVFoundation /
file-handling / SwiftUI work a Sonnet-class agent can execute.

## Transport model (decided by feasibility doc, not re-decided here)

Model 1 — file into the watched iCloud folder — is the v1 transport. The client binds the watched
folder once via the same visual folder-pick + security-scoped-bookmark pattern the vault uses (no
iCloud entitlements needed — free-provisioning compatible per
`docs/BIFROST/APP_DEPLOYMENT_POSTURE.md`). Delivery discipline (temp-name-then-rename, admissible
extension only at the final name) composes with the adapter's stability guard so the hub never
ingests a partial file. Model 2 (tailnet streaming) is built **only** if the EXP-1 measurement —
folded into the round-trip task here — proves Model 1's latency insufficient; Model 3 (Watch
streaming) stays "do not build" (R-EXTERNAL).

## Implementation tasks

| Task | Repo | Purpose |
|---|---|---|
| [HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING.md](HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING.md) | `RasmusTho/bifrost` | Second bounded client in the shell: Heimdal area, capture-folder visual binding, capture session state machine (no audio yet) |
| [DISCRETE_RECORD_WITH_BACKGROUND_AUDIO.md](DISCRETE_RECORD_WITH_BACKGROUND_AUDIO.md) | `RasmusTho/bifrost` | Press-to-record with background continuation, interruption pause/resume, finalized `.m4a` segments in local staging |
| [DELIVER_RECORDINGS_TO_WATCHED_FOLDER.md](DELIVER_RECORDINGS_TO_WATCHED_FOLDER.md) | `RasmusTho/bifrost` | Staging → watched folder with completeness discipline, visible pending queue, delete-local-after-confirmed-placement |
| [DEVICE_REGISTRATION_AND_CONSENT_SURFACE.md](DEVICE_REGISTRATION_AND_CONSENT_SURFACE.md) | `RasmusTho/bifrost` | JC: first-run device note (`_heimdal/devices/{device_id}.md`), standing-grant display, registration truthfulness |
| [DEVICE_HEALTH_PANEL_WITH_GAP_LOG.md](DEVICE_HEALTH_PANEL_WITH_GAP_LOG.md) | `RasmusTho/bifrost` | JD: live telemetry panel (the declared UI-only bend) + durable `capture_gap_log`/`last_known_snapshot` writes |
| [WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS.md](WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS.md) | `RasmusTho/bifrost` | watchOS target: one-tap record, pause/resume haptics, WatchConnectivity file relay into the phone's delivery queue |
| [CAPTURE_TIME_METADATA_SIDECAR.md](CAPTURE_TIME_METADATA_SIDECAR.md) | both | Versioned sidecar with capture-time context (episode-dimension signals, ADR-0051); bifrost writes it, hub adapter consumes it |
| [PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL.md](PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL.md) | `RasmusTho/agentic-pkm-mvp` (hub) | Real-runtime receipt: app-delivered file → watched dir → raw-store admission (→ manually driven ASR/note stages); EXP-1 latency observation |
| [PROVE_CAPTURE_UAT_JOURNEYS.md](PROVE_CAPTURE_UAT_JOURNEYS.md) | `RasmusTho/bifrost` | XCUITest journeys delivered by PR #56; operator device walkthrough remains on bifrost#21 (`agent:needs-human`) |
| [RECONCILE_AND_CLOSE_B3_TRACKING.md](RECONCILE_AND_CLOSE_B3_TRACKING.md) | `RasmusTho/agentic-pkm-mvp` (hub) | Assemble the ledger on #3026, close truthfully, update Epic B #3020 |

## Execution order

1. `HEIMDAL_CLIENT_SCAFFOLD_AND_CAPTURE_FOLDER_BINDING` — **delivered** by bifrost#14 / PR #24.
2. `DISCRETE_RECORD_WITH_BACKGROUND_AUDIO` — **delivered** by bifrost#15 / PR #28.
3. `DELIVER_RECORDINGS_TO_WATCHED_FOLDER` — **delivered** by bifrost#16 / PR #36.
4. `DEVICE_REGISTRATION_AND_CONSENT_SURFACE` — after 1; **vault-write gated** (bifrost#4/#5 merged). May run parallel with 2–3.
5. `DEVICE_HEALTH_PANEL_WITH_GAP_LOG` — after 2 and 4; gap-log writes share 4's gate.
6. `WATCH_ONE_TAP_RECORD_WITH_HAPTIC_STATUS` — **delivered** by bifrost#19 / PR #38.
   Physical-device WatchConnectivity timing and haptic feel remain HCAP-09 walkthrough scope.
7. `CAPTURE_TIME_METADATA_SIDECAR` — Bifrost producer half **delivered** by bifrost#20 / PR #37;
   hub consumer half remains its own issue, sequenced with the ERE lane.
8. `PROVE_CAPTURE_ROUND_TRIP_ON_TEST_CHANNEL` — after 3 and 4 (registered device delivering real files).
9. `PROVE_CAPTURE_UAT_JOURNEYS` — agent-verifiable journeys **delivered** by bifrost PR #56;
   physical-device walkthrough receipt remains on bifrost#21 (`agent:needs-human`).
10. `RECONCILE_AND_CLOSE_B3_TRACKING` — strictly last; blocked on 8's and 9's receipts.

## Gates (slice-granular, recorded on #3026)

- **Vault-write slices (4, 5) carry the same gate as B2's write-bearing slices:** hub
  #3129/#3131/#3132 (ADR-0055 enactment) **and** bifrost#4 + bifrost#5 (the client write seam) all
  merged. This honors the recorded owner gate on Epic B ("B2/B3 remain gated on ADR-0055
  enactment") without loosening it. Observation for the owner, stated but NOT enacted here: these
  are low-contention per-device notes with a single writer in practice, so the hub-trio half of
  the gate could defensibly be relaxed for HCAP-04/05 specifically — if the owner wants that, a
  ruling comment on #3026 relaxes it auditable-ly; absent that comment, the full gate stands.
- **Capture delivery (2, 3, 6) is not vault work** — new uniquely-named files in a non-vault
  folder, append-only semantics, no multi-writer exposure. Not gated on ADR-0055 enactment.
- The former `agent:needs-human` posture on #3026 is discharged by decided facts: Posture A is
  ratified (ADR-0049 §3), the deploy posture is decided (`APP_DEPLOYMENT_POSTURE.md` — and with
  no App-Store submission, App-Review split-trigger risk is dormant), and the ASR conflict is
  ruled above. The one remaining owner-reserved boundary: **any** design needing public ingress
  (Model 3 or a cellular-Watch direct path) is R-EXTERNAL and returns to the owner.

## Cross-Task Invariants / Interaction Safety

- **INV-B3-1 — A stopped recording is never silently lost.** From the moment a recording stops,
  its file exists in exactly one accountable place: local staging (visible in the pending queue,
  with error state if delivery fails), or the watched folder (complete, final name), or — after
  confirmed placement — deleted locally by design. Delivery is temp-name-then-rename so the hub's
  stability guard never admits a partial. Partial-failure paths: app killed mid-recording →
  segment finalized on next launch from the recorder's file (AVAudioRecorder writes as it goes),
  surfaced in the queue; stale folder bookmark → queue accumulates, JD panel shows the backlog,
  nothing deleted; iCloud sync latency → hub-side stability guard already handles it.
- **INV-B3-2 — The raw seam is preserved.** The client ships audio (+ sidecar metadata), never
  transcripts, never summaries. No speech framework, no ML inference on capture content, no
  cloud upload of audio to anything but the operator's own iCloud folder (owner-acknowledged
  transit, feasibility doc §9-h reference).
- **INV-B3-3 — Consent and registration are surfaced truthfully, adjudicated hub-side.** The JC
  surface shows the standing grant and this device's registration state as read from the vault;
  the client never fabricates registration, never blocks capture client-side on hub state it
  cannot verify — an unregistered device's deliveries being refused at admission is hub behavior,
  visible in the JD/queue surface, not silently pre-empted.
- **INV-B3-4 — The client authors no vault content except its own device note.** Transcripts,
  capture notes (`_heimdal/captures/…`), attention/consent updates are hub-authored. The one
  client-owned vault artifact is `_heimdal/devices/{device_id}.md` via the coordinated write seam.
- **INV-B3-5 — The Watch is a relay, not a network client.** Watch recordings reach the system
  only via WatchConnectivity file transfer into the phone's delivery queue (then INV-B3-1
  applies). No watchOS networking, no public ingress. Native phoneless Watch capture is
  explicitly NOT claimed — the stock-Voice-Memos floor (shipped Model 1) remains the documented
  phoneless fallback.
- **INV-B3-6 — Split-readiness is structural.** Heimdal-client code lives in its own directory
  boundary (`Yggdrasil/Yggdrasil/Heimdal/…`) importing only the shell (App/Auth/Vault/Design
  system) and `YggdrasilCore` — never Mimer lens internals — so the ADR-0049 §4 split trigger
  stays a repackaging, not a re-architecture.

## Capability acceptance criteria

B3 (#3026) can be closed when all of the following hold:

- [ ] Press-to-record captures with background continuation and interruption pause/resume;
  finalized recordings reach the watched folder under INV-B3-1 discipline (tasks 1–3 merged; CI
  green).
- [ ] JC: device note exists with grant binding; registration/consent state visible (task 4).
- [ ] JD: live panel shows session/battery/queue state (UI-only bend); gap log + last-known
  snapshot persist to the device note (task 5).
- [ ] Watch: one-tap record with pause/resume haptics relays recordings into the delivery queue
  (task 6).
- [ ] Capture-time metadata sidecar is written and consumed (task 7, both halves).
- [ ] A real recording from the app lands in the test channel's raw store with a
  `RawEvidenceReceipt`, and the EXP-1 latency observation is recorded (task 8).
- [ ] Capture journeys run as XCUITests in CI; operator's device walkthrough receipt on #3026
  (task 9).
- [ ] #3026 closed with the assembled ledger; Epic B #3020 updated (task 10).

## Relationship to GitHub issues

- **Parent / validation hub:** #3026 — already exists, stays the hub; its ACs are repaired to this
  spec when the spec lands.
- **Grandparent:** Epic B #3020.
- **Bifrost child issues** implement tasks 1–7 (bifrost halves); **hub child issues** implement
  the task-7 hub half, task 8, and task 10.
- Adjacent hub gaps this spec names but does NOT own (pre-existing, filed or file-worthy):
  the capture→ASR→note→publish chain has no unattended orchestrator on `main` (only raw admission
  runs on a tick) — task 8 documents which stages it drives manually; the signed-capture-manifest
  hardening (`FABLE_COMPANION.md` red-team F2b) remains unimplemented hub-side — TCD-gated
  single-operator posture, tracked outside this spec.

## Verification path

Swift verification in bifrost CI (macos-14; iPhone + Watch simulator builds — the Watch target
must at minimum build in CI; Watch XCUITest automation is best-effort). Hub-side verification on
the test channel (mac mini) per `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md`. Human steps:
the device walkthrough (task 9) and the EXP-1 observation window (task 8) — both scripted,
both receipted on #3026.

## Evidence surface

Validation receipts accumulate as comments on #3026. Owner-doc promotion happens once, at task 10.
