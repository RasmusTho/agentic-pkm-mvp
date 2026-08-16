"""MVR-05A1 (#4560): durable DDL executes only inside the Alembic revision chain.

`app/db/migrations_obsidian.sql` was executed by `app/db/db.py::ensure_schema`
on the first `conn_rw()` of **every process**. It was a second DDL owner for
`objects` and the only owner of `agent_memories`, and two of its statements

    ALTER TABLE public.objects DROP CONSTRAINT IF EXISTS objects_pkey;
    ALTER TABLE public.objects ADD CONSTRAINT objects_pkey PRIMARY KEY (id);

reverted any binding-keyed primary key a migration installed — at the next
process boot, with no error, because a single-binding instance has no duplicate
ids for the re-add to trip over. Nothing failed; the constraint was simply gone,
and only then did rows begin overwriting.

MVR-05A0 (#4543) cleared `file_state` and `objects.path` one table at a time and
left this guard scoped to those two surfaces, with a docstring stating that the
wider `objects` table "belongs to MVR-05A's projection cutover, not here". That
was wrong, and PR #4550's own residual-risk note said the opposite. MVR-05A
cannot own it: the revert fires at process boot, before any cutover could hold.
So MVR-05A1 (#4560) adopted `objects` and `agent_memories` into revision
`d1e8a0c5f37b`, rekeyed `objects` to `(vault_binding_id, id)` with
`objects_uuid_idx` scoped to `UNIQUE (vault_binding_id, uuid)`, and **deleted**
the bootstrap file and the runtime path that executed it — because superseding
those statements while the file still ran would only have re-broken the key at
the next boot.

This guard is the durable half of the fix. It fails if any of those surfaces
regains a second production DDL owner, and if the runtime ever starts issuing
schema statements again.

MVR-05A2 (#4576) widened it past `app/db/db.py`. The seam population is now
**derived** — every durable DDL statement under `app/**` targeting a table the
Alembic revision chain creates — so `app/stores/pg.py`, the Heimdal bootstrap
modules and the outbox are covered without being named, and so is the next seam
nobody names. That scan is also what found the `store_vector_index` autocreate
branch issuing three unconditional `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
statements without the "skip the group if the table already exists" probe
`app/db/db.py` had.

The test-fixture create-on-demand path in `app/db/db.py`
(`STORE_SCHEMA_AUTOCREATE=1`) is not a second owner: it mirrors the established
KERNEL-04 (#2766) / KERNEL-05 (#2850) contract for `store_*` and `outbox`, is
inert outside tests, and its shape parity with the revisions is asserted by
`tests/migrations/test_file_state_adoption.py` and
`tests/migrations/test_objects_adoption.py`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest import mock

import pytest

from tests.architecture.durable_table_classification import (
    RECORDED_ATTACHED_DDL_DEBT,
    discover_durable_tables,
    discover_runtime_ddl_seams,
    observed_attached_ddl_debt,
)

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SQL = REPO_ROOT / "app" / "db" / "migrations_obsidian.sql"
LEGACY_SQL_RUNNER = REPO_ROOT / "scripts" / "run_migration.py"
DB_MODULE = REPO_ROOT / "app" / "db" / "db.py"
ALEMBIC_VERSIONS = REPO_ROOT / "app" / "alembic" / "versions"

# The revision that took ownership of `file_state` and `objects.path` (MVR-05A0,
# #4543) and the one that took the rest (MVR-05A1, #4560).
FILE_STATE_OWNING_REVISION = "c7f4b1a83d29"
OBJECTS_OWNING_REVISION = "d1e8a0c5f37b"


def _revision_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ALEMBIC_VERSIONS.glob("*.py"))
    }


def _owning_revision_filename(revision: str) -> str:
    return next(ALEMBIC_VERSIONS.glob(f"{revision}_*.py")).name


def _raw_ddl_pattern(table: str) -> re.Pattern[str]:
    return re.compile(
        r"(?is)\b(?:create\s+table|alter\s+table|drop\s+table"
        r"|create(?:\s+unique)?\s+index)\b"
        rf"[^\"';]*\b(?:public\.)?{table}\b"
    )


def _op_ddl_pattern(table: str) -> re.Pattern[str]:
    # `op.create_table`/`add_column`/... take the table first, while
    # `op.create_index`/`drop_constraint`/... take the *name* first, so the table
    # name is matched anywhere in the call's arguments rather than only in first
    # position — otherwise half these alternatives could never fire.
    return re.compile(
        r"""(?is)\bop\.(?:create_table|add_column|drop_column|alter_column|drop_table"""
        r"""|create_index|drop_index|rename_table|create_primary_key|drop_constraint)\s*\("""
        rf"""[^)]*["'](?:public\.)?{table}["']"""
    )


def _table_ddl_owners(table: str) -> list[str]:
    raw = _raw_ddl_pattern(table)
    api = _op_ddl_pattern(table)
    return sorted(
        name for name, text in _revision_sources().items() if raw.search(text) or api.search(text)
    )


# --------------------------------------------------------------------------- #
# The runtime issues no durable DDL at all
# --------------------------------------------------------------------------- #


