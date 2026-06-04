"""Production resurfacing bundle consumption tests (#1563)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.app import app
from app.context_bundles.schema import (
    AuthorityFlags,
    BundleScope,
    BundleTrigger,
    ContextBundle,
    ExpiryPosture,
)


def test_resurfacing_path_suggestion_only():
    client = TestClient(app)
    resp = client.get("/api/resurfacing/bundle/rb-1")
    assert resp.status_code == 200
    body = resp.json()

    assert body["bundle_id"] == "rb-1"
    assert body["suggestion_only"] is True
    assert body["may_write"] is False
    # Auditable why-now: a human-readable rationale anchored to a named signal.
    assert body["why_now"].strip()
    assert body["why_now_signal_name"].strip()


def test_rejects_bundle_not_scoped_for_resurface(monkeypatch):
    import app.api.routes.resurfacing as rr

    def _mis_scoped(bundle_id: str) -> ContextBundle:
        # Scoped for answering only — not for resurfacing.
        return ContextBundle(
            id=bundle_id,
            created_at=datetime.now(tz=timezone.utc),
            trigger=BundleTrigger(type="retrieval"),
            intended_use=["answer"],
            scope=BundleScope(),
            included=[],
            excluded=[],
            authority=AuthorityFlags(may_answer=True, may_resurface=False, may_write=False),
            expiry=ExpiryPosture(),
        )

    monkeypatch.setattr(rr, "_resurfacing_bundle_source", _mis_scoped)

    client = TestClient(app)
    resp = client.get("/api/resurfacing/bundle/rb-bad")
    assert resp.status_code == 409
