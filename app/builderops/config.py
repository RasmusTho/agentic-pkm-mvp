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
    validate_db_path_outside_vault(paths.db_path, vault_root=paths.vault_root)


def validate_db_path_outside_vault(
    db_path: Path,
    *,
    vault_root: Path | None = None,
) -> Path:
    """Return the DB path after enforcing the shared-vault confinement invariant.

    ``SqliteBuilderOpsStore`` calls this seam as well as configuration loading so
    explicit API/tool and observe-only callers cannot bypass the invariant.
    """

    configured_root = vault_root
    if configured_root is None:
        raw_root = os.environ.get("BUILDEROPS_VAULT_ROOT", "").strip()
        configured_root = Path(raw_root).expanduser() if raw_root else None
    candidate_path = Path(db_path).expanduser()
    candidate_lexical = candidate_path.absolute()
    candidate = candidate_path.resolve(strict=False)
    if configured_root is None:
        return candidate
    vault_path = configured_root.expanduser()
    vault_lexical = vault_path.absolute()
    vault = vault_path.resolve(strict=False)
    if (
        candidate_lexical == vault_lexical
        or vault_lexical in candidate_lexical.parents
        or candidate == vault
        or vault in candidate.parents
    ):
        raise ValueError("BUILDEROPS_DB_PATH must be outside BUILDEROPS_VAULT_ROOT")
    return candidate