class _RecordingCursor:
    def __init__(self, conn: "_RecordingConn") -> None:
        self._conn = conn

    def __enter__(self) -> "_RecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, statement: str, *args, **kwargs) -> None:
        self._conn.executed.append(statement)

    def fetchone(self):
        # Satisfies both reads the fixture path performs: the `to_regclass`
        # existence probe that decides whether a table group runs at all, and
        # `assert_file_state_schema`, the read-only preflight afterwards.
        return {
            "present": self._conn.tables_present,
            "table_exists": True,
            "primary_key": ["vault_binding_id", "path"],
            "path_only_unique": [],
        }


class _RecordingConn:
    def __init__(self, *, tables_present: bool = False) -> None:
        self.executed: list[str] = []
        self.tables_present = tables_present

    def cursor(self) -> _RecordingCursor:
        return _RecordingCursor(self)

    def rollback(self) -> None:  # pragma: no cover - defensive
        raise AssertionError("ensure_schema must not need a rollback")


def _statements_executed_by_ensure_schema(
    *, autocreate: bool, tables_present: bool = False
) -> list[str]:
    from app.db import db as db_module

    env = {key: value for key, value in os.environ.items() if key != "STORE_SCHEMA_AUTOCREATE"}
    if autocreate:
        env["STORE_SCHEMA_AUTOCREATE"] = "1"
    conn = _RecordingConn(tables_present=tables_present)
    with mock.patch.dict(os.environ, env, clear=True):
        db_module.ensure_schema(conn)  # type: ignore[arg-type]
    return conn.executed


# --------------------------------------------------------------------------- #
# The same behavioural proof, for the store seam (MVR-05A2, #4576)
# --------------------------------------------------------------------------- #
#
# `app/db/db.py` has had the recording-connection proof above since MVR-05A1.
# `app/stores/pg.py` had none, so a structural read of its source was carrying
# the whole weight for the store tables — and three review rounds each found a
# new way to satisfy a structural read while the runtime still reshaped a
# migration-owned table: a stray `sqlite3.connect` in the same function, a
# predicate named `*autocreate*` that never reads the flag, a `continue` guarded
# by a constant that is never true. Every one of those is a statement about the
# *shape* of the code. None of them survives being asked what the function
# actually executes.


class _UnobservedConnection(BaseException):
    """Raised when the seam opens a connection this harness cannot record.

    Deriving from `BaseException`, not `Exception`, on purpose: the seam under
    test is allowed to wrap work in `try/except Exception`, and a sentinel that
    a bare `except Exception: pass` can swallow proves nothing.
    """


#: The store tables and the binding-keyed named-set endpoint they consume.
STORE_TABLES = frozenset(
    {
        "store_objects",
        "store_vector_index",
        "store_relations",
        "store_relation_memberships",
        "vector_index_meta",
        "sets",
    }
)

# MVR-05A3's test-only producer also reproduces the minimum child binding/FK
# mechanism. `sets` only supports the deliberately unchanged fresh
# membership.set_id FK; its key remains outside #4577.
MVR05A3_CHILD_FIXTURE_TABLES = frozenset(
    {"chunks", "embeddings", "relations", "sets", "membership", "decisions", "audit"}
)
AUTOCREATE_TABLES = STORE_TABLES | MVR05A3_CHILD_FIXTURE_TABLES


class _StoreRecordingCursor:
    def __init__(self, conn: "_StoreRecordingConn") -> None:
        self._conn = conn
        self._last_params: tuple = ()
        self._last_statement = ""

    def __enter__(self) -> "_StoreRecordingCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, statement: str, params: tuple = (), *args, **kwargs) -> None:
        self._conn.executed.append(statement)
        self._last_params = tuple(params or ())
        self._last_statement = statement

    def fetchone(self):
        # The `to_regclass` existence probe answers **for the table it was
        # asked about**. A fake that returned one blanket answer would let a
        # group probe table A and then reshape table B: the probe would report
        # B present, the group would be skipped, and the gate would see no
        # statements — while against a real database the ALTERs run on every
        # boot. `_every_group_only_touches_its_own_table` closes the same hole
        # from the other side.
        probed = self._last_params[0] if self._last_params else None
        return {"present": probed in self._conn.tables_present, "oid": 1}

    def fetchall(self):
        if "AS pk_columns" in self._last_statement:
            return [
                {
                    "table_name": table,
                    "pk_columns": pk,
                    "has_binding": True,
                }
                for table, pk in {
                    "store_objects": ["vault_binding_id", "object_id"],
                    "store_vector_index": ["vault_binding_id", "object_id"],
                    "store_relations": ["vault_binding_id", "src_id", "dst_id", "rel"],
                    "store_relation_memberships": [
                        "vault_binding_id",
                        "src_id",
                        "rel",
                        "value",
                    ],
                    "vector_index_meta": ["vault_binding_id", "id"],
                    "sets": ["vault_binding_id", "id"],
                }.items()
            ]
        # `assert_store_schema_with_connection`'s identity-column census.
        return [{"column_name": column} for column in ("dim", "model", "provider", "normalize")]


class _StoreRecordingConn:
    def __init__(self, *, tables_present: frozenset[str]) -> None:
        self.executed: list[str] = []
        self.tables_present = tables_present

    def __enter__(self) -> "_StoreRecordingConn":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def cursor(self) -> _StoreRecordingCursor:
        return _StoreRecordingCursor(self)

    def close(self) -> None:
        return None


