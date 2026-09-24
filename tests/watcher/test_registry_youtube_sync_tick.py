"""YSS-06 (#3921): the sync sub-tick inside the watcher registry loop.

The sub-tick shares its host with vault watching, so the two properties that
matter here are the ones a unit test of the scheduler cannot show: both gates
are honoured before any work happens, and a scheduler failure cannot break the
watcher cycle around it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.watcher import registry as registry_module
from app.watcher.registry import SyncTickCadence, _run_youtube_sync_tick

pytestmark = pytest.mark.not_pg


class _Cfg:
    def __init__(self, tmp_path: Path, *, enable: bool = True) -> None:
        self.enable = enable
        self.vault_path = tmp_path / "vault"
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self.stop_file = tmp_path / "STOP"


class _Context:
    status = "selected"
    active_vault_path = "/tmp/vault"


class _Manager:
    def validate_vault(self, path: Any) -> _Context:
        del path
        return _Context()


def test_sub_tick_gated_and_exception_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _Cfg(tmp_path)
    monkeypatch.setattr(registry_module, "VaultManager", _Manager)

    calls: list[str] = []

    # --- disabled watcher / paused watcher never reach the scheduler --------
    disabled = _Cfg(tmp_path, enable=False)
    assert _run_youtube_sync_tick(
        disabled, now=1000.0, cadence=SyncTickCadence()
    )["reason"] == "watcher_disabled"

    cfg.stop_file.write_text("stop", encoding="utf-8")
    assert _run_youtube_sync_tick(cfg, now=1000.0, cadence=SyncTickCadence())[
        "reason"
    ] == "watcher_paused"
    cfg.stop_file.unlink()

    # --- cadence keeps the sub-tick sparse ---------------------------------
    cadence = SyncTickCadence()
    monkeypatch.setattr(
        registry_module,
        "run_scheduled_sync_tick",
        lambda **kwargs: calls.append("ran") or _Outcome("disabled"),
        raising=False,
    )

    def _fake_runtime(**kwargs: Any) -> Any:
        calls.append("ran")
        return _Outcome("disabled")

    import app.knowledge_acquisition.sync_runtime as sync_runtime

    monkeypatch.setattr(sync_runtime, "run_scheduled_sync_tick", _fake_runtime)

    first = _run_youtube_sync_tick(cfg, now=1000.0, cadence=cadence)
    assert first["reason"] == "disabled", "both gates closed means no work"
    assert calls == ["ran"]

    # Within the interval the scheduler is not called again at all.
    second = _run_youtube_sync_tick(cfg, now=1001.0, cadence=cadence)
    assert second["reason"] == "cadence_not_due"
    assert calls == ["ran"]

    # --- a scheduler failure must not escape into the watcher cycle --------
    def _boom(**kwargs: Any) -> Any:
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(sync_runtime, "run_scheduled_sync_tick", _boom)
    result = _run_youtube_sync_tick(cfg, now=9999.0, cadence=SyncTickCadence())

    assert result["triggered"] is False
    assert result["reason"] == "sync_failed"
    assert "provider exploded" in result["error"]


class _Outcome:
    def __init__(self, reason: str) -> None:
        self.reason = reason

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason}


def test_sub_tick_does_not_reuse_cycle_timestamp_for_lease(tmp_path, monkeypatch) -> None:
    import app.knowledge_acquisition.sync_runtime as sync_runtime
    monkeypatch.setattr(registry_module, "VaultManager", _Manager)
    observed = []
    def run(**kwargs):
        observed.append(kwargs)
        return _Outcome("ran")
    monkeypatch.setattr(sync_runtime, "run_scheduled_sync_tick", run)
    _run_youtube_sync_tick(_Cfg(tmp_path), now=1.0, cadence=SyncTickCadence())
    assert len(observed) == 1
    assert "now" not in observed[0], "cycle start predates scans; runtime must sample the current clock"
