"""Production filesystem read boundaries for nested vaults."""

from pathlib import Path

from app.api.routes.companion import _find_workspace_note, _iter_vault_note_files
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


def test_parent_authority_cannot_read_registered_child_vault(tmp_path: Path) -> None:
    parent, child = tmp_path / "parent", tmp_path / "parent" / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("# Parent", encoding="utf-8")
    (child / "secret.md").write_text("# Child secret", encoding="utf-8")
    initialize_test_vault(parent)
    initialize_test_vault(child)

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
