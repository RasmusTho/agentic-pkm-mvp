from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from app.cli import cli as root_cli
import app.cli as cli_module


def test_panel_update_writes_via_knowledge_port(monkeypatch, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("Original", encoding="utf-8")
    captured: dict[str, str] = {}

    def _fake_write(path: Path, content: str, *, vault_root: Path | None = None):  # type: ignore[no-untyped-def]
        captured["path"] = Path(path).resolve().relative_to(Path(path).anchor).as_posix()
        captured["content"] = content
        return None

    fake_result = SimpleNamespace(
        panel=SimpleNamespace(updated_markdown="Updated", intents=[]),
        events=[],
        dispatch_count=0,
        plans=[],
    )

    monkeypatch.setattr(cli_module, "handle_panel_update", lambda **kwargs: fake_result)
    monkeypatch.setattr(cli_module, "write_note_from_absolute", _fake_write)

    runner = CliRunner()
    result = runner.invoke(root_cli, ["panel-update", str(note)])
    assert result.exit_code == 0
    expected_rel = note.resolve().relative_to(Path(note.anchor)).as_posix()
    assert captured["path"] == expected_rel
    assert captured["content"] == "Updated"
