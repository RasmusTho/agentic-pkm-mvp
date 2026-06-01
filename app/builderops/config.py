"""Runtime path configuration for the BuilderOps Vault MVP store."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_STATE_DIR = Path("runtime/builderops")
DEFAULT_DB_NAME = "builderops.sqlite3"


@dataclass(frozen=True)
class BuilderOpsPaths:
    state_dir: Path
    db_path: Path

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_paths(env: dict[str, str] | None = None) -> BuilderOpsPaths:
    src = env if env is not None else os.environ
    state_dir = Path(src.get("BUILDEROPS_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
    db_path = Path(
        src.get("BUILDEROPS_DB_PATH", str(state_dir / DEFAULT_DB_NAME))
    ).expanduser()
    return BuilderOpsPaths(state_dir=state_dir, db_path=db_path)
