from __future__ import annotations

import time
from pathlib import Path

from app.watcher.vault_watcher import VaultWatcher, compute_changes, load_snapshot, save_snapshot


def _write_note(base: Path, rel: str, content: str = "Body") -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_first_run_marks_all_changed(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write_note(vault, "Concepts/A.md")
    _write_note(vault, "Concepts/B.md")

    watcher = VaultWatcher(vault, snapshot_path=vault / ".state.json")
    result = watcher.run()

    assert set(p.relative_to(vault) for p in result.changed) == {
        Path("Concepts/A.md"),
        Path("Concepts/B.md"),
    }
    assert result.deleted == []
    assert load_snapshot(vault / ".state.json")


def test_second_run_detects_only_modified(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    a = _write_note(vault, "Concepts/A.md")
    b = _write_note(vault, "Concepts/B.md")

    watcher = VaultWatcher(vault, snapshot_path=vault / ".state.json")
    first = watcher.run()
    assert len(first.changed) == 2

    time.sleep(0.01)
    b.write_text("Updated", encoding="utf-8")

    second = watcher.run()
    assert second.deleted == []
    assert set(p.relative_to(vault) for p in second.changed) == {Path("Concepts/B.md")}


def test_detects_new_and_deleted_files(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    a = _write_note(vault, "Concepts/A.md")
    _write_note(vault, "Concepts/B.md")

    snapshot_path = vault / ".state.json"
    save_snapshot(snapshot_path, {"Concepts/A.md": a.stat().st_mtime})

    changed, deleted, current = compute_changes(vault, load_snapshot(snapshot_path))
    assert set(p.relative_to(vault) for p in changed) == {Path("Concepts/B.md")}
    assert set(p.relative_to(vault) for p in deleted) == set()
    assert "Concepts/A.md" in current
    assert "Concepts/B.md" in current
