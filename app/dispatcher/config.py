"""Runtime path configuration for the dispatcher MVP."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE_DIR = Path("runtime/dispatcher")
DEFAULT_DB_NAME = "dispatcher.sqlite3"
DEFAULT_EVENTS_NAME = "events.jsonl"
_PATH_ENV_KEYS = frozenset([
    "DISPATCHER_STATE_DIR",
    "DISPATCHER_DB_PATH",
    "DISPATCHER_EVENTS_PATH",
])


@dataclass(frozen=True)
class DispatcherPaths:
    state_dir: Path
    db_path: Path
    events_path: Path

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)


def load_paths(
    env: dict[str, str] | None = None,
    *,
    cwd: Path | str | None = None,
) -> DispatcherPaths:
    src = env if env is not None else os.environ
    if "DISPATCHER_STATE_DIR" in src:
        state_dir = Path(src["DISPATCHER_STATE_DIR"]).expanduser()
    else:
        state_dir = _default_state_dir(src, cwd=cwd).expanduser()
    db_path = Path(
        src.get("DISPATCHER_DB_PATH", str(state_dir / DEFAULT_DB_NAME))
    ).expanduser()
    events_path = Path(
        src.get("DISPATCHER_EVENTS_PATH", str(state_dir / DEFAULT_EVENTS_NAME))
    ).expanduser()
    return DispatcherPaths(state_dir=state_dir, db_path=db_path, events_path=events_path)


def _default_state_dir(
    env: Mapping[str, str],
    *,
    cwd: Path | str | None = None,
) -> Path:
    if any(key in env for key in _PATH_ENV_KEYS):
        return DEFAULT_STATE_DIR
    primary_worktree = discover_primary_worktree(cwd=cwd)
    if primary_worktree is None:
        return DEFAULT_STATE_DIR
    return primary_worktree / DEFAULT_STATE_DIR


def discover_primary_worktree(*, cwd: Path | str | None = None) -> Path | None:
    """Return Git's primary worktree path, when available.

    Issue branches usually run in linked worktrees. Git records the primary
    worktree first in ``git worktree list --porcelain``, which gives dispatcher
    commands a stable shared state root without making GitHub lifecycle state
    subordinate to dispatcher state.
    """

    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(cwd) if cwd is not None else None,
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            path = line.removeprefix("worktree ").strip()
            if path:
                return Path(path).expanduser()
            return None
    return None
