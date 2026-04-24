"""Canvas CLI round-trip test (no Postgres required)."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

import app.cli as cli_module
from app.cli import cli


def _run(args: list[str], env: dict[str, str] | None = None):
    return CliRunner().invoke(cli, args, env=env, catch_exceptions=False)


def test_canvas_cli_open_edit_close_roundtrip(tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text("# Test\n\nOriginal.\n", encoding="utf-8")

    cli_module._canvas_sessions.clear()

    open_result = _run(
        ["canvas", "open", str(note), "--label", "roundtrip", "--vault-root", str(tmp_path)]
    )
    assert open_result.exit_code == 0, open_result.output
    session_id = None
    for line in open_result.output.splitlines():
        if line.startswith("session_id "):
            session_id = line.split(" ", 1)[1].strip()
    assert session_id, f"No session_id in output:\n{open_result.output}"

    edit_result = _run(
        [
            "canvas", "edit", session_id,
            "--body", "Edited content.",
            "--summary", "test edit",
            "--vault-root", str(tmp_path),
        ]
    )
    assert edit_result.exit_code == 0, edit_result.output
    assert "Edited content." in note.read_text(encoding="utf-8")

    close_result = _run(
        ["canvas", "close", session_id, "--summary", "done", "--vault-root", str(tmp_path)]
    )
    assert close_result.exit_code == 0, close_result.output
    assert "closed" in close_result.output

    # Session log must exist on disk
    logs = list(tmp_path.rglob("*.md"))
    session_logs = [p for p in logs if "canvas" in p.name or "roundtrip" in p.name]
    assert session_logs, f"No session log found under {tmp_path}; files: {[p.name for p in logs]}"
