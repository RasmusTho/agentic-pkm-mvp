from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.db.dsn import resolve_dsn
from app.stores import reset_store_backends
from app.stores.pg import pg_available


@pytest.mark.pg
def test_store_stats_pg(monkeypatch) -> None:
    if not pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("STORE_BACKEND", "pg")
    # Use whatever the run was pointed at — CI service container, local scratch
    # DB — and nothing otherwise. Hardcoding a DSN here once overrode CI's
    # service DSN and broke the test (#2937); the unset-fallback that replaced
    # it resolved to production (#4573). The pg lane guarantees an explicit,
    # non-prod DATABASE_URL by the time this runs.
    monkeypatch.setenv("DATABASE_URL", resolve_dsn())
    reset_store_backends()

    runner = CliRunner()
    result = runner.invoke(cli, ["store", "stats", "--json"])
    assert result.exit_code == 0

    data = json.loads(result.output.strip())
    assert data.get("backend") == "pg"
    assert isinstance(data.get("objects"), int)
    assert isinstance(data.get("vectors"), int)
    assert data.get("objects") >= 0
    assert data.get("vectors") >= 0
