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
    assert payload["environment"] in {"dev", "prod"}
    assert payload["state"] in {"running", "catch_up", "degraded", "recovery"}
    assert payload["index_doctor_status"] == "pass"
    assert payload["events_doctor_status"] == "pass"
    assert payload["errors_last_10m"] >= 0
    assert payload["settings_status"] in {"ok", "missing", "fail"}
    assert payload["thresholds"]["outbox_degrade_oldest_age_s"] > 0
    assert payload["settings_source"]["path"].endswith("health.md")
    assert payload["writes_allowed"] is True
    assert payload["write_guard_reason"] is None


def test_health_status_cli_environment_explicit_dev(monkeypatch, tmp_path: Path) -> None:
    """Test that health status surfaces explicit dev environment."""
    reset_state_machine()
    monkeypatch.setenv("PKM_ENVIRONMENT", "dev")
    outbox = tmp_path / "outbox.jsonl"
    now = uuid4()
    records = [
        {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z", "trace_id": str(now)},
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
    assert payload["environment"] == "dev"


def test_health_status_cli_environment_explicit_prod(monkeypatch, tmp_path: Path) -> None:
    """Test that health status surfaces explicit prod environment."""
    reset_state_machine()
    monkeypatch.setenv("PKM_ENVIRONMENT", "prod")
    outbox = tmp_path / "outbox.jsonl"
    now = uuid4()
    records = [
        {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z", "trace_id": str(now)},
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
    assert payload["environment"] == "prod"
