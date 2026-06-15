"""Tests for companion vault routing in the unset / no-vault case (#2006).

#1757 routed a *set-but-missing* ``VAULT_ROOT`` to the picker state. This suite
closes the **unset / no-vault** gap: with no vault ever bound, the companion
boundary must return the ``vault_selection_required`` picker state (200) — not a
500 and not an empty default ``./vault`` note list — and must surface the
``known_vaults`` recent list so the picker can switch between registered vaults.

It also verifies open / switch / register-multiple end-to-end against the
existing ``VaultManager`` registry: selecting a vault re-resolves in-process
(no restart) and switching between two registered vaults persists the
last-active pointer.

Shape mirrors ``tests/api/test_companion_vault_notes_api.py``: in-process
``TestClient(app)`` with the global ``get_vault_manager`` monkeypatched to a
``VaultManager`` backed by a tmp app-local store.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> VaultManager:
    """A fresh no-vault manager wired into the companion routes.

    No ``VAULT_ROOT`` is set, so the optional resolver reports the explicit
    no-vault state. ``DESIGN_HANDOFF_APP_LOCAL_SETTINGS`` is also redirected so
    ``known_vaults`` writes land in the tmp dir, never the real app-local file.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    app_local_path = tmp_path / "app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    mgr = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: mgr)
    # Reset the lazy last-active flag that the companion module stashes on the
    # manager so each test starts from a clean no-vault posture.
    if hasattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(mgr, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)
    return mgr


def _seed_vault(mgr: VaultManager, vault_path: Path, *, name: str) -> str:
    """Initialize + register a vault, returning its vault_id. Leaves it inactive."""
    result = mgr.initialize_vault(vault_path, vault_name=name, remember=True)
    assert result.context.status == "selected"
    return result.context.active_vault_id or ""


def test_no_vault_returns_selection_required(
    client: TestClient, manager: VaultManager
) -> None:
    """No vault bound -> /vault/context returns the picker state (200, not 500)."""
    resp = client.get("/api/companion/vault/context")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    # Must not have silently resolved a default ./vault as a "selected" vault.
    assert body["context"]["status"] != "selected"


def test_selection_required_lists_known_vaults(
    client: TestClient, manager: VaultManager, tmp_path: Path
) -> None:
    """The selection-required payload includes the known_vaults recent list."""
    _seed_vault(manager, tmp_path / "vault-a", name="Vault A")
    _seed_vault(manager, tmp_path / "vault-b", name="Vault B")
    # Drop back to a genuine no-vault posture: both vaults stay registered in
    # known_vaults, but no last-active pointer remains, so /vault/context cannot
    # silently restore one and must fall through to the picker state.
    settings = manager.app_local_store.load()
    settings.last_active_vault_ref = None
    manager.app_local_store.save(settings)
    manager._context = companion_module.VaultContext(status="none")
    if hasattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)

    resp = client.get("/api/companion/vault/context")

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    recent_names = {item["vault_name"] for item in body["recent_vaults"]}
    assert {"Vault A", "Vault B"} <= recent_names


def test_select_vault_reresolves_in_process(
    client: TestClient, manager: VaultManager, tmp_path: Path
) -> None:
    """Selecting a vault re-resolves in-process; reads then render full bodies."""
    vault = tmp_path / "vault-a"
    manager.initialize_vault(vault, vault_name="Vault A", remember=True)
    (vault / "hello.md").write_text("# Hello\n\nFull body here.\n", encoding="utf-8")
    # Back to no-vault before the select so we prove in-process re-resolution.
    manager._context = companion_module.VaultContext(status="none")
    if hasattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)

    select = client.post(
        "/api/companion/vault/select", json={"path": str(vault), "remember": True}
    )
    assert select.status_code == 200
    assert select.json()["status"] == "selected"

    # Same process, no restart: notes now resolve against the selected vault and
    # render full note bodies, not an empty ./vault default list.
    notes = client.get("/api/companion/vault/notes")
    assert notes.status_code == 200
    note_paths = [n["path"] for n in notes.json()["notes"]]
    assert "hello.md" in note_paths


