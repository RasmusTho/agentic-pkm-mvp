from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.stores import get_object_store, reset_store_backends


def test_orchestrate_external_command(tmp_path: Path) -> None:
    reset_store_backends()
    root = tmp_path / "drop"
    root.mkdir()
    (root / "clip.txt").write_text("external via orchestrator", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrate-external", "--root", str(root)])
    assert result.exit_code == 0, result.output

    store = get_object_store()
    assert len(getattr(store, "_objects", {})) >= 1
