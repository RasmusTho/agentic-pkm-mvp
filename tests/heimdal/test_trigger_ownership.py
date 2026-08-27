"""Production-path proof for migration-owned Heimdal mutation triggers (#4598)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from app.heimdal import (
    consent_ledger,
    media_receipts,
    observation_log,
    raw_read_gate,
)
from app.heimdal.trigger_ownership import (
    CONSENT_GRANT_TRIGGER,
    MEDIA_RECEIPT_TRIGGER,
    OBSERVATION_LOG_TRIGGER,
    RAW_DELETION_RECEIPT_TRIGGER,
    RAW_READ_RECEIPT_TRIGGER,
    RAW_RECORD_TRIGGER,
    RejectMutationTrigger,
    assert_migration_owned_reject_mutation_trigger,
)
from tests.architecture.durable_table_classification import (
    RECORDED_ATTACHED_DDL_DEBT,
    discover_durable_tables,
    discover_runtime_ddl_seams,
    observed_attached_ddl_debt,
)

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIGGER_SPECS = (
    CONSENT_GRANT_TRIGGER,
    MEDIA_RECEIPT_TRIGGER,
    OBSERVATION_LOG_TRIGGER,
    RAW_READ_RECEIPT_TRIGGER,
    RAW_DELETION_RECEIPT_TRIGGER,
    RAW_RECORD_TRIGGER,
)
SIMPLE_TRIGGER_SEAMS = (
    (consent_ledger, CONSENT_GRANT_TRIGGER),
    (media_receipts, MEDIA_RECEIPT_TRIGGER),
    (observation_log, OBSERVATION_LOG_TRIGGER),
    (raw_read_gate, RAW_READ_RECEIPT_TRIGGER),
)


class _PresentCursor:
    def __init__(self, conn: "_PresentConnection") -> None:
        self._conn = conn
        self._row: tuple[str, ...] = ()

    def execute(self, statement: str, params: object = None) -> None:
        sql = str(statement)
        self._conn.executed.append(sql)
        if "FROM pg_trigger AS trigger" in sql:
            assert params == (self._conn.spec.table, self._conn.spec.trigger)
            self._rows = [_catalog_row(self._conn.spec)]
            self._row = ()
        else:
            count = sql.lower().count("to_regclass")
            self._row = tuple("present" for _ in range(count))
            self._rows = []

    def fetchone(self) -> tuple[str, ...]:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _PresentConnection:
    def __init__(self, spec: RejectMutationTrigger) -> None:
        self.executed: list[str] = []
        self.spec = spec

    def cursor(self) -> _PresentCursor:
        return _PresentCursor(self)


class _CatalogCursor:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def execute(self, statement: str, params: object = None) -> None:
        assert "FROM pg_trigger AS trigger" in statement
        assert params is not None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _CatalogConnection:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def cursor(self) -> _CatalogCursor:
        return _CatalogCursor(self._rows)


def _catalog_row(
    spec: RejectMutationTrigger,
    *,
    enabled: str = "O",
) -> tuple[Any, ...]:
    return (
        "public",
        spec.table,
        spec.trigger,
        27,
        enabled,
        "",
        True,
        True,
        spec.function,
        "f",
        True,
        0,
        "",
        "plpgsql",
        "v",
        False,
        False,
        False,
        "u",
        None,
        spec.body,
    )


def _assert_catalog(spec: RejectMutationTrigger, rows: list[tuple[Any, ...]]) -> None:
    assert_migration_owned_reject_mutation_trigger(
        _CatalogConnection(rows),
        spec,
        error_type=RuntimeError,
        migration_hint="run alembic upgrade head",
    )


@pytest.mark.parametrize(
    ("module", "spec"),
    SIMPLE_TRIGGER_SEAMS,
    ids=lambda value: value.__name__ if hasattr(value, "__name__") else value.table,
)
def test_present_trigger_is_not_dropped_and_recreated(
    module: Any,
    spec: RejectMutationTrigger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production bootstrap authenticates, but never mutates, an existing trigger."""

    conn = _PresentConnection(spec)
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")

    module._bootstrap_pg(conn)

    assert any("FROM pg_trigger AS trigger" in sql for sql in conn.executed)
    assert all(not re.match(r"\s*(?:CREATE|ALTER|DROP)\b", sql, re.I) for sql in conn.executed)


