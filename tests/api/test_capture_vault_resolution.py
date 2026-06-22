from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

import app.api.routes.capture as capture_module
from app.api.app import app
from app.api.routes.vault_resolution import active_vault_root_or_selection_required
from tests.api._vault_test_helpers import bind_selected_vault


def test_capture_selected_uninitialized_vault_reports_uninitialized(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "bare-vault"
    vault.mkdir(parents=True)
    manager = bind_selected_vault(monkeypatch, vault, store_dir=tmp_path)
    assert manager.context.status == "uninitialized"

    def _fail_append(*args: object, **kwargs: object) -> None:
        raise AssertionError("capture must not write to an uninitialized vault")

    monkeypatch.setattr(capture_module, "append_note_relative", _fail_append)

    response = TestClient(app).post("/api/companion/capture", json={"text": "Remember this"})

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "uninitialized"
    assert body["configured_vault_root"] == str(vault.resolve())
    assert body["context"]["status"] == "uninitialized"
    assert body["context"]["active_vault_path"] == str(vault.resolve())


def test_capture_uses_shared_uninitialized_vault_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "bare-vault"
    vault.mkdir(parents=True)
    manager = bind_selected_vault(monkeypatch, vault, store_dir=tmp_path)
    assert manager.context.status == "uninitialized"

    response = active_vault_root_or_selection_required(require_initialized=True)

    assert isinstance(response, JSONResponse)
    assert response.status_code == 200
    assert b'"reason":"uninitialized"' in response.body
    assert str(vault.resolve()).encode() in response.body
