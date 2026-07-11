from __future__ import annotations

import secrets

import pytest

from app.heimdal.capture_adapter import register_sensor
from app.heimdal.consent_ledger import grant_consent, reset_memory_consent_ledger
from app.heimdal.raw_store import all_raw_records, reset_memory_raw_store
from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE, ingest_screen_bundle

pytestmark = pytest.mark.not_pg
_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_raw_store(); reset_memory_consent_ledger()
    register_sensor("screen-test", "v1")
    grant_consent(grant_ref="screen-test-grant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")


def bundle(shape: str = "raw_capture_bundle") -> dict:
    return {"bundle_shape": shape, "sensor": {"adapter": "screen-test", "version": "v1", "machine": "mac-1"}, "raw": {"frame": "redacted"}}


def test_endpoint_admits_only_via_consent_gate_and_registered_sensor():
    ack = ingest_screen_bundle(bundle(), key=_KEY)
    assert ack.created and ack.record_id
    bad = bundle(); bad["sensor"] = {"adapter": "unknown", "version": "v1", "machine": "mac-1"}
    with pytest.raises(RuntimeError): ingest_screen_bundle(bad, key=_KEY)


def test_frame_bundle_lands_encrypted_idempotent():
    first = ingest_screen_bundle(bundle(), key=_KEY); second = ingest_screen_bundle(bundle(), key=_KEY)
    assert first.created and not second.created and len(all_raw_records()) == 1
    assert all_raw_records()[0].ciphertext != b'{"frame":"redacted"}'


def test_both_bundle_shapes_accepted():
    assert ingest_screen_bundle(bundle(), key=_KEY).bundle_shape == "raw_capture_bundle"
    derived = bundle("derived_observation")
    # Contract-level future shape: the endpoint accepts and lands it even before SCREEN-02 owns production derivation.
    assert ingest_screen_bundle(derived, key=_KEY).bundle_shape == "derived_observation"
