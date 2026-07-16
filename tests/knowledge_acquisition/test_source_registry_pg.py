"""YSS-01 (#3916): source registry service-layer contract, Postgres backend.

Exercises the SAME service-layer contract suite as
`tests/knowledge_acquisition/test_source_registry.py` (memory backend)
against the real Postgres-backed `SourceRegistry`, via the shared assertions
in `_source_registry_contract.py` -- proving the integrity rules hold
identically on both backends (AC8: "the pg backend passes the same
service-layer suite").

Marked `pg`: excluded by the default `-m "not pg"` suite; does not run
locally without a real Postgres. When it does run (CI's pg lane), the
standard `tests/conftest.py` autouse fixtures provide `DATABASE_URL` and
`STORE_SCHEMA_AUTOCREATE=1` for pg-marked tests, so this file selects the
backend the same way every other pg-marked test in this repo does (DSN-based
auto-detection, no explicit STORE_BACKEND override needed) and the
`acquisition_source_registry` table is created on demand if the migration
has not been applied to that database.
"""

from __future__ import annotations

import pytest

from app.knowledge_acquisition.source_registry import SourceRegistry
from tests.knowledge_acquisition._source_registry_contract import ALL_CONTRACT_ASSERTIONS


def _make_pg_registry() -> SourceRegistry:
    return SourceRegistry.for_runtime()


@pytest.mark.pg
def test_pg_backend_contract() -> None:
    pytest.importorskip("psycopg")
    for assertion in ALL_CONTRACT_ASSERTIONS:
        assertion(_make_pg_registry)
