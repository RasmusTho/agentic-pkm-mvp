"""Tests for vault/channel identity in the companion workspace API response.

Covers:
- vault_identity field present in runtime response
- vault_name derived from last path component of VAULT_ROOT
- channel read from PKM_ENVIRONMENT, CHANNEL, PKM_CHANNEL (in that order)
- provenance="env" when VAULT_ROOT is set and used; no-vault (unset, none
  selected) routes to the vault picker instead of a ./vault default (#2184)
- provenance="fallback" when VAULT_ROOT is invalid and runtime falls back
- vault paths containing spaces (iCloud Mobile Documents)
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
import app.panel.confirmation as confirm_module
from app.api.app import app


@pytest.fixture(autouse=True)
def _clear_runtime_state() -> None:
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    confirm_module._proposal_store.clear()
    confirm_module._idempotency_store.clear()


@pytest.fixture()
def vault_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path))
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    note = tmp_path / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: note-uuid-1\n---\n\n# Test Note\n\nBody text.\n",
        encoding="utf-8",
    )
    return note


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _workspace(client: TestClient, note_path: str = "notes/note.md"):
    return client.get("/api/companion/workspace", params={"note_path": note_path})


def test_vault_identity_present_in_runtime(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    resp = _workspace(client)
    assert resp.status_code == 200
    runtime = resp.json()["runtime"]
    assert "vault_identity" in runtime


def test_vault_name_derived_from_vault_root_basename(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PKM_ENVIRONMENT", raising=False)
    # tmp_path basename is used as vault_name
    resp = _workspace(client)
    assert resp.status_code == 200
    identity = resp.json()["runtime"]["vault_identity"]
    assert identity["vault_name"] == tmp_path.name


def test_vault_name_prefers_host_root_over_container_path(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the container VAULT_ROOT is /app/vault; the real operator vault name
    comes from VAULT_HOST_ROOT (issue #2141), so a correctly-mounted Niflheim
    must not be mislabeled "vault"."""
    monkeypatch.delenv("PKM_ENVIRONMENT", raising=False)
    monkeypatch.setenv(
        "VAULT_HOST_ROOT",
        "/Users/op/Library/Mobile Documents/iCloud~md~obsidian/Documents/Niflheim",
    )
    resp = _workspace(client)
    assert resp.status_code == 200
    identity = resp.json()["runtime"]["vault_identity"]
    assert identity["vault_name"] == "Niflheim"
    assert identity["provenance"] == "host_root"


