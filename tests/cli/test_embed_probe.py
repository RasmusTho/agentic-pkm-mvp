from __future__ import annotations

from click.testing import CliRunner

from app.cli.embed_probe import embed_probe


def test_embed_probe_dim_stable_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    runner = CliRunner()
    result = runner.invoke(embed_probe, [])
    assert result.exit_code == 0, result.output
    assert "Provider profile=default" in result.output
    assert "dim=" in result.output
