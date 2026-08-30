from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.health_contract import HealthContract, HealthStateMachine
from app.stores import reset_store_backends
from app.watcher.heartbeat import write_registry_heartbeat


def _mock_index_doctor() -> dict[str, object]:
    return {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    }


def test_watcher_health_distinguishes_idle_catch_up_and_degraded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    heartbeat = tmp_path / "watcher-heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(heartbeat))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setattr("app.health_contract.diagnose_index", _mock_index_doctor)
    reset_store_backends()

    contract = HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
    )
    heartbeat_now = time.time()

    for reported, expected in (
        ("healthy-idle", "healthy-idle"),
        ("catch-up", "catch-up"),
        ("degraded", "degraded"),
    ):
        write_registry_heartbeat(
            path=heartbeat,
            status=reported,
            watchers={
                "ingest": {
                    "observation_status": reported,
                    "scan_in_progress": reported == "catch-up",
                }
            },
            paused=reported == "degraded",
            now=heartbeat_now,
        )
        snapshot = contract.evaluate()
        assert snapshot["watcher_observation"]["state"] == expected
        assert snapshot["watcher_observation"]["pending"] is (expected == "catch-up")
        assert snapshot["watcher_observation"]["healthy"] is (expected != "degraded")

    reset_store_backends()