def _statements_executed_by_ensure_tables(
    *, autocreate: bool, tables_present: frozenset[str]
) -> list[str]:
    from app.stores import pg as pg_module

    env = {key: value for key, value in os.environ.items() if key != "STORE_SCHEMA_AUTOCREATE"}
    if autocreate:
        env["STORE_SCHEMA_AUTOCREATE"] = "1"
    conn = _StoreRecordingConn(tables_present=tables_present)
    previous = pg_module._TABLES_READY
    try:
        pg_module._TABLES_READY = False
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(pg_module, "_connect", lambda: conn):
                # Patching `_connect` alone records only the statements that go
                # through it. A `psycopg.connect(...)` opened directly inside
                # `_ensure_tables` would execute against a real database and be
                # invisible here, so it is made impossible rather than assumed
                # absent.
                with mock.patch.object(
                    pg_module.psycopg,
                    "connect",
                    side_effect=_UnobservedConnection(
                        "_ensure_tables opened a connection outside _connect(); every "
                        "statement it issues must be observable by this harness"
                    ),
                ):
                    pg_module._ensure_tables()
    finally:
        pg_module._TABLES_READY = previous
    return conn.executed


_SQL_COMMENT = re.compile(r"(?s)/\*.*?\*/|--[^\n]*")
_SCHEMA_VERB = re.compile(
    r"(?is)\b(?:create|alter|drop)\s+"
    r"(?:or\s+replace\s+)?"
    r"(?:unlogged\s+|temporary\s+|temp\s+|unique\s+|materialized\s+)*"
    r"(?:table|index|view|trigger|function|sequence|extension|rule|type)\b"
    r"|\bselect\b[^;]*\binto\s+(?!temporary\b|temp\b)"
)


def _schema_statements(statements: list[str]) -> list[str]:
    """The DDL among ``statements`` — data repairs are not schema changes.

    Comments are stripped and `;`-separated statements split before matching,
    and the verb is searched for rather than anchored at position 0. Anchoring
    meant a single leading `-- keep retrieval fast` hid a
    `DROP INDEX` / `CREATE UNIQUE INDEX` pair from this test entirely; the
    vocabulary is wider than table DDL because an index, trigger or function
    dropped and recreated against a migration-owned table is the same
    drop-and-re-add mechanism MVR-05A1 (#4560) removed from `objects_pkey`.
    """
    schema: list[str] = []
    for statement in statements:
        for fragment in _SQL_COMMENT.sub(" ", statement).split(";"):
            normalized = " ".join(fragment.split())
            if normalized and _SCHEMA_VERB.search(normalized):
                schema.append(normalized)
    return schema


def test_every_autocreate_group_only_touches_the_table_it_probes() -> None:
    """A group's statements name the table its existence probe asked about.

    The probe is per table and the skip is per group, so a statement in group
    A that targets table B runs whenever A is absent — regardless of whether B
    already exists. Nothing in the loop's shape prevents that, and the
    behavioural harness cannot see it either: it would observe a skipped group
    and no statements. This is the pairing the two mechanisms both assume.
    """
    from app.stores.pg import _MIGRATION_OWNED_AUTOCREATE_SQL

    assert {table for table, _ in _MIGRATION_OWNED_AUTOCREATE_SQL} == set(AUTOCREATE_TABLES)
    for table, statements in _MIGRATION_OWNED_AUTOCREATE_SQL:
        for statement in statements:
            targets = set(
                re.findall(
                    r"(?i)\b(?:table|index|on)\s+(?:if\s+not\s+exists\s+)?" r"(?:public\.)?(\w+)",
                    statement,
                )
            ) & set(AUTOCREATE_TABLES)
            assert targets <= {table}, (
                f"the {table!r} autocreate group issues {statement.split()[0:4]} against "
                f"{sorted(targets - {table})}. A group runs when *its* table is absent, so a "
                "statement here reshapes a table nobody probed."
            )


