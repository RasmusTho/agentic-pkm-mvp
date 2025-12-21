import json
from datetime import datetime, UTC
from pathlib import Path

from app.health_contract import HealthContract, HealthStateMachine


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
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["state"] == "degraded"
    assert entry["settings_source"]["path"] == str(settings_path)
    assert entry["catch_up_progress"]["processing_mode"] == "replay"
    assert entry["recent_transition_history"]
    assert entry["recent_transition_history"][0]["state"] == "degraded"
