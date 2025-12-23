from __future__ import annotations

import json
from pathlib import Path

from app.runtime.worker_heartbeat import DEFAULT_WORKER_HEARTBEAT_PATH, resolve_worker_heartbeat_path, write_worker_heartbeat


def test_resolve_worker_heartbeat_path_override(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "hb.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(target))
    assert resolve_worker_heartbeat_path() == target


def test_write_worker_heartbeat(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "worker_hb.json"
    monkeypatch.setenv("WORKER_HEARTBEAT_PATH", str(target))
    write_worker_heartbeat(
        path=resolve_worker_heartbeat_path(),
        ticks_total=5,
        errors_total=1,
        processed_total=3,
        outbox_path=tmp_path / "index-outbox.jsonl",
        status="running",
        now=123.0,
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ts"] == 123.0
    assert payload["ticks_total"] == 5
    assert payload["errors_total"] == 1
    assert payload["processed_total"] == 3
    assert payload["status"] == "running"
    assert str(tmp_path / "index-outbox.jsonl") in payload["outbox_path"]


def test_default_worker_heartbeat_path(monkeypatch) -> None:
    monkeypatch.delenv("WORKER_HEARTBEAT_PATH", raising=False)
    path = resolve_worker_heartbeat_path()
    assert path == DEFAULT_WORKER_HEARTBEAT_PATH
