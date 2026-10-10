from __future__ import annotations

from click.testing import CliRunner

from app.cli.embed_probe import embed_probe


def test_embed_probe_dim_stable_mock(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_FORCE_PROVIDER", "mock")
    monkeypatch.delenv("MODEL_ACCESS_CODEX_VLAN_ENDPOINT", raising=False)
    runner = CliRunner()
    result = runner.invoke(embed_probe, [])
    assert result.exit_code == 0, result.output
    assert "Provider profile=default" in result.output
    assert "provider=mock" in result.output
    assert "dim=" in result.output
