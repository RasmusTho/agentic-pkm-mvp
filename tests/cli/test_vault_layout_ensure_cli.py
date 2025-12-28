from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def test_vault_layout_ensure_cli_json(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "vault-layout-ensure",
            "--vault-root",
            str(vault_root),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["system_folder"] == "~system"
    assert payload["inbox_folder"] == "@Inbox"
    assert payload["desk_folder"] == "@Desk"
    assert payload["layout_note"].endswith("~system/vault.layout.md")
    assert "warnings" in payload
    assert "migrated_legacy_system" in payload
