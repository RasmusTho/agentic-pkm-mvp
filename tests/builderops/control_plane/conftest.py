from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.builderops.control_plane import AuthorityEnvelope, PostgresBuilderOpsStore


def _base_dsn() -> str:
    """The control-plane database, named explicitly or not at all (#4573).

    This used to fall back to the production DSN, so an unset environment
    pointed schema creation at prod. The pg lane's guard in tests/conftest.py
    refuses a prod-looking value for either variable.
    """

    from app.db.dsn import resolve_dsn

    dsn = os.getenv("BUILDEROPS_DATABASE_URL", "").strip() or resolve_dsn()
    if not dsn:
        pytest.skip(
            "no control-plane database configured: set BUILDEROPS_DATABASE_URL "
            "(or DATABASE_URL) to an explicit non-production Postgres"
        )
    return dsn


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def control_plane_store() -> Iterator[PostgresBuilderOpsStore]:
    base_dsn = _base_dsn()
    try:
        with psycopg.connect(base_dsn, connect_timeout=2, autocommit=True) as conn:
            schema = f"builderops_test_{uuid4().hex}"
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable for BuilderOps integration test: {exc}")
    dsn = _schema_dsn(base_dsn, schema)
    store = PostgresBuilderOpsStore(dsn)
    store.initialize()
    try:
        yield store
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def envelope() -> AuthorityEnvelope:
    return AuthorityEnvelope(
        repository="RasmusTho/agentic-pkm-mvp",
        scope="issue:3792",
        stack="builderops-control-plane",
        actor="agent:codex-root",
        source_refs=("github:issue:3792",),
        schema_version=1,
    )
