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

## Retention posture

Pixels are never published. `_heimdal/settings.md` owns the required,
fail-loud `screen_frame_retention_minutes` bound. SCREEN-02 enforces the
derive-and-discard lifecycle through the existing governed raw-store deletion
and receipt seams; no client or endpoint may create a parallel frame store.