def test_each_reject_mutation_trigger_has_one_owner() -> None:
    """Alembic owns all six objects; runtime fixture DDL is existence-fenced."""

    assert len({spec.table for spec in TRIGGER_SPECS}) == 6
    assert len({spec.trigger for spec in TRIGGER_SPECS}) == 6
    assert len({spec.function for spec in TRIGGER_SPECS}) == 6
    seams = discover_runtime_ddl_seams(discover_durable_tables())
    governed_tables = {spec.table for spec in TRIGGER_SPECS}
    runtime_trigger_creates = [
        seam
        for seam in seams
        if seam.verb == "create trigger" and seam.table in governed_tables
    ]
    assert runtime_trigger_creates
    assert all(seam.autocreate_gated and seam.existence_probed for seam in runtime_trigger_creates)
    runtime = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((REPO_ROOT / "app" / "heimdal").glob("*.py"))
    )
    assert "DROP TRIGGER" not in runtime.upper()


def test_seam_issues_no_ddl_when_objects_are_present() -> None:
    """Every currently discovered attached-object group has the skip guard."""

    observed = observed_attached_ddl_debt(discover_runtime_ddl_seams(discover_durable_tables()))
    assert dict(observed) == {}
    assert dict(RECORDED_ATTACHED_DDL_DEBT) == {}


def test_append_only_enforcement_has_no_window() -> None:
    """The accepted catalog modes stay continuously active and exact."""

    for spec in TRIGGER_SPECS:
        _assert_catalog(spec, [_catalog_row(spec, enabled="O")])
        _assert_catalog(spec, [_catalog_row(spec, enabled="A")])

    body = RAW_RECORD_TRIGGER.body
    assert "TG_OP = 'DELETE'" in body
    assert "TG_OP = 'UPDATE'" not in body
    assert "current_setting('app.heimdal_retention_bypass', true) = 'true'" in body
    assert "heimdal_raw_deletion_tombstone" in body
    liveness_source = (REPO_ROOT / "app/heimdal/raw_liveness.py").read_text(encoding="utf-8")
    assert "SELECT set_config(%s, 'true', true)" in liveness_source


@pytest.mark.parametrize(
    ("index", "drifted"),
    (
        (0, "other_schema"),
        (1, "other_table"),
        (2, "other_trigger"),
        (3, 19),
        (4, "D"),
        (5, "1"),
        (6, False),
        (7, False),
        (8, "other_function"),
        (9, "p"),
        (10, False),
        (11, 1),
        (12, "23"),
        (13, "sql"),
        (14, "s"),
        (15, True),
        (16, True),
        (17, True),
        (18, "s"),
        (19, ["search_path=public"]),
        (20, "BEGIN RETURN NEW; END;"),
    ),
)
def test_structural_trigger_authentication_rejects_drift_matrix(
    index: int,
    drifted: object,
) -> None:
    """Every catalog identity, attribute, binding, and body field is load-bearing."""

    row = list(_catalog_row(RAW_RECORD_TRIGGER))
    row[index] = drifted
    with pytest.raises(RuntimeError, match="Alembic-owned definition"):
        _assert_catalog(RAW_RECORD_TRIGGER, [tuple(row)])

    with pytest.raises(RuntimeError, match="Alembic-owned definition"):
        _assert_catalog(RAW_RECORD_TRIGGER, [])
    with pytest.raises(RuntimeError, match="Alembic-owned definition"):
        _assert_catalog(
            RAW_RECORD_TRIGGER,
            [_catalog_row(RAW_RECORD_TRIGGER), _catalog_row(RAW_RECORD_TRIGGER)],
        )


def test_function_body_authentication_preserves_literal_whitespace() -> None:
    """Whitespace inside SQL literals cannot collapse to the accepted body."""

    row = list(_catalog_row(RAW_RECORD_TRIGGER))
    row[20] = RAW_RECORD_TRIGGER.body.replace(
        "outside the governed tombstone transaction",
        "outside  the governed tombstone transaction",
    )
    with pytest.raises(RuntimeError, match="Alembic-owned definition"):
        _assert_catalog(RAW_RECORD_TRIGGER, [tuple(row)])
