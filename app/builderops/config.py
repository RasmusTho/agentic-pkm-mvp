"""Runtime path configuration for the BuilderOps Vault MVP store."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_NAME = "builderops.sqlite3"
LEGACY_STATE_DIR = Path("runtime/builderops")


def default_state_dir() -> Path:
    """Return the implicit same-user, same-host state home lazily.

    Home resolution must not run at import time: hostless automation can still
    use an explicit absolute DB/state override even when ``Path.home()`` is not
    available.
    """

    return Path.home() / ".local" / "state" / "builderops"


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
    configured_state_dir = src.get("BUILDEROPS_STATE_DIR")
    configured_db_path = src.get("BUILDEROPS_DB_PATH")
    exact_db_path = (
        db_path_override if db_path_override is not None else configured_db_path
    )
    if configured_state_dir is not None:
        state_dir = Path(configured_state_dir).expanduser()
    elif exact_db_path is not None:
        state_dir = Path(exact_db_path).expanduser().parent
    else:
        _fail_if_legacy_stores_exist()
        state_dir = default_state_dir()
    db_path = (
        db_path_override.expanduser()
        if db_path_override is not None
        else Path(
            configured_db_path
            if configured_db_path is not None
            else state_dir / DEFAULT_DB_NAME
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


def _fail_if_legacy_stores_exist() -> None:
    legacy_paths = _legacy_store_paths()
    if not legacy_paths:
        return
    raise ValueError(
        "Refusing implicit host-stable BuilderOps store selection: found "
        f"{len(legacy_paths)} legacy per-worktree store(s). Stop BuilderOps writers, "
        "reconcile the legacy stores, then set BUILDEROPS_DB_PATH or "
        "BUILDEROPS_STATE_DIR explicitly for the operator-approved cutover."
    )


def _legacy_store_paths() -> tuple[Path, ...]:
    """Return existing legacy stores for the current repo without exposing paths."""

    roots = _git_worktree_roots()
    if not roots:
        current = Path.cwd()
        repo_root = next(
            (p for p in (current, *current.parents) if (p / ".git").exists()),
            current,
        )
        roots = (repo_root,)
    paths = {
        (root / LEGACY_STATE_DIR / DEFAULT_DB_NAME).resolve(strict=False)
        for root in roots
        if (root / LEGACY_STATE_DIR / DEFAULT_DB_NAME).is_file()
    }
    return tuple(sorted(paths))


def _git_worktree_roots() -> tuple[Path, ...]:
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ()
    if result.returncode != 0:
        return ()
    return tuple(
        Path(line.removeprefix("worktree "))
        for line in result.stdout.splitlines()
        if line.startswith("worktree ")
    )


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
