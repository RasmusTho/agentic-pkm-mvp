"""Child-process probes for late pytest database configuration (#4573).

The filename intentionally does not start with ``test_``: the parent guard
suite invokes each probe explicitly with the record-and-block psycopg plugin,
so a broken safety wrapper is measured without ever opening a real socket.
"""

from __future__ import annotations

import asyncio

import psycopg
import pytest


@pytest.mark.pg
def test_dynamic_explicit_conninfo_is_blocked() -> None:
    target = "postgresql://app:app@" + "127.0.0.1:15432/app"
    psycopg.connect(target)


@pytest.mark.pg
def test_late_runtime_default_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PKM_DB_HOST", "127.0.0.1")
    psycopg.connect("postgresql://app:app@127.0.0.1:15434/app_test")


@pytest.mark.pg
def test_late_ambient_socket_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGHOST", "/var/run/postgresql")
    monkeypatch.setenv("PGDATABASE", "app")
    psycopg.connect("")


@pytest.mark.pg
def test_late_service_file_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PGSERVICEFILE", "/tmp/hidden-service.conf")
    psycopg.connect("")


@pytest.mark.pg
def test_module_kwargs_only_prod_target_is_blocked() -> None:
    psycopg.connect(host="127.0.0.1", port=15432, dbname="safe")


@pytest.mark.pg
def test_sync_kwargs_override_safe_conninfo_is_blocked() -> None:
    safe = "postgresql://app:app@127.0.0.1:15434/app_test"
    psycopg.Connection.connect(safe, port=15432)


@pytest.mark.pg
def test_async_service_kwarg_is_blocked() -> None:
    asyncio.run(psycopg.AsyncConnection.connect(service="hidden"))


@pytest.mark.pg
def test_implicit_local_defaults_are_blocked() -> None:
    psycopg.connect("")


@pytest.mark.pg
def test_explicit_local_socket_is_blocked() -> None:
    psycopg.connect(host="/var/run/postgresql", dbname="app_test")


@pytest.mark.pg
def test_leading_empty_host_member_is_blocked() -> None:
    psycopg.connect(host=",127.0.0.1", port=15434, dbname="app_test")


@pytest.mark.pg
def test_trailing_empty_host_member_is_blocked() -> None:
    target = "host=127.0.0.1, port=15434 dbname=app_test"
    psycopg.Connection.connect(target)


@pytest.mark.pg
def test_empty_hostaddr_member_is_blocked() -> None:
    asyncio.run(
        psycopg.AsyncConnection.connect(
            hostaddr=",127.0.0.1", port=15434, dbname="app_test"
        )
    )


@pytest.mark.pg
def test_paired_empty_host_member_is_blocked() -> None:
    psycopg.connect(
        host=",127.0.0.1",
        hostaddr=",127.0.0.1",
        port=15434,
        dbname="app_test",
    )
