"""Shared lock for answer/dismiss arbitration on one revisit surface."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config.paths import resolve_optional_vault_root
from app.vault.paths import NoVaultSelectedError, resolve_vault_system_dir_rel_or_default


_LOCK_NAME = ".calibration_revisit_actions.lock"


@contextmanager
def revisit_action_lock(vault_root: Path | None = None) -> Iterator[None]:
    """Serialize answer and dismiss decision/rung arbitration for one vault.

    The lock is deliberately shared by both ledgers.  Each append function
    retains its own ledger lock, while the route holds this lock across the
    durable lookup and append so answer-vs-dismiss cannot both win a rung.
    """

    root = vault_root if vault_root is not None else resolve_optional_vault_root()
    if root is None:
        raise NoVaultSelectedError(
            "calibration revisit action lock requires a selected vault"
        )
    system_dir = root.expanduser() / resolve_vault_system_dir_rel_or_default(root)
    lock_path = system_dir / "receipts" / _LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


__all__ = ["revisit_action_lock"]
