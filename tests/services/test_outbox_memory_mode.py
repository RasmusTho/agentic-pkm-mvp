"""Regression coverage for #4064's memory-mode outbox connection guard."""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.config.database import (
    RUNTIME_DATABASE_ENV_KEYS,
    explicit_runtime_database_url,
    resolve_runtime_database_url,
)
from app.events.models import new_event
from app.services import outbox as outbox_service

pytestmark = pytest.mark.not_pg

_UNREACHABLE_DSN = "postgresql://app:app@192.0.2.1:5432/app"


def _event():
    return new_event(event_type="test.outbox.memory", payload={"value": "test"}, trace_id="t-4064")


class _Cursor:
    def __init__(self, row_id: str = "inserted-key") -> None:
        self.row_id = row_id
        self.calls: list[tuple[object, ...]] = []

    def execute(self, _sql: str, params: tuple[object, ...]) -> None:
        self.calls.append(params)

    def fetchone(self) -> tuple[str]:
        return (self.row_id,)


class _Connection:
    def __init__(self, row_id: str = "inserted-key") -> None:
        self.autocommit = False
        self.closed = False
        self.cursor_instance = _Cursor(row_id)

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


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
    conn = _Connection("dsn-key")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda: conn)

    assert outbox_service.write_outbox_event(_event(), idempotency_key="dsn-key") == "dsn-key"
    assert conn.cursor_instance.calls


def test_write_outbox_event_uses_explicit_pg_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit Postgres backend must retain the canonical self-owned path."""
    monkeypatch.setenv("STORE_BACKEND", " pg ")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    conn = _Connection("pg-key")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda: conn)

    assert outbox_service.write_outbox_event(_event(), idempotency_key="pg-key") == "pg-key"
    assert conn.cursor_instance.calls


def test_settings_resolved_dsn_is_not_treated_as_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The skip predicate may not be narrower than the connection's resolver (#4214 D1).

    ``conn_rw()`` resolves through ``resolve_runtime_database_url(os.environ)``,
    which also honours ``PKM_DB_HOST``/``PKM_DB_NAME_*``/``POSTGRES_*``. A skip
    predicate that read only ``DATABASE_URL``/``DB_DSN`` therefore classified a
    runtime whose connection WOULD have succeeded as unconfigured, and dropped
    the write while returning ``""`` — the value this contract defines as
    success/dedup.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)
    monkeypatch.setenv("PKM_DB_HOST", "named-host.example")
    conn = _Connection("resolver-key")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda: conn)

    assert outbox_service.write_outbox_event(_event(), idempotency_key="resolver-key") == "resolver-key"
    assert conn.cursor_instance.calls


@pytest.mark.parametrize("naming_key", RUNTIME_DATABASE_ENV_KEYS)
def test_skip_decision_never_contradicts_the_connection_resolver(
    monkeypatch: pytest.MonkeyPatch,
    naming_key: str,
) -> None:
    """Every key the connection's resolver reads must also make the write connect.

    Parametrized over ``RUNTIME_DATABASE_ENV_KEYS`` itself, so a new synthesis
    input added to ``app/config/database.py`` is covered here automatically
    instead of quietly re-opening the #4214 D1 divergence.
    """
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv(
        naming_key,
        "postgresql://named.example/app" if naming_key in {"DATABASE_URL", "DB_DSN"} else "named",
    )
    conn = _Connection(f"named-{naming_key}")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda: conn)

    assert (
        outbox_service.write_outbox_event(_event(), idempotency_key=f"named-{naming_key}")
        == f"named-{naming_key}"
    )
    # The DSN the write would use is byte-identical to the one the connection
    # resolves, so the decision and the connection cannot disagree.
    assert explicit_runtime_database_url(os.environ) == resolve_runtime_database_url(os.environ)


def test_write_outbox_event_skips_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The chosen best-effort contract skips when the runtime names no database.

    "Unconfigured" now means every input the connection's resolver would use is
    a built-in default, so the DSN it hands back is the compose-shaped fallback
    nobody named — connecting to it is exactly the stalling DNS lookup #4064
    exists to avoid.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    for key in RUNTIME_DATABASE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    def _fail_if_called(*args: object, **kwargs: object) -> Any:
        raise AssertionError("unconfigured write_outbox_event must not open a DB connection")

    monkeypatch.setattr(outbox_service, "conn_rw", _fail_if_called)

    assert explicit_runtime_database_url(os.environ) is None
    assert outbox_service.write_outbox_event(_event(), idempotency_key="unconfigured-key") == ""


@pytest.mark.parametrize("backend", ["postgres", "pgvector"])
def test_write_outbox_event_rejects_unsupported_backend(
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    """Unsupported explicit backends fail loud before any self-owned connection attempt."""
    monkeypatch.setenv("STORE_BACKEND", backend)
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _fail_if_called(*args: object, **kwargs: object) -> Any:
        raise AssertionError("invalid backend must fail before opening a connection")

    monkeypatch.setattr(outbox_service, "conn_rw", _fail_if_called)

    with pytest.raises(RuntimeError, match="not supported"):
        outbox_service.write_outbox_event(_event(), idempotency_key="invalid-key")


def test_required_memory_write_uses_configured_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required DB intent overrides the optional memory-mode skip when a DSN is configured."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    conn = _Connection("required-key")
    monkeypatch.setattr(outbox_service, "conn_rw", lambda: conn)

    assert (
        outbox_service.write_outbox_event(
            _event(),
            idempotency_key="required-key",
            required_db=True,
        )
        == "required-key"
    )
    assert conn.cursor_instance.calls


def test_required_memory_write_propagates_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Required DB intent must fail loud rather than masquerade as an optional skip."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")

    def _raise() -> Any:
        raise RuntimeError("required connection failed")

    monkeypatch.setattr(outbox_service, "_open_conn", _raise)

    with pytest.raises(RuntimeError, match="required connection failed"):
        outbox_service.write_outbox_event(
            _event(),
            idempotency_key="required-failure-key",
            required_db=True,
        )


def test_supplied_connection_bypasses_self_owned_backend_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supplied transaction is authoritative and remains caller-owned."""
    monkeypatch.setenv("STORE_BACKEND", "postgres")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured.example/app")
    conn = _Connection("supplied-key")

    assert (
        outbox_service.write_outbox_event(
            _event(),
            conn=conn,
            idempotency_key="supplied-key",
        )
        == "supplied-key"
    )
    assert conn.cursor_instance.calls
    assert conn.closed is False
