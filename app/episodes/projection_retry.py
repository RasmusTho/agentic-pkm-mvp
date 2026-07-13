"""Bounded background retry for one rebuildable episode-projection row.

The segmenter launches this module rather than opening a new database connection
from its hot path when a redelivery finds an already-durable note. A supervisor
process owns one worker process and terminates it after the fixed deadline, so a
DNS outage, connection stall, schema lock, or SQL lock cannot stall the tick.
The vault note remains canonical and later redelivery or rebuild can retry.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys

from app.episodes.notes import parse_validated_episode_note

PROJECTION_RETRY_TIMEOUT_SECONDS = 1.0
PROJECTION_RETRY_REAP_TIMEOUT_SECONDS = 0.1


def _sync_worker(vault_root: str, rel_path: str) -> None:
    """Read and sync once in an isolated child process."""
    # Lazy import keeps the supervisor lightweight and avoids importing the
    # segmenter in the tick process merely to construct a retry command.
    from app.episodes.segmenter import _sync_new_episode_row

    note_path = Path(vault_root) / rel_path
    fields = parse_validated_episode_note(note_path.read_text(encoding="utf-8"))
    _sync_new_episode_row(fields, rel_path)


def _worker_command(*, vault_root: str, rel_path: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "app.episodes.projection_retry",
        "--worker",
        "--vault-root",
        vault_root,
        "--note-path",
        rel_path,
    ]


def _signal_worker_group(worker: subprocess.Popen[bytes], signal_number: int) -> None:
    """Signal the worker and any descendants without waiting for reaping."""
    if worker.pid is None:  # pragma: no cover - Popen supplies pid after construction
        return
    try:
        os.killpg(worker.pid, signal_number)
    except ProcessLookupError:
        pass


def run_projection_retry(
    *, vault_root: str, rel_path: str, timeout: float = PROJECTION_RETRY_TIMEOUT_SECONDS
) -> bool:
    """Run one sync attempt without allowing its I/O to delay the segmentation tick."""
    worker = subprocess.Popen(
        _worker_command(vault_root=vault_root, rel_path=rel_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )
    try:
        return worker.wait(timeout) == 0
    except subprocess.TimeoutExpired:
        _signal_worker_group(worker, signal.SIGTERM)
        try:
            worker.wait(PROJECTION_RETRY_REAP_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _signal_worker_group(worker, signal.SIGKILL)
            try:
                worker.wait(PROJECTION_RETRY_REAP_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        return False
    return worker.exitcode == 0


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--vault-root", required=True)
    parser.add_argument("--note-path", required=True)
    args = parser.parse_args()
    if args.worker:
        _sync_worker(args.vault_root, args.note_path)
        return 0
    return 0 if run_projection_retry(vault_root=args.vault_root, rel_path=args.note_path) else 1


if __name__ == "__main__":  # pragma: no cover - exercised through the detached launcher
    raise SystemExit(_main())
