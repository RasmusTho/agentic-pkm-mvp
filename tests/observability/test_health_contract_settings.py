import json
from datetime import UTC, datetime
from pathlib import Path

from app.health_contract import HealthContract, HealthStateMachine
from app.settings.health_settings import HealthThresholds
from app.vault.paths import get_vault_system_dir_rel


def _mock_index_doctor() -> dict:
    return {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    }


def _write_health_markdown(path, thresholds_block: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{thresholds_block}---\n", encoding="utf-8")


def _prepare_outbox(tmp_path) -> Path:
    outbox = tmp_path / "outbox.jsonl"
    records = [
        {"event": "watcher.run", "timestamp": "2024-01-01T00:00:00Z", "trace_id": "1"},
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return outbox


def test_health_contract_uses_vault_thresholds(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(_prepare_outbox(tmp_path)))
    monkeypatch.setattr("app.index.doctor.diagnose_index", lambda: _mock_index_doctor())
    vault = tmp_path / "vault"
    settings_path = vault / get_vault_system_dir_rel(vault) / "Settings" / "health.md"
    _write_health_markdown(
        settings_path,
        """
thresholds:
  outbox_degrade_oldest_age_s: 20.5
  outbox_recover_oldest_age_s: 3.0
  degrade_samples: 4
  recover_samples: 12
incident_capture:
  enabled: true
  transition_history: false
policy:
  env_overrides: false
""",
    )
    contract = HealthContract(
        state_machine=HealthStateMachine(),
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=UTC),
        vault_root_fn=lambda: vault,
    )
    result = contract.evaluate()
    assert result["settings_status"] == "ok"
    assert result["thresholds"]["outbox_degrade_oldest_age_s"] == 20.5
    assert result["settings_source"]["path"] == str(settings_path)


def test_health_contract_invalid_settings_fallbacks(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(_prepare_outbox(tmp_path)))
    monkeypatch.setattr("app.index.doctor.diagnose_index", lambda: _mock_index_doctor())
    vault = tmp_path / "vault"
    settings_path = vault / get_vault_system_dir_rel(vault) / "Settings" / "health.md"
    _write_health_markdown(
        settings_path,
        """
thresholds:
  outbox_degrade_oldest_age_s: 1.0
  outbox_recover_oldest_age_s: 0.5
""",
    )
    contract = HealthContract(
        state_machine=HealthStateMachine(),
        now_fn=lambda: datetime(2025, 1, 1, tzinfo=UTC),
        vault_root_fn=lambda: vault,
    )
    result = contract.evaluate()
    assert result["settings_status"] == "fail"
    assert result["thresholds"] == HealthThresholds.defaults().to_payload()
    assert any("thresholds.degrade_samples" in err for err in result["settings_errors"])
    assert result["settings_source"]["path"] == str(settings_path)
