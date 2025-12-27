from __future__ import annotations

import json

from click.testing import CliRunner

from app.cli import cli
from app.stores import reset_store_backends


def test_store_stats_memory(monkeypatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    runner = CliRunner()
    result = runner.invoke(cli, ["store-stats", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output.strip())
    assert data.get("backend") == "memory"
    assert data.get("objects") == 0
    assert data.get("vectors") == 0
