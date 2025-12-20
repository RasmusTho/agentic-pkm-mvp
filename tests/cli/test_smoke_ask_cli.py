from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def test_smoke_ask_cli(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    outbox = tmp_path / "outbox.jsonl"
    env = {
        "STORE_BACKEND": "memory",
        "POLICY_ENFORCE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "INDEX_OUTBOX_PATH": str(outbox),
        "PANEL_AGENT_PIPELINE": "planner",
        "LLM_PROVIDER": "mock",
        "EMBED_DIM": "1536",
    }

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "smoke",
            "ask",
            "--vault",
            str(vault),
            "--outbox",
            str(outbox),
            "--query",
            "What is the capital of Sweden?",
            "--json",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    payload = result.output.strip().splitlines()[-1]
    data = json.loads(payload)
    assert data.get("mutations") is True
    citations = data.get("citations") or []
    assert len(citations) >= 1
    note_path = Path(data.get("note_path") or "")
    assert note_path.exists()
    assert str(note_path).startswith(str(vault))
