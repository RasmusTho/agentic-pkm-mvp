from __future__ import annotations

from pathlib import Path

from app.settings.yggdrasil_scaffolder import YggdrasilScaffolder


def test_scaffolder_writes_placeholder_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    writes: list[str] = []
    mimer_root = tmp_path / "Mimer"

    def _fake_write_note(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        resolved_root = (vault_root or tmp_path).resolve()
        resolved_path = Path(path).resolve()
        rel = resolved_path.relative_to(resolved_root).as_posix()
        writes.append(rel)
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(content, encoding="utf-8")
        return None

    monkeypatch.setattr("app.settings.yggdrasil_scaffolder.write_note_from_absolute", _fake_write_note)

    result = YggdrasilScaffolder(root=tmp_path).scaffold()

    assert (mimer_root / "@Settings" / "global.md").exists()
    assert (mimer_root / "@Settings" / "system-settings.yaml").exists()
    assert "@Settings/global.md" in writes
    assert "@Settings/system-settings.yaml" in writes
    assert result["created"]
