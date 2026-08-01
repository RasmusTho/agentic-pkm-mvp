---
name: Admit Media With Durable Receipts
description: Governed hub media ingress that admits capture bytes idempotently and acknowledges only durable acceptance, with queryable receipts.
task_id: CDLM-01
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4384"
source_anchor: docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md :: Fixed scope
parent_capability: Cross-Device Capture & Live Meeting
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Admit Media With Durable Receipts

State: Delivered by hub issue #4384 (2026-07-30). `POST /api/heimdal/capture/media` and
`GET /api/heimdal/capture/receipts` are implemented in `app/api/routes/heimdal_capture.py` over
`app/heimdal/media_ingress.py` + `app/heimdal/media_receipts.py`, with the six acceptance criteria
below proven by `tests/heimdal/test_media_ingress.py`; the event contract is recorded in
`docs/EVENTS.md :: Heimdal governed media ingress + durable receipts`.

Two things were deliberately **not** claimed by this slice. First, the api process needs
`HEIMDAL_RAW_STORE_KEY` to encrypt into the raw store, and at this slice's merge the host secret
contract declared that secret for the `heimdal-capture-watch` consumer only, so admission returned a
named 500 `raw_store_key_unavailable` / `not_acknowledged` rather than a receipt (the pre-existing
`POST /api/heimdal/screen/capture` shared that gap). **That gap is now closed:** #4422 declared the
api process as the `heimdal-api-ingress` consumer, wired the governed deploy wrapper and the `api`
Compose service to deliver the key, and added an api startup preflight that reports both ingress
lanes `unavailable` on `/api/status` before first use. Placing key material into each channel's
Keychain item remains an operator step — see `docs/STATUS.md :: Runtime verification`. Second, the
parent-acceptance promotion of this lane into `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4.4 landed
in PR #4531 / merge `0fadbe5af4a91ee1b36344264c4b43cf66135f89`.

## Purpose

Give every capture client one governed answer to "is my original durably accepted?". Today that
question is unanswerable: audio ingress is filesystem-only, placement is mistaken for delivery,
and #4369 shows what that costs — recordings that "should have landed" with an empty capture tree
and no way to know.

## What This Task Does

Adds the governed media ingress lane to the hub API and makes its receipt the single definition of
durable acceptance:

- **Endpoint:** `POST /api/heimdal/capture/media` (LAN/loopback/tailnet posture per
  `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4; no public ingress). Multipart request: one `media`
  part (bytes) plus one `sidecar` JSON part carrying at minimum
  `{capture_id (client-minted UUID), content_sha256, kind ∈ {audio, image, video, document},
  captured_at, device_id, schema_version}` and optional session fields consumed by CDLM-02
  (`session_id`, `session_seq`). The sidecar composes with, and does not fork, the HCAP-07
  capture-time metadata sidecar schema.
- **Admission:** verifies `content_sha256` against the received bytes, then admits into the
  existing encrypted raw store through the same idempotent content-hash seam the capture watcher
  uses (`app/heimdal/capture_adapter.py` family). One object per content hash; a re-send of the
  same `(capture_id, content_sha256)` re-admits nothing and returns the same receipt identity.
- **Ack ordering (the load-bearing rule):** the 2xx response exists only after (1) the raw-store
  write is durable and (2) the admission outbox event (`heimdal.capture.media.admitted`, carrying
  `capture_id`, `content_sha256`, raw ref, `kind`, trace id) is committed — the same
  outbox-before-ack ordering the governed text capture already enforces. Failure of either leaves
  no acknowledged state.
- **Receipt body:** `{outcome: "admitted", capture_id, content_sha256, receipt_id, raw_ref,
  admitted_at, trace_id}` plus `idempotent_replay: true` when the pair was already admitted.
- **Receipt query:** `GET /api/heimdal/capture/receipts?capture_id=…` (repeatable parameter,
  bounded batch) returns each id's receipt or `unknown` — the client's reconnect/recovery answer
  after a lost response, per INV-CDLM-3.
- **Named error states,** never blind-retryable: schema violation and hash mismatch (422),
  unsupported kind (415), oversize per configured per-kind caps (413), raw-store or event-commit
  failure (500, nothing acknowledged).
- **Legacy lane convergence:** watched-folder admissions flow through the same admission seam and
  also produce receipts (keyed by content hash; `capture_id` when a sidecar carries one), so
  Model-1 files are queryable — while the retention guarantee remains an outbox-lane property
  (README partial-failure matrix, last row).

## Concretely

