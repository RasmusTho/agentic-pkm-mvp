State: Filed target-state specification (authored 2026-07-29). Parent validation hub #4383 (`agent:blocked`); children hub #4384–#4389 and bifrost #57–#60 filed 2026-07-29; only CDLM-01 (#4384) is `agent:ready`. No runtime behavior described here is implemented until a child PR delivers it.
Doc role: Specification directory (feature-breakdown lane)
Authority: Owns the bounded implementation order, cross-task durability/authority invariants, and acceptance path for the first Bifrost product vertical: durable cross-device capture ingress plus live meeting analysis. Subordinate to `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md` (ingestion organ, hub-side ASR, Topology C), `docs/adr/ADR-0060-capture-posture-b-full-voice-identity.md` (posture target and consent classes), `docs/adr/ADR-0055-vault-multiwriter-consistency-model.md` / `docs/adr/ADR-0056-mimer-client-contract-and-transports.md` / `docs/contracts/MIMER_CLIENT_CONTRACT.md` (transports, writer discipline, Sources zone), and the entity-review authority boundary in `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`. ADRs win on conflict.
Owner: Product/Runtime — Heimdal ingestion + Mimer meeting cognition + Bifrost client surfaces
Temporal class: target-state delivery contract
Review cadence: event-driven (filing, each child merge, terminal acceptance)
Source of truth: this directory for task shape; the owner documents named above for current authority and shipped behavior
Last reviewed: 2026-07-29

# Cross-Device Capture & Live Meeting (CDLM)

## Why this spec exists

The owner's product priority (2026-07-29) makes cross-device capture the first Bifrost product
vertical: capture audio, photos, video, receipts, and documents on Apple Watch, iPhone, and iPad;
transfer them to the hub reliably; and run live meeting capture with a provisional, revisable
analysis surface on iPad.

The delivered substrate is honest but insufficient for that contract:

