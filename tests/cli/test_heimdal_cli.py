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
import secrets
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
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
