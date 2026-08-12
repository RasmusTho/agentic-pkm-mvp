"""Screen-capture ingress seam (SCREEN-01).

This module deliberately contains admission and durable landing only.  It
does not derive pixels into observations (SCREEN-02) or implement a client
(SCREEN-03).  Both accepted wire shapes therefore retain one stable contract.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from app.heimdal import raw_store
from app.heimdal.capture_adapter import SensorIdentity, _assert_sensor_registered
from app.heimdal.consent_ledger import admit_raw_evidence
from app.heimdal.publish import publish_full_observation

SCREEN_CAPTURE_SCOPE = "screen_always_on"
RAW_CAPTURE_BUNDLE = "raw_capture_bundle"
DERIVED_OBSERVATION = "derived_observation"


@dataclass(frozen=True)
class ScreenCaptureAck:
    record_id: str | None
    content_identity: str
    created: bool
    bundle_shape: str
    observation_published: bool = False


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def ingest_screen_bundle(bundle: Mapping[str, Any], *, key: bytes | None = None) -> ScreenCaptureAck:
    """Admit, encrypt, and land one client bundle through the shared Heimdal seams.

    Sensor registration and consent admission occur before encryption or raw
    write.  A derived observation is published only after that same admission;
    its optional raw payload is still landed so the opaque raw_ref remains a
    governed reference, not a client-side escape hatch.
    """
    shape = bundle.get("bundle_shape")
    if shape not in {RAW_CAPTURE_BUNDLE, DERIVED_OBSERVATION}:
        raise ValueError("bundle_shape must be raw_capture_bundle or derived_observation")
    derived_payload = bundle.get("derived_observation")
    if shape == DERIVED_OBSERVATION:
        if not isinstance(derived_payload, Mapping):
            raise ValueError("derived_observation bundles require a derived_observation mapping")
        if derived_payload.get("modality") != "screen":
            raise ValueError("derived_observation modality must be screen")
    sensor_data = bundle.get("sensor")
    if not isinstance(sensor_data, Mapping):
        raise ValueError("screen bundle requires sensor {adapter, version, machine}")
    sensor = SensorIdentity(
        adapter=str(sensor_data.get("adapter", "")),
        version=str(sensor_data.get("version", "")),
        device=str(sensor_data.get("machine", "")),
    )
    _assert_sensor_registered(sensor)
    # The admitting scope is always the screen lane's own scope, never a
    # value read from the client-supplied bundle: a screen client must not
    # be able to name another lane's standing grant to admit its capture.
    admitted = admit_raw_evidence(scope=SCREEN_CAPTURE_SCOPE)

    raw_payload = bundle.get("raw")
    if raw_payload is None:
        raw_payload = {k: v for k, v in bundle.items() if k != "derived_observation"}
    if isinstance(raw_payload, str):
        plaintext = raw_payload.encode("utf-8")
    elif isinstance(raw_payload, bytes):
        plaintext = raw_payload
    elif isinstance(raw_payload, Mapping):
        plaintext = _canonical_bytes(raw_payload)
    else:
        raise ValueError("raw must be bytes, text, or an object")
    identity = hashlib.sha256(plaintext).hexdigest()
    encryption_key = key if key is not None else raw_store.resolve_raw_store_key()
    ciphertext, nonce = raw_store.encrypt_raw_bytes(plaintext, key=encryption_key)
    record, created = raw_store.insert_raw_record(
        content_identity=identity,
        capture_chain=list(bundle.get("capture_chain") or ["screen_capture_post"]),
        sensor={"adapter": sensor.adapter, "version": sensor.version, "machine": sensor.device},
        consent=admitted.consent.as_dict(),
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="v1-process-key",
        key=encryption_key,
        source_path="screen-capture-endpoint",
        payload={"modality": "screen", "bundle_shape": shape},
    )
    published = False
    if shape == DERIVED_OBSERVATION:
        # The declared on-device path is still admitted through the same
        # guards, then handed directly to the canonical validated publish
        # seam.  It is not a second raw-store or observation writer.
        assert isinstance(derived_payload, Mapping)  # guaranteed by the shape guard above
        payload = dict(derived_payload)
        provenance = dict(payload.get("provenance") or {})
        provenance.setdefault("content_identity", identity)
        provenance.setdefault("capture_chain", list(bundle.get("capture_chain") or ["screen_capture_post"]))
        provenance.setdefault("sensor", {"adapter": sensor.adapter, "version": sensor.version, "machine": sensor.device})
        payload["provenance"] = provenance
        payload.setdefault("raw_ref", record.id)
        # The published observation carries the admission that this endpoint
        # actually obtained, never a client-supplied claim about consent.
        payload["consent"] = admitted.consent.as_dict()
        publish_full_observation(topic="heimdal.observation.published", payload=payload, source="heimdal.screen_capture")
        published = True
    return ScreenCaptureAck(record.id, identity, created, shape, published)
