from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner
import yaml

from app.cli import cli
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR
from app import objects as object_store_module


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


def test_uat_seed_cli_extends_ingest_scope_with_test_folder(tmp_path: Path) -> None:
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

    override_path = tmp_path / "settings" / "ingest.override.md"
    assert override_path.exists()
    assert not (tmp_path / "⚙️ System" / "settings" / "ingest.override.md").exists()

    raw = override_path.read_text(encoding="utf-8")
    parts = raw.split("---", 2)
    payload = yaml.safe_load(parts[1])
    assert payload["include_folders"] == [DEFAULT_TARGET_SUBDIR]


def test_uat_seed_reads_legacy_override_but_writes_only_canonical(tmp_path: Path) -> None:
    legacy = tmp_path / "Meta" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "---\ninclude_folders:\n  - Existing\n---\n",
        encoding="utf-8",
    )
    layout = tmp_path / "Meta" / "vault.layout.md"
    layout.write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    original_legacy = legacy.read_text(encoding="utf-8")
    runner = CliRunner()

    with patch(
        "app.cli.uat.emit_settings_write_receipts_for_changes"
    ) as emit_receipts:
        result = runner.invoke(
            cli,
            ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
            env={"STORE_BACKEND": "memory"},
        )

    assert result.exit_code == 0, result.output
    canonical = tmp_path / "settings" / "ingest.override.md"
    payload = yaml.safe_load(canonical.read_text(encoding="utf-8").split("---", 2)[1])
    assert payload["include_folders"] == ["Existing", DEFAULT_TARGET_SUBDIR]
    assert legacy.read_text(encoding="utf-8") == original_legacy
    emit_receipts.assert_called_once()
    assert emit_receipts.call_args.kwargs["file"] == canonical
    assert emit_receipts.call_args.kwargs["require_durable"] is True


def test_uat_seed_canonical_override_shadows_legacy(tmp_path: Path) -> None:
    legacy = tmp_path / "Meta" / "settings" / "ingest.override.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("---\ninclude_folders: [Legacy]\n---\n", encoding="utf-8")
    (tmp_path / "Meta" / "vault.layout.md").write_text(
        "---\nsystem_folder: Meta\ninbox_folder: Inbox\ndesk_folder: Desk\n---\n",
        encoding="utf-8",
    )
    canonical = tmp_path / "settings" / "ingest.override.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("---\ninclude_folders: [Canonical]\n---\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        ["uat-seed-vault-test", "--vault-root", str(tmp_path)],
        env={"STORE_BACKEND": "memory"},
    )

    assert result.exit_code == 0, result.output
    payload = yaml.safe_load(canonical.read_text(encoding="utf-8").split("---", 2)[1])
    assert payload["include_folders"] == ["Canonical", DEFAULT_TARGET_SUBDIR]
    assert "Legacy" not in payload["include_folders"]