```bash
curl -s -X POST http://hub.local/api/heimdal/capture/media \
  -H 'x-trace-id: t-123' \
  -F media=@segment-000.m4a \
  -F 'sidecar={"capture_id":"9f7c…","content_sha256":"ab12…","kind":"audio","captured_at":"2026-07-29T12:00:00Z","device_id":"ipad-1","schema_version":1};type=application/json'
# → 200 {"outcome":"admitted","capture_id":"9f7c…","receipt_id":"rcp_…","raw_ref":"heimraw:…","admitted_at":"…","trace_id":"t-123"}
# re-run the identical command
# → 200 {…,"idempotent_replay":true}   # same receipt_id, raw store unchanged

curl -s 'http://hub.local/api/heimdal/capture/receipts?capture_id=9f7c…'
# → {"receipts":[{"capture_id":"9f7c…","outcome":"admitted","receipt_id":"rcp_…",…}]}
```

## Why This Matters

Every other task in this vertical stands on this receipt. If acknowledgement can precede
durability, CDLM-03's receipt-gated deletion destroys originals; if admission is not idempotent,
CDLM-02's ledger and CDLM-06's projections double-count segments; if receipts are not queryable,
reconnect recovery cannot distinguish "lost response" from "never arrived" and must guess — the
exact guessing that lost the #4369 recordings.

## Acceptance Criteria

- [x] A successful admission returns the receipt only after the raw object is durably written and
  the admission event is committed; a forced event-commit failure yields a 500 with no acknowledged
  state and no orphaned acknowledged artifacts.
  - Verify: `tests/heimdal/test_media_ingress.py::test_ack_requires_raw_write_and_committed_event`
    (enforcement: asserts the ordering on the production route path by fault-injecting the event
    commit, not by unit-testing a helper in isolation).
- [x] Re-posting the same `(capture_id, content_sha256)` after a simulated lost response returns
  the same `receipt_id`, leaves exactly one raw object, and emits no second admission event.
  - Verify: `tests/heimdal/test_media_ingress.py::test_resend_is_idempotent_end_to_end`
- [x] Each media kind admits within its configured cap and lands in the raw store with lineage
  metadata; hash mismatch, unsupported kind, and oversize input return their named errors with
  nothing admitted.
  - Verify: `tests/heimdal/test_media_ingress.py::test_kind_caps_and_named_error_states`
- [x] The receipt query returns `admitted` for admitted ids and `unknown` for never-seen ids,
  through the production route.
  - Verify: `tests/heimdal/test_media_ingress.py::test_receipt_query_answers_recovery`
- [x] A watched-folder admission produces a queryable receipt through the same seam (content-hash
  keyed; `capture_id` when the sidecar supplies one).
  - Verify: `tests/heimdal/test_media_ingress.py::test_watched_folder_admission_shares_receipt_seam`
- [x] The endpoint refuses operation on a non-loopback/LAN/tailnet binding consistent with the
  client contract's v1 posture.
  - Verify: `tests/heimdal/test_media_ingress.py::test_ingress_refuses_public_binding`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -p pytest_asyncio.plugin -q tests/heimdal/test_media_ingress.py`
  runs every behavioral AC above, including the fault-injection ordering test.
- `ruff check app tests` per the repo lint gate; `python -m app.cli settings-validate --json` if
  new settings keys (per-kind caps) are introduced.
- CI: `Unit tests (not pg)` green on the head SHA; the PR body records the commands and output.

## Out of Scope

- Session/segment ledger semantics and gap detection (CDLM-02) — this task stores the session
  sidecar fields opaquely alongside the admission when present.
- Any client-side behavior (CDLM-03/04/05/09).
- ASR, analysis, or any derivation (CDLM-06).
- Streaming/chunked transfer, resumable uploads, auth keys (client-contract F2), or public
  ingress (R-EXTERNAL, owner-reserved).
- Removing or changing the watched-folder watcher (#4362 owns its env-delivery bug).

## Related Docs

- `docs/CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/README.md` (INV-CDLM-1/3; partial-failure matrix)
- `docs/contracts/MIMER_CLIENT_CONTRACT.md` §4 (governed-write ack ordering precedent; F5 gap)
- `docs/contracts/HEIMDAL_SCREEN_CLIENT_CONTRACT.md` (prior HTTP ingress-seam contract precedent)
- `docs/HEIMDAL_CAPTURE_CLIENT/CAPTURE_TIME_METADATA_SIDECAR.md` (sidecar schema this composes with)

## Related GitHub Issues

One hub issue implements this task ("Implements CROSS_DEVICE_CAPTURE_AND_LIVE_MEETING/ADMIT_MEDIA_WITH_DURABLE_RECEIPTS").
TCD hint for the child issue body: Opus / high — new externally-called API surface with
durability-ordering and idempotency obligations; the ordering test is the hard part.
