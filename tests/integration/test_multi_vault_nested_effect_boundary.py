from pathlib import Path

from app.vault.manager import nearest_enclosing_vault_root
from tests.helpers.vault_settings import initialize_test_vault


def test_provisional_uninitialized_parent_reads_stop_at_initialized_child(tmp_path: Path) -> None:
    parent, child = tmp_path / "parent", tmp_path / "parent" / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("parent")
    (child / "child.md").write_text("child")
    initialize_test_vault(child)
    assert nearest_enclosing_vault_root(child / "child.md", search_root=parent) == child


def test_parent_authority_cannot_read_registered_child_vault(tmp_path: Path) -> None:
    parent, child = tmp_path / "parent", tmp_path / "parent" / "child"
    child.mkdir(parents=True)
    (parent / "parent.md").write_text("parent")
    (child / "secret.md").write_text("child")
    initialize_test_vault(child)
    assert nearest_enclosing_vault_root(child / "secret.md", search_root=parent) == child