def test_the_store_seam_never_reshapes_a_table_that_already_exists() -> None:
    """`app/stores/pg.py::_ensure_tables`, asked what it executes.

    Three cases, and the third is the one that matters:

    * with no `STORE_SCHEMA_AUTOCREATE` opt-in, production issues **no schema
      statement at all** — only the read-only assertions;
    * with the opt-in against an empty database, it creates the five store
      tables plus MVR-05A3's minimum child-FK fixture shape, and may `ALTER`
      only a table it has just created;
    * with the opt-in against a database that already holds them, it issues
      **zero** schema statements.

    That third assertion is the whole guard. Before MVR-05A2 the three
    `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS` statements ran on
    every boot of the fixture path, so a scratch database stamped at a
    pre-EMBEDREL-06 revision had its migration-owned table reshaped from the
    runtime — the same mechanism, one seam over, that silently reverted the
    `objects` primary key before #4560.

    Being behavioural is what makes it hold. It does not ask whether the DDL
    sits in a probed loop, whether the guard's condition looks right, or
    whether the enclosing function imports `sqlite3`; it runs the function and
    reads the statement list.
    """
    # Both database states, because with only the populated one a gate that
    # *defaults the opt-in on* — `os.getenv("STORE_SCHEMA_AUTOCREATE", "1") != "0"`,
    # autocreate enabled in production — still looks clean: the existence probe
    # skips every group, so nothing is issued. On an empty database it creates
    # the complete fixture group, which is the behavior that distinguishes it.
    for tables_present in (STORE_TABLES, frozenset()):
        production = _schema_statements(
            _statements_executed_by_ensure_tables(autocreate=False, tables_present=tables_present)
        )
        assert production == [], (
            f"_ensure_tables issued {production!r} without the STORE_SCHEMA_AUTOCREATE "
            f"test-fixture opt-in (tables_present={tables_present}). Outside tests the "
            "store schema is migration-owned (KERNEL-04, #2766) and this path is "
            "assert-only; a fixture flag that defaults to on is not a fixture flag."
        )

    fresh = _schema_statements(
        _statements_executed_by_ensure_tables(autocreate=True, tables_present=frozenset())
    )
    created = {
        match.group(1)
        for statement in fresh
        for match in [re.match(r"(?i)^CREATE TABLE IF NOT EXISTS (\w+)", statement)]
        if match
    }
    assert created == set(
        AUTOCREATE_TABLES
    ), f"the fixture path created {sorted(created)} on an empty database"

    existing = _schema_statements(
        _statements_executed_by_ensure_tables(autocreate=True, tables_present=AUTOCREATE_TABLES)
    )
    assert existing == [], (
        f"_ensure_tables issued {existing!r} against tables that already exist. The "
        "runtime may not reshape a migration-owned table: `CREATE TABLE IF NOT EXISTS` "
        "no-ops silently against an older shape while the ALTERs after it still run "
        "against that shape, which is how a fixture becomes a second schema owner. "
        "Idempotence has to come from the existence probe, not from `IF NOT EXISTS`."
    )


