from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.vault.paths import get_vault_inbox_dir_rel
from app.watcher.heartbeat import write_registry_heartbeat, write_runtime_heartbeat


def test_runtime_heartbeat_writes_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "watcher_heartbeat.json"
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(target))

    path = write_runtime_heartbeat(ticks=5, changed=2, errors=0)

    assert path == target
    assert target.exists(), "heartbeat file should be created"

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload.get("ticks") == 5
    assert payload.get("changed") == 2
    assert payload.get("errors") == 0
    assert payload.get("status") == "running"
    assert "ts" in payload
    assert "pid" in payload


def test_registry_heartbeat_includes_watchers(tmp_path: Path) -> None:
    target = tmp_path / "watcher_registry.json"
    scope_glob = f"{get_vault_inbox_dir_rel(tmp_path)}/**"
    watchers = {
        "panel": {
            "ticks_total": 4,
            "changed_total": 2,
            "emitted_total": 1,
            "errors_total": 0,
            "scope_glob": scope_glob,
        },
        "ingest": {
            "ticks_total": 3,
            "changed_total": 1,
            "emitted_total": 1,
            "errors_total": 0,
            "scope_glob": scope_glob,
        },
    }

    write_registry_heartbeat(
        path=target,
        status="running",
        watchers=watchers,
        outbox_path=tmp_path / "index-outbox.jsonl",
        now=123.0,
    )

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["ts"] == 123.0
    assert payload["status"] == "running"
    assert payload["watchers"]["panel"]["scope_glob"] == scope_glob
    assert payload["watchers"]["ingest"]["emitted_total"] == 1
    assert "pid" in payload
