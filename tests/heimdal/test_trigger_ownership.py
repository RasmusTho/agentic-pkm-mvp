"""Migration ownership and continuous enforcement for Heimdal append-only guards.

Issue #4598 removes the runtime-wins path for the six migration-owned
reject-mutation triggers.  The cheap recording proof covers every production
bootstrap seam.  The ``pg`` proof makes the old drop/recreate window
deterministic by pausing the real production statement immediately after the
DROP and attempting a concurrent mutation through a second connection.
"""

from __future__ import annotations

import importlib
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class _TriggerSeam:
    module: str
    table: str
    trigger: str
    function: str
    indexes: tuple[str, ...]
    migration: str
    columns: tuple[str, ...]
    error_type: str


TRIGGER_SEAMS = (
    _TriggerSeam(
        "app.heimdal.consent_ledger",
        "heimdal_consent_grant",
        "heimdal_consent_grant_no_update",
        "heimdal_consent_grant_reject_mutation",
        (
            "heimdal_consent_grant_seq_idx",
            "heimdal_consent_grant_grant_ref_idx",
            "heimdal_consent_grant_scope_idx",
        ),
        "c4f7a1b2d9e3",
        ("sequence bigint", "grant_ref text", "scope text", "basis text"),
        "ConsentLedgerSchemaMissingError",
    ),
    _TriggerSeam(
        "app.heimdal.media_receipts",
        "heimdal_media_receipt",
        "heimdal_media_receipt_no_update",
        "heimdal_media_receipt_reject_mutation",
        ("heimdal_media_receipt_seq_idx", "heimdal_media_receipt_capture_id_idx"),
        "e3c1a7f5d2b8",
        ("sequence bigint", "capture_id text"),
        "MediaReceiptSchemaMissingError",
    ),
    _TriggerSeam(
        "app.heimdal.observation_log",
        "heimdal_observation_log",
        "heimdal_observation_log_no_update",
        "heimdal_observation_log_reject_mutation",
        ("heimdal_observation_log_seq_idx", "heimdal_observation_log_topic_idx"),
        "8b21e6a1f0c4",
        ("sequence bigint", "topic text"),
        "ObservationLogSchemaMissingError",
    ),
    _TriggerSeam(
        "app.heimdal.raw_read_gate",
        "heimdal_raw_read_receipt",
        "heimdal_raw_read_receipt_no_update",
        "heimdal_raw_read_receipt_reject_mutation",
        ("heimdal_raw_read_receipt_seq_idx", "heimdal_raw_read_receipt_raw_ref_idx"),
        "f1c7e2a9b4d6",
        ("sequence bigint", "raw_ref text"),
        "RawReadReceiptSchemaMissingError",
    ),
    _TriggerSeam(
        "app.heimdal.raw_store",
        "heimdal_raw_record",
        "heimdal_raw_record_no_update",
        "heimdal_raw_record_reject_mutation",
        ("heimdal_raw_record_seq_idx", "heimdal_raw_record_content_identity_uq"),
        "d5a8e2f1b6c3",
        ("sequence bigint", "content_identity text"),
        "RawStoreSchemaMissingError",
    ),
    _TriggerSeam(
        "app.heimdal.retention",
        "heimdal_raw_deletion_receipt",
        "heimdal_raw_deletion_receipt_no_update",
        "heimdal_raw_deletion_receipt_reject_mutation",
        (
            "heimdal_raw_deletion_receipt_seq_idx",
            "heimdal_raw_deletion_receipt_record_id_idx",
        ),
        "a3f9d1c6e2b8",
        ("sequence bigint", "record_id integer"),
        "DeletionReceiptSchemaMissingError",
    ),
)


