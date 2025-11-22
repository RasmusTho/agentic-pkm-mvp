from datetime import datetime

from click.testing import CliRunner

from app.cli import cli
from app.observability.status_model import AskStatus, IngestionStatus, StoreStatus, SystemStatus


def test_status_cli_prints_snapshot(monkeypatch):
    snapshot = SystemStatus(
        timestamp=datetime(2025, 1, 1, 0, 0, 0),
        sot_version="vX",
        stores=[StoreStatus(name="vault", object_count=2), StoreStatus(name="external", object_count=1)],
        ingestion=IngestionStatus(last_run_at=None, last_run_ok=True, last_error_message=None),
        ask=AskStatus(total_queries_24h=3, avg_latency_ms_24h=120.0),
    )
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot)

    runner = CliRunner()
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "SoT version: vX" in result.output
    assert "vault: 2 objects" in result.output
    assert "queries (24h): 3" in result.output
