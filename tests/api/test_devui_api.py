"""API contract for the read-only devUI composition route (#4682)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.auth as auth_module
from app.api.app import app
from app.api.routes import devui as devui_route


def test_devui_composition_route_is_get_only_and_read_only(monkeypatch) -> None:
    cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {"kind": "counted", "text": "one thread"},
        "sources": [],
        "unread_planes": [],
        "withdrawn_counts": [],
    }
    ckm = {
        "schema_version": 1,
        "resource_type": "capability",
        "query_digest": "1" * 64,
        "projection": {"status": "derived_projection", "authoritative": False},
        "snapshot": {
            "epoch": "epoch-1",
            "state_revision": 1,
            "ckm_schema_version": 5,
            "envelope_schema_version": 1,
            "resource_schema_version": 1,
            "taxonomy_digest": "2" * 64,
            "effective_audience": "single_operator_local",
            "access_policy_version": "ckm-local-access-v1",
            "redaction_profile": "none",
            "read_set_digest": "3" * 64,
            "snapshot_digest": "4" * 64,
            "watermarks": {},
            "provenance": [],
            "completeness": {
                "complete": True,
                "object_classes": [
                    {
                        "object_class": "capability",
                        "included": 0,
                        "filtered": 0,
                        "omitted": 0,
                        "truncated": 0,
                    }
                ],
            },
        },
        "resources": [],
    }
    seen: list[Path] = []

    class ReadOnlyCkm:
        def __init__(self, db_path: Path) -> None:
            seen.append(db_path)

        def list_capabilities(self):
            return SimpleNamespace(to_dict=lambda: ckm)

    monkeypatch.setattr(devui_route, "read_cockpit_registry", lambda: cockpit)
    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path("/state/builderops.sqlite3")),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", ReadOnlyCkm)

    client = TestClient(app)
    response = client.get("/api/devui/composition")

    assert response.status_code == 200
    assert response.json()["contract_version"] == "devui.composition.v1"
    assert response.json()["providers"]["work"]["payload"] == cockpit
    assert response.json()["providers"]["capabilities"]["payload"] == ckm
    assert seen == [Path("/state/builderops.sqlite3")]

    assert client.post("/api/devui/composition").status_code == 405
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/devui/composition"
    )
    assert route.methods == {"GET"}


def test_devui_composition_refuses_non_loopback_even_with_api_key(
    monkeypatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", "valid-key")

    def must_not_read() -> dict:
        raise AssertionError("local providers must not be read for a remote caller")

    monkeypatch.setattr(devui_route, "read_cockpit_registry", must_not_read)
    remote = TestClient(app, client=("203.0.113.10", 50000))

    response = remote.get(
        "/api/devui/composition",
        headers={"X-API-Key": "valid-key"},
    )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "devUI composition is available only to a local caller"
    }


def test_devui_composition_refuses_forwarded_remote_caller(monkeypatch) -> None:
    monkeypatch.setattr(auth_module.settings, "api_key", None)
    response = TestClient(app).get(
        "/api/devui/composition",
        headers={"X-Forwarded-For": "203.0.113.10"},
    )

    assert response.status_code == 403


def test_devui_composition_refuses_trusted_proxy_forwarding_loopback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        auth_module.settings,
        "companion_trusted_proxy_hosts",
        "172.18.0.1",
    )
    response = TestClient(app, client=("172.18.0.1", 50000)).get(
        "/api/devui/composition",
        headers={"X-Forwarded-For": "127.0.0.1"},
    )

    assert response.status_code == 403


def test_devui_composition_refuses_other_forwarded_identity_headers() -> None:
    client = TestClient(app, client=("127.0.0.1", 50000))

    for name, value in (
        ("Forwarded", "for=127.0.0.1"),
        ("X-Real-IP", "127.0.0.1"),
        ("CF-Connecting-IP", "127.0.0.1"),
    ):
        assert client.get(
            "/api/devui/composition",
            headers={name: value},
        ).status_code == 403


def test_devui_composition_sanitizes_ckm_refusal_diagnostics(
    monkeypatch,
) -> None:
    secret = "/private/ckm.sqlite3"
    cockpit = {
        "authority": "read_time_join",
        "generated_at": "2026-08-08T21:00:00+00:00",
        "claim": {"kind": "refused", "text": "source unavailable"},
        "sources": [],
        "unread_planes": [],
        "withdrawn_counts": [],
    }
    refusal = {
        "schema_version": 1,
        "error": {
            "code": "unsupported_store",
            "message": f"SQLite could not open {secret}",
            "details": {
                "path": secret,
                "reason": f"OperationalError while reading {secret}",
            },
        },
    }

    class RefusingCkm:
        def __init__(self, db_path: Path) -> None:
            self.db_path = db_path

        def list_capabilities(self):
            return SimpleNamespace(to_dict=lambda: refusal)

    monkeypatch.setattr(devui_route, "read_cockpit_registry", lambda: cockpit)
    monkeypatch.setattr(
        devui_route,
        "load_builderops_paths",
        lambda: SimpleNamespace(db_path=Path(secret)),
    )
    monkeypatch.setattr(devui_route, "CkmQueryService", RefusingCkm)

    payload = TestClient(app).get("/api/devui/composition").json()
    contribution = payload["providers"]["capabilities"]

    assert contribution["refusal"] == {
        "code": "unsupported_store",
        "message": "CKM refused the read request",
        "details": {},
    }
    assert secret not in repr(payload)
    assert "OperationalError" not in repr(payload)
