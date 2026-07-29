State: Filed 2026-07-29 as live parent validation hub [#4383](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4383) (`agent:blocked`). GitHub issue #4383 is now the authoritative backlog and validation surface; this file records the authored contract, and the live issue body carries the child table with filed numbers.
Doc role: Parent feature issue contract (feature-breakdown lane)

# Parent feature issue — Cross-Device Capture & Live Meeting

Title: `feature: durable cross-device capture ingress + live meeting analysis (CDLM)`

Labels at filing: `type:feature`, `prio:high`, `agent:blocked` (validation hub — never a direct
pickup issue).

Body:

---

## Context

The owner's 2026-07-29 product priority makes cross-device capture the first Bifrost product
vertical: capture audio, photos, video, receipts, and documents on Apple Watch, iPhone, and iPad;
transfer them to the hub with durable-acceptance receipts; and run live meeting capture with a
revisable analysis surface on iPad. The delivered substrate is placement-gated (B3 Model 1) and
proved lossy-in-practice during the 2026-07-29 prod bring-up (#4369, #4362). The governing
specification is `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/` (README + ten task specs); this
issue is the validation hub for its delivery.

## Scope

The capability outcome (not one PR): governed media ingress with durable receipts; receipt-gated
client retention with an idempotent transfer outbox; multi-modality capture on iPhone/iPad; the
five-state iPad transfer queue; meeting session/segment ledger with gap reconciliation; revisable
transcript + generic-default-template analysis projections; fail-closed meeting block ownership
(`user_note` vs `derived_projection`); finalization into Sources-zone artifacts with verbatim
user-note preservation; and a composed test-channel proof with reconnect chaos.

## Source Anchors

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope`
- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md :: 9. Runtime gaps — feature-breakdown inputs (deferred, not solved here)`

## SBS Impact

- Primary subsystem: Heimdal ingestion seam + Mimer meeting cognition (Product/Runtime)
- Secondary subsystem(s): Bifrost constituent surfaces; PDM persistence; OEF outbox
- Write class: authority-bearing (raw admission, session ledger, block guard, Sources-zone
  materialization) delivered across child slices
- Persistence impact: durable (raw store, ledger, projections, receipts, vault artifacts)
- Derived/rebuildable impact: transcript/analysis projections are rebuildable from admitted
  segments; never canonical
- New or changed contract: media ingress + receipts lane extending the Mimer client contract;
  meeting session/projection/user-note surfaces; block-ownership model
- Owner-doc impact: follow-up at acceptance (client contract media lane, ARCHITECTURE/STATUS) —
  one promotion PR at parent closure, not per child
- Transition debt impact: supersedes placement-gated deletion (HCAP-03 lane) with receipt-gated
  retention; legacy lane retained and stated honestly
- Boundary risk: derived writers must never gain write access to `user_note` content; iPad must
  never become a merge executor; no person inference from voice/face/diarization in this vertical

## Constraints

- ADR-0049 §3 (hub-side ASR; client ships bytes), ADR-0060 defaults (third-party speech withheld;
  no voiceprint work here), ADR-0055/0056 + `MIMER_CLIENT_CONTRACT` (transports, Sources zone,
  writer discipline), entity-review journal authority boundary (Hub-only merges).
- No public ingress (R-EXTERNAL stays owner-reserved). Watch remains a relay (INV-B3-5).
- INV-CDLM-1..9 (README) bind every child slice.

## Acceptance Criteria

- [ ] Multi-modality capture round trip with receipt-gated retention proven, kill/relaunch-safe,
  duplicate-free. Verify: CDLM-10 stage 1–3 receipt on this issue.
- [ ] iPad queue shows the five states truthfully across restart/reconnect. Verify: bifrost
  `Yggdrasil/YggdrasilUITests/TransferQueueJourneyTests.swift::testOfflineToCompleteJourney` green
  + CDLM-10 receipt.
- [ ] Live meeting with reconnect reconciliation and the user-note/derived separation holds
  end-to-end. Verify: CDLM-10 stage 4 receipt (user-note hash comparison inline).
- [ ] Finalization produces the three separated artifacts with gap legibility. Verify: CDLM-10
  stage 5 receipt + `tests/heimdal/test_meeting_finalization.py` suite green on the delivering
  head.
- [ ] Every child slice delivered per its own ACs with receipts recorded here. Verify: per-child
  validation receipt comments on this issue.

## Out of Scope

Rich meeting templates; participant/owner inference; voiceprint attribution (ADR-0060 gates);
share-sheet ingestion; push transport; prod-channel activation (release-channel workflows own
promotion); physical-device walkthrough truths (bifrost#21, unblocked after CDLM-10).

## Suggested Validation

Per-child: the task spec's `How to Verify (Pre-Merge)` commands. Capability-level: the CDLM-10
proof run on the test channel with its receipt posted here.

## Source Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/HEIMDAL/CAPTURE_TRANSPORT_FEASIBILITY.md`
- `docs/adr/ADR-0060-capture-posture-b-full-voice-identity.md`

## Implementation Tasks

Specification directory: `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/` — intended order:

1. CDLM-01 `ADMIT_MEDIA_WITH_DURABLE_RECEIPTS` (hub) — the only initially `agent:ready` child
2. CDLM-02 `TRACK_MEETING_SESSIONS_AND_SEGMENT_GAPS` (hub) ∥ CDLM-03
3. CDLM-03 `RETAIN_ORIGINALS_UNTIL_BACKEND_RECEIPT` (bifrost) ∥ CDLM-02
4. CDLM-04 `CAPTURE_PHOTOS_DOCUMENTS_AND_VIDEO` (bifrost) ∥ CDLM-05/06
5. CDLM-05 `SHOW_DURABLE_TRANSFER_QUEUE_ON_IPAD` (bifrost) ∥ CDLM-04/06
6. CDLM-06 `PROJECT_LIVE_TRANSCRIPT_AND_DEFAULT_ANALYSIS` (hub)
7. CDLM-07 `ENFORCE_MEETING_BLOCK_OWNERSHIP` (hub)
8. CDLM-08 `CONSOLIDATE_MEETING_ON_END` (hub) ∥ CDLM-09
9. CDLM-09 `RUN_LIVE_MEETING_ON_IPAD` (bifrost)
10. CDLM-10 `PROVE_CROSS_DEVICE_ROUND_TRIP_WITH_RECONNECT` (hub; carries the parent-closure
    handoff)

## Verification Path

Hub children: named pytest targets per AC (enforcement ACs at production call sites); `Unit tests
(not pg)` green on each delivering head. Bifrost children: named XCTest/XCUITest targets under
**execution gate G-CI** — bifrost#52 fixed, or local `xcodebuild test` evidence attached to the
child PR. Composed: the CDLM-10 test-channel run.

## Validation / Acceptance Path

Each child merge posts a validation receipt comment here (delivering PR, head SHA, Verify-target
results). CDLM-10's run report is the capability-level receipt. When all ACs above are checked
with receipts, close this issue and open the single owner-doc promotion PR (client contract media
lane + ARCHITECTURE/STATUS wording). Until then, owner docs continue to claim nothing from this
vertical.

---

## Relationship to child issues (recorded at filing, 2026-07-29)

| Order | ID | Issue | Initial label |
| --- | --- | --- | --- |
| 1 | CDLM-01 | hub [#4384](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4384) | `agent:ready` |
| 2 | CDLM-02 | hub [#4385](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4385) | `agent:blocked` |
| 3 | CDLM-03 | [bifrost#57](https://github.com/RasmusTho/bifrost/issues/57) | `agent:blocked` |
| 4 | CDLM-04 | [bifrost#58](https://github.com/RasmusTho/bifrost/issues/58) | `agent:blocked` |
| 5 | CDLM-05 | [bifrost#59](https://github.com/RasmusTho/bifrost/issues/59) | `agent:blocked` |
| 6 | CDLM-06 | hub [#4386](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4386) | `agent:blocked` |
| 7 | CDLM-07 | hub [#4387](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4387) | `agent:blocked` |
| 8 | CDLM-08 | hub [#4388](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4388) | `agent:blocked` |
| 9 | CDLM-09 | [bifrost#60](https://github.com/RasmusTho/bifrost/issues/60) | `agent:blocked` |
| 10 | CDLM-10 | hub [#4389](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4389) | `agent:blocked` |

The parent (#4383) is `agent:blocked` as a validation hub, never a pickup issue. Only CDLM-01 was
filed `agent:ready`, after strict readiness validation passed on its body
(`scripts/validate_issue_readiness.py` → `ready_candidate`; `scripts/validate_source_anchors.py`
→ pass). Every other child is `agent:blocked` on its named prerequisite's acceptance receipt.
