from __future__ import annotations

from pathlib import Path

from app.settings.mimer_scaffolder import MimerScaffolder


def test_scaffolder_writes_placeholder_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    writes: list[str] = []
    mimer_root = tmp_path / "Mimer"

    def _fake_write_note(path: Path, content: str, *, vault_root: Path | None = None, **_kwargs):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or tmp_path).resolve()
        resolved_path = Path(path).resolve()
        rel = resolved_path.relative_to(resolved_root).as_posix()
        writes.append(rel)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr("app.settings.mimer_scaffolder.write_note_from_absolute", _fake_write_note)

    result = MimerScaffolder(root=tmp_path).scaffold()

    assert (mimer_root / "settings" / "global.md").exists()
    assert (mimer_root / "settings" / "system-settings.md").exists()
    assert "settings/global.md" in writes
    assert "settings/system-settings.md" in writes
    assert result["created"]
