State: Host-side ingress and governed-control contract. SCREEN-06 implements the host control boundary; native-client and live capability acceptance remain open in Bifrost #72 and #3340.

# Heimdal Screen Client Contract

The client posts `POST /api/heimdal/screen/capture`. It is a Heimdal ingress
seam, not a new store or server. Every request supplies a registered sensor
`{adapter, version, machine}`, `scope: screen_always_on`, a capture chain, and
one of `raw_capture_bundle` or `derived_observation`.

## Observation schema

Screen observations use `heimdal.observation.published.v1` with `modality:
screen`. They require a non-empty `observed_at_end`; `provenance.sensor` is an
object carrying adapter, version, and stable work-machine identity. Content is
the minimized textual activity summary, never pixels. The normal field
families remain mandatory: identity, bitemporal time, operator attribution,
per-axis confidence, provenance, sensitivity, and a `screen_always_on`
consent block. `raw_ref` is an opaque, gated raw-store handle.

## Ingestion endpoint obligations

Before it reads or writes a bundle, the host verifies the registered sensor
and calls `consent_ledger.admit_raw_evidence`. It encrypts the raw bundle and
lands it in `heimdal_raw_record`, idempotently by `content_identity`, then
returns an acknowledgement containing the durable record identity. A client
may remove its offline-buffer entry only after that acknowledgement.

`raw_capture_bundle` is the default and stops at the host derivation seam.
`derived_observation` is the contract-held future on-device path; its supplied
observation is validated/published through the existing Heimdal publish path.

## Governed control boundary

The host exposes authenticated `GET /api/heimdal/screen/control` and
`PUT /api/heimdal/screen/control`. GET accepts optional `app_id` and repeated `scopes` query
parameters. PUT accepts exactly `{"key": "<screen setting>", "value": <typed value>}`;
authentication supplies the actor. Shared-settings role permission, the existing scoped-context
mutation guard, and WriteGuard apply before mutation. The existing Companion settings POST uses
the same server-derived authentication for screen keys.

The vault-shared source is `<vault>/settings/screen_control.md`, with defaults and bounds declared
only in `app/settings/models.py::ScreenControlSettings`. Markdown edits enter through the live
Settings Spine watcher. The returned `controls` come from the accepted runtime-gating projection,
bound to the selected vault ID and local-instance ID. Each effective control change gets one
durable actor-tagged `settings.write.receipt` with `receipt_type=heimdal_screen_control_receipt`;
unchanged writes and watcher replay do not create another receipt.

Pause revokes every active `screen_always_on` grant through the canonical consent ledger before
settings acceptance. That ledger fence denies new raw admission and invokes the existing
grant-linked hot/cold raw-erasure path; published observations are not retracted. An erasure
failure after revocation leaves consent inactive and the control change unaccepted. The durable
revocation row owns recovery; pause retry reconciles screen-scope erasure before accepting the
setting. Other lanes' grants and scheduled all-scope recovery are unchanged. An explicit pause
of an already-paused setting still revokes an active grant, without a duplicate settings receipt.
A later resume setting never re-grants consent; capture remains refused until a separate explicit
grant exists.

`requested_state` is `paused` or `resume_requested`; effective `state` is `paused`, `ready`, or
`degraded`. `settings_state` and `errors` expose invalid or pending sources and loss of receipt
authority. `capture_permitted` is true only for a nonempty queried app ID when accepted controls
request resume, standing consent exists, and neither that app nor its supplied/mapped scopes is
excluded. Invalid or pending settings deny permission even when a last-valid value exists.

The host always returns `capture_state=unknown_external_client`. A resume setting, `ready`, or
`capture_permitted` is not evidence that capture is running. SCREEN-03/Bifrost #72 must consume
these controls, honor pause/exclusions before capture/buffering/shipping, default to paused on
ambiguous restart, and render its actual loop state. #3341 and parent #3340 retain that acceptance.
The client cadence/buffer and reserved coalescing settings are described in
`docs/HEIMDAL_SCREEN_STREAM/README.md :: Provisional constants`; their declaration alone does not
implement those consumers.

## Retention posture

Pixels are never published. The accepted Settings Spine projection of
`settings/screen_control.md` owns `screen_frame_retention_minutes`. Invalid replacement values
retain a proven last-valid bound; absent valid authority fails loudly before cleanup. Existing
SCREEN-01 `_heimdal/settings.md` policies require an explicit canonical selection and old-value
receipt before activation; the legacy source is retained only as migration evidence. SCREEN-02
enforces the derive-and-discard lifecycle through the existing governed raw-store deletion and
receipt seams; no client or endpoint may create a parallel frame store.
