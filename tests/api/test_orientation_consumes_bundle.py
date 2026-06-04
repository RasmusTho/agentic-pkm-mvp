"""Production orientation bundle consumption tests (#1563)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app


def test_orientation_path_consumes_bundle():
    client = TestClient(app)
    resp = client.get("/api/orientation/bundle/ob-1")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bundle_id"] == "ob-1"
    # Exclusions are surfaced for review (part of provenance).
    assert isinstance(body["exclusions"], list)
    assert body["exclusions"], "exclusions must be preserved in the orientation frame"

    # Included items are projected into the frame buckets, with provenance kept.
    segments = body["facts"] + body["inferences"] + body["candidate_actions"]
    assert segments, "bundle included items must be projected into the frame"
    assert any(seg.get("provenance") for seg in segments), "per-item provenance must be preserved"


def test_orientation_path_non_write_authoritative():
    client = TestClient(app)
    body = client.get("/api/orientation/bundle/ob-2").json()
    assert body["may_write"] is False
    assert body["read_only"] is True
