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
    discover_durable_tables,
    discover_runtime_ddl_seams,
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
    assert "_MIGRATION_SQL_PATH" not in db_source, (
        "app/db/db.py reads a bootstrap SQL file again (MVR-05A1, #4560)."
    )
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

    ungated = [
        f"{seam.path}:{seam.lineno} {seam.verb.upper()} {seam.table} "
        f"(in {seam.function or '<module level>'})"
        for seam in seams
        if not seam.autocreate_gated
    ]
    assert ungated == [], (
        "these durable DDL statements run outside the STORE_SCHEMA_AUTOCREATE "
        "test-fixture opt-in, so production issues schema statements against a "
        "migration-owned table:\n  " + "\n  ".join(ungated)
    )

    unprobed = [
        f"{seam.path}:{seam.lineno} {seam.verb.upper()} {seam.table} "
        f"(in {seam.function or '<module level>'})"
        for seam in seams
        if seam.verb != "create table" and not seam.existence_probed
    ]
    assert unprobed == [], (
        "these statements reshape a durable table from the runtime without first "
        "skipping the group when the table already exists:\n  "
        + "\n  ".join(unprobed)
        + "\nIdempotence must come from the `to_regclass` probe `app/db/db.py` uses, "
        "not from `IF NOT EXISTS`: `CREATE TABLE IF NOT EXISTS` no-ops silently "
        "against an older shape while the ALTERs after it still run against it. "
        "This is the defect MVR-05A2 (#4576) closed in `app/stores/pg.py`, whose "
        "three `ALTER TABLE store_vector_index ADD COLUMN IF NOT EXISTS` statements "
        "previously ran unconditionally in the autocreate branch."
    )


# --------------------------------------------------------------------------- #
# Every adopted surface has exactly one production DDL owner
# --------------------------------------------------------------------------- #


def test_no_durable_ddl_has_two_owners() -> None:
    """`file_state`, `agent_memories` and `objects.path` each have one owner.

    Both spellings the repo actually uses are matched: raw SQL through
    `op.execute`, and the Alembic operation API (`op.create_table` etc, which
    `fe9a3607841f_bootstrap.py` already uses). Matching only raw SQL would let a
    second owner written in the repo's other native style walk straight past.
    """
    file_state_owners = _table_ddl_owners("file_state")
    assert len(file_state_owners) == 1, (
        f"expected exactly one Alembic revision to own file_state DDL, got {file_state_owners}"
    )
    assert file_state_owners[0].startswith(FILE_STATE_OWNING_REVISION), file_state_owners

    agent_memories_owners = _table_ddl_owners("agent_memories")
    assert len(agent_memories_owners) == 1, (
        "expected exactly one Alembic revision to own agent_memories DDL, got "
        f"{agent_memories_owners}"
    )
    assert agent_memories_owners[0].startswith(OBJECTS_OWNING_REVISION), agent_memories_owners

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
    assert len(objects_path_owners) == 1, (
        f"expected exactly one Alembic revision to own objects.path, got {objects_path_owners}"
    )
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
        name for name, text in _revision_sources().items()
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
            if re.search(
                rf"(?is)create\s+table\s+if\s+not\s+exists\s+(?:public\.)?{table}\b", text
            )
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
    # Exercises `outbox.bootstrap()`, which calls the `ensure_schema` seam this
    # slice rewrote; it was also pg-marked and in no lane.
    "tests/services/test_outbox_bootstrap_assert_only.py",
    "tests/instance/test_file_state_binding_key.py",
    "tests/services/test_vault_sync_binding_scope.py",
    "tests/integration/test_single_vault_compatibility.py",
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
        missing = [
            target for target in DURABLE_OWNERSHIP_PG_TARGETS if target not in invocation
        ]
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
