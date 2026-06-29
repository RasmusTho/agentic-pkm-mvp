from __future__ import annotations

from pathlib import Path

from app.watcher.registry import _scan_markdown_many as scan_registry_markdown_many
from app.watcher.vault_watcher import VaultWatcher, _scan_md_files
from app.watcher.watcher import _scan_markdown_many

_SCOPE_GLOB = "*.md,**/*.md"


def _write_note(path: Path, *, body: str = "Body.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _make_vault_root(path: Path) -> None:
    settings = path / "settings"
    settings.mkdir(parents=True, exist_ok=True)
    (settings / "vault.md").write_text(
        "---\nschema: design-handoff.vault.v1\nvaultId: child-vault\n---\n",
        encoding="utf-8",
    )


def _build_parent_with_nested_child(vault_root: Path) -> Path:
    _write_note(vault_root / "notes" / "Parent Note.md")
    _write_note(vault_root / "projects" / "Roadmap.md")
    child_root = vault_root / "projects" / "private-child"
    _make_vault_root(child_root)
    _write_note(child_root / "Secret Plan.md")
    return child_root


def _symlinked_selected_root(tmp_path: Path) -> tuple[Path, Path]:
    real_root = tmp_path / "real-vault"
    selected_root = tmp_path / "selected-vault"
    selected_root.symlink_to(real_root, target_is_directory=True)
    return real_root, selected_root


def test_watcher_enumeration_excludes_child_vault_notes(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    child_root = _build_parent_with_nested_child(vault_root)
    (vault_root / "notes" / "link-to-secret.md").symlink_to(child_root / "Secret Plan.md")

    expected = {"notes/Parent Note.md", "projects/Roadmap.md"}

    snapshot = _scan_md_files(vault_root)
    assert set(snapshot) == expected

    watcher = VaultWatcher(vault_root, snapshot_path=vault_root / ".state.json")
    result = watcher.run()
    changed_paths = {path.relative_to(vault_root).as_posix() for path in result.changed}
    assert changed_paths == expected

    watcher_scan = {
        rel.as_posix()
        for rel, _mtime, _path in _scan_markdown_many(vault_root, [vault_root], _SCOPE_GLOB)
    }
    assert watcher_scan == expected

    registry_scan = {
        rel.as_posix()
        for rel, _mtime, _path in scan_registry_markdown_many(vault_root, [vault_root], _SCOPE_GLOB)
    }
    assert registry_scan == expected

    assert list(_scan_markdown_many(vault_root, [child_root], _SCOPE_GLOB)) == []
    assert list(scan_registry_markdown_many(vault_root, [child_root], _SCOPE_GLOB)) == []


def test_watcher_enumeration_keeps_symlinked_selected_vault_namespace(tmp_path: Path) -> None:
    real_root, selected_root = _symlinked_selected_root(tmp_path)
    child_root = _build_parent_with_nested_child(real_root)
    (real_root / "notes" / "link-to-secret.md").symlink_to(child_root / "Secret Plan.md")

    expected = {"notes/Parent Note.md", "projects/Roadmap.md"}

    snapshot = _scan_md_files(selected_root)
    assert set(snapshot) == expected

    watcher = VaultWatcher(selected_root, snapshot_path=selected_root / ".state.json")
    result = watcher.run()
    changed_paths = {path.relative_to(selected_root).as_posix() for path in result.changed}
    assert changed_paths == expected

    watcher_entries = list(_scan_markdown_many(selected_root, [selected_root], _SCOPE_GLOB))
    assert all(path.is_relative_to(selected_root) for _rel, _mtime, path in watcher_entries)
    watcher_scan = {rel.as_posix() for rel, _mtime, _path in watcher_entries}
    assert watcher_scan == expected

    registry_entries = list(scan_registry_markdown_many(selected_root, [selected_root], _SCOPE_GLOB))
    assert all(path.is_relative_to(selected_root) for _rel, _mtime, path in registry_entries)
    registry_scan = {rel.as_posix() for rel, _mtime, _path in registry_entries}
    assert registry_scan == expected