def test_no_durable_ddl_executes_outside_the_revision_chain() -> None:
    """`ensure_schema` issues no schema statements outside the test-fixture opt-in.

    Structural absence of the bootstrap file is only half of it. The behavioural
    half is what stops a drop-and-re-add pair returning through some other file:
    with no `STORE_SCHEMA_AUTOCREATE` opt-in the function must touch the
    connection zero times, and with the opt-in it may only issue `CREATE` —
    never an `ALTER` or `DROP` against a migration-owned table — and only for a
    table that does not already exist. Idempotence comes from the existence
    probe, not from `IF NOT EXISTS`, which no-ops silently on an older shape
    while the statements after it still run against it.
    """
    assert not BOOTSTRAP_SQL.exists(), (
        "app/db/migrations_obsidian.sql is back. It executed on the first "
        "conn_rw() of every process and silently reverted the objects primary "
        "key; Alembic revisions c7f4b1a83d29 and d1e8a0c5f37b own that schema "
        "(MVR-05A1, #4560)."
    )
    assert not LEGACY_SQL_RUNNER.exists(), (
        "scripts/run_migration.py is back. It was the second caller of the "
        "retired bootstrap SQL; scripts/run_migrations.sh (alembic upgrade head) "
        "is the single migration authority."
    )

    db_source = DB_MODULE.read_text(encoding="utf-8")
    assert (
        "_MIGRATION_SQL_PATH" not in db_source
    ), "app/db/db.py reads a bootstrap SQL file again (MVR-05A1, #4560)."
    executed_sql_file = re.search(r"(?im)^[^#\n]*\.sql\b", db_source)
    assert executed_sql_file is None, (
        f"app/db/db.py references a SQL file again ({executed_sql_file.group(0).strip()!r}); "
        "durable DDL belongs to the Alembic revision chain."
    )

    production_statements = _statements_executed_by_ensure_schema(autocreate=False)
    assert production_statements == [], (
        f"ensure_schema issued {production_statements!r} without the "
        "STORE_SCHEMA_AUTOCREATE test-fixture opt-in. In production it must "
        "issue nothing at all."
    )

    fixture_statements = _statements_executed_by_ensure_schema(autocreate=True)
    assert fixture_statements, "the STORE_SCHEMA_AUTOCREATE fixture path issued nothing"
    for statement in fixture_statements:
        normalized = " ".join(statement.split()).upper()
        if normalized.startswith("SELECT"):
            # The `to_regclass` existence probe that decides whether a table
            # group runs, and `assert_file_state_schema`'s read-only preflight.
            continue
        assert re.match(r"^CREATE (TABLE|UNIQUE INDEX|INDEX)\b", normalized), (
            f"the test-fixture autocreate path issued {statement!r}. Only plain "
            "`CREATE` is allowed there: an ALTER or DROP would make it a second "
            "owner able to reshape a migration-owned table, which is the defect "
            "MVR-05A1 (#4560) removed."
        )

    # And a table that already exists is left completely alone. Anything else
    # would reshape a migration-owned table from the runtime, which is the
    # mechanism this slice retired -- `CREATE TABLE IF NOT EXISTS` no-ops on an
    # older shape while the statements after it still run against it.
    existing = _statements_executed_by_ensure_schema(autocreate=True, tables_present=True)
    assert [
        statement for statement in existing if not statement.strip().upper().startswith("SELECT")
    ] == [], existing

    # ------------------------------------------------------------------ #
    # MVR-05A2 (#4576): the same property, derived rather than named
    # ------------------------------------------------------------------ #
    #
    # A structural backstop, not the primary proof. The two seams that carry
    # a recording-connection harness — `app/db/db.py` above and
    # `app/stores/pg.py` in
    # `test_the_store_seam_never_reshapes_a_table_that_already_exists` — are
    # proved behaviourally, by running them and reading the statement list.
    # This scan covers the seams that have no such harness (the twelve Heimdal
    # bootstrap modules, the entity-review journal, the four
    # knowledge-acquisition stores, the outbox), and the next seam nobody
    # names. Every one of those issues `CREATE` only, so the weaker
    # `existence_probed` half is not load-bearing for them; if one ever starts
    # issuing `ALTER` or `DROP`, give it the harness rather than trusting the
    # shape of its guard.
    #
    # Everything above is scoped to `app/db/db.py` because that is the seam
    # MVR-05A1 found. The seam inventory below is derived instead: every
    # durable DDL statement anywhere under `app/**` that targets a table the
    # Alembic revision chain creates, which today reaches `app/stores/pg.py`,
    # the twelve Heimdal bootstrap modules, the entity-review journal, the
    # four knowledge-acquisition stores and `app/services/outbox.py` without
    # any of them being listed here. A thirteenth Heimdal module, or a seam
    # nobody thought to name, is covered on the commit that adds it.
    tables = discover_durable_tables()
    seams = discover_runtime_ddl_seams(tables)
    assert seams, "the durable DDL seam scan found nothing, so it is proving nothing"

    # A table created under `app/**` that the revision chain does not own is a
    # second schema authority the classification gate cannot even see, because
    # its population comes from `app/alembic/versions/**`. Without this,
    # `cur.execute("CREATE TABLE rogue (...)")` in a production module leaves
    # both gates green. The four modules that legitimately create their own
    # tables are SQLite-backed local stores, which the scan reads off their
    # imports rather than off a path allowlist.
    unowned = [
        f"{seam.path}:{seam.lineno} CREATE TABLE {seam.table}"
        for seam in seams
        if seam.durable_database_source and not seam.owned_by_revision_chain
    ]
    assert unowned == [], (
        "these statements create a durable table the Alembic revision chain does not "
        "own, from a file that can reach the durable PostgreSQL database:\n  "
        + "\n  ".join(unowned)
        + "\nA table created this way has no migration, no classification, and no "
        "owner. Add the revision, or move the table to a store that is not the "
        "durable database."
    )

    ungated = [
        f"{seam.path}:{seam.lineno} {seam.verb.upper()} {seam.table} "
        f"(in {seam.function or '<module level>'})"
        for seam in seams
        if seam.durable_database_source
        and seam.owned_by_revision_chain
        and not seam.autocreate_gated
    ]
    assert ungated == [], (
        "these durable DDL statements run outside the STORE_SCHEMA_AUTOCREATE "
        "test-fixture opt-in, so production issues schema statements against a "
        "migration-owned table:\n  " + "\n  ".join(ungated)
    )

    # Statements already recorded as debt are excluded here and pinned by
    # `test_the_attached_object_ddl_debt_is_exactly_what_is_recorded` instead.
    # A *new* attached-object statement is in neither place and fails here.
    recorded = dict(RECORDED_ATTACHED_DDL_DEBT)
    unprobed: list[str] = []
    for seam in seams:
        if not (seam.durable_database_source and seam.owned_by_revision_chain):
            continue
        if seam.verb == "create table" or seam.existence_probed:
            continue
        key = (seam.path, seam.verb, seam.table)
        if seam.autocreate_gated and recorded.get(key, 0) > 0:
            recorded[key] -= 1
            continue
        unprobed.append(
            f"{seam.path}:{seam.lineno} {seam.verb.upper()} {seam.table} "
            f"(in {seam.function or '<module level>'})"
        )
    assert unprobed == [], (
        "these statements reshape a durable table from the runtime without first "
        "skipping the group when the table already exists:\n  "
        + "\n  ".join(unprobed)
        + "\nIf this is a *new* seam, give it the probe. If it belongs to the debt "
        "https://github.com/RasmusTho/agentic-pkm-mvp/issues/4598 owns, that Issue is "
        "where it retires — do not widen RECORDED_ATTACHED_DDL_DEBT to make this pass. "
        "Idempotence must come from the `to_regclass` probe `app/db/db.py` uses, "
        "not from `IF NOT EXISTS`: `CREATE TABLE IF NOT EXISTS` no-ops silently "
        "against an older shape while the ALTERs after it still run against it. "
        "This is the defect MVR-05A2 (#4576) closed in `app/stores/pg.py`, whose "
        "three `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS` statements "
        "previously ran unconditionally in the autocreate branch."
    )


# --------------------------------------------------------------------------- #
# Every adopted surface has exactly one production DDL owner
# --------------------------------------------------------------------------- #


