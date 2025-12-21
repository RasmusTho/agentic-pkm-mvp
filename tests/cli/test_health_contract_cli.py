import json
from pathlib import Path
from uuid import uuid4

from click.testing import CliRunner

from app.cli import health
from app.health_contract import reset_state_machine


def _write_health_markdown(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{body}---\n", encoding="utf-8")


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
    assert payload["recent_transition_history"] is None
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


def test_health_incidents_tail_cli(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    log_path = tmp_path / "incidents.log"
    lines = ["{\"id\": 1}", "{\"id\": 2}", "{\"id\": 3}"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings_path = vault / "@System" / "Settings" / "health.md"
    _write_health_markdown(
        settings_path,
        f"""
thresholds:
  outbox_degrade_oldest_age_s: 15.0
  outbox_recover_oldest_age_s: 5.0
  degrade_samples: 3
  recover_samples: 10
incident_capture:
  enabled: false
  transition_history: false
policy:
  env_overrides: false
incident_log_path: "{log_path}"
""",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))

    result = CliRunner().invoke(health, ["incidents", "tail", "--n", "2"])
    assert result.exit_code == 0
    assert result.output.strip().splitlines() == lines[-2:]


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
