from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app


def _write_worker_heartbeat(path: Path, *, ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = {
        "ts": ts,
        "pid": 123,
        "status": "running",
        "ticks_total": 3,
        "errors_total": 0,
        "processed_total": 2,
        "outbox_path": "/app/tmp/index-outbox.jsonl",
    }
    path.write_text(json.dumps(heartbeat, ensure_ascii=False), encoding="utf-8")


@pytest.mark.e2e
def test_operator_can_diagnose_stale_worker(tmp_path: Path, monkeypatch) -> None:
    """
    Validate full operator workflow for diagnosing stale worker.

    Scenario:
    1. Worker stops updating heartbeat (simulate by writing old timestamp)
    2. Operator calls GET /api/health
    3. Response shows worker.ok = False
    4. Response includes suggested_actions with actionable command

    See: docs/runbooks/RUNBOOK_STARTUP_FULL_SYSTEM.md §Interpreting /api/health
    """
    worker_hb = tmp_path / "worker-heartbeat.json"
    _write_worker_heartbeat(worker_hb, ts=time.time() - 7200)

    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(worker_hb))
    monkeypatch.setenv("WORKER_ENABLE", "1")
    monkeypatch.setenv("STORE_BACKEND", "memory")

    client = TestClient(app)
    resp = client.get("/api/health")
    assert resp.status_code == 200

    data = resp.json()

    assert data["runtime"]["worker"]["ok"] is False
    assert data["runtime"]["worker"]["status"] == "stale"

    actions = data.get("suggested_actions", [])
    worker_action = next((a for a in actions if "worker" in str(a.get("id", ""))), None)
    assert worker_action is not None, "Should suggest worker restart"
    assert "command" in worker_action or "script" in worker_action
