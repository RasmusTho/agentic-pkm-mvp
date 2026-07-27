"""Regression coverage for #4064's memory-mode outbox connection guard."""

from __future__ import annotations

from typing import Any

import pytest

from app.events.models import new_event
from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg

_UNREACHABLE_DSN = "postgresql://app:app@192.0.2.1:5432/app"


def _event():
    return new_event(event_type="test.outbox.memory", payload={"value": "test"}, trace_id="t-4064")


def test_write_outbox_event_skips_connection_in_memory_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """A memory backend must not probe a stale/unreachable DB DSN (#4064)."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", _UNREACHABLE_DSN)

    def _fail_if_called(*args: object, **kwargs: object) -> Any:
        raise AssertionError("memory-mode write_outbox_event must not open a DB connection")

    monkeypatch.setattr(outbox_service, "conn_rw", _fail_if_called)

    assert outbox_service.write_outbox_event(_event(), idempotency_key="memory-key") == ""


def test_write_outbox_event_uses_explicit_dsn_without_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit DSN remains an opt-in request for durable Postgres delivery."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    calls: list[object] = []

    class _Cursor:
        def execute(self, _sql: str, params: tuple[object, ...]) -> None:
            calls.append(params)

        def fetchone(self) -> tuple[str]:
            return ("dsn-key",)

    class _Connection:
        autocommit = False

        def cursor(self) -> _Cursor:
            return _Cursor()

        def close(self) -> None:
            return None

    monkeypatch.setattr(outbox_service, "conn_rw", lambda: _Connection())

    assert outbox_service.write_outbox_event(_event(), idempotency_key="dsn-key") == "dsn-key"
    assert calls
