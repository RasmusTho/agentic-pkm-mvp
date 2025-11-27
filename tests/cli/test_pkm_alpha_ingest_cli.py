from pathlib import Path

from click.testing import CliRunner

from app.cli import cli


def test_pkm_alpha_ingest_uses_default_root(tmp_path, monkeypatch):
    fake_root = tmp_path / "pkm-alpha"
    fake_root.mkdir()

    called: dict[str, Path | int | None] = {}

    def fake_ingest(root: Path, limit: int | None = None) -> int:
        called["root"] = root
        called["limit"] = limit
        return 1

    monkeypatch.setattr("app.cli.DEFAULT_VAULT_ROOT", fake_root)
    monkeypatch.setattr("app.cli.ingest_vault_root", fake_ingest)

    runner = CliRunner()
    result = runner.invoke(cli, ["pkm-alpha-ingest", "--limit", "1"])

    assert result.exit_code == 0, result.output
    assert called["root"] == fake_root
    assert called["limit"] == 1
    assert "Successfully ingested" in result.output
