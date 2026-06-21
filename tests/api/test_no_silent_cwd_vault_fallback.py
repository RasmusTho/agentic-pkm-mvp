from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.companion as companion_module
import app.api.routes.vault_resolution as vault_resolution_module
from app.api.app import app
from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from tests.api._vault_test_helpers import bind_initialized_vault


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _bind_no_vault_manager(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app_local_path = tmp_path / ".app-local.md"
    monkeypatch.setenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", str(app_local_path))
    manager = VaultManager(app_local_store=AppLocalSettingsStore(app_local_path))
    monkeypatch.setattr(companion_module, "get_vault_manager", lambda: manager)
    monkeypatch.setattr(vault_resolution_module, "get_vault_manager", lambda: manager)
    if hasattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR):
        delattr(manager, companion_module._LAST_ACTIVE_LOAD_ATTEMPTED_ATTR)


def _assert_picker_response(response, *, requested_note_path: str | None = None) -> None:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "no_vault_bound"
    assert body["configured_vault_root"] is None
    if requested_note_path is not None:
        assert body["requested_note_path"] == requested_note_path
    assert "hidden" not in response.text
    assert "# Leaked" not in response.text


def test_api_request_endpoints_do_not_resolve_cwd_vault_without_selection(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_no_vault_manager(monkeypatch, tmp_path)
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.chdir(tmp_path)

    cwd_vault = tmp_path / "vault"
    note = cwd_vault / "notes" / "leaked.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nuuid: leaked-note\n---\n\n# Leaked\n\nbody\n- [x] hidden <!--ai:id=hidden-->\n",
        encoding="utf-8",
    )

    artifact = client.get("/api/artifacts/note", params={"note_path": "notes/leaked.md"})
    _assert_picker_response(artifact, requested_note_path="notes/leaked.md")

    debug = client.get("/api/debug/panel", params={"note_rel": "notes/leaked.md"})
    _assert_picker_response(debug, requested_note_path="notes/leaked.md")

    canvas = client.post(
        "/api/canvas/sessions",
        json={"note_path": "notes/leaked.md", "label": "no-vault"},
    )
    _assert_picker_response(canvas, requested_note_path="notes/leaked.md")

    capture = client.post("/api/companion/capture", json={"text": "do not write"})
    _assert_picker_response(capture)
    assert not (cwd_vault / "Inbox" / "inbox.md").exists()


def test_api_request_endpoints_report_channel_specific_configured_root(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_no_vault_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    dev_vault = tmp_path / "configured-dev-vault"
    dev_vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT_DEV", str(dev_vault))

    capture = client.post("/api/companion/capture", json={"text": "needs a vault"})

    assert capture.status_code == 200
    body = capture.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "no_vault_bound"
    assert body["configured_vault_root"] == str(dev_vault)


def test_api_request_endpoints_report_missing_channel_specific_root(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_no_vault_manager(monkeypatch, tmp_path)
    monkeypatch.setenv("PKM_ENVIRONMENT", "test")
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    missing = tmp_path / "missing-test-vault"
    monkeypatch.setenv("VAULT_ROOT_TEST", str(missing))

    artifact = client.get("/api/artifacts/note", params={"note_path": "notes/missing.md"})

    assert artifact.status_code == 200
    body = artifact.json()
    assert body["state"] == "vault_selection_required"
    assert body["reason"] == "vault_root_misconfigured"
    assert body["configured_vault_root"] == str(missing)


def test_api_request_endpoints_preserve_selected_vault_behavior(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "selected-vault"
    bind_initialized_vault(monkeypatch, vault, store_dir=tmp_path)
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "Inbox")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))

    note = vault / "notes" / "active.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "---\nuuid: selected-note\n---\n\n# Active\n\nbody\n- [x] Promote <!--ai:id=promote.evergreen-->\n",
        encoding="utf-8",
    )
    actions_path = tmp_path / "panel-actions.md"
    actions_path.write_text(
        "---\nmappings:\n  - id: promote.evergreen\n    labels: [Promote]\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PANEL_ACTIONS_ROOT", str(actions_path))

    artifact = client.get("/api/artifacts/note", params={"note_path": "notes/active.md"})
    assert artifact.status_code == 200, artifact.text
    assert artifact.json()["title"] == "Active"

    debug = client.get("/api/debug/panel", params={"note_rel": "notes/active.md"})
    assert debug.status_code == 200, debug.text
    assert debug.json()["parsed_actions"][0]["action_id"] == "promote.evergreen"

    canvas = client.post(
        "/api/canvas/sessions",
        json={"note_path": "notes/active.md", "label": "selected"},
    )
    assert canvas.status_code == 200, canvas.text
    assert canvas.json()["session_id"]

    capture = client.post("/api/companion/capture", json={"text": "selected write"})
    assert capture.status_code == 200, capture.text
    assert "selected write" in (vault / "Inbox" / "inbox.md").read_text(encoding="utf-8")


def test_canvas_mutations_use_session_vault_after_selection_changes(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault_a = tmp_path / "vault-a"
    bind_initialized_vault(monkeypatch, vault_a, store_dir=tmp_path)
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    note_a = vault_a / "notes" / "session.md"
    note_a.parent.mkdir(parents=True)
    note_a.write_text(
        "---\nuuid: session-vault-a\n---\n\n# A\n\nOriginal A.\n",
        encoding="utf-8",
    )

    opened = client.post(
        "/api/canvas/sessions",
        json={"note_path": "notes/session.md", "label": "bound-vault"},
    )
    assert opened.status_code == 200, opened.text
    session_id = opened.json()["session_id"]

    vault_b = tmp_path / "vault-b"
    bind_initialized_vault(monkeypatch, vault_b, store_dir=tmp_path)
    note_b = vault_b / "notes" / "session.md"
    note_b.parent.mkdir(parents=True)
    note_b.write_text(
        "---\nuuid: session-vault-b\n---\n\n# B\n\nOriginal B.\n",
        encoding="utf-8",
    )

    edited = client.post(
        f"/api/canvas/sessions/{session_id}/edits",
        json={
            "new_body": "# A\n\nEdited while another vault is selected.\n",
            "change_summary": "edit after selection change",
        },
    )

    assert edited.status_code == 200, edited.text
    assert "Edited while another vault is selected" in note_a.read_text(encoding="utf-8")
    assert "Original B" in note_b.read_text(encoding="utf-8")


def test_companion_request_helpers_do_not_fallback_to_cwd_vault() -> None:
    target_files = [
        Path("app/api/routes/capture.py"),
        Path("app/api/routes/artifacts.py"),
        Path("app/api/routes/canvas.py"),
        Path("app/api/routes/debug.py"),
        Path("app/api/routes/companion.py"),
    ]
    violations: list[str] = []
    for path in target_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "resolve_vault_root":
                    violations.append(f"{path}:{node.lineno}")
                elif isinstance(func, ast.Attribute) and func.attr == "resolve_vault_root":
                    violations.append(f"{path}:{node.lineno}")
    assert violations == []
