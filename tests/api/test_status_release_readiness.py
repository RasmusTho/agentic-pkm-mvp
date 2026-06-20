from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import health as health_route
from app.observability import status_service
from app.observability.status_model import (
    IngestionStatus,
    IntegratedRuntimeCapabilityStatus,
    OutboxLagStatus,
    PanelDiagnostics,
    WatcherAutomationStatus,
    WatcherLifecycleStatus,
    WorkerQueueStatus,
    WriteGuardStatus,
)


V1_CAPABILITIES = {
    "system_entry_point",
    "companion_ui_routes",
    "orientation",
    "resurfacing",
    "capture",
    "vault_browser",
    "panel_confirm",
    "receipts_history",
    "memory_review",
    "source_understanding",
    "canvas_chat",
    "tts_readback",
    "health_status",
    "environment_config",
}

TIERS = {"core", "optional", "experimental", "out_of_scope"}
STATES = {"enabled", "degraded", "unavailable", "experimental_off"}


def _patch_status_inputs(
    monkeypatch,
    tmp_path: Path,
    *,
    worker_queue: WorkerQueueStatus | None = None,
    outbox_lag: OutboxLagStatus | None = None,
) -> None:
    outbox = tmp_path / "outbox.jsonl"
    outbox.write_text("", encoding="utf-8")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr(status_service, "INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr(status_service, "get_store_status", lambda: [])
    monkeypatch.setattr(status_service, "get_ingestion_status", IngestionStatus)
    monkeypatch.setattr(status_service, "_get_index_status", lambda: None)
    monkeypatch.setattr(status_service, "_get_panel_diagnostics", PanelDiagnostics)
    monkeypatch.setattr(status_service, "_get_write_guard_status", lambda: WriteGuardStatus(writes_allowed=True, mode="ok"))
    monkeypatch.setattr(
        status_service,
        "_get_worker_queue_status",
        lambda: worker_queue or WorkerQueueStatus(mode="db", pending=0, processed_total=0, source_path="outbox"),
    )
    monkeypatch.setattr(
        status_service,
        "_get_outbox_lag",
        lambda: outbox_lag or OutboxLagStatus(outbox_events=0, worker_processed_total=0, pending_estimate=0),
    )
    monkeypatch.setattr(status_service, "_get_watcher_automation_status", lambda write_guard=None: WatcherAutomationStatus())
    monkeypatch.setattr(status_service, "_get_watcher_lifecycle_status", WatcherLifecycleStatus)
    monkeypatch.setattr(status_service, "_get_v6_seams", lambda: {})


def _status_body(monkeypatch, tmp_path: Path) -> dict:
    _patch_status_inputs(monkeypatch, tmp_path)
    response = TestClient(app).get("/api/status")
    assert response.status_code == 200
    return response.json()


def test_matrix_names_all_v1_capabilities_truthfully(monkeypatch, tmp_path: Path) -> None:
    body = _status_body(monkeypatch, tmp_path)

    matrix = body.get("integrated_runtime_v1")
    assert set(matrix) == V1_CAPABILITIES
    for capability, entry in matrix.items():
        assert entry["tier"] in TIERS, capability
        assert entry["state"] in STATES, capability
        assert isinstance(entry["reasons"], list)
        assert entry["reasons"], capability

    assert matrix["system_entry_point"]["tier"] == "core"
    assert matrix["capture"]["tier"] == "core"
    assert matrix["memory_review"]["tier"] == "optional"
    assert matrix["canvas_chat"]["tier"] == "experimental"


def test_flag_states_map_truthfully(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setenv("TTS_ENABLED", "0")
    monkeypatch.setenv("MEMORY_ENABLED", "0")

    matrix = _status_body(monkeypatch, tmp_path)["integrated_runtime_v1"]

    assert matrix["canvas_chat"]["state"] == "experimental_off"
    assert any("CANVAS_ENABLED is off" in reason for reason in matrix["canvas_chat"]["reasons"])
    assert matrix["tts_readback"]["state"] == "unavailable"
    assert any("TTS_ENABLED is off" in reason for reason in matrix["tts_readback"]["reasons"])
    assert matrix["memory_review"]["state"] == "unavailable"
    assert any("MEMORY_ENABLED is off" in reason for reason in matrix["memory_review"]["reasons"])


def test_missing_outbox_reports_degraded_reason(monkeypatch, tmp_path: Path) -> None:
    _patch_status_inputs(
        monkeypatch,
        tmp_path,
        worker_queue=WorkerQueueStatus(mode="db", pending=None, processed_total=None, source_path="outbox"),
        outbox_lag=OutboxLagStatus(outbox_events=None, worker_processed_total=None, pending_estimate=None),
    )

    response = TestClient(app).get("/api/status")
    assert response.status_code == 200
    matrix = response.json()["integrated_runtime_v1"]

    for capability in ("receipts_history", "panel_confirm"):
        assert matrix[capability]["state"] == "degraded"
        assert any("DB outbox source unavailable" in reason for reason in matrix[capability]["reasons"])


def test_db_outbox_requires_worker_evidence(monkeypatch, tmp_path: Path) -> None:
    _patch_status_inputs(
        monkeypatch,
        tmp_path,
        worker_queue=WorkerQueueStatus(mode="db", pending=0, processed_total=None, source_path="outbox"),
        outbox_lag=OutboxLagStatus(outbox_events=0, worker_processed_total=None, pending_estimate=0),
    )

    response = TestClient(app).get("/api/status")
    assert response.status_code == 200
    matrix = response.json()["integrated_runtime_v1"]

    for capability in ("receipts_history", "panel_confirm"):
        assert matrix[capability]["state"] == "degraded"
        assert any("worker evidence unavailable" in reason for reason in matrix[capability]["reasons"])


def test_matrix_does_not_affect_health_passfail(monkeypatch, tmp_path: Path) -> None:
    _patch_status_inputs(monkeypatch, tmp_path)
    monkeypatch.setattr(
        status_service,
        "_integrated_runtime_v1_matrix",
        lambda **_: {
            name: IntegratedRuntimeCapabilityStatus(
                tier="core",
                state="unavailable",
                reasons=["forced unavailable for informational-only regression test"],
            )
            for name in V1_CAPABILITIES
        },
    )
    monkeypatch.setattr(
        health_route,
        "run_health",
        lambda: {"ok": True, "required_ok": True, "checks": {}, "runtime": {}, "suggested_actions": []},
    )

    status_response = TestClient(app).get("/api/status")
    assert status_response.status_code == 200
    assert all(
        entry["state"] == "unavailable"
        for entry in status_response.json()["integrated_runtime_v1"].values()
    )

    health_response = TestClient(app).get("/api/health")
    assert health_response.status_code == 200
    assert health_response.json()["required_ok"] is True


def test_source_understanding_reports_api_only(monkeypatch, tmp_path: Path) -> None:
    matrix = _status_body(monkeypatch, tmp_path)["integrated_runtime_v1"]

    source_understanding = matrix["source_understanding"]
    assert source_understanding["tier"] == "optional"
    assert source_understanding["state"] == "enabled"
    assert any("API-only" in reason for reason in source_understanding["reasons"])


def test_source_understanding_reports_unavailable_when_api_route_unregistered(monkeypatch, tmp_path: Path) -> None:
    saved = status_service._source_understanding_availability_provider
    try:
        status_service.register_source_understanding_availability_provider(lambda: False)

        matrix = _status_body(monkeypatch, tmp_path)["integrated_runtime_v1"]

        source_understanding = matrix["source_understanding"]
        assert source_understanding["tier"] == "optional"
        assert source_understanding["state"] == "unavailable"
        assert any("route registration is owned by the API assembly" in reason for reason in source_understanding["reasons"])
    finally:
        status_service.register_source_understanding_availability_provider(saved)