def test_the_attached_object_ddl_debt_is_exactly_what_is_recorded() -> None:
    """The recorded attached-object DDL debt is a measurement, not a waiver.

    MVR-05A2 widened this scan's vocabulary past table-level DDL, because an
    index or trigger dropped and recreated against a migration-owned table is
    the same drop-and-re-add mechanism MVR-05A1 (#4560) removed from
    `objects_pkey`. Forty-one such statements across thirteen modules already
    run without an existence probe, including five
    `DROP TRIGGER` / `CREATE TRIGGER` pairs —
    `app/heimdal/raw_read_gate.py`'s own docstring records that migration
    `f1c7e2a9b4d6` installs an identical trigger, so a migration owns the object
    and the runtime recreates it.

    MVR-05A2's AC-5 asks for the existence probe in exactly one place
    (`app/stores/pg.py`, delivered), so repairing the rest belongs to
    https://github.com/RasmusTho/agentic-pkm-mvp/issues/4598, which owns both
    the repair and shrinking this mapping as statements retire. Pinning the
    count is what keeps it evidence: a statement that goes away must come off
    the pin, and a statement that appears is in neither the pin nor the
    exclusion and fails the guard above.

    **This mapping is not a clean bill of health.** Reading it as one is the
    mistake it exists to prevent.
    """
    observed = observed_attached_ddl_debt(discover_runtime_ddl_seams(discover_durable_tables()))
    assert dict(observed) == dict(RECORDED_ATTACHED_DDL_DEBT), (
        "the recorded attached-object DDL debt no longer matches the tree.\n"
        f"  gone:  {sorted(set(RECORDED_ATTACHED_DDL_DEBT) - set(observed))}\n"
        f"  new:   {sorted(set(observed) - set(RECORDED_ATTACHED_DDL_DEBT))}\n"
        f"  moved: {sorted(k for k in set(observed) & set(RECORDED_ATTACHED_DDL_DEBT) if observed[k] != RECORDED_ATTACHED_DDL_DEBT[k])}\n"
        "If a statement retired, lower its count here — that is #4598 making progress. "
        "If one appeared, it needs the existence probe, not a bigger pin."
    )


def test_durable_ddl_owners_are_exactly_the_governed_revision_set() -> None:
    """Adopted tables name every intentional revision that may reshape them.

    Both spellings the repo actually uses are matched: raw SQL through
    `op.execute`, and the Alembic operation API (`op.create_table` etc, which
    `fe9a3607841f_bootstrap.py` already uses). Matching only raw SQL would let a
    second owner written in the repo's other native style walk straight past.
    """
    file_state_owners = _table_ddl_owners("file_state")
    assert (
        len(file_state_owners) == 1
    ), f"expected exactly one Alembic revision to own file_state DDL, got {file_state_owners}"
    assert file_state_owners[0].startswith(FILE_STATE_OWNING_REVISION), file_state_owners

    agent_memories_owners = _table_ddl_owners("agent_memories")
    assert agent_memories_owners == [
        "d1e8a0c5f37b_mvr05a1_objects_agent_memories_adoption.py",
        "f8a05a9b0001_mvr05a_residual_binding_keys.py",
    ]

    # `objects.path` keeps its single MVR-05A0 owner: the MVR-05A1 revision
    # deliberately does not re-declare the column with an `ALTER`.
    objects_path_raw_ddl = re.compile(
        r"(?is)alter\s+table[^\"']*\bobjects\b[^\"']*add\s+column\s+(?:if\s+not\s+exists\s+)?path\b"
    )
    objects_path_op_ddl = re.compile(
        r"""(?is)\bop\.add_column\s*\(\s*["'](?:public\.)?objects["']\s*,[^)]*["']path["']"""
    )
    objects_path_owners = sorted(
        name
        for name, text in _revision_sources().items()
        if objects_path_raw_ddl.search(text) or objects_path_op_ddl.search(text)
    )
    assert (
        len(objects_path_owners) == 1
    ), f"expected exactly one Alembic revision to own objects.path, got {objects_path_owners}"
    assert objects_path_owners[0].startswith(FILE_STATE_OWNING_REVISION), objects_path_owners


def test_the_objects_key_shape_has_exactly_one_owner() -> None:
    """Only `d1e8a0c5f37b` writes the `objects` primary key.

    `objects` is created by two historical roots (`fe9a3607841f` and
    `202510241200`), which is tolerated lineage — `CREATE TABLE IF NOT EXISTS`
    cannot reshape a table that already exists. What must never happen again is
    a *second* mechanism rewriting the key: that is what silently reverted the
    binding rekey on every process boot.
    """
    pkey_writers = sorted(
        name
        for name, text in _revision_sources().items()
        if re.search(r"(?is)\bobjects_pkey\b", text)
        or re.search(
            r"""(?is)\bop\.(?:create_primary_key|drop_constraint)\s*\([^)]*["']objects""", text
        )
    )
    assert pkey_writers == [_owning_revision_filename(OBJECTS_OWNING_REVISION)], pkey_writers

    uuid_index_writers = sorted(
        name
        for name, text in _revision_sources().items()
        if re.search(r"(?is)\bobjects_uuid_idx\b", text)
    )
    assert uuid_index_writers == sorted(
        {
            # Historical root; creates it non-unique on `(uuid)`, which is why
            # the bootstrap's `CREATE UNIQUE INDEX IF NOT EXISTS` silently
            # no-opped on every Alembic-created database.
            "fe9a3607841f_bootstrap.py",
            _owning_revision_filename(OBJECTS_OWNING_REVISION),
        }
    ), uuid_index_writers

    # And no non-Alembic SQL file in the tree declares uniqueness on
    # `objects.uuid`. `app/db/sql/objects_uuid_unrestrict.sql` did exactly that
    # — a global `create unique index ... on public.objects(uuid)` — with no
    # caller anywhere, and would have reinstated the constraint MVR-05A1 removed
    # if anyone had ever run it.
    stray = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "app").rglob("*.sql")
        if re.search(
            r"(?is)create\s+unique\s+index[^;]*\b(?:public\.)?objects\s*\(\s*uuid\s*\)",
            path.read_text(encoding="utf-8"),
        )
    )
    assert stray == [], (
        f"{stray} declare a globally unique index on objects.uuid outside the "
        "revision chain; MVR-05A's AC-1 needs uniqueness scoped to the binding."
    )


