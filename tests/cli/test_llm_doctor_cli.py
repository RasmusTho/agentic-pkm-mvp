from __future__ import annotations

import json
from click.testing import CliRunner

from app.cli import cli


def test_llm_check_reports_unreachable(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    runner = CliRunner()
    result = runner.invoke(cli, ["llm", "check", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data.get("ok") is False
    assert data.get("error")
    assert data.get("url", "").endswith("/api/tags")


def test_llm_check_strict_fails(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    runner = CliRunner()
    result = runner.invoke(cli, ["llm", "check", "--json", "--strict"])
    assert result.exit_code != 0
    data = json.loads(result.output)
    assert data.get("ok") is False
