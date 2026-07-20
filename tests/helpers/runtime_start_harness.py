"""Load-stable subprocess runner for runtime-start contract tests."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path


class RuntimeStartHarnessTimeout(TimeoutError):
    """A runtime-start fixture failed to begin or stopped making progress."""

    def __init__(
        self,
        *,
        stage: str,
        timeout_seconds: float,
        command: Sequence[str],
        progress_tail: str,
        stdout: str,
        stderr: str,
    ) -> None:
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        self.command = tuple(command)
        self.progress_tail = progress_tail
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"runtime-start harness {stage} after {timeout_seconds:g}s without "
            f"observable progress; command={list(command)!r}; "
            f"progress_tail={progress_tail!r}; stdout={stdout[-800:]!r}; "
            f"stderr={stderr[-800:]!r}"
        )


def _progress_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return stat_result.st_size, stat_result.st_mtime_ns


def _progress_tail(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-800:]
    except FileNotFoundError:
        return ""


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - exercised by supported Windows hosts
            process.terminate()
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=1)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - exercised by supported Windows hosts
            process.kill()
    except ProcessLookupError:
        return
    process.wait(timeout=1)


def run_runtime_start(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    progress_path: Path,
    initial_progress_timeout: float = 30,
    stall_timeout: float = 30,
    poll_interval: float = 0.02,
) -> subprocess.CompletedProcess[str]:
    """Run a synthetic startup while bounding lack of progress, not total time.

    The fake external tools used by the contract test append events to
    ``progress_path``. Initial tool readiness and an in-flight stall have
    separate deadlines, so host scheduling delay cannot consume the whole
    startup budget while a truly hung phase still fails within ``stall_timeout``.
    """

    progress_path.unlink(missing_ok=True)
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file,
    ):
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
        )
        stage = "initial_progress_timeout"
        timeout_seconds = initial_progress_timeout
        deadline = time.monotonic() + initial_progress_timeout
        last_signature: tuple[int, int] | None = None

        while process.poll() is None:
            signature = _progress_signature(progress_path)
            if signature is not None and signature != last_signature:
                last_signature = signature
                stage = "progress_stall_timeout"
                timeout_seconds = stall_timeout
                deadline = time.monotonic() + stall_timeout
            if time.monotonic() >= deadline:
                _stop_process(process)
                stdout_file.seek(0)
                stderr_file.seek(0)
                raise RuntimeStartHarnessTimeout(
                    stage=stage,
                    timeout_seconds=timeout_seconds,
                    command=command,
                    progress_tail=_progress_tail(progress_path),
                    stdout=stdout_file.read(),
                    stderr=stderr_file.read(),
                )
            time.sleep(poll_interval)

        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=process.returncode,
            stdout=stdout_file.read(),
            stderr=stderr_file.read(),
        )
