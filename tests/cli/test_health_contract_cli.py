import importlib
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
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
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


def test_run_health_does_not_create_default_outbox_path(
    monkeypatch, tmp_path: Path
) -> None:
    """Health inspection must not create the producer-owned outbox path."""
    health_module = importlib.import_module("app.cli.health")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("INDEX_OUTBOX_PATH", raising=False)

    def ok(*args, **kwargs):
        return {"ok": True, "detail": "ok"}

    for name in (
        "_check_ffmpeg",
        "_check_yt_dlp",
        "_check_dead_letters",
        "_check_panel_actions",
        "_check_ollama",
        "_check_obsidian_dependencies",
        "_check_llm_router",
        "_check_llm_providers",
        "_check_embedding_index",
        "_check_companion_diagnostics",
    ):
        monkeypatch.setattr(health_module, name, ok)
    monkeypatch.setattr(health_module, "_check_llm_task_routes", ok)
    monkeypatch.setattr(health_module, "_watcher_runtime_status", lambda: {"ok": True})
    monkeypatch.setattr(health_module, "_worker_runtime_status", lambda: {"ok": True})
    monkeypatch.setattr(health_module, "_db_runtime_status", lambda: {"ok": True})
    monkeypatch.setattr(health_module, "_llm_runtime_status", lambda *_args: {"ok": True})
    monkeypatch.setattr(health_module, "_settings_ingestion_status", lambda: {})
    monkeypatch.setattr(health_module, "check_v6_seams", lambda: {})
    monkeypatch.setattr(health_module, "get_runtime_version", lambda: {"git_sha": "test"})

    result = health_module.run_health()
    outbox_path = tmp_path / "tmp" / "index-outbox.jsonl"

    assert result["checks"]["index_outbox"]["ok"] is False
    assert result["checks"]["index_outbox"]["data"]["status"] == "missing"
    assert not outbox_path.exists()
    assert not outbox_path.parent.exists()


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
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
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
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
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
