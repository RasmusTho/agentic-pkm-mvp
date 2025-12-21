from fastapi.testclient import TestClient

from app.api.app import app


def _mock_snapshot(state: str, reason: str) -> dict[str, object]:
    return {
        "state": state,
        "reason": reason,
        "since_ts": "2025-01-01T00:00:00+00:00",
        "outbox_count": 1,
        "outbox_oldest_age_s": 0.1,
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
            "path": "/fake/vault/@System/Settings/health.md",
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

    resp_status = client.get("/status")
    assert resp_status.status_code == 200
    assert resp_status.json()["state"] == "running"
    assert resp_status.json()["settings_status"] == "ok"


def test_readyz_unhealthy(monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        lambda: _mock_snapshot("boot", "starting"),
    )
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["detail"]["state"] == "boot"
