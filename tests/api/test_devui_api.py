"""API contract for the read-only devUI composition route (#4682)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

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
        "query_digest": "digest",
        "projection": {"status": "derived_projection", "authoritative": False},
        "snapshot": {
            "epoch": "epoch-1",
            "state_revision": 1,
            "snapshot_digest": "snapshot-1",
            "watermarks": {},
            "completeness": {"complete": True, "object_classes": []},
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
