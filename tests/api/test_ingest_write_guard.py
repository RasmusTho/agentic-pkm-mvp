"""`POST /ingest` WriteGuard assertion (formal-model.md F-D, owner-decided on
epic #2778).

Before this change the seam was guardless: any well-formed payload became a
``P.objects`` row + event regardless of runtime write-health state. This pins
the same fail-closed ``assert_writes_allowed`` pattern used at the other
named V-write seams (#2910 knowledge write port, ``app/api/routes/
capture.py``'s ``/capture``): a blocked write-health state must deny the
request atomically, before ``insert_object_and_outbox`` runs, and an
authorized request must still succeed unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ingest as ingest_module
from app.services import outbox as outbox_service
from app.write_guard import WritesBlockedError

pytestmark = pytest.mark.not_pg

_BODY = {
    "uuid": "00000000-0000-0000-0000-0000000004d4",
    "title": "WriteGuard seam",
    "review_state": "inbox",
    "content": "body",
}


class _Cursor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def execute(self, _sql: str, params: tuple[object, ...]) -> None:
        self.calls.append(params)

    def fetchone(self) -> tuple[str]:
        return ("inserted-row",)


class _Connection:
    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False
        self.cursor_instance = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_ingest_blocks_the_write_when_writeguard_denies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked write-health state must deny /ingest before any persistence call."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    def _blocked(action: str) -> None:
        raise WritesBlockedError(state="safe_mode", reason="test lock", action=action)

    monkeypatch.setattr(
        ingest_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _blocked
    )

    calls: list[Any] = []
    monkeypatch.setattr(
        ingest_module,
        "insert_object_and_outbox",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    client = TestClient(app)
    response = client.post("/ingest", json=_BODY)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "writeguard_blocked"
    assert detail["state"] == "blocked"
    assert detail["message"]
    assert not calls, "a WriteGuard-blocked ingest must not reach the persistence call"


def test_ingest_asserts_the_named_guard_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the action string the seam asserts, not only its observable effect."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    seen: list[str] = []
    real_assert = ingest_module.DEFAULT_WRITE_GUARD.assert_writes_allowed

    def _spy(action: str) -> None:
        seen.append(action)
        return real_assert(action)

    monkeypatch.setattr(
        ingest_module.DEFAULT_WRITE_GUARD, "assert_writes_allowed", _spy
    )
    conn = _Connection()
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: conn)

    client = TestClient(app)
    response = client.post("/ingest", json=_BODY)

    assert response.status_code == 200
    assert seen == [ingest_module._WRITE_GUARD_ACTION]


def test_ingest_still_succeeds_when_writeguard_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The guard must not break the configured happy path (allowed write)."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    conn = _Connection()
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: conn)

    client = TestClient(app)
    response = client.post("/ingest", json=_BODY)

    assert response.status_code == 200
    assert response.json()["trace_id"]
    assert conn.cursor_instance.calls, "an authorized ingest must still be persisted"
