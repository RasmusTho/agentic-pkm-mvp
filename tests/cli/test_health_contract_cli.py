import json
from pathlib import Path
from uuid import uuid4

from click.testing import CliRunner

from app.cli import health
from app.health_contract import reset_state_machine


def test_health_status_cli_json(monkeypatch, tmp_path: Path) -> None:
    reset_state_machine()
    outbox = tmp_path / "outbox.jsonl"
    now = uuid4()
    records = [
        {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z", "trace_id": str(now)},
        {"event": "ingest.error", "timestamp": "2024-01-01T00:02:00Z", "trace_id": str(now)},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setattr(
        "app.health_contract.diagnose_index",
        lambda: {
            "backend": "mock",
            "expected_identity": {"provider": "test"},
            "stored_identity": {"provider": "test"},
            "issues": [],
            "warnings": [],
        },
    )

    result = CliRunner().invoke(health, ["status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["state"] in {"running", "catch_up", "degraded", "recovery"}
    assert payload["index_doctor_status"] == "pass"
    assert payload["events_doctor_status"] == "pass"
    assert payload["errors_last_10m"] >= 0
    assert payload["settings_status"] in {"ok", "missing", "fail"}
    assert payload["thresholds"]["outbox_degrade_oldest_age_s"] > 0
    assert payload["settings_source"]["path"].endswith("health.md")
    assert payload["writes_allowed"] is True
    assert payload["write_guard_reason"] is None
    assert "catch_up_progress" in payload
    assert isinstance(payload["suggested_actions"], list)


def test_health_explain_cli(monkeypatch, tmp_path: Path) -> None:
    reset_state_machine()
    outbox = tmp_path / "outbox.jsonl"
    records = [
        {"event": "watcher.run", "timestamp": "2000-01-01T00:00:00Z", "trace_id": str(uuid4())},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setattr(
        "app.health_contract.diagnose_index",
        lambda: {
            "backend": "mock",
            "expected_identity": None,
            "stored_identity": None,
            "issues": [],
            "warnings": ["lag"],
        },
    )

    result = CliRunner().invoke(health, ["explain"])
    assert result.exit_code == 0
    output = result.output
    assert "State:" in output
    assert "Reason:" in output
    assert "Writes allowed: yes" in output
    assert "Index doctor: warn" in output
    assert "Events doctor:" in output
    assert "Catch-up progress:" in output
    assert "Suggested actions:" in output
    assert "- python -m app.cli events doctor --json" in output
    assert "- python -m app.cli index doctor --json" in output
