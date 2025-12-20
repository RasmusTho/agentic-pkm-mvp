from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def test_smoke_reality_cli(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    outbox = tmp_path / "outbox.jsonl"
    env = {
        "STORE_BACKEND": "memory",
        "POLICY_ENFORCE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "INDEX_OUTBOX_PATH": str(outbox),
    }

    runner = CliRunner()
    result = runner.invoke(cli, ["smoke", "reality", "--vault", str(vault), "--outbox", str(outbox), "--json"], env=env)

    assert result.exit_code == 0, result.output
    payload = result.output.strip().splitlines()[-1]
    data = json.loads(payload)
    assert data["append_plan"]["status"] == "ok"
    assert Path(data["outbox_path"]).exists()
    assert Path(data["outbox_path"]).read_text(encoding="utf-8").strip()
    created_dir = vault / "_mcp"
    assert created_dir.exists()
    assert list(created_dir.glob("*.md"))
