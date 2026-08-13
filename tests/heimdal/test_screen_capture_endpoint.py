from __future__ import annotations

import secrets

import pytest
from fastapi import HTTPException

from app.heimdal.capture_adapter import register_sensor
from app.heimdal.consent_ledger import (
    ConsentRefusedError,
    MEDIA_CAPTURE_SCOPE,
    SELF_RECORD_SCOPE,
    grant_consent,
    reset_memory_consent_ledger,
)
from app.heimdal.observation_log import count_observations, reset_memory_observation_log
from app.heimdal.raw_store import (
    all_raw_records,
    all_raw_representations,
    reset_memory_raw_store,
)
from app.heimdal import screen_capture
from app.heimdal.screen_capture import SCREEN_CAPTURE_SCOPE, ingest_screen_bundle

pytestmark = pytest.mark.not_pg
_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def reset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _KEY.hex())
    reset_memory_raw_store(); reset_memory_consent_ledger(); reset_memory_observation_log()
    register_sensor("screen-test", "v1")
    grant_consent(grant_ref="screen-test-grant", scope=SCREEN_CAPTURE_SCOPE, basis="screen_always_on", granted_by="operator")


def bundle(shape: str = "raw_capture_bundle") -> dict:
    return {"bundle_shape": shape, "sensor": {"adapter": "screen-test", "version": "v1", "machine": "mac-1"}, "raw": {"frame": "redacted"}}


def test_endpoint_admits_only_via_consent_gate_and_registered_sensor(monkeypatch: pytest.MonkeyPatch):
    """The production endpoint cannot reach the raw store before both guards."""
    from app.api.routes.heimdal_screen import capture_screen_bundle

    calls: list[str] = []
    registered = screen_capture._assert_sensor_registered
    admit = screen_capture.admit_raw_evidence
    raw_write = screen_capture.raw_store.insert_raw_record

    def assert_registered(sensor):
        calls.append("registered-sensor")
        return registered(sensor)

    def admit_raw_evidence(*, scope: str):
        calls.append("consent-admission")
        return admit(scope=scope)

    def insert_raw_record(**kwargs):
        calls.append("raw-write")
        assert calls[:-1] == ["registered-sensor", "consent-admission"]
        return raw_write(**kwargs)

    monkeypatch.setattr(screen_capture, "_assert_sensor_registered", assert_registered)
    monkeypatch.setattr(screen_capture, "admit_raw_evidence", admit_raw_evidence)
    monkeypatch.setattr(screen_capture.raw_store, "insert_raw_record", insert_raw_record)

    ack = capture_screen_bundle(bundle())
    assert ack["created"] and ack["record_id"]
    assert calls == ["registered-sensor", "consent-admission", "raw-write"]
    bad = bundle(); bad["sensor"] = {"adapter": "unknown", "version": "v1", "machine": "mac-1"}
    with pytest.raises(RuntimeError): ingest_screen_bundle(bad, key=_KEY)


def test_frame_bundle_lands_encrypted_idempotent():
    first = ingest_screen_bundle(bundle(), key=_KEY); second = ingest_screen_bundle(bundle(), key=_KEY)
    assert first.created and not second.created and len(all_raw_records()) == 1
    assert all_raw_records()[0].ciphertext != b'{"frame":"redacted"}'
    assert first.record_id is not None
    representations = all_raw_representations(first.record_id)
    assert len(representations) == 1 and representations[0].active


def test_both_bundle_shapes_accepted():
    assert ingest_screen_bundle(bundle(), key=_KEY).bundle_shape == "raw_capture_bundle"
    derived = bundle("derived_observation")
    derived["derived_observation"] = {
        "observation_id": "screen-derived-1", "episode_id": "screen-session-1",
        "observed_at_start": "2026-07-11T08:00:00Z", "observed_at_end": "2026-07-11T08:01:00Z",
        "attributions": [{"mention_id": "operator", "role": "recorder", "resolution": "resolved", "basis": "capture_context"}],
        "modality": "screen", "content": "Editing a note",
        "confidence": {"attribution": {"score": 1.0, "calibration": "by_construction"}},
        "provenance": {}, "sensitivity": "private", "consent": {"basis": "untrusted-client-claim"},
    }
    ack = ingest_screen_bundle(derived, key=_KEY)
    assert ack.bundle_shape == "derived_observation"
    assert ack.observation_published
    assert count_observations() == 1
    with pytest.raises(ValueError, match="derived_observation mapping"):
        ingest_screen_bundle(bundle("derived_observation"), key=_KEY)
    derived["derived_observation"]["modality"] = "speech"
    with pytest.raises(ValueError, match="modality must be screen"):
        ingest_screen_bundle(derived, key=_KEY)


def test_client_supplied_scope_cannot_select_another_lanes_grant():
    """A screen client naming another lane's standing scope must not be admitted under it.

    `reset_memory_consent_ledger` (invoked by the autouse fixture before this
    test's own reset below) seeds the standing `SELF_RECORD_SCOPE` and
    `MEDIA_CAPTURE_SCOPE` grants active by default -- the same two scopes the
    Issue reproduces the defect against. This test drives the production
    route so it also proves the route does not forward a client-controlled
    `scope` field.
    """
    from app.api.routes.heimdal_screen import capture_screen_bundle

    # Start from a ledger with no screen_always_on grant, but with the two
    # other lanes' standing grants still seeded and active.
    reset_memory_consent_ledger()
    register_sensor("screen-test", "v1")

    for foreign_scope in (SELF_RECORD_SCOPE, MEDIA_CAPTURE_SCOPE):
        before = len(all_raw_records())
        payload = bundle()
        payload["scope"] = foreign_scope
        with pytest.raises(HTTPException) as excinfo:
            capture_screen_bundle(payload)
        assert excinfo.value.status_code == 400
        assert len(all_raw_records()) == before
    assert count_observations() == 0


def test_screen_bundle_admits_under_the_screen_grant():
    """With an active screen_always_on grant, a normal bundle admits and is
    stamped with that grant -- not a foreign one, even if named."""
    from app.api.routes.heimdal_screen import capture_screen_bundle

    payload = bundle()
    payload["scope"] = MEDIA_CAPTURE_SCOPE  # a client-named foreign scope must be ignored
    ack = capture_screen_bundle(payload)
    assert ack["created"] and ack["record_id"]
    records = all_raw_records()
    assert len(records) == 1
    assert records[0].consent["grant_ref"] == "screen-test-grant"


def test_screen_capture_refused_without_a_screen_grant():
    """With no screen_always_on grant, a default-scope bundle is still refused."""
    reset_memory_consent_ledger()
    register_sensor("screen-test", "v1")

    with pytest.raises(ConsentRefusedError):
        ingest_screen_bundle(bundle(), key=_KEY)
    assert len(all_raw_records()) == 0
