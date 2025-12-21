import json
from datetime import datetime, UTC
from pathlib import Path

from click.testing import CliRunner

from app.cli import health
from app.health_contract import HealthContract, HealthStateMachine, reset_state_machine


def _write_health_markdown(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{body}---\n", encoding="utf-8")


def test_health_incident_logging(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    settings_path = vault / "@System" / "Settings" / "health.md"
    log_path = tmp_path / "incidents.jsonl"
    _write_health_markdown(
        settings_path,
        f"""
thresholds:
  outbox_degrade_oldest_age_s: 15.0
  outbox_recover_oldest_age_s: 5.0
  degrade_samples: 1
  recover_samples: 10
incident_capture:
  enabled: true
  transition_history: true
policy:
  env_overrides: false
incident_log_path: "{log_path}"
""",
    )
    outbox = tmp_path / "outbox.jsonl"
    records = [
        {"event": "watcher.run", "timestamp": "2000-01-01T00:00:00Z", "trace_id": "t"},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(
        "app.index.doctor.diagnose_index",
        lambda: {
            "backend": "mock",
            "expected_identity": None,
            "stored_identity": None,
            "issues": [],
            "warnings": [],
        },
    )

    contract = HealthContract(
        state_machine=HealthStateMachine(),
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=UTC),
        vault_root_fn=lambda: vault,
    )
    result = contract.evaluate()
    assert result["state"] == "degraded"
    assert log_path.exists()
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["state"] == "degraded"
    assert entry["settings_source"]["path"] == str(settings_path)
    assert entry["catch_up_progress"]["processing_mode"] == "replay"
    assert entry["recent_transition_history"]
    assert entry["recent_transition_history"][0]["state"] == "degraded"


def test_health_incidents_compose_cli(monkeypatch, tmp_path: Path) -> None:
    reset_state_machine()
    vault = tmp_path / "vault"
    settings_path = vault / "@System" / "Settings" / "health.md"
    log_path = tmp_path / "incidents.jsonl"
    _write_health_markdown(
        settings_path,
        f"""
thresholds:
  outbox_degrade_oldest_age_s: 15.0
  outbox_recover_oldest_age_s: 5.0
  degrade_samples: 1
  recover_samples: 10
incident_capture:
  enabled: true
  transition_history: true
policy:
  env_overrides: false
incident_log_path: "{log_path}"
""",
    )
    outbox = tmp_path / "outbox.jsonl"
    records = [
        {"event": "watcher.run", "timestamp": "2000-01-01T00:00:00Z", "trace_id": "cli"},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setattr(
        "app.health_contract.diagnose_index",
        lambda: {
            "backend": "mock",
            "expected_identity": None,
            "stored_identity": None,
            "issues": [],
            "warnings": [],
        },
    )

    runner = CliRunner()
    result = runner.invoke(health, ["status", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["state"] in {"degraded", "safe_mode", "unhealthy"}
    assert payload["outbox_oldest_age_s"] > 0
    assert payload["settings_source"]["path"] == str(settings_path)
    assert payload["recent_transition_history"]
    assert payload["suggested_actions"], "Expected suggested actions"
    assert log_path.exists()
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["state"] == payload["state"]
    tail = runner.invoke(health, ["incidents", "tail", "--n", "1"])
    assert tail.exit_code == 0
    tail_lines = [line for line in tail.output.strip().splitlines() if line]
    assert tail_lines, "Expected incident tail output"
    tail_entry = json.loads(tail_lines[-1])
    required = [
        "state",
        "reason",
        "settings_source",
        "outbox_count",
        "outbox_oldest_age_s",
        "index_doctor_status",
        "events_doctor_status",
        "suggested_actions",
        "recent_transition_history",
    ]
    for key in required:
        assert key in tail_entry
    assert tail_entry["state"] == entry["state"]


def test_health_incidents_tail_no_file(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    settings_path = vault / "@System" / "Settings" / "health.md"
    missing_log = tmp_path / "missing-incidents.jsonl"
    _write_health_markdown(
        settings_path,
        f"""
thresholds:
  outbox_degrade_oldest_age_s: 15.0
  outbox_recover_oldest_age_s: 5.0
  degrade_samples: 1
  recover_samples: 10
incident_capture:
  enabled: true
  transition_history: true
policy:
  env_overrides: false
incident_log_path: "{missing_log}"
""",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    runner = CliRunner()
    result = runner.invoke(health, ["incidents", "tail", "--n", "1"])
    assert result.exit_code == 0
    lines = [line for line in result.output.strip().splitlines() if line]
    assert lines[0] == f"No incidents yet (path: {missing_log})"
    assert "Trigger degraded/safe_mode" in lines[1]
