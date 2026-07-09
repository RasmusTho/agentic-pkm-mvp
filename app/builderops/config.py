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
    vault_root: Path | None

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_paths(
    env: dict[str, str] | None = None,
    *,
    db_path_override: Path | None = None,
) -> BuilderOpsPaths:
    src = env if env is not None else os.environ
    state_dir = Path(src.get("BUILDEROPS_STATE_DIR", str(DEFAULT_STATE_DIR))).expanduser()
    db_path = (
        db_path_override.expanduser()
        if db_path_override is not None
        else Path(
            src.get("BUILDEROPS_DB_PATH", str(state_dir / DEFAULT_DB_NAME))
        ).expanduser()
    )
    vault_value = src.get("BUILDEROPS_VAULT_ROOT", "").strip()
    vault_root = Path(vault_value).expanduser() if vault_value else None
    paths = BuilderOpsPaths(
        state_dir=state_dir,
        db_path=db_path,
        vault_root=vault_root,
    )
    _validate_separation(paths)
    return paths


def _validate_separation(paths: BuilderOpsPaths) -> None:
    """Fail closed when mutable local state would enter the shared vault."""
    if paths.vault_root is None:
        return
    vault = paths.vault_root.resolve(strict=False)
    candidate = paths.db_path.resolve(strict=False)
    if candidate == vault or vault in candidate.parents:
        raise ValueError("BUILDEROPS_DB_PATH must be outside BUILDEROPS_VAULT_ROOT")