- **Delivery today is placement-gated, not receipt-gated.** B3's shipped delivery discipline
  (`docs/HEIMDAL_CAPTURE_CLIENT/DELIVER_RECORDINGS_TO_WATCHED_FOLDER.md`, bifrost#16 / PR #36)
  deletes the local original after confirmed *placement in the watched folder*. Placement is not
  hub admission: the 2026-07-29 prod bring-up found owner recordings that "should have landed"
  with the entire capture tree empty (#4369) while the test channel's capture watcher had been
  crash-looping behind a healthy healthcheck for weeks (#4362). Nothing in the shipped chain can
  tell the client — or the owner — whether an original is durably accepted.
- **The governed capture surface has no media lane and no client idempotency key.**
  `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4 ships text capture only, and names the missing
  client-visible idempotency key as gap F5. Audio ingress is filesystem-only.
- **Nothing produces a live, revisable meeting projection.** ASR is hub-side and shared
  (ADR-0049 §3; `app/media/transcribe.py`), but the capture→ASR→note chain has no unattended
  orchestrator, no session/segment model, no analysis projection, and no block-ownership model
  for a meeting surface.

This directory specifies that vertical as ten bounded, independently verifiable tasks across the
hub (`RasmusTho/agentic-pkm-mvp`) and the Bifrost client repo (`RasmusTho/bifrost`).

## Classification and authority boundary

**Change classification:** target-state / future-state work. This docs-only breakdown claims no
shipped behavior. Delivered B3 slices (HCAP-01/02/03/06 and the sidecar producer) remain truthful
history; where this spec supersedes their semantics, the supersession is stated explicitly below.

**SBS classification:** Product/Runtime.

- **Primary:** Heimdal ingestion seam (durable media admission, session/segment ledger) and Mimer
  meeting cognition (transcript/analysis projections, block ownership, finalization).
- **Secondary:** Bifrost constituent (capture surfaces, durable transfer outbox, iPad queue and
  meeting surfaces); PDM persistence (ledger/projection state); OEF outbox (admission events).

Authority boundaries this spec inherits and never reopens:

- **The client captures and delivers; the hub transcribes and derives.** ADR-0049 §3 as encoded by
  B3's ASR ruling. No on-device ASR, no on-device analysis, no client-side ML over capture content.
- **Hub-side merge authority.** Entity merges are canonicalized and executed by the Hub alone
  (`docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`, `docs/contracts/MIMER_CLIENT_CONTRACT.md`
  §3). iPad surfaces — including any reused B2 merge UI — display proposals and submit
  proposal-bound approval/reject/pre-application-undo signals only. This vertical adds no merge
  surface and no merge execution path.
- **No person inference in the first slice.** No speaker identity from voice, face, or uncertain
  diarization. Third-party speech follows ADR-0060's default: without a per-person consent-linked
  grant it is not transcribed into published content and remains a withheld span. Template
  selection uses explicit user choice, then explicitly permitted metadata, then the generic
  default — never inferred participant identity.
- **No public ingress.** The media ingress endpoint follows the client contract's v1 posture:
  loopback/LAN/tailnet only. Any design requiring public ingress is R-EXTERNAL and returns to the
  owner. The Watch remains a relay through the phone (INV-B3-5); it gains no networking.

**Transport ruling encoded by this spec.** The live-meeting requirement is latency-bound by
definition, so this vertical introduces the direct tailnet/LAN HTTP transfer lane that
`docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md` proposed as Model 2 and that ADR-0060 G1/G3
already anticipate as the stream transport. The owner's 2026-07-29 product-priority directive is
the decision authority for building this lane; EXP-1 remains only as a memo-flow latency
observation. Model 1 (watched folder) stays the phoneless/legacy floor and is explicitly **not**
receipt-gated; Model 3 (Watch streaming) stays do-not-build.

## Fixed scope

| Order | Task | Repo | Outcome |
| --- | --- | --- | --- |
| 1 | [ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md](ADMIT_MEDIA_WITH_DURABLE_RECEIPTS.md) (CDLM-01) | hub | Governed media ingress: idempotent durable admission of audio/image/video/document bytes with a queryable durable-acceptance receipt; acknowledged only after raw-store write and committed outbox event. |
| 2 | [TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md](TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS.md) (CDLM-02) | hub | Meeting session ledger over admitted segments: open/close, per-session monotonic sequence set, gap detection, late-segment reconciliation. |
| 3 | [RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md](RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT.md) (CDLM-03) | bifrost | Durable transfer outbox: originals retained until the hub receipt is persisted locally; idempotent resend; disk-rebuilt queue across relaunch; supersedes placement-gated deletion for the outbox lane. |
| 4 | [CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO.md](CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO.md) (CDLM-04) | bifrost | Photo, receipt/document scan, and video capture on iPhone/iPad feeding the same outbox with typed sidecars; Watch stays audio-relay-only. |
| 5 | [SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD.md](SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD.md) (CDLM-05) | bifrost | iPad transfer-queue surface with the five truthful states `pending locally → transferring → backend durably received → processing → complete / needs attention`, derived only from durable local state plus hub answers. |
| 6 | [PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md](PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS.md) (CDLM-06) | hub | Per-segment ASR into a revisable transcript projection plus a generic-default-template analysis projection (summary, themes, provisional decisions, open questions, action candidates) with revision and derivation provenance. |
| 7 | [ENFORCE_MEETING_BLOCK_OWNERSHIP.md](ENFORCE_MEETING_BLOCK_OWNERSHIP.md) (CDLM-07) | hub | Meeting block model: stable id, owner, type, provenance; `user_note` writable only by the user's editor seam; derived writers confined to `derived_projection`; unknown/conflicting ownership fails closed preserving user content. |
| 8 | [CONSOLIDATE_MEETING_ON_END.md](CONSOLIDATE_MEETING_ON_END.md) (CDLM-08) | hub | Meeting finalization: consolidated transcript and final derived analysis materialized create-once into the Sources zone; user notes preserved verbatim as their own artifact; gaps surface as needs-attention, never silent completeness. |
| 9 | [RUN_LIVE_MEETING_ON_IPAD.md](RUN_LIVE_MEETING_ON_IPAD.md) (CDLM-09) | bifrost | iPad live meeting surface: segment capture into the outbox, clearly labeled provisional AI blocks vs the user's own notes editor, reconnect resend + reconciled refresh, and the final view separation. |
| 10 | [PROVE_CROSS_DEVICE_ROUND_TRIP_WITH_RECONNECT.md](PROVE_CROSS_DEVICE_ROUND_TRIP_WITH_RECONNECT.md) (CDLM-10) | hub | Test-channel proof: multi-modality round trip with kill/restart and disconnect/reconnect chaos steps, duplicate-free idempotency evidence, and receipts on the parent issue. |

## Execution order

```text
CDLM-01 durable admission + receipts            (hub, first — everything depends on it)
  -> CDLM-02 session/segment ledger             (hub)      — may run parallel with CDLM-03
  -> CDLM-03 receipt-gated client outbox        (bifrost)  — may run parallel with CDLM-02
    -> CDLM-04 photo/document/video capture     (bifrost)  — parallel with CDLM-05/06
    -> CDLM-05 iPad transfer-queue surface      (bifrost)  — parallel with CDLM-04/06
    -> CDLM-06 transcript + default analysis    (hub)      — needs CDLM-02
      -> CDLM-07 block ownership enforcement    (hub)
        -> CDLM-08 finalization                 (hub)
        -> CDLM-09 iPad live meeting surface    (bifrost, needs CDLM-03/06/07)
          -> CDLM-10 round-trip + reconnect proof (strictly last)
```

Only CDLM-01 may be `agent:ready` after strict issue-contract validation. Every other child and
the parent validation hub stay `agent:blocked` until their named prerequisites' acceptance
receipts are recorded on the parent issue.

## Cross-Task Invariants / Interaction Safety

- **INV-CDLM-1 — a receipt means durable acceptance.** The ingress endpoint acknowledges success
  only after the original is durably written to the raw store and the admission event is committed
  to the outbox (same ack ordering as the governed text capture in
  `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.1). An HTTP 2xx without both is a contract
  violation, not a receipt. Transport success, folder placement, and iCloud sync are never
  receipts.
- **INV-CDLM-2 — originals outlive everything until their receipt.** The client deletes a captured
  original only after that item's durable-acceptance receipt is persisted in the client's own
  durable outbox state. Process kill, relaunch, device reboot, or hub unavailability may delay
  transfer forever; they may never lose an original or a persisted receipt.
- **INV-CDLM-3 — retries are idempotent end-to-end.** Transfer identity is
  `(capture_id, content_sha256)`, minted once at capture finalization. Re-sending after a lost
  response, crash, or reconnect re-admits nothing: the hub returns the same receipt identity, the
  raw store holds one object, the session ledger holds one row per sequence number, and
  projections derive each segment once. Duplicates are a hub-side impossibility, not a client-side
  courtesy.
- **INV-CDLM-4 — displayed queue state is derived truth.** The iPad queue renders only from
  durable client state plus hub receipt/status answers. `backend durably received` requires a
  persisted receipt; `complete` requires a hub processing answer; reconnect and relaunch may
  regress a *display* to a less-advanced state only when the underlying evidence is genuinely
  absent — they never fabricate an advanced state and never lose a persisted receipt.
- **INV-CDLM-5 — projections are revisable, never canonical.** Live transcript and analysis derive
  only from durably admitted segments; every derived block carries a revision id and the segment
  set it derived from. Re-derivation after reconnect or late segments converges: the same admitted
  segment set yields the same content. Canonical truth is only what CDLM-08 materializes through
  governed create-once writes — and it is derived material, subordinate to human authority.
- **INV-CDLM-6 — user content is inviolable.** `user_note` blocks are writable exclusively through
  the user's editor seam. Analysis revision, reconciliation, template change, and finalization can
  never overwrite, merge, move, reorder, or normalize a `user_note` block. Unknown or conflicting
  block ownership fails the *derived* write closed and preserves user content untouched. The final
  surface keeps user notes as their own artifact, never folded into derived output.
- **INV-CDLM-7 — merge authority does not move.** Nothing in this vertical executes, canonicalizes,
  or emits an entity merge. iPad surfaces display hub proposals and durable outcomes and submit
  proposal-bound approval signals per the entity-review operation journal contract.
- **INV-CDLM-8 — no person inference.** No task in this vertical attributes speech, images, or
  documents to a named person from voice, face, or uncertain diarization. Third-party speech takes
  ADR-0060's withheld default. Template selection and analysis use explicit user input or
  explicitly permitted metadata only.
- **INV-CDLM-9 — gaps are legible.** A missing segment, failed derivation, refused admission, or
  incomplete close is surfaced as `needs attention` with item identity (which capture, which
  sequence numbers) on both the queue and meeting surfaces and in the finalization receipt.
  Silent completeness is a contract violation everywhere in this vertical.

## Cross-task partial-failure matrix

| Failure point | Durable evidence after restart | Required behavior | Forbidden outcome |
| --- | --- | --- | --- |
| Client crash after capture finalization, before any send | Original + sidecar in the outbox store | Queue rebuilds from disk; item shows `pending locally` | Losing the original; fabricating a sent state |
| Response lost after the hub durably admitted | Hub: raw object + committed event; client: outbox item without receipt | Client re-queries receipts by `capture_id` or resends; hub answers idempotently with the same receipt | A duplicate raw object, ledger row, or derived segment |
| Hub crash between raw write and outbox commit | Raw object without committed event | Admission is not acknowledged; the client resend completes admission idempotently and only then receives the receipt | Acknowledging before the event commit; orphaned acknowledged state |
| Disconnect mid-meeting | Outbox holds unsent segments; ledger holds a gapped sequence set | Ledger reports the gap; client resends missing segments on reconnect; projections re-derive and converge | Projections claiming completeness over a gapped prefix; double-derived segments |
| Meeting closed while segments are missing | Close record + gapped ledger | Finalization marks the output `needs attention` with the missing sequence numbers; late admission triggers reconciliation and re-finalization | A final transcript/analysis presented as complete over known gaps |
| Hub restart mid-meeting | Admitted segments + ledger + projection revisions in durable state | Session state and projections rebuild from durable rows; the next derivation resumes at the correct revision | Restart resetting the ledger, losing admitted segments, or replaying derivations non-idempotently |
| Template switched mid-meeting | User's explicit selection recorded with the session | Derived blocks re-render under the new template as a new revision; user notes untouched | Any rewrite, move, or merge of `user_note` blocks |
| User note written while reconciliation runs | The note write lands through the user-editor seam | The seam serializes; the user write is preserved verbatim regardless of concurrent derived revisions | A derived writer touching, reordering, or displacing the user's block |
| Watched-folder (Model 1) file arrives with no `capture_id` sidecar | Raw admission + receipt keyed by content hash only | Admitted and receipted hub-side; explicitly outside the outbox retention guarantee | Claiming receipt-gated retention for the legacy lane |

## Supersessions (explicit)

- **HCAP-03 deletion semantics.** `DELIVER_RECORDINGS_TO_WATCHED_FOLDER.md`'s
  delete-local-after-confirmed-placement remains truthful for the delivered Model-1 lane but is
  **superseded as the target contract** by CDLM-03's receipt-gated retention for everything the
  outbox carries. The watched-folder lane continues to exist as the phoneless/legacy floor without
  receipt-gated retention, stated honestly.
- **bifrost#21 (HCAP-09 UAT)** is now the named remaining **human step** — the physical-device
  walkthrough (locked-screen capture, real calls, wrist haptics, on-device app-lifecycle truths).
  CDLM-10's scripted proof (#4389, `scripts/cdlm_roundtrip_proof.py`) covers the hub contract and
  the simulator-verifiable composition only; those simulator-only limits are stated in its run
  report on #4383. With CDLM-03/05/08/09 delivered and the CDLM-10 receipt posted, bifrost#21 is
  unblocked for the operator's walkthrough.
- **Execution gate G-CI is retired (2026-07-30).** This directory originally required bifrost#52
  to be fixed, or local `xcodebuild test` evidence attached, before any bifrost child could merge.
  That gate rested on a stale premise: all three defects bifrost#52 described had already been
  removed by bifrost PR #32 (merged 2026-07-20), nine days before the issue was filed — the filing
  read `.github/workflows/ci.yml` out of a shared checkout parked on an old branch rather than out
  of the resolved base SHA. Bifrost CI pins `-scheme Yggdrasil`, runs both an iPhone and an iPad
  destination, and runs `xcodebuild test` unpiped under `set -euo pipefail`. Its fail-closed
  behavior was then proven empirically for the first time by scratch PR bifrost#61 (closed
  unmerged): an injected `XCTFail` turned the check red and `set -e` aborted the destination loop
  on the first non-zero exit. Bifrost children therefore verify on ordinary bifrost CI with no
  extra evidence obligation.
- **HCAP-08 (#3191) is not absorbed.** That issue keeps proving the Model-1 watched-folder round
  trip; CDLM-10 (#4389) proves the receipt-gated outbox lane. The boundary is recorded as a
  comment on #3191 so neither re-proves the other's lane.
- **EXP-1 / Model-2 trigger.** The owner's product-priority directive resolves the Model-2 build
  trigger for session/segment transfer (see Transport ruling above). EXP-1's memo-latency
  observation in HCAP-08 remains informative, no longer gating.

## Capability acceptance criteria

The parent feature issue can be closed when all of the following hold:

- [ ] A capture on iPhone or iPad (audio, photo, document/receipt, video) reaches the hub with a
  durable-acceptance receipt, retained locally until that receipt, surviving kill/relaunch at any
  point, with duplicate-free resend proven (CDLM-01/03/04, receipts on the parent).
- [ ] The iPad queue shows the five states truthfully across restart and reconnect (CDLM-05).
- [ ] A live meeting session yields a revisable transcript + generic-template analysis on iPad
  while recording, reconciles a forced disconnect by resending missing segments and re-deriving,
  and separates "your notes" from "AI keeps updating" per INV-CDLM-6 (CDLM-02/06/07/09).
- [ ] Meeting end produces the consolidated transcript and final derived analysis with user notes
  preserved as their own artifact, and known gaps surfaced as needs-attention (CDLM-08).
- [ ] The composed round trip with chaos steps runs on the test channel with receipts on the
  parent issue (CDLM-10).

## Relationship to GitHub issues

- **Parent / validation hub:** [#4383](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4383),
  filed 2026-07-29 with `agent:blocked` — a validation hub, never a pickup issue. It carries the
  live child table and the capability acceptance ledger.
- **Hub children:** CDLM-01 [#4384](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4384)
  (`agent:ready`), CDLM-02 [#4385](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4385),
  CDLM-06 [#4386](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4386),
  CDLM-07 [#4387](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4387),
  CDLM-08 [#4388](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4388),
  CDLM-10 [#4389](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4389).
- **Bifrost children:** CDLM-03 [bifrost#57](https://github.com/RasmusTho/bifrost/issues/57),
  CDLM-04 [bifrost#58](https://github.com/RasmusTho/bifrost/issues/58),
  CDLM-05 [bifrost#59](https://github.com/RasmusTho/bifrost/issues/59),
  CDLM-09 [bifrost#60](https://github.com/RasmusTho/bifrost/issues/60) (same repo split as B3).
  Every child except CDLM-01 is `agent:blocked` on its named prerequisite's acceptance receipt.
- **Adjacent, not owned here:** #4362 (capture-watch env delivery bug) and #4369 (locate the
  legacy recording path — owner-gated) repair the Model-1 floor; #3026/B3 remains the audio
  floor's validation hub.

## Verification path

Hub tasks verify with pytest targets named per AC (new test files are spec-level commitments);
enforcement ACs assert the guard at its production call site. Bifrost tasks verify with
XCTest/XCUITest targets in bifrost CI, which runs the `Yggdrasil` scheme explicitly on both an
iPhone and an iPad destination and is proven fail-closed (see the retired-gate note below).
CDLM-10's test-channel run follows `docs/RELEASE_CHANNELS/DEFINE_CHANNEL_IDENTITY.md` and posts
its receipts on the parent issue.

## Evidence surface

Validation receipts accumulate as comments on the parent feature issue. Owner-doc promotion
(client contract media lane, ARCHITECTURE/STATUS claims) happens once, at acceptance, per
`.codex/skills/feature-breakdown/SKILL.md` — not per child merge.
