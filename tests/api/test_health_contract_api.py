import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.health_contract import HealthContract, HealthStateMachine


def _mock_snapshot(state: str, reason: str) -> dict[str, object]:
    return {
        "state": state,
        "reason": reason,
        "since_ts": "2025-01-01T00:00:00+00:00",
        "outbox_count": 1,
        "outbox_recent_age_s": 0.1,
        "store_object_count": 1,
        "bootstrap_state": "active",
        "bootstrap_reason": "objects or outbox events detected",
        "embedding_identity": {
            "backend": "mock",
            "expected_identity": None,
            "stored_identity": None,
        },
        "index_doctor_status": "pass",
        "events_doctor_status": "pass",
        "errors_last_10m": 0,
        "settings_status": "ok",
        "settings_source": {
            "path": "/fake/vault/System/Settings/health.md",
            "mtime": "2025-01-01T00:00:00+00:00",
            "sha256": "deadbeef",
        },
        "settings_errors": [],
        "thresholds": {
            "outbox_degrade_oldest_age_s": 15.0,
            "outbox_recover_oldest_age_s": 5.0,
            "degrade_samples": 3,
            "recover_samples": 10,
        },
        "writes_allowed": True,
        "write_guard_reason": None,
    }


def test_health_endpoints_ready(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        lambda: _mock_snapshot("running", "ok"),
    )
    resp_live = client.get("/healthz")
    assert resp_live.status_code == 200
    assert resp_live.json() == {"ok": True}

    resp_ready = client.get("/readyz")
    assert resp_ready.status_code == 200
    assert resp_ready.json()["state"] == "running"
    assert resp_ready.json()["class"] == "active"

    resp_status = client.get("/status")
    assert resp_status.status_code == 200
    payload = resp_status.json()
    assert payload["state"] == "running"
    assert payload["settings_status"] == "ok"
    assert payload["writes_allowed"] is True


def test_readyz_unhealthy(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        lambda: _mock_snapshot("boot", "starting"),
    )
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["detail"]["state"] == "boot"
    assert resp.json()["detail"]["class"] == "active"


def test_health_contract_degrades_on_stale_outbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outbox_path = tmp_path / "index-outbox.jsonl"
    old_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    record = {
        "event": "watcher.run",
        "timestamp": old_ts.isoformat().replace("+00:00", "Z"),
        "trace_id": "trace-health",
        "source": "test",
        "payload": {},
    }
    outbox_path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox_path))
    monkeypatch.setattr("app.outbox.events.INDEX_OUTBOX_PATH", outbox_path, raising=False)
    monkeypatch.setattr("app.events.outbox.INDEX_OUTBOX_PATH", outbox_path, raising=False)

    now = datetime(2025, 1, 1, 0, 0, 30, tzinfo=timezone.utc)
    contract = HealthContract(
        state_machine=HealthStateMachine(),
        now_fn=lambda: now,
        vault_root_fn=lambda: tmp_path,
    )
    snapshot = None
    for _ in range(3):
        snapshot = contract.evaluate()

    assert snapshot is not None
    assert snapshot["state"] == "degraded"
    assert "outbox idle" in snapshot["reason"]
    assert any("events-doctor" in action for action in snapshot["suggested_actions"])
