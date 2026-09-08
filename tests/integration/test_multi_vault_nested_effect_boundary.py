"""Production filesystem read boundaries for nested vaults."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes.companion import _find_workspace_note, _iter_vault_note_files
from tests._mvr03_principal_harness import provisioned_instance
from app.vault.manager import nearest_enclosing_vault_root
from tests.helpers.vault_settings import initialize_test_vault


def test_provisional_uninitialized_parent_reads_stop_at_initialized_child(tmp_path: Path) -> None:
    parent, child = tmp_path / "parent", tmp_path / "parent" / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("# Parent", encoding="utf-8")
    (child / "child.md").write_text("# Child", encoding="utf-8")
    initialize_test_vault(child)

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
