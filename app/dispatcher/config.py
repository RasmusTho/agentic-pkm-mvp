"""Runtime path configuration for the dispatcher MVP."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE_DIR = Path("runtime/dispatcher")
DEFAULT_DB_NAME = "dispatcher.sqlite3"
DEFAULT_EVENTS_NAME = "events.jsonl"


@dataclass(frozen=True)
class DispatcherPaths:
    state_dir: Path
    db_path: Path
    events_path: Path

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)


def load_paths(env: dict[str, str] | None = None) -> DispatcherPaths:
    src = env if env is not None else os.environ
    state_dir = Path(src.get("DISPATCHER_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
    db_path = Path(
        src.get("DISPATCHER_DB_PATH", str(state_dir / DEFAULT_DB_NAME))
    ).expanduser()
    events_path = Path(
        src.get("DISPATCHER_EVENTS_PATH", str(state_dir / DEFAULT_EVENTS_NAME))
    ).expanduser()
    return DispatcherPaths(state_dir=state_dir, db_path=db_path, events_path=events_path)
