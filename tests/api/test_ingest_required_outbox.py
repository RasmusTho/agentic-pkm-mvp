"""`POST /ingest` may not answer 2xx for an ingest that was never queued (#4214 D2).

The route's ONLY persistence side effect is its self-owned
``insert_object_and_outbox`` call, and it has no compensating JSONL sink. Left
unclassified, that call takes the ``required_db=False`` default, so an explicit
memory runtime silently skipped the enqueue, returned ``""``, and the route
answered ``200 {"trace_id": ...}`` for an ingest that reached nothing.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg

_BODY = {
    "uuid": "00000000-0000-0000-0000-000000004214",
    "title": "Required outbox",
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


def test_ingest_does_not_return_2xx_when_the_outbox_write_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable/unconfigured outbox must surface, not be answered 200."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    def _unavailable() -> Any:
        raise RuntimeError("required outbox unavailable")

    monkeypatch.setattr(outbox_service, "_open_conn", _unavailable)

    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/ingest", json=_BODY)

    assert response.status_code >= 500, (
        "POST /ingest returned a success status for an ingest whose outbox event "
        "was never queued"
    )


def test_ingest_returns_200_once_the_event_is_actually_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fail-loud classification must not break the configured happy path."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    conn = _Connection()
    monkeypatch.setattr(outbox_service, "_open_conn", lambda: conn)

    client = TestClient(app)
    response = client.post("/ingest", json=_BODY)

    assert response.status_code == 200
    assert response.json()["trace_id"]
    assert conn.cursor_instance.calls, "the route must have enqueued the ingest event"


def test_ingest_classifies_its_producer_as_db_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the classification itself, not only its observable effect."""
    seen: dict[str, object] = {}

    def _capture(payload: object, topic: str, trace_id: object = None, **kwargs: object) -> str:
        seen.update(kwargs)
        return "row"

    monkeypatch.setattr("app.api.routes.ingest.insert_object_and_outbox", _capture)

    client = TestClient(app)
    assert client.post("/ingest", json=_BODY).status_code == 200
    assert seen.get("required_db") is True