class _RecordingCursor:
    def __init__(self, conn: "_RecordingConn") -> None:
        self._conn = conn
        self._statement = ""
        self._params: tuple[Any, ...] = ()

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> None:
        self._statement = statement
        self._params = tuple(params or ())
        self._conn.executed.append(statement)

    def fetchone(self) -> tuple[Any, ...]:
        lowered = self._statement.lower()
        if "from pg_trigger" in lowered:
            if self._conn.missing_trigger:
                return None  # type: ignore[return-value]
            seam = self._conn.seam
            retention_fragment = (
                " IF TG_OP = 'DELETE' AND current_setting('app.heimdal_retention_bypass', true) = 'true' "
                "THEN RETURN OLD; END IF; "
                if seam.table == "heimdal_raw_record"
                else ""
            )
            return (
                seam.trigger,
                f"CREATE TRIGGER {seam.trigger} BEFORE UPDATE OR DELETE ON {seam.table} "
                f"FOR EACH ROW EXECUTE FUNCTION {seam.function}()",
                self._conn.trigger_enabled,
                seam.function,
                self._conn.function_body
                or f"CREATE FUNCTION {seam.function}() RETURNS trigger LANGUAGE plpgsql "
                f"AS $$ BEGIN IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'append-only'; END IF; "
                f"{retention_fragment} RAISE EXCEPTION 'append-only'; END $$",
            )
        # ``to_regclass`` and consent-ledger standing-grant probes both need a
        # truthy row.  The exact metadata queries are covered by the real-PG test.
        return (1,)

    def fetchall(self) -> list[tuple[str]]:
        return [(name,) for name in self._conn.seam.indexes if name != self._conn.missing_index]


class _RecordingConn:
    def __init__(
        self,
        seam: _TriggerSeam,
        *,
        missing_index: str | None = None,
        missing_trigger: bool = False,
        trigger_enabled: str = "O",
        function_body: str | None = None,
    ) -> None:
        self.seam = seam
        self.missing_index = missing_index
        self.missing_trigger = missing_trigger
        self.trigger_enabled = trigger_enabled
        self.function_body = function_body
        self.executed: list[str] = []

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)


