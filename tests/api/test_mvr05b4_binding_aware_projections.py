"""MVR-05B4b (#6161): binding-aware companion read projections restored for scoped reads.

A scoped ``/workspace`` read reports the watcher binding status for the request's own binding by
comparing the single process watcher heartbeat with the request binding's root. A heartbeat that
names another root never surfaces that root.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from tests._mvr03_principal_harness import provisioned_instance
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


@pytest.fixture()
def two_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import app.vault.manager as vault_manager_module

    runtime, first, extra, _record = provisioned_instance(tmp_path, extra_roots=("two",))
    second = extra[0]
    root_a, root_b = Path(first.path), Path(second.path)
    for root in (root_a, root_b):
        initialize_test_vault(root)
        (root / "shared.md").write_text("# Shared\n", encoding="utf-8")
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    selection_routes.reset_selection_store_for_tests()
    heartbeat = tmp_path / "heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    return TestClient(app), first, second, root_a, root_b, heartbeat


def _beat(path: Path, vault_path: Path, *, age: float = 0.0) -> None:
    path.write_text(json.dumps({"vault_path": str(vault_path), "ts": time.time() - age}))


def _ingest(client: TestClient, binding_id: str) -> dict:
    created = client.post(
        "/api/companion/active-context/selection", json={"vault_binding_ids": [binding_id]}
    )
    assert created.status_code == 201, created.text
    headers = {"X-Active-Context-Session": created.json()["context_selection_id"]}
    response = client.get(
        "/api/companion/workspace", params={"note_path": "shared.md"}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["runtime"]["ingest"]


def test_scoped_workspace_reports_watcher_status_for_request_binding(two_bindings) -> None:
    client, first, second, root_a, root_b, heartbeat = two_bindings

    # No heartbeat at all: the request binding is unbound, nothing is published.
    missing = _ingest(client, first.vault_binding_id)
    assert missing["state"] == "unbound" and missing["bound"] is False
    assert missing["watcher_vault_path"] is None

    # Heartbeat names binding A: A is bound, B must not see A's path.
    _beat(heartbeat, root_a)
    bound = _ingest(client, first.vault_binding_id)
    assert bound["state"] == "bound" and bound["bound"] is True
    assert bound["watcher_vault_path"] == str(root_a)
    other = _ingest(client, second.vault_binding_id)
    assert other["state"] == "unbound" and other["bound"] is False
    assert other["watcher_vault_path"] is None
    assert str(root_a) not in json.dumps(other)

    # Heartbeat names B: now A reports unbound and never B's path.
    _beat(heartbeat, root_b)
    flipped = _ingest(client, first.vault_binding_id)
    assert flipped["state"] == "unbound" and flipped["bound"] is False
    assert flipped["watcher_vault_path"] is None
    assert str(root_b) not in json.dumps(flipped)

    # A stale heartbeat naming another root also never leaks that root.
    _beat(heartbeat, root_b, age=3600)
    stale = _ingest(client, first.vault_binding_id)
    assert stale["bound"] is False and stale["watcher_vault_path"] is None
    assert str(root_b) not in json.dumps(stale)


def test_scoped_workspace_blank_carrier_never_publishes_watcher_root(two_bindings) -> None:
    client, _first, _second, root_a, _root_b, heartbeat = two_bindings
    _beat(heartbeat, root_a)
    response = client.get(
        "/api/companion/workspace",
        params={"note_path": "shared.md"},
        headers={"X-Active-Context-Session": ""},
    )
    assert str(root_a) not in response.text


def test_scoped_workspace_probe_failure_stays_visible(two_bindings, monkeypatch) -> None:
    """#6204 review: a failed heartbeat probe degrades to a visible ``unbound``."""

    from app.api.routes import companion as companion_routes

    client, first, _second, _root_a, _root_b, _heartbeat = two_bindings

    def boom(**_kwargs):
        raise RuntimeError("heartbeat unreadable")

    monkeypatch.setattr(companion_routes, "ingest_binding_status", boom)

    failed = _ingest(client, first.vault_binding_id)

    assert failed["state"] == "unbound" and failed["bound"] is False
    assert failed["watcher_vault_path"] is None
