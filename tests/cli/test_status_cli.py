from datetime import datetime, timezone

from click.testing import CliRunner

from app.cli import cli
from app.observability.status_model import (
    AskStatus,
    IngestionPlaneStatus,
    IngestionStatus,
    StoreStatus,
    SystemStatus,
)


def test_status_cli_prints_snapshot(monkeypatch):
    snapshot = SystemStatus(
        timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        sot_version="vX",
        sot_baseline_version="v4.10",
        sot_forward_line_version="v5.4",
        sot_label="baseline v4.10 (Reality-MVP), forward v5.4 (PanelAgent + Watchers)",
        stores=[
            StoreStatus(name="vault", object_count=2, last_ingest_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
            StoreStatus(name="external", object_count=1, last_ingest_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        ],
        ingestion=IngestionStatus(
            last_run_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            last_run_ok=True,
            last_error_message=None,
            total_scanned=5,
            total_ingested=4,
            total_errors=1,
            total_malformed=0,
            planes=[
                IngestionPlaneStatus(
                    plane="vault",
                    last_run_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    last_run_ok=False,
                    scanned=3,
                    ingested=2,
                    errors=1,
                    malformed=0,
                ),
                IngestionPlaneStatus(
                    plane="external",
                    last_run_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    last_run_ok=True,
                    scanned=2,
                    ingested=2,
                    errors=0,
                    malformed=0,
                ),
            ],
        ),
        ask=AskStatus(total_queries_24h=3, avg_latency_ms_24h=120.0, error_count_24h=1),
    )
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot)

    runner = CliRunner()
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "SoT baseline: v4.10" in result.output
    assert "SoT forward line: v5.4" in result.output
    assert "vault: 2 objects" in result.output
    assert "queries (24h): 3" in result.output
    assert "errors (24h): 1" in result.output
    assert "totals: scanned=5 ingested=4 errors=1 malformed=0" in result.output
    assert "vault: scanned=3 ingested=2 errors=1 malformed=0" in result.output
