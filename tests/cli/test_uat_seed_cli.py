from pathlib import Path

from click.testing import CliRunner

from app.cli import cli
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR
from app.store import object_store as object_store_module


def test_uat_seed_cli_copies_notes(tmp_path: Path) -> None:
    runner = CliRunner()
    env = {"STORE_BACKEND": "memory"}

    result = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert result.exit_code == 0, result.output

    dest = tmp_path / DEFAULT_TARGET_SUBDIR / DEFAULT_FOLDER_NAME
    files = sorted(dest.glob("*.md"))
    assert files, "expected seed files to be copied"

    target = dest / "evergreen-strategy.md"
    original = target.read_text(encoding="utf-8")

    target.write_text("changed", encoding="utf-8")
    result_no_overwrite = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
        ],
        env=env,
    )
    assert result_no_overwrite.exit_code == 0, result_no_overwrite.output
    assert target.read_text(encoding="utf-8") == "changed"

    result_overwrite = runner.invoke(
        cli,
        [
            "uat-seed-vault-test",
            "--vault-root",
            str(tmp_path),
            "--overwrite",
        ],
        env=env,
    )
    assert result_overwrite.exit_code == 0, result_overwrite.output
    assert target.read_text(encoding="utf-8") == original

    object_store_module._MEMORY_STORE.clear()
