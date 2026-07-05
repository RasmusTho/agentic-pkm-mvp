from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.stores import reset_store_backends
from app.stores.pg import pg_available


@pytest.mark.pg
def test_store_stats_pg(monkeypatch) -> None:
    if not pg_available():
        pytest.skip("Postgres backend not available")

    monkeypatch.setenv("STORE_BACKEND", "pg")
    # Respect an env-provided DATABASE_URL (CI service container, local dev DB);
    # the 15432 literal is only an unset-fallback, mirroring
    # tests/conftest.py::default_pg_dsn_for_pg_tests. Hardcoding this DSN
    # unconditionally overrode CI's service DSN and broke the test (#2937).
    monkeypatch.setenv(
        "DATABASE_URL",
        os.environ.get("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app"),
    )
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