@pytest.mark.parametrize("seam", TRIGGER_SEAMS, ids=lambda seam: seam.table)
def test_present_trigger_is_not_dropped_and_recreated(
    seam: _TriggerSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real bootstrap entrypoint is SELECT-only on a migrated table."""
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(seam)

    module._bootstrap_pg(conn)

    non_select = [sql for sql in conn.executed if not sql.lstrip().lower().startswith("select")]
    assert non_select == []


def test_each_reject_mutation_trigger_has_one_owner() -> None:
    """Each trigger is declared once by Alembic; runtime ownership is assert-only."""
    versions = REPO_ROOT / "app" / "alembic" / "versions"
    for seam in TRIGGER_SEAMS:
        owner = next(versions.glob(f"{seam.migration}_*.py"))
        declaration = f"create trigger {seam.trigger}".lower()
        declarations = [
            (candidate, candidate.read_text(encoding="utf-8").lower().count(declaration))
            for candidate in versions.glob("*.py")
        ]
        declarations = [(candidate, count) for candidate, count in declarations if count]
        assert declarations == [(owner, 1)], (seam.trigger, declarations)


def test_seam_issues_no_ddl_when_objects_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One aggregate assertion keeps all six SELECT-only receipts visible."""
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    observed: dict[str, list[str]] = {}
    for seam in TRIGGER_SEAMS:
        module = importlib.import_module(seam.module)
        conn = _RecordingConn(seam)
        module._bootstrap_pg(conn)
        observed[seam.table] = [
            sql for sql in conn.executed if not sql.lstrip().lower().startswith("select")
        ]
    assert observed == {seam.table: [] for seam in TRIGGER_SEAMS}


@pytest.mark.parametrize("seam", TRIGGER_SEAMS, ids=lambda seam: seam.table)
def test_missing_migration_owned_trigger_fails_loud_without_repair(
    seam: _TriggerSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(seam, missing_trigger=True)

    error_type = getattr(module, seam.error_type)
    with pytest.raises(error_type, match="missing migration-owned trigger"):
        module._bootstrap_pg(conn)

    assert all(sql.lstrip().lower().startswith("select") for sql in conn.executed)


@pytest.mark.parametrize("seam", TRIGGER_SEAMS, ids=lambda seam: seam.table)
def test_missing_migration_owned_index_fails_loud_without_repair(
    seam: _TriggerSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(seam, missing_index=seam.indexes[0])

    error_type = getattr(module, seam.error_type)
    with pytest.raises(error_type, match="missing migration-owned index"):
        module._bootstrap_pg(conn)

    assert all(sql.lstrip().lower().startswith("select") for sql in conn.executed)


@pytest.mark.parametrize("enabled", ["R", "D"])
def test_non_origin_trigger_mode_fails_loud_without_repair(
    enabled: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seam = TRIGGER_SEAMS[0]
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(seam, trigger_enabled=enabled)

    with pytest.raises(getattr(module, seam.error_type), match="incompatible"):
        module._bootstrap_pg(conn)


def test_non_rejecting_function_fails_loud_without_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seam = TRIGGER_SEAMS[0]
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(
        seam,
        function_body=(
            f"CREATE FUNCTION {seam.function}() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN RETURN NEW; END $$"
        ),
    )

    with pytest.raises(getattr(module, seam.error_type), match="required guard"):
        module._bootstrap_pg(conn)


def test_retention_guard_requires_narrow_delete_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seam = next(item for item in TRIGGER_SEAMS if item.table == "heimdal_raw_record")
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    module = importlib.import_module(seam.module)
    conn = _RecordingConn(
        seam,
        function_body=(
            f"CREATE FUNCTION {seam.function}() RETURNS trigger LANGUAGE plpgsql "
            "AS $$ BEGIN IF current_setting('app.heimdal_retention_bypass', true) = 'true' "
            "THEN RETURN NEW; END IF; RAISE EXCEPTION 'append-only'; END $$"
        ),
    )

    with pytest.raises(getattr(module, seam.error_type), match="required guard"):
        module._bootstrap_pg(conn)


class _GapCursor:
    def __init__(
        self,
        inner: Any,
        gap_open: threading.Event,
        release_gap: threading.Event,
    ) -> None:
        self._inner = inner
        self._gap_open = gap_open
        self._release_gap = release_gap

    def execute(self, statement: str, params: tuple[Any, ...] = ()) -> Any:
        result = self._inner.execute(statement, params)
        if statement.lstrip().lower().startswith("drop trigger"):
            self._gap_open.set()
            if not self._release_gap.wait(timeout=5):
                raise AssertionError("timed out waiting for the concurrent mutation probe")
        return result

    def fetchone(self) -> Any:
        return self._inner.fetchone()

    def fetchall(self) -> Any:
        return self._inner.fetchall()


class _GapConn:
    def __init__(
        self,
        inner: Any,
        gap_open: threading.Event,
        release_gap: threading.Event,
    ) -> None:
        self._inner = inner
        self._gap_open = gap_open
        self._release_gap = release_gap

    def cursor(self) -> _GapCursor:
        return _GapCursor(self._inner.cursor(), self._gap_open, self._release_gap)


def _create_guard_fixture(conn: Any, seam: _TriggerSeam) -> None:
    columns = ", ".join(
        ("id integer PRIMARY KEY", "marker integer NOT NULL DEFAULT 0", *seam.columns)
    )
    conn.execute(f"CREATE TABLE {seam.table} ({columns})")
    for index in seam.indexes:
        if index.endswith("_uq"):
            target = "content_identity"
            unique = "UNIQUE "
        elif "grant_ref" in index:
            target = "grant_ref"
            unique = ""
        elif "scope" in index:
            target = "scope"
            unique = ""
        elif "capture_id" in index:
            target = "capture_id"
            unique = ""
        elif "topic" in index:
            target = "topic"
            unique = ""
        elif "raw_ref" in index:
            target = "raw_ref"
            unique = ""
        elif "record_id" in index:
            target = "record_id"
            unique = ""
        else:
            target = "sequence"
            unique = ""
        conn.execute(f"CREATE {unique}INDEX {index} ON {seam.table} ({target})")
    retention_guard = (
        """
        IF TG_OP = 'DELETE' AND current_setting('app.heimdal_retention_bypass', true) = 'true' THEN
            RETURN OLD;
        END IF;
    """
        if seam.table == "heimdal_raw_record"
        else ""
    )
    conn.execute(
        f"""
        CREATE FUNCTION {seam.function}() RETURNS trigger AS $$
        BEGIN
            {retention_guard}
            RAISE EXCEPTION 'append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    conn.execute(
        f"CREATE TRIGGER {seam.trigger} BEFORE UPDATE OR DELETE ON {seam.table} "
        f"FOR EACH ROW EXECUTE FUNCTION {seam.function}()"
    )
    if seam.table == "heimdal_consent_grant":
        conn.execute(
            f"INSERT INTO {seam.table} (id, marker, sequence, grant_ref, scope, basis) VALUES "
            "(1, 0, 1, 'grant-v1-voice-memo', 'voice', 'self_record'), "
            "(2, 0, 2, 'grant-media-capture-v1', 'media', 'self_record')"
        )
    else:
        values = ["1", "0"] + [
            "1" if "bigint" in col or "integer" in col else "'value'" for col in seam.columns
        ]
        conn.execute(f"INSERT INTO {seam.table} VALUES ({', '.join(values)})")


@pytest.mark.pg
@pytest.mark.parametrize("seam", TRIGGER_SEAMS, ids=lambda seam: seam.table)
def test_append_only_enforcement_has_no_window(
    seam: _TriggerSeam, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent UPDATE is rejected throughout the production seam call."""
    psycopg = pytest.importorskip("psycopg")
    from app.db.dsn import looks_like_prod_dsn, resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("explicit non-production DATABASE_URL/DB_DSN required")
    assert not looks_like_prod_dsn(dsn), "refusing append-only proof against a production DSN"
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    schema = f"issue4598_{uuid.uuid4().hex[:12]}"

    with psycopg.connect(dsn, autocommit=True) as setup:
        setup.execute(f'CREATE SCHEMA "{schema}"')
        setup.execute(f'SET search_path TO "{schema}"')
        _create_guard_fixture(setup, seam)

    seam_conn = psycopg.connect(dsn, autocommit=True)
    mutator = psycopg.connect(dsn, autocommit=True)
    gap_open = threading.Event()
    release_gap = threading.Event()
    errors: list[BaseException] = []
    try:
        seam_conn.execute(f'SET search_path TO "{schema}"')
        mutator.execute(f'SET search_path TO "{schema}"')
        wrapped = _GapConn(seam_conn, gap_open, release_gap)
        module = importlib.import_module(seam.module)

        def _invoke_seam() -> None:
            try:
                module._bootstrap_pg(wrapped)
            except BaseException as exc:  # surfaced in the main test thread
                errors.append(exc)

        thread = threading.Thread(target=_invoke_seam, daemon=True)
        thread.start()
        gap_open.wait(timeout=0.25)
        mutation_rejected = False
        try:
            mutator.execute(f"UPDATE {seam.table} SET marker = marker + 1 WHERE id = 1")
        except Exception:
            mutation_rejected = True
        finally:
            release_gap.set()
        thread.join(timeout=5)

        assert not thread.is_alive(), "bootstrap seam did not finish"
        assert errors == []
        assert mutation_rejected, f"{seam.trigger} left an observable mutation window"
    finally:
        release_gap.set()
        seam_conn.close()
        mutator.close()
        with psycopg.connect(dsn, autocommit=True) as cleanup:
            cleanup.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