def test_vault_channel_from_pkm_environment(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.delenv("CHANNEL", raising=False)
    monkeypatch.delenv("PKM_CHANNEL", raising=False)
    resp = _workspace(client)
    assert resp.status_code == 200
    assert resp.json()["runtime"]["vault_identity"]["channel"] == "dev"


def test_vault_channel_from_channel_env(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PKM_ENVIRONMENT", raising=False)
    monkeypatch.setenv("CHANNEL", "dev")
    monkeypatch.delenv("PKM_CHANNEL", raising=False)
    resp = _workspace(client)
    assert resp.status_code == 200
    assert resp.json()["runtime"]["vault_identity"]["channel"] == "dev"


def test_vault_channel_from_pkm_channel_env(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PKM_ENVIRONMENT", raising=False)
    monkeypatch.delenv("CHANNEL", raising=False)
    monkeypatch.setenv("PKM_CHANNEL", "test")
    resp = _workspace(client)
    assert resp.status_code == 200
    assert resp.json()["runtime"]["vault_identity"]["channel"] == "test"


def test_vault_provenance_env_when_vault_root_set(
    client: TestClient, vault_note: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = _workspace(client)
    assert resp.status_code == 200
    identity = resp.json()["runtime"]["vault_identity"]
    assert identity["provenance"] == "env"


def test_no_vault_root_routes_to_picker_not_default_vault(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # No vault selected and VAULT_ROOT unset must route the human into the vault
    # picker (#2184 / no-vault idle-boot invariant) instead of silently
    # defaulting to a CWD-relative ./vault. A ./vault on disk must NOT be picked
    # up implicitly.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    default_vault = Path("vault").resolve()
    default_note = default_vault / "notes" / "note.md"
    default_note.parent.mkdir(parents=True, exist_ok=True)
    default_note.write_text(
        "---\nuuid: default-uuid-1\n---\n\n# Default Note\n\nBody.\n",
        encoding="utf-8",
    )
    resp = _workspace(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["reason"] == "no_vault_bound"
    assert data["configured_vault_root"] is None
    # Must not have masqueraded the CWD ./vault as a selected/default vault.
    assert "runtime" not in data


def test_vault_root_invalid_returns_selection_required_state(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    missing_vault = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing_vault))
    resp = _workspace(client)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["configured_vault_root"] == str(missing_vault)
    assert data["context"]["status"] == "missing"


def _configure_runtime_vault(monkeypatch, tmp_path, name):
    """Point the settings runtime at a temp instance.yaml carrying vault.name."""
    from app.settings import runtime as settings_runtime

    runtime_dir = tmp_path / "runtime_settings"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "global.yaml").write_text("{}\n", encoding="utf-8")
    (runtime_dir / "providers.yaml").write_text("{}\n", encoding="utf-8")
    (runtime_dir / "instance.yaml").write_text(
        f"vault:\n  name: {name}\n", encoding="utf-8"
    )
    monkeypatch.setattr(settings_runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(settings_runtime, "_SUBSCRIBERS", [])
    monkeypatch.setattr(settings_runtime, "_CURRENT", None)
    return runtime_dir


def test_mounted_vault_reports_truthful_identity(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A configured vault name is authoritative: provenance="settings", real name.
    _configure_runtime_vault(monkeypatch, tmp_path, "Niflheim")
    resp = _workspace(client)
    assert resp.status_code == 200
    identity = resp.json()["runtime"]["vault_identity"]
    assert identity["vault_name"] == "Niflheim"
    assert identity["provenance"] == "settings"


def test_configured_vault_name_does_not_allow_missing_vault_root_fallback(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A configured display name cannot override a missing env vault root into
    # silently reading ./vault; the human must choose the real vault instead.
    monkeypatch.chdir(tmp_path)
    fallback_note = Path("vault") / "notes" / "note.md"
    fallback_note.parent.mkdir(parents=True, exist_ok=True)
    fallback_note.write_text(
        "---\nuuid: fallback-uuid-1\n---\n\n# Fallback Note\n\nBody.\n",
        encoding="utf-8",
    )
    missing_vault = tmp_path / "host-only" / "Niflheim"
    monkeypatch.setenv("VAULT_ROOT", str(missing_vault))
    _configure_runtime_vault(monkeypatch, tmp_path, "Niflheim")
    resp = _workspace(client, note_path="notes/note.md")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "vault_selection_required"
    assert data["configured_vault_root"] == str(missing_vault)
    assert data["context"]["status"] == "missing"


def test_configured_vault_name_hot_reloads_without_restart(
    client: TestClient, vault_note: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.settings import runtime as settings_runtime

    runtime_dir = _configure_runtime_vault(monkeypatch, tmp_path, "Niflheim")
    assert (
        _workspace(client).json()["runtime"]["vault_identity"]["vault_name"]
        == "Niflheim"
    )
    # Rename on disk + reload (no process restart) → next request reflects it.
    (runtime_dir / "instance.yaml").write_text(
        "vault:\n  name: Midgard\n", encoding="utf-8"
    )
    settings_runtime.reload_settings_bundle(notify=False)
    assert (
        _workspace(client).json()["runtime"]["vault_identity"]["vault_name"]
        == "Midgard"
    )


def test_vault_name_safe_for_path_with_spaces(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_dir = tmp_path / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Niflheim"
    vault_dir.mkdir(parents=True)
    note = vault_dir / "notes" / "note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(
        "---\nuuid: nifl-uuid-1\n---\n\n# Note\n\nBody.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault_dir))
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.delenv("CANVAS_ENABLED", raising=False)
    resp = _workspace(client)
    assert resp.status_code == 200
    identity = resp.json()["runtime"]["vault_identity"]
    assert identity["vault_name"] == "Niflheim"
    assert identity["provenance"] == "env"
