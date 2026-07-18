"""Runtime path configuration for the BuilderOps Vault MVP store."""

from __future__ import annotations

import json
import os
import platform
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

DEFAULT_DB_NAME = "builderops.sqlite3"
CUTOVER_ACK_NAME = "host-store-cutover-v1.json"
CUTOVER_ACK_SCHEMA = "builderops.host-store-cutover.v1"


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
        state_dir = default_state_dir()
        _validate_host_cutover_ack(state_dir)
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


def host_cutover_ack_path(state_dir: Path | None = None) -> Path:
    return (state_dir if state_dir is not None else default_state_dir()) / CUTOVER_ACK_NAME


def current_host_id() -> str:
    """Return the local host identity recorded in cutover evidence."""

    return platform.node().strip()


def current_user_id() -> str:
    """Return the local OS user identity recorded in cutover evidence."""

    return str(os.getuid())


def _legacy_store_mtimes(root: Path) -> tuple[float, ...]:
    """Inventory legacy stores recursively without following symlinked trees."""

    def fail_on_walk_error(error: OSError) -> None:
        raise error

    mtimes: list[float] = []
    for directory, child_dirs, files in os.walk(
        root, followlinks=False, onerror=fail_on_walk_error
    ):
        directory_path = Path(directory)
        child_dirs[:] = [
            name for name in child_dirs if not (directory_path / name).is_symlink()
        ]
        if (
            directory_path.name == "builderops"
            and directory_path.parent.name == "runtime"
            and DEFAULT_DB_NAME in files
        ):
            candidate = directory_path / DEFAULT_DB_NAME
            candidate_stat = candidate.lstat()
            if stat.S_ISLNK(candidate_stat.st_mode) or not stat.S_ISREG(
                candidate_stat.st_mode
            ):
                raise ValueError
            mtimes.append(candidate_stat.st_mtime)
    return tuple(mtimes)


def _validate_host_cutover_ack(state_dir: Path) -> None:
    """Require bounded host-global evidence before implicit store selection."""

    path = host_cutover_ack_path(state_dir)
    try:
        path_stat = path.lstat()
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or stat.S_IMODE(path_stat.st_mode) != 0o600
            or path_stat.st_uid != os.getuid()
        ):
            raise ValueError
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
        acknowledged_at = datetime.fromisoformat(
            str(payload["acknowledged_at"]).replace("Z", "+00:00")
        )
        participating_repos = payload["participating_repos"]
        participating_roots = payload["participating_roots"]
        roots = tuple(Path(root).resolve(strict=True) for root in participating_roots)
        cwd = Path.cwd().resolve()
        cwd_is_in_inventory = cwd in roots
        latest_legacy_write = max(
            (
                datetime.fromtimestamp(mtime, tz=timezone.utc)
                for root in roots
                for mtime in _legacy_store_mtimes(root)
            ),
            default=None,
        )
        now = datetime.now(timezone.utc)
        valid = (
            isinstance(payload, dict)
            and payload.get("schema_version") == CUTOVER_ACK_SCHEMA
            and payload.get("scope") == "same-user-same-host"
            and payload.get("host_id") == current_host_id()
            and payload.get("user_id") == current_user_id()
            and payload.get("legacy_stores_reconciled") is True
            and isinstance(payload.get("actor"), str)
            and bool(payload["actor"].strip())
            and acknowledged_at.tzinfo is not None
            and acknowledged_at <= now + timedelta(minutes=5)
            and (
                latest_legacy_write is None
                or latest_legacy_write <= acknowledged_at
            )
            and isinstance(payload.get("inventory_epoch"), str)
            and bool(UUID(payload["inventory_epoch"]))
            and isinstance(participating_repos, list)
            and all(isinstance(repo, str) and repo.strip() for repo in participating_repos)
            and len(set(participating_repos)) == len(participating_repos)
            and isinstance(participating_roots, list)
            and bool(participating_roots)
            and all(
                isinstance(root, str) and Path(root).is_absolute()
                for root in participating_roots
            )
            and len(set(participating_roots)) == len(participating_roots)
            and len(set(roots)) == len(roots)
            and all(root.is_dir() for root in roots)
            and len(participating_repos) == len(roots)
            and cwd_is_in_inventory
        )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        valid = False
    if valid:
        return
    raise ValueError(
        "Refusing implicit host-stable BuilderOps store selection: a valid "
        "same-user/same-host cutover acknowledgement is required. Stop BuilderOps "
        "writers, reconcile legacy stores across every participating repository, "
        "bind a fresh inventory epoch to this host, user, and every participating "
        "root, then install the documented host-store-cutover-v1 acknowledgement or set "
        "BUILDEROPS_DB_PATH / BUILDEROPS_STATE_DIR explicitly."
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