def test_adopted_tables_are_reachable_from_the_alembic_revision_chain() -> None:
    """The stop condition that blocked MVR-05A cannot silently return.

    Before #4543, `git grep -l file_state app/alembic/versions/` was empty; the
    same was true of `agent_memories` before #4560. No migration test and no
    `alembic upgrade head` PG lane could observe either table. Assert positively
    that a revision now issues real DDL against each — a prose mention in a
    docstring would not make a table reachable, so a substring check would not
    prove the stop condition is gone.
    """
    sources = _revision_sources()
    for table in ("file_state", "agent_memories", "objects"):
        creating = sorted(
            name
            for name, text in sources.items()
            if re.search(rf"(?is)create\s+table\s+if\s+not\s+exists\s+(?:public\.)?{table}\b", text)
        )
        assert creating, (
            f"no Alembic revision creates {table}; MVR-05A's AC-1 becomes "
            "unprovable again (see #3859's stop reports)."
        )

    # And the owning revisions are genuinely on the chain the PG lane upgrades
    # to, not orphaned files: each must be an ancestor of the single head.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single Alembic head, got {heads}"
    ancestry = {revision.revision for revision in script.iterate_revisions(heads[0], "base")}
    for owning in (FILE_STATE_OWNING_REVISION, OBJECTS_OWNING_REVISION):
        assert owning in ancestry, (
            f"{owning} is not an ancestor of head {heads[0]}; `alembic upgrade "
            "head` would never reach the tables it owns."
        )


# --------------------------------------------------------------------------- #
# The PG proofs must actually run in a CI lane
# --------------------------------------------------------------------------- #

# The two lanes that actually execute `-m "pg"`. Both select files by explicit
# allow-list, and every other lane runs `-m "not pg"`, so a pg-marked test that
# is in neither runs in no CI lane at all.
#
# `integration-nightly / pg-contracts` triggers on `schedule` + `workflow_dispatch`
# only. `ci-smoke / index_pg` is the PR-path lane — the same precedent EROJ-01
# (#4350) set for its own pg-marked mechanism proofs.
PG_LANES = (
    (
        REPO_ROOT / ".github" / "workflows" / "integration-nightly.yaml",
        "Bounded PG verification lane",
    ),
    (
        REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml",
        "durable table ownership PG surface",
    ),
)
DURABLE_OWNERSHIP_PG_TARGETS = (
    "tests/migrations/test_file_state_adoption.py",
    "tests/migrations/test_objects_adoption.py",
    # Both were pg-marked and in no lane at all before #4560, and both guard the
    # same `objects` table this slice rekeys.
    "tests/migrations/test_legacy_objects_fk_migration.py",
    "tests/migrations/test_outbox_schema_parity.py",
    # MVR-05A7 (#4581): forward-only outbox classification plus runtime
    # dual-key compatibility dedup both require real PostgreSQL.
    "tests/migrations/test_multi_vault_outbox_upgrade.py",
    "tests/services/test_multi_vault_outbox_dual_key_dedup.py",
    # Exercises `outbox.bootstrap()`, which calls the `ensure_schema` seam this
    # slice rewrote; it was also pg-marked and in no lane.
    "tests/services/test_outbox_bootstrap_assert_only.py",
    "tests/instance/test_file_state_binding_key.py",
    "tests/services/test_vault_sync_binding_scope.py",
    "tests/integration/test_single_vault_compatibility.py",
    # MVR-05A3 (#4577): composite parent/children, projection isolation,
    # reset scope, and audited fixture parity are one PostgreSQL mechanism.
    "tests/migrations/test_store_schema_parity.py",
    "tests/migrations/test_multi_vault_ingest_projection_keys.py",
    "tests/migrations/test_ingest_schema_parity.py",
    "tests/migrations/test_multi_vault_replay_projection_backfill.py",
    "tests/migrations/test_replay_schema_parity.py",
    "tests/migrations/test_decisions_fk_set_null.py",
    "tests/integration/test_decisions_rebuild_from_log_only.py",
    "tests/integration/test_multi_vault_projection_isolation.py",
    "tests/episodes/test_episode_projection.py",
    "tests/integration/test_vault_sync_atomicity.py",
    "tests/ingest/test_vault_root_ingest_pg.py",
    "tests/invariants/test_retrieval_spine_invariants.py",
    "tests/jobs/test_decisions_export.py",
    "tests/jobs/test_decisions_projection_rebuild.py",
    "tests/jobs/test_multi_vault_decisions_rebuild_scope.py",
    "tests/cli/test_index_doctor_mixed.py",
    "tests/cli/test_index_rebuild_cli.py",
    "tests/cli/test_index_reconcile.py",
    "tests/index/test_identity_migration.py",
    "tests/index/test_provenance_stamp.py",
    "tests/indexer/test_mixed_identity_detection.py",
    "tests/stores/test_decisions_fk_semantics.py",
    "tests/stores/test_ensure_tables_assert_only.py",
    "tests/stores/test_multi_vault_store_reset_scope.py",
    "tests/stores/test_pg_truncate_reset.py",
    "tests/stores/test_pg_vector_index.py",
    "tests/stores/test_store_contract_pg.py",
    "tests/stores/test_vector_generation_identity.py",
    "tests/services/test_audit_writer.py",
)


