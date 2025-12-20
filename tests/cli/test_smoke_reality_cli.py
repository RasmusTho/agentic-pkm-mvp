from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def test_smoke_reality_cli(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outbox = tmp_path / "outbox.jsonl"
    env = {
        "STORE_BACKEND": "memory",
        "POLICY_ENFORCE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "INDEX_OUTBOX_PATH": str(outbox),
        "PANEL_AGENT_PIPELINE": "planner",
    }

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["smoke", "reality", "--vault", str(vault), "--outbox", str(outbox), "--runs", "2", "--json"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    payload = result.output.strip().splitlines()[-1]
    data = json.loads(payload)
    runs = data.get("runs") or []
    assert len(runs) >= 2
    assert runs[0].get("mutations") is True
    assert runs[1].get("mutations") is False
    assert runs[0].get("note_hash_after") == runs[1].get("note_hash_after")
    outbox_path = Path(data["outbox_path"])
    assert outbox_path.exists()
    assert outbox_path.read_text(encoding="utf-8").strip()
    created_dir = vault / "_mcp"
    assert created_dir.exists()
    assert list(created_dir.glob("*.md"))
