from datetime import datetime, timezone

from click.testing import CliRunner

from app.cli import cli
from app.observability.status_model import (
    AskStatus,
    EventCounters,
    IngestionPlaneStatus,
    IngestionStatus,
    IntentStatus,
    StoreStatus,
    SystemStatus,
    WatcherAutomationStatus,
    WatcherLifecycleStatus,
)


def test_status_cli_prints_snapshot(monkeypatch):
    snapshot = SystemStatus(
        timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        environment="prod",
        sot_version="vX",
        sot_baseline_version="v5.5",
        sot_forward_line_version="v5.6",
        sot_label="baseline v5.5 (Reality-MVP), forward v5.6 (LangGraph + Reasoning)",
        feature_line_version="v5.6",
        active_features=["PanelAgent runtime", "Watcher"],
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
        intents=IntentStatus(promote_created_total=2, promote_created_24h=1, source_path="/tmp/outbox.jsonl"),
        events=EventCounters(
            watcher_runs_total=4,
            watcher_runs_24h=2,
            panel_runs_total=3,
            panel_runs_24h=2,
            promote_created_total=2,
            promote_created_24h=1,
            promotion_executed_total=2,
            promotion_executed_24h=1,
            ingest_runs_by_plane={"vault": 1, "external": 1},
            source_path="/tmp/outbox.jsonl",
        ),
        watcher_automation=WatcherAutomationStatus(
            auto_exec_enabled=True,
            mode="auto-exec",
            source="env",
            env_key="WATCHER_AUTO_EXEC",
            raw_value="1",
            default_enabled=False,
            allowed_actions=["promote.evergreen"],
            invalid_allowed_actions=[],
            source_path="/tmp/watchers.md",
            tick_log_path="/tmp/watcher_tick.jsonl",
            panel_event_log_path="/tmp/outbox.jsonl",
            writes_allowed=True,
            write_guard_mode="open",
            last_tick_timestamp="2025-01-01T00:00:00Z",
            last_tick_panel_candidates=2,
            last_tick_panel_skipped_policy=1,
            last_tick_panel_skipped_auto_exec=0,
            last_run_skipped_dedup=1,
            last_run_skipped_idempotent=0,
            last_run_skipped_writes_blocked=0,
            last_run_skipped_allowed_actions=0,
        ),
    )
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot)

    runner = CliRunner()
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Environment: prod" in result.output
    assert "SoT baseline: v5.5" in result.output
    assert "SoT forward line: v5.6" in result.output
    assert "Active features:" in result.output
    assert "panelagent runtime" in result.output.lower()
    assert "vault: 2 objects" in result.output
    assert "queries (24h): 3" in result.output
    assert "errors (24h): 1" in result.output
    assert "totals: scanned=5 ingested=4 errors=1 malformed=0" in result.output
    assert "vault: scanned=3 ingested=2 errors=1 malformed=0" in result.output
    assert "panel runs: total=3" in result.output
    assert "promotion intents:" in result.output
    assert "total=2 (24h=1)" in result.output
    assert "promotion executed:" in result.output
    assert "watcher runs: total=4" in result.output
    assert "Watcher automation:" in result.output
    assert "gate: auto-exec (enabled=True, source=env, env=WATCHER_AUTO_EXEC, raw=1, default=False)" in result.output
    assert "allowlist: promote.evergreen" in result.output
    assert "last_run_skips: dedup=1" in result.output
    assert "ingest runs by plane:" in result.output
    assert "source: /tmp/outbox.jsonl" in result.output


def _minimal_system_status(**overrides) -> SystemStatus:
    base = dict(
        timestamp=datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        environment="prod",
        sot_version="vX",
        sot_baseline_version="v5.5",
        sot_forward_line_version="v5.6",
        sot_label="test",
        active_features=[],
        stores=[],
        ingestion=IngestionStatus(),
        ask=AskStatus(total_queries_24h=0),
    )
    base.update(overrides)
    return SystemStatus(**base)


def test_status_reports_last_panel_run_when_latest_tick_has_zero_candidates(monkeypatch):
    lifecycle = WatcherLifecycleStatus(
        panel_changed_total=2162,
        panel_emitted_total=41,
        panel_rate_limited_total=2114,
        last_panel_run_at="2026-05-15T17:49:16Z",
        last_panel_run_actions_count=2,
        last_panel_run_executed_count=1,
        last_panel_run_summary="triggered: promote.evergreen",
    )
    automation = WatcherAutomationStatus(
        last_tick_timestamp="2026-05-15T17:50:00Z",
        last_tick_panel_candidates=0,
    )
    snapshot = _minimal_system_status(
        watcher_automation=automation,
        watcher_lifecycle=lifecycle,
    )
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot)

    runner = CliRunner()
    result = runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Watcher lifecycle:" in result.output
    assert "last_panel_run:" in result.output
    assert "2026-05-15T17:49:16Z" in result.output
    assert "actions=2" in result.output
    assert "executed=1" in result.output


def test_status_distinguishes_zero_action_panel_run_from_no_run(monkeypatch):
    lifecycle_zero = WatcherLifecycleStatus(
        panel_changed_total=10,
        panel_emitted_total=1,
        panel_rate_limited_total=0,
        last_panel_run_at="2026-05-15T12:00:00Z",
        last_panel_run_actions_count=0,
        last_panel_run_executed_count=0,
    )
    snapshot_zero = _minimal_system_status(watcher_lifecycle=lifecycle_zero)
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot_zero)

    runner = CliRunner()
    result_zero = runner.invoke(cli, ["status"])
    assert result_zero.exit_code == 0, result_zero.output
    assert "actions=0" in result_zero.output

    lifecycle_no_run = WatcherLifecycleStatus(
        panel_changed_total=10,
        panel_emitted_total=0,
        panel_rate_limited_total=0,
        last_panel_run_at=None,
    )
    snapshot_no_run = _minimal_system_status(watcher_lifecycle=lifecycle_no_run)
    monkeypatch.setattr("app.cli.get_system_status", lambda: snapshot_no_run)

    result_no_run = runner.invoke(cli, ["status"])
    assert result_no_run.exit_code == 0, result_no_run.output
    assert "last_panel_run: none" in result_no_run.output
    assert "actions=0" not in result_no_run.output
