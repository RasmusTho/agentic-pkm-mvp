"""CLI wiring for the Heimdal capture-runtime driver (#3094).

``test_capture_watch_command_registered`` proves the command exists and
reads its config from the environment (missing ``HEIMDAL_CAPTURE_WATCH_DIR``
fails loud with a clear message). ``test_capture_watch_once_admits_real_file``
drives the actual production call site end-to-end -- CLI invocation ->
``run_capture_tick`` -> ``run_watch_cycle`` -> ``admit_capture_file`` against
the memory-backed raw store and consent ledger -- so the wiring is proven on
the real path, not just a stubbed dependency.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.heimdal import capture_runtime
from app.heimdal.consent_ledger import reset_memory_consent_ledger
from app.heimdal.raw_store import all_raw_records, reset_memory_raw_store

pytestmark = pytest.mark.not_pg

_TEST_KEY_HEX = secrets.token_hex(32)


@pytest.fixture(autouse=True)
def _reset_heimdal_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("HEIMDAL_RAW_STORE_KEY", _TEST_KEY_HEX)
    reset_memory_consent_ledger()
    reset_memory_raw_store()
    yield
    reset_memory_consent_ledger()
    reset_memory_raw_store()


def test_capture_watch_command_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["heimdal", "capture-watch", "--help"])
    assert result.exit_code == 0
    assert "capture-watch" in result.output or "HEIMDAL_CAPTURE_WATCH_DIR" in result.output


def test_capture_watch_requires_watch_dir_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)
    runner = CliRunner()
    result = runner.invoke(cli, ["heimdal", "capture-watch", "--once"])
    assert result.exit_code != 0
    assert "HEIMDAL_CAPTURE_WATCH_DIR" in str(result.output)


def test_capture_watch_once_admits_real_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    memo = tmp_path / "memo.m4a"
    memo.write_bytes(b"fake audio bytes")
    monkeypatch.setenv("HEIMDAL_CAPTURE_WATCH_DIR", str(tmp_path))

    runner = CliRunner()
    result = runner.invoke(cli, ["heimdal", "capture-watch", "--once"])

    assert result.exit_code == 0, result.output
    summary_line = result.output.strip().splitlines()[-1]
    summary = json.loads(summary_line)
    assert summary == {"admitted": 1, "refused": 0}

    # Real path was exercised: the raw store has the record and the source
    # file was deleted after confirmed ingest (delete-after-confirmed-ingest).
    assert len(all_raw_records()) == 1
    assert not memo.exists()


@pytest.mark.skipif(
    hasattr(os, "getuid") and os.getuid() == 0,
    reason="root ignores chmod 0o000, so this permission-based repro doesn't trigger as root",
)
def test_capture_watch_once_fails_loud_on_tick_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A genuine tick failure (unreadable watch dir) must not report fake success.

    `run_capture_tick` returns `None` when the tick itself fails (not a
    per-file admission failure) -- e.g. the watch directory becomes
    unreadable mid-scan (`Path.iterdir()` raises `PermissionError`, which
    happens outside `run_watch_cycle`'s per-file try/except). `--once` must
    surface that as a failure, not as `{"admitted": 0, "refused": 0}` (which
    is indistinguishable from a real, healthy empty tick).
    """
    watch_dir = tmp_path / "unreadable"
    watch_dir.mkdir()
    watch_dir.chmod(0o000)
    monkeypatch.setenv("HEIMDAL_CAPTURE_WATCH_DIR", str(watch_dir))

    try:
        runner = CliRunner()
        result = runner.invoke(cli, ["heimdal", "capture-watch", "--once"])

        assert result.exit_code != 0, (
            f"Expected a non-zero exit on tick failure, got 0 with output: {result.output}"
        )
        assert '"admitted": 0' not in result.output
    finally:
        watch_dir.chmod(0o755)


def test_capture_watch_forever_mode_retries_instead_of_exiting_on_missing_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """#4362: without `--once` (the compose service's default), a missing
    HEIMDAL_CAPTURE_WATCH_DIR at startup must not exit the process -- that
    defeats the container healthcheck under `restart: unless-stopped`
    (crash-loop hides behind a stale healthy status instead of the
    healthcheck ever observing a consistent failure). It must retry in
    place and only proceed once config resolves."""
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)

    sleep_calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Resolve on the second retry so the command can actually finish.
        if len(sleep_calls) == 2:
            monkeypatch.setenv("HEIMDAL_CAPTURE_WATCH_DIR", str(tmp_path))

    monkeypatch.setattr(capture_runtime.time, "sleep", fake_sleep)

    runner = CliRunner()
    # max-ticks=0 with forever mode means run_forever executes zero ticks and
    # returns immediately once config resolves -- this proves the command
    # reached the looping path without exiting on the initial config error.
    result = runner.invoke(
        cli, ["heimdal", "capture-watch", "--max-ticks", "0"]
    )

    assert result.exit_code == 0, result.output
    assert len(sleep_calls) >= 2
    assert "stopped after 0 ticks" in result.output
