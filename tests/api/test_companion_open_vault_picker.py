from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
from app.api.app import app
from app.config.paths import VaultRootMisconfiguredError
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _manager(tmp_path: Path) -> VaultManager:
    return VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "app-local.md"))


def _write_note(vault_root: Path, rel_path: str, body: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _assert_selection_required(data: dict[str, object], missing_root: Path) -> None:
    assert data["state"] == "vault_selection_required"
    assert data["reason"] == "vault_root_misconfigured"
    assert data["configured_vault_root"] == str(missing_root)
    context = data["context"]
    assert isinstance(context, dict)
    assert context["status"] == "missing"
    assert context["active_vault_path"] == str(missing_root)
    assert context["validation_error"]
    actions = data["actions"]
    assert isinstance(actions, list)
    assert {action["kind"] for action in actions if isinstance(action, dict)} >= {
        "open_existing",
        "create_new",
        "open_recent",
    }


def test_misconfigured_vault_root_returns_selection_required_state(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_root = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing_root))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: _manager(tmp_path))

    workspace_resp = client.get(
        "/api/companion/workspace",
        params={"note_path": "notes/missing.md"},
    )
    notes_resp = client.get("/api/companion/vault/notes")

    assert workspace_resp.status_code == 200
    workspace_data = workspace_resp.json()
    _assert_selection_required(workspace_data, missing_root)
    assert workspace_data["requested_note_path"] == "notes/missing.md"
    assert "artifact" not in workspace_data

    assert notes_resp.status_code == 200
    notes_data = notes_resp.json()
    _assert_selection_required(notes_data, missing_root)
    assert "notes" not in notes_data


def test_vault_misconfigured_error_caught_at_request_boundary(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_root = tmp_path / "missing-vault"

    def _raise_misconfigured() -> Path:
        raise VaultRootMisconfiguredError("VAULT_ROOT", missing_root)

    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: _manager(tmp_path))
    # The companion boundary now resolves through resolve_optional_vault_root
    # (#2184), so the misconfigured-error catch must be proven on that call path.
    monkeypatch.setattr(companion_module, "resolve_optional_vault_root", _raise_misconfigured)

    resp = client.get(
        "/api/companion/workspace",
        params={"note_path": "notes/missing.md"},
    )

    assert resp.status_code == 200
    data = resp.json()
    _assert_selection_required(data, missing_root)
    assert "traceback" not in resp.text.lower()


def test_select_real_vault_recovers_full_note_bodies(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_root = tmp_path / "missing-vault"
    real_vault = tmp_path / "real-vault"
    setup_manager = VaultManager(app_local_store=AppLocalSettingsStore(tmp_path / "setup-app-local.md"))
    initialized = setup_manager.initialize_vault(
        real_vault,
        vault_name="Real Vault",
        machine_role="testNode",
        remember=False,
    )
    assert initialized.context.status == "selected"
    _write_note(
        real_vault,
        "notes/recovered.md",
        "# Recovered\n\nFull note body rendered after selecting a real vault.\n",
    )
    monkeypatch.setenv("VAULT_ROOT", str(missing_root))
    manager = _manager(tmp_path)
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)

    before_resp = client.get(
        "/api/companion/workspace",
        params={"note_path": "notes/recovered.md"},
    )
    assert before_resp.status_code == 200
    _assert_selection_required(before_resp.json(), missing_root)

    select_resp = client.post(
        "/api/companion/vault/select",
        json={"path": str(real_vault), "remember": True},
    )
    assert select_resp.status_code == 200
    assert select_resp.json()["status"] == "selected"

    workspace_resp = client.get(
        "/api/companion/workspace",
        params={"note_path": "notes/recovered.md"},
    )

    assert workspace_resp.status_code == 200
    data = workspace_resp.json()
    assert data["artifact"]["note_path"] == "notes/recovered.md"
    assert "Full note body rendered after selecting a real vault." in data["artifact"]["body"]
    assert data["runtime"]["vault_identity"]["vault_name"] == "Real Vault"
    assert data["runtime"]["vault_identity"]["provenance"] == "selected"
