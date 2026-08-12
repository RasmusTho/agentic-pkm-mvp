"""Self-owned connection policy for the real vault deletion seam (#4468)."""

from __future__ import annotations

import pytest

from app.config.database import RUNTIME_DATABASE_ENV_KEYS
from app.services import vault_sync

pytestmark = pytest.mark.not_pg


def test_delete_note_memory_mode_does_not_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unnamed memory runtime has no DB state or outbox to reconcile."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _must_not_connect() -> object:
        raise AssertionError("delete_note opened an unnamed memory database")

    monkeypatch.setattr(vault_sync, "conn_rw", _must_not_connect)

    assert vault_sync.delete_note("/vault/unconfigured.md") is False
