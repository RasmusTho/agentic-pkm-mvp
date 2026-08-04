"""A pytest plugin that records every `psycopg.connect` attempt (#4573).

Loaded with `-p` into the child pytest processes driven by
`test_pg_dsn_resolution.py`, so those tests can assert on what the guarded run
*actually did* rather than on the absence of a connection-failure string. An
assertion built from failure messages is vacuous against a connection that
succeeds — which is precisely the case that matters when the DSN points at a
live production server.

The spy is installed at plugin import, which pytest performs before any test
module is imported, so it also sees import-time probes such as a `skipif` that
evaluates `pg_available()`.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg


ATTEMPTS_ENV = "PG_CONNECT_SPY_LOG"


def _log_path() -> Path | None:
    target = os.environ.get(ATTEMPTS_ENV, "").strip()
    return Path(target) if target else None


# An empty conninfo is NOT nothing: libpq then supplies its own defaults from
# PGHOST/PGPORT/PGDATABASE or the local socket, which is a silently picked
# target. It must be recorded as a distinguishable value rather than as a blank
# line a reader would strip away.
AMBIENT = "<ambient libpq defaults (empty conninfo)>"


def _record(conninfo: str) -> None:
    path = _log_path()
    if path is None:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{conninfo.strip() or AMBIENT}\n")


def _spy_module_function(module, name: str) -> None:
    original = getattr(module, name)

    def _spying(conninfo: str = "", *args, **kwargs):
        _record(conninfo)
        return original(conninfo, *args, **kwargs)

    setattr(module, name, _spying)


def _spy_classmethod(cls, name: str) -> None:
    # `cls.connect` is an already-bound classmethod, so wrapping the bound
    # object and re-decorating would pass `cls` twice and land the class object
    # where the conninfo belongs. Take the underlying function instead.
    original = getattr(cls, name).__func__

    def _spying(owner, conninfo: str = "", *args, **kwargs):
        _record(conninfo)
        return original(owner, conninfo, *args, **kwargs)

    setattr(cls, name, classmethod(_spying))


# psycopg exposes three connect entry points and they are distinct objects:
# `psycopg.connect is not psycopg.Connection.connect`. Patching only the module
# function would let a caller using either classmethod slip past unrecorded,
# silently weakening every `attempts == []` assertion built on this spy.
_spy_module_function(psycopg, "connect")
_spy_classmethod(psycopg.Connection, "connect")
_spy_classmethod(psycopg.AsyncConnection, "connect")
