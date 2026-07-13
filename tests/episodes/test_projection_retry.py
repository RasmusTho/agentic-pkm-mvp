"""Bounded detached retry tests for missed episode projection writes (#3564)."""

from __future__ import annotations

from pathlib import Path

from app.episodes import projection_retry


def test_projection_retry_terminates_a_hung_worker(monkeypatch) -> None:
    """A DNS, connection, or lock stall cannot survive the supervisor deadline."""

    class HungWorker:
        def __init__(self, _command: list[str], **_kwargs) -> None:
            self.pid = 4242
            self.wait_timeouts: list[float | None] = []

        def wait(self, timeout: float | None = None) -> int:
            self.wait_timeouts.append(timeout)
            raise projection_retry.subprocess.TimeoutExpired("projection-retry", timeout)

    worker = HungWorker([])
    monkeypatch.setattr(projection_retry.subprocess, "Popen", lambda *args, **kwargs: worker)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(projection_retry.os, "killpg", lambda pid, sig: signals.append((pid, sig)))

    assert (
        projection_retry.run_projection_retry(
            vault_root=str(Path("/tmp/vault")), rel_path="episodes/ep-hung.md", timeout=0.01
        )
        is False
    )
    assert signals == [
        (worker.pid, projection_retry.signal.SIGTERM),
        (worker.pid, projection_retry.signal.SIGKILL),
    ]
    assert worker.wait_timeouts == [
        0.01,
        projection_retry.PROJECTION_RETRY_REAP_TIMEOUT_SECONDS,
        projection_retry.PROJECTION_RETRY_REAP_TIMEOUT_SECONDS,
    ]
