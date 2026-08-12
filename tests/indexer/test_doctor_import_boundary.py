"""Import-order regression for the optional Postgres index-doctor adapter."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = pytest.mark.not_pg


def test_index_doctor_lazy_loader_survives_postgres_first_import() -> None:
    """The production import order must not cache a circular-import false negative."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.stores.pg as pg; "
            "import app.index.doctor as doctor; "
            "loaded = doctor._load_pg_diagnostics(); "
            "assert loaded is not None; "
            "assert loaded[0] is pg.PgVectorIndex",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
