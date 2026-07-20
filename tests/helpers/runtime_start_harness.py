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
    """A runtime-start fixture exceeded one of its bounded deadlines."""

    def __init__(
        self,
        *,
        stage: str,
        timeout_seconds: float,
        elapsed_seconds: float,
        command: Sequence[str],
        progress_tail: str,
        stdout: str,
        stderr: str,
    ) -> None:
        self.stage = stage
        self.timeout_seconds = timeout_seconds
        self.elapsed_seconds = elapsed_seconds
        self.command = tuple(command)
        self.progress_tail = progress_tail
        self.stdout = stdout
        self.stderr = stderr
        reason = (
            "exceeded its non-resettable total deadline"
            if stage == "total_timeout"
            else "stopped making observable progress"
        )
        super().__init__(
            f"runtime-start harness {stage} {reason}; "
            f"elapsed={elapsed_seconds:.3f}s; budget={timeout_seconds:g}s; "
            f"command={list(command)!r}; "
            f"progress_tail={progress_tail!r}; stdout={stdout[-800:]!r}; "
            f"stderr={stderr[-800:]!r}"
        )


class RuntimeStartHarnessCleanupError(RuntimeError):
    """A runtime-start process group survived the bounded cleanup budget."""


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


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - defensive on restricted hosts
        return True
    return True


def _wait_for_process_group_exit(
    process: subprocess.Popen[str],
    *,
    process_group_id: int,
    deadline: float,
    poll_interval: float = 0.01,
) -> bool:
    while time.monotonic() < deadline:
        process.poll()  # Reap the group leader as soon as it becomes terminal.
        if not _process_group_exists(process_group_id):
            return True
        time.sleep(poll_interval)
    process.poll()
    return not _process_group_exists(process_group_id)


def _stop_process(
    process: subprocess.Popen[str], *, cleanup_timeout: float = 2
) -> None:
    cleanup_deadline = time.monotonic() + cleanup_timeout

    if os.name != "posix":  # pragma: no cover - exercised by supported Windows hosts
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=cleanup_timeout / 2)
            return
        except subprocess.TimeoutExpired:
            process.kill()
        try:
            process.wait(timeout=max(0, cleanup_deadline - time.monotonic()))
            return
        except subprocess.TimeoutExpired as exc:
            raise RuntimeStartHarnessCleanupError(
                "runtime-start process survived bounded cleanup"
            ) from exc

    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        process.poll()
        return

    term_deadline = min(cleanup_deadline, time.monotonic() + cleanup_timeout / 2)
    if _wait_for_process_group_exit(
        process,
        process_group_id=process_group_id,
        deadline=term_deadline,
    ):
        return

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        process.poll()
        return
    if _wait_for_process_group_exit(
        process,
        process_group_id=process_group_id,
        deadline=cleanup_deadline,
    ):
        return
    raise RuntimeStartHarnessCleanupError(
        "runtime-start process group "
        f"{process_group_id} survived {cleanup_timeout:g}s cleanup budget"
    )


def run_runtime_start(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    progress_path: Path,
    initial_progress_timeout: float = 30,
    stall_timeout: float = 30,
    total_timeout: float | None = None,
    poll_interval: float = 0.02,
) -> subprocess.CompletedProcess[str]:
    """Run a synthetic startup with independent progress and total bounds.

    The fake external tools used by the contract test append events to
    ``progress_path``. Initial tool readiness and an in-flight stall have
    separate deadlines, so host scheduling delay cannot consume the whole
    startup budget while a truly hung phase still fails within ``stall_timeout``.
    The total deadline is measured once from process launch and is never reset
    by progress, so a process cannot run forever by emitting progress events.
    By default, its budget is exactly one initial window plus one stall window
    (60 seconds with the defaults), rather than an independently inflated wait.
    """

    if total_timeout is None:
        total_timeout = initial_progress_timeout + stall_timeout
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
        started_at = time.monotonic()
        total_deadline = started_at + total_timeout
        stage = "initial_progress_timeout"
        timeout_seconds = initial_progress_timeout
        progress_deadline = started_at + initial_progress_timeout
        last_signature: tuple[int, int] | None = None

        while process.poll() is None:
            now = time.monotonic()
            signature = _progress_signature(progress_path)
            if signature is not None and signature != last_signature:
                last_signature = signature
                stage = "progress_stall_timeout"
                timeout_seconds = stall_timeout
                progress_deadline = now + stall_timeout
            if now >= total_deadline:
                stage = "total_timeout"
                timeout_seconds = total_timeout
            elif now < progress_deadline:
                time.sleep(poll_interval)
                continue
            if now >= progress_deadline or stage == "total_timeout":
                _stop_process(process)
                stdout_file.seek(0)
                stderr_file.seek(0)
                raise RuntimeStartHarnessTimeout(
                    stage=stage,
                    timeout_seconds=timeout_seconds,
                    elapsed_seconds=now - started_at,
                    command=command,
                    progress_tail=_progress_tail(progress_path),
                    stdout=stdout_file.read(),
                    stderr=stderr_file.read(),
                )

        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=process.returncode,
            stdout=stdout_file.read(),
            stderr=stderr_file.read(),
        )
