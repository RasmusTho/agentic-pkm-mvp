"""Production filesystem read boundaries for nested vaults."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes.companion import _find_workspace_note, _iter_vault_note_files
from tests._mvr03_principal_harness import provisioned_instance
from app.vault.manager import nearest_enclosing_vault_root
from tests.helpers.vault_settings import initialize_test_vault


def _scoped_client(runtime, monkeypatch) -> TestClient:
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    return TestClient(app)


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _select(client: TestClient, binding_id: str) -> dict[str, str]:
    selection = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [binding_id]},
    )
    assert selection.status_code == 201, selection.text
    return {"X-Active-Context-Session": selection.json()["context_selection_id"]}


def test_provisional_uninitialized_parent_reads_stop_at_initialized_child(
    tmp_path: Path, monkeypatch
) -> None:
    # The production read-before-initialize journey: a registered, still
    # uninitialized (provisional) binding is readable through the migrated
    # companion read routes, stops at an initialized nested child, and stays
    # write-sealed.
    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    parent = Path(first.path)
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("# Parent", encoding="utf-8")
    (child / "child.md").write_text("# Child", encoding="utf-8")
    initialize_test_vault(child)

    client = _scoped_client(runtime, monkeypatch)
    headers = _select(client, first.vault_binding_id)
    before = _tree_snapshot(parent)

    context = client.get("/api/companion/vault/context", headers=headers)
    assert context.status_code == 200, context.text
    assert context.json()["status"] == "uninitialized"
    assert context.json()["active_vault_path"] == str(parent.resolve())

    notes = client.get("/api/companion/vault/notes", headers=headers)
    assert notes.status_code == 200, notes.text
    listed = [note["path"] for note in notes.json()["notes"]]
    assert "parent.md" in listed
    assert all(not path.startswith("child/") for path in listed)

    parent_note = client.get(
        "/api/companion/workspace", params={"note_path": "parent.md"}, headers=headers
    )
    assert parent_note.status_code == 200, parent_note.text
    child_note = client.get(
        "/api/companion/workspace", params={"note_path": "child/child.md"}, headers=headers
    )
    assert child_note.status_code == 404, child_note.text
    orientation = client.get("/api/companion/orientation", headers=headers)
    assert orientation.status_code == 200, orientation.text
    assert orientation.json()["reason"] == "uninitialized"
    # Every scoped read above was write-free inside the provisional root.
    assert _tree_snapshot(parent) == before

    sealed = client.post(
        "/api/companion/workspace/body",
        json={"note_path": "parent.md", "body": "# Changed"},
        headers=headers,
    )
    assert sealed.status_code == 409, sealed.text
    assert sealed.json()["detail"]["error"] == "capability_not_ready"
    assert (parent / "parent.md").read_text(encoding="utf-8") == "# Parent"

    parent_notes = [relative for _path, relative in _iter_vault_note_files(parent)]

    assert "parent.md" in parent_notes
    assert all(not relative.startswith("child/") for relative in parent_notes)
    assert _find_workspace_note(parent, "child/child.md") is None


def test_parent_authority_cannot_read_registered_child_vault(tmp_path: Path, monkeypatch) -> None:
    runtime, first, _extra, _record = provisioned_instance(tmp_path)
    parent = Path(first.path)
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("# Parent", encoding="utf-8")
    (child / "secret.md").write_text("# Child secret", encoding="utf-8")
    initialize_test_vault(parent)
    initialize_test_vault(child)
    child_registration = runtime.production_register(child, producer="picker")

    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("PKM_ENVIRONMENT", runtime.layout.channel_id)
    selection_routes.reset_selection_store_for_tests()
    client = TestClient(app)

    parent_selection = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [first.vault_binding_id]},
    )
    assert parent_selection.status_code == 201, parent_selection.text
    parent_read = client.get(
        "/api/companion/vault/notes/scoped",
        headers={
            "X-Active-Context-Session": parent_selection.json()["context_selection_id"]
        },
    )
    assert parent_read.status_code == 200, parent_read.text
    parent_payload = parent_read.json()
    assert all(note["path"] != "child/secret.md" for note in parent_payload["notes"])
    assert all(note["vault_binding_id"] == first.vault_binding_id for note in parent_payload["notes"])

    child_selection = client.post(
        "/api/companion/active-context/selection",
        json={"vault_binding_ids": [child_registration.vault_binding_id]},
    )
    assert child_selection.status_code == 201, child_selection.text
    child_read = client.get(
        "/api/companion/vault/notes/scoped",
        headers={
            "X-Active-Context-Session": child_selection.json()["context_selection_id"]
        },
    )
    assert child_read.status_code == 200, child_read.text
    assert any(
        note["path"] == "secret.md"
        and note["vault_binding_id"] == child_registration.vault_binding_id
        for note in child_read.json()["notes"]
    )

    # MVR-05B2: the migrated companion read routes enforce the same boundary.
    parent_headers = {
        "X-Active-Context-Session": parent_selection.json()["context_selection_id"]
    }
    child_headers = {
        "X-Active-Context-Session": child_selection.json()["context_selection_id"]
    }
    migrated_parent = client.get("/api/companion/vault/notes", headers=parent_headers)
    assert migrated_parent.status_code == 200, migrated_parent.text
    assert all(
        not note["path"].startswith("child/") for note in migrated_parent.json()["notes"]
    )
    crossing = client.get(
        "/api/companion/workspace",
        params={"note_path": "child/secret.md"},
        headers=parent_headers,
    )
    assert crossing.status_code == 404, crossing.text
    link_index = client.get("/api/companion/vault-link-index", headers=parent_headers)
    assert link_index.status_code == 200, link_index.text
    assert all(not path.startswith("child/") for path in link_index.json()["note_paths"])
    child_note = client.get(
        "/api/companion/workspace",
        params={"note_path": "secret.md"},
        headers=child_headers,
    )
    assert child_note.status_code == 200, child_note.text
    child_context = client.get("/api/companion/vault/context", headers=child_headers)
    assert child_context.status_code == 200, child_context.text
    assert child_context.json()["active_vault_path"] == str(child.resolve())

    parent_notes = [relative for _path, relative in _iter_vault_note_files(parent)]
    child_notes = [relative for _path, relative in _iter_vault_note_files(child)]

    parent_notes = [
        item
        for item in parent_notes
        if not item.startswith("settings/") and not item.startswith("⚙️ System/")
    ]
    child_notes = [
        item
        for item in child_notes
        if not item.startswith("settings/") and not item.startswith("⚙️ System/")
    ]
    assert parent_notes == ["parent.md"]
    assert child_notes == ["secret.md"]
    assert nearest_enclosing_vault_root(child / "secret.md", search_root=parent) == child
    assert _find_workspace_note(parent, "child/secret.md") is None
    assert _find_workspace_note(child, "secret.md") == (child / "secret.md").resolve()


def test_parent_authority_cannot_write_registered_child_vault(tmp_path, monkeypatch):
    from tests.api.test_multi_vault_governed_writes import setup_capture
    runtime, first, _, client, headers = setup_capture(tmp_path, monkeypatch)
    child = Path(first.path) / "child"
    initialize_test_vault(child)
    # Both unregistered and registered initialized child boundaries are refused.
    for registered in (False, True):
        if registered:
            runtime.production_register(child, producer="picker")
        monkeypatch.setenv("VAULT_CAPTURE_NOTE_REL", "child/inbox.md")
        result = client.post("/api/companion/capture/scoped", headers=headers,
            json={"text": "Forbidden", "target_binding_id": first.vault_binding_id})
        assert result.status_code == 409, result.text
        assert not (child / "inbox.md").exists()