def test_switch_between_known_vaults_persists_last_active(
    client: TestClient, manager: VaultManager, tmp_path: Path
) -> None:
    """Switching A -> B persists the last-active pointer to B."""
    vault_a = tmp_path / "vault-a"
    vault_b = tmp_path / "vault-b"
    manager.initialize_vault(vault_a, vault_name="Vault A", remember=True)
    manager.initialize_vault(vault_b, vault_name="Vault B", remember=True)

    sel_a = client.post(
        "/api/companion/vault/select", json={"path": str(vault_a), "remember": True}
    )
    assert sel_a.json()["active_vault_name"] == "Vault A"
    ref_a = f"path:{vault_a}"

    settings = manager.app_local_store.load()
    assert settings.last_active_vault_ref == ref_a

    sel_b = client.post(
        "/api/companion/vault/select", json={"path": str(vault_b), "remember": True}
    )
    assert sel_b.json()["active_vault_name"] == "Vault B"
    ref_b = f"path:{vault_b}"

    settings = manager.app_local_store.load()
    assert settings.last_active_vault_ref == ref_b
    # Both remain registered for future switching.
    assert {ref_a, ref_b} <= set(settings.known_vaults.keys())


# --- Cross-endpoint picker-routing contract (set-but-missing VAULT_ROOT) -----
#
# Every companion boundary that resolves the vault root must route a
# *set-but-missing* ``VAULT_ROOT`` into the ``vault_selection_required`` picker
# state (200, reason ``vault_root_misconfigured``) — never a 500 and never a
# silent ``./vault`` default. The file docstring above asserted #1757 did this,
# but until now only ``/vault/context`` was exercised; ``/vault/notes``,
# ``/workspace``, and the governed ``queue-review`` write action carried the same
# ``_vault_selection_required_response`` branch untested. This parametrized suite
# pins that contract for all of them so a future refactor can't silently drop a
# catch (the gap that let #2006's queue-review path regress to a 500).


def _picker_endpoints() -> list[tuple[str, str, str, dict | None, str | None]]:
    """(id, method, url, json_body, expected_requested_note_path)."""
    note_path = "notes/x.md"
    return [
        ("vault_context", "GET", "/api/companion/vault/context", None, None),
        ("vault_notes", "GET", "/api/companion/vault/notes", None, None),
        (
            "workspace",
            "GET",
            f"/api/companion/workspace?note_path={note_path}",
            None,
            note_path,
        ),
        (
            "queue_review",
            "POST",
            "/api/companion/vault-browser/actions/queue-review",
            {"note_path": note_path},
            note_path,
        ),
    ]


@pytest.mark.parametrize(
    "method, url, json_body, expected_requested_note_path",
    [case[1:] for case in _picker_endpoints()],
    ids=[case[0] for case in _picker_endpoints()],
)
def test_set_but_missing_vault_root_routes_to_picker(
    client: TestClient,
    manager: VaultManager,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    url: str,
    json_body: dict | None,
    expected_requested_note_path: str | None,
) -> None:
    """Set-but-missing VAULT_ROOT -> every picker endpoint returns the misconfig
    picker state (200), surfaces the configured path, and never 500s.
    """
    missing_root = tmp_path / "does-not-exist-vault"
    assert not missing_root.exists()
    # The `manager` fixture deletes VAULT_ROOT and reports a no-vault context, so
    # each endpoint falls through to resolve_vault_root() and raises on the
    # missing path — exactly the misconfigured-root branch under test.
    monkeypatch.setenv("VAULT_ROOT", str(missing_root))

    resp = client.request(method, url, json=json_body)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "vault_root_misconfigured"
    assert body["configured_vault_root"] == str(missing_root)
    if expected_requested_note_path is not None:
        assert body["requested_note_path"] == expected_requested_note_path
