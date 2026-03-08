from __future__ import annotations

from pathlib import Path

from app.settings.yggdrasil_scaffolder import YggdrasilScaffolder


def test_scaffolder_writes_placeholder_via_knowledge_port(tmp_path: Path, monkeypatch) -> None:
    writes: list[str] = []
    mimer_root = tmp_path / "Mimer"

    class FakePort:
        def write_note(self, locator, content):  # type: ignore[no-untyped-def]
            writes.append(locator.path)
            target = (mimer_root / locator.path).resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return None

    monkeypatch.setattr(
        "app.settings.yggdrasil_scaffolder.resolve_knowledge_port",
        lambda **kwargs: FakePort(),
    )

    result = YggdrasilScaffolder(root=tmp_path).scaffold()

    assert (mimer_root / "@Settings" / "global.md").exists()
    assert "@Settings/global.md" in writes
    assert result["created"]
