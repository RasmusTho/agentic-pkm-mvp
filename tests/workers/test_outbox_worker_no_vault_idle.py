from __future__ import annotations

from pathlib import Path

import pytest

import app.workers.outbox_worker as outbox_worker

pytestmark = pytest.mark.not_pg


def test_outbox_worker_idles_without_selected_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no vault selected the worker tick idles and never reads ./vault.

    Slice 05B (#2384): the legacy CWD-relative ``Path("vault")`` fallback is
    removed from the outbox worker resolver, so a tick with ``VAULT_ROOT`` unset
    must report a no-vault idle state without polling the outbox or creating a
    ``./vault`` directory under the current working directory.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    # The worker must idle before any outbox poll: poll_outbox_one must not run.
    def _fail_poll() -> None:  # pragma: no cover - asserts it is never called
        raise AssertionError("poll_outbox_one must not run when no vault is selected")

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _fail_poll)

    result = outbox_worker.run_once(vault_root=None)

    assert result.state == "no_vault"
    assert result.processed == 0
    assert not (tmp_path / "vault").exists()


def test_run_once_processes_when_vault_selected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Selected-vault behavior is preserved: a bound vault still polls/processes."""
    vault = tmp_path / "selected-vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.delenv("WATCHER_VAULT_PATH", raising=False)

    polled: list[bool] = []

    def _poll_empty() -> None:
        polled.append(True)
        return None

    monkeypatch.setattr(outbox_worker, "poll_outbox_one", _poll_empty)

    result = outbox_worker.run_once(vault_root=None)

    assert polled == [True]
    assert result.state == "idle"
    assert result.processed == 0
