"""Route-layer tests for the read-only Context Bundle construction route (#1560).

These cover the production route contract that returns an inspectable
``ContextBundle`` envelope, before real-vault emission lands (#1562).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.app import app
from app.context_bundles.construction import build_inspectable_bundle


def test_route_returns_inspectable_bundle_envelope():
    client = TestClient(app)
    resp = client.get("/api/context-bundles/cb-test-1")
    assert resp.status_code == 200
    body = resp.json()

    # Self-describing envelope: identity plus the contract-required fields.
    assert body["id"] == "cb-test-1"
    assert "authority" in body
    assert "included" in body
    assert "excluded" in body

    # Exclusions are surfaced (exclusion tracking is part of provenance).
    assert isinstance(body["excluded"], list)
    assert body["excluded"], "envelope must surface at least one exclusion"

    # Authority flags are all present and inspectable.
    for flag in ("may_answer", "may_orient", "may_resurface", "may_propose", "may_write"):
        assert flag in body["authority"]


def test_bundle_route_is_read_only():
    client = TestClient(app)

    # GET is the only verb the route exposes.
    assert client.get("/api/context-bundles/cb-ro").status_code == 200
    assert client.post("/api/context-bundles/cb-ro").status_code == 405
    assert client.put("/api/context-bundles/cb-ro").status_code == 405
    assert client.delete("/api/context-bundles/cb-ro").status_code == 405

    # Repeated reads are identical apart from the volatile creation timestamp,
    # which demonstrates the route performs no state/vault mutation.
    first = client.get("/api/context-bundles/cb-ro").json()
    second = client.get("/api/context-bundles/cb-ro").json()
    first.pop("created_at", None)
    second.pop("created_at", None)
    assert first == second


def test_route_does_not_upgrade_authority():
    client = TestClient(app)
    body = client.get("/api/context-bundles/cb-auth").json()

    # may_write must never be defaulted or upgraded to true on this read-only route.
    assert body["authority"]["may_write"] is False

    # Authority flags are surfaced verbatim from the construction layer; the
    # route does not upgrade any flag in transit.
    constructed = build_inspectable_bundle("cb-auth")
    assert body["authority"] == constructed.authority.model_dump()


def test_route_registered_via_seam():
    # The route is registered through the seam in app/api/app.py without an
    # import-time failure (the seam variable resolves to a real router).
    from app.api import app as app_module

    assert app_module.context_bundles_router is not None

    paths = {route.path for route in app.routes}
    assert "/api/context-bundles/{bundle_id}" in paths
