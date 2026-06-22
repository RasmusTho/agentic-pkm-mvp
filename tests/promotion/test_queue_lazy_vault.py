from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _clear_vault_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("VAULT_ROOT", "VAULT_ROOT_DEV", "VAULT_ROOT_TEST"):
        monkeypatch.delenv(name, raising=False)


def test_queue_import_does_not_bind_cwd_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()

    import app.promotion.queue as queue

    reloaded = importlib.reload(queue)

    assert reloaded.QUEUE is None
    assert reloaded.LOG is None
    assert reloaded.SETTINGS is None


def test_run_once_idles_without_configured_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault" / "_system" / "events").mkdir(parents=True)

    import app.promotion.queue as queue

    importlib.reload(queue)

    assert queue.run_once() == 0
    assert not (tmp_path / "vault" / "_system" / "events" / "promote.log.jsonl").exists()


def test_promotion_agent_idles_without_configured_vault(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clear_vault_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "vault").mkdir()

    import app.agents.promotion.agent as agent
    import app.promotion.queue as queue

    importlib.reload(queue)
    reloaded_agent = importlib.reload(agent)

    assert reloaded_agent.PromotionAgent().run_once() == 0
    assert not (tmp_path / "vault" / "_system").exists()
