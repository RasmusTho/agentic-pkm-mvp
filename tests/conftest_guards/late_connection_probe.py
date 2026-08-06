"""Child-process probes for late pytest database configuration (#4573).

The filename intentionally does not start with ``test_``: the parent guard
suite invokes each probe explicitly with the record-and-block psycopg plugin,
so a broken safety wrapper is measured without ever opening a real socket.
"""

from __future__ import annotations

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