def _pytest_invocation_after(workflow: str, step_name_fragment: str) -> str:
    """The `pytest ...` command of the step whose name contains the fragment.

    Scoped deliberately: a plain substring search over the whole workflow would
    pass if a path were moved into a YAML comment or into an unrelated job.
    """
    marker = workflow.index(step_name_fragment)
    start = workflow.index("pytest", marker)
    end = workflow.index("\n\n", start)
    return workflow[start:end]


def test_durable_ownership_pg_targets_run_in_both_pg_lanes() -> None:
    """The adoption and rekey guards must actually execute in CI, not just exist.

    Most of #4543's and #4560's machine-checkable acceptance criteria are
    `pg`-marked. If these paths are not inside a pg lane's own pytest
    invocation, a forward-only migration on a live table is proven once, by
    hand, and then never again — and the CI-coverage sentence in
    `docs/DB_SCHEMA.md` becomes false-green evidence. PR #4550 shipped with five
    of six ACs initially running in no lane at all while its body claimed PG
    coverage.
    """
    for workflow_path, step_fragment in PG_LANES:
        workflow = workflow_path.read_text(encoding="utf-8")
        invocation = _pytest_invocation_after(workflow, step_fragment)
        missing = [target for target in DURABLE_OWNERSHIP_PG_TARGETS if target not in invocation]
        assert missing == [], (
            f"{missing} are pg-marked but absent from the {step_fragment!r} pytest "
            f"invocation in {workflow_path.name}; they would not run in that lane."
        )

    for target in DURABLE_OWNERSHIP_PG_TARGETS:
        assert (REPO_ROOT / target).exists(), f"{target} is listed in CI but does not exist"


def test_the_pr_path_pg_lane_is_triggered_by_the_sources_it_guards() -> None:
    """The PR-path lane is paths-filtered, so its filter must name what it guards.

    Listing the tests in the run step is not enough: `ci-smoke / index_pg` only
    executes when its paths filter matches, so a change to a migration or to
    `vault_sync.py` that never touches a listed test file would skip the lane
    entirely and merge unverified.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml").read_text(encoding="utf-8")
    guarded_sources = (
        f"app/alembic/versions/{_owning_revision_filename(FILE_STATE_OWNING_REVISION)}",
        f"app/alembic/versions/{_owning_revision_filename(OBJECTS_OWNING_REVISION)}",
        "app/db/db.py",
        "app/memory_kv/store.py",
        "app/services/vault_sync.py",
        "app/services/outbox.py",
        "app/workers/outbox_worker.py",
        "app/alembic/versions/f6a05a7b0001_mvr05a7_outbox_binding_dual_key.py",
        "app/alembic/versions/e6c4a2b8d1f3_mvr05a3_store_object_binding_keys.py",
        "app/alembic/versions/f5a05a5b0001_mvr05a5_replay_projection_binding_keys.py",
        "app/db/replay_projection_schema.py",
        "app/stores/pg.py",
        "app/stores/__init__.py",
        "app/stores/base.py",
        "app/objects/__init__.py",
        "app/objects/identity.py",
        "app/db/decisions_schema.py",
        "app/episodes/assignment.py",
        "app/ingest/vault_alpha.py",
        "app/agents/projector/agent.py",
        "app/jobs/backfill.py",
        "app/jobs/decisions_export.py",
        "app/jobs/decisions_projection.py",
        "app/jobs/episodes_projection.py",
        "app/standing_questions/projection.py",
        "app/episodes/engine_state.py",
        "app/episodes/closure.py",
        "app/episodes/closure_decay.py",
        "app/episodes/recut.py",
        "app/episodes/segmenter.py",
        "app/receipts/outcome_receipt_log.py",
        "app/receipts/outcome_receipt_projection.py",
        "app/observability/status_service.py",
        "app/instance/binding_ids.py",
        "app/knowledge_acquisition/extraction_persistence.py",
        "app/knowledge_acquisition/raw_record.py",
        "app/services/audit.py",
        "app/services/decisions.py",
        "app/store/membership_store.py",
        "app/objects/relation_types.py",
        "app/stores/postgres.py",
        "tests/architecture/durable_table_classification.py",
        "tests/architecture/test_durable_table_ownership.py",
        "tests/architecture/test_multi_vault_projection_inventory.py",
        "tests/architecture/durable_table_classification.json",
    )
    missing = [
        source
        for source in guarded_sources + DURABLE_OWNERSHIP_PG_TARGETS
        if f"'{source}'" not in workflow
    ]
    assert missing == [], (
        f"{missing} are not in the ci-smoke index_pg paths filter, so editing them "
        "would skip the PR-path pg lane."
    )
    for source in guarded_sources:
        assert (REPO_ROOT / source).exists(), f"{source} is in the paths filter but missing"
