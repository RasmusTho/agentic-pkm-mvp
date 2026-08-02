"""MVR-05A0 (#4543): durable vault-sync DDL has exactly one owning mechanism.

`file_state` and `objects.path` were declared by the legacy runtime bootstrap
SQL (`app/db/migrations_obsidian.sql`, applied by `app/db/db.py::ensure_schema`)
rather than by the Alembic revision chain. For `file_state` that meant no
revision could see the table at all, so MVR-05A's PG verification lane — which
runs `alembic upgrade head` — could never reach the table its own AC-1 governs.
For `objects.path` it meant the column was declared in three places in that SQL
file while `objects` itself is created by Alembic revision `202510241200`.

This guard is the durable half of the fix: it fails if either surface regains a
second production DDL owner. It is deliberately scoped to the two surfaces this
slice took ownership of. The wider `objects` table still has split ownership
(the bootstrap SQL creates it and mutates its primary key while Alembic also
creates it), which belongs to MVR-05A's projection cutover, not here — see the
residual-risk note on #4543.

The test-fixture create-on-demand path in `app/db/db.py`
(`STORE_SCHEMA_AUTOCREATE=1`) is not a second owner: it mirrors the established
KERNEL-04 (#2766) / KERNEL-05 (#2850) contract for `store_*` and `outbox`, is
inert outside tests, and its shape parity with the revision is asserted by
`tests/migrations/test_file_state_adoption.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP_SQL = REPO_ROOT / "app" / "db" / "migrations_obsidian.sql"
ALEMBIC_VERSIONS = REPO_ROOT / "app" / "alembic" / "versions"

# The revision that took ownership of both surfaces (MVR-05A0, #4543).
FILE_STATE_OWNING_REVISION = "c7f4b1a83d29"


def _sql_without_comments(text: str) -> str:
    """Strip `--` line comments so prose about the DDL is not read as DDL."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _revision_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(ALEMBIC_VERSIONS.glob("*.py"))
    }


def test_no_durable_ddl_has_two_owners() -> None:
    """`file_state` and `objects.path` each have exactly one production owner."""

    bootstrap_sql = _sql_without_comments(BOOTSTRAP_SQL.read_text(encoding="utf-8"))

    # 1. The legacy bootstrap SQL declares neither surface any more.
    assert "file_state" not in bootstrap_sql.lower(), (
        "app/db/migrations_obsidian.sql declares file_state DDL again; Alembic "
        f"revision {FILE_STATE_OWNING_REVISION} is its sole production owner "
        "(MVR-05A0, #4543)."
    )

    objects_path_ddl = re.findall(
        r"(?is)\b(?:alter\s+table[^;]*\bobjects\b[^;]*\bpath\b[^;]*"
        r"|create\s+table[^;]*\b(?:public\.)?objects\b\s*\([^;]*?^\s*path\s+text)",
        bootstrap_sql,
        flags=re.MULTILINE,
    )
    assert objects_path_ddl == [], (
        "app/db/migrations_obsidian.sql declares objects.path DDL again "
        f"({objects_path_ddl!r}); Alembic revision {FILE_STATE_OWNING_REVISION} "
        "is its sole owner (MVR-05A0, #4543)."
    )

    sources = _revision_sources()

    # 2. Exactly one Alembic revision issues DDL against file_state. Both
    #    spellings the repo actually uses are matched: raw SQL through
    #    `op.execute`, and the Alembic operation API (`op.create_table` etc,
    #    which `fe9a3607841f_bootstrap.py` already uses). Matching only raw SQL
    #    would let a second owner written in the repo's other native style walk
    #    straight past this guard.
    file_state_raw_ddl = re.compile(
        r"(?is)\b(?:create\s+table|alter\s+table|drop\s+table|create(?:\s+unique)?\s+index)\b"
        r"[^\"';]*\b(?:public\.)?file_state\b"
    )
    # `op.create_table`/`add_column`/... take the table first, while
    # `op.create_index`/`drop_constraint`/... take the *name* first, so the table
    # name is matched anywhere in the call's arguments rather than only in first
    # position — otherwise half these alternatives could never fire.
    file_state_op_ddl = re.compile(
        r"""(?is)\bop\.(?:create_table|add_column|drop_column|alter_column|drop_table"""
        r"""|create_index|drop_index|rename_table|create_primary_key|drop_constraint)\s*\("""
        r"""[^)]*["'](?:public\.)?file_state["']"""
    )
    file_state_owners = sorted(
        name
        for name, text in sources.items()
        if file_state_raw_ddl.search(text) or file_state_op_ddl.search(text)
    )
    assert len(file_state_owners) == 1, (
        f"expected exactly one Alembic revision to own file_state DDL, got {file_state_owners}"
    )
    assert file_state_owners[0].startswith(FILE_STATE_OWNING_REVISION), file_state_owners

    # 3. Exactly one Alembic revision owns objects.path, in either spelling.
    #    `IF NOT EXISTS` is deliberately optional here — a second owner would be
    #    just as real without it.
    objects_path_raw_ddl = re.compile(
        r"(?is)alter\s+table[^\"']*\bobjects\b[^\"']*add\s+column\s+(?:if\s+not\s+exists\s+)?path\b"
    )
    objects_path_op_ddl = re.compile(
        r"""(?is)\bop\.add_column\s*\(\s*["'](?:public\.)?objects["']\s*,[^)]*["']path["']"""
    )
    objects_path_owners = sorted(
        name
        for name, text in sources.items()
        if objects_path_raw_ddl.search(text) or objects_path_op_ddl.search(text)
    )
    assert len(objects_path_owners) == 1, (
        f"expected exactly one Alembic revision to own objects.path, got {objects_path_owners}"
    )
    assert objects_path_owners[0].startswith(FILE_STATE_OWNING_REVISION), objects_path_owners


def test_file_state_is_reachable_from_the_alembic_revision_chain() -> None:
    """The stop condition that blocked MVR-05A cannot silently return.

    Before #4543, `git grep -l file_state app/alembic/versions/` was empty across
    all 35 revisions: no migration test and no `alembic upgrade head` PG lane
    could observe the table. Assert positively that a revision now issues real
    DDL against it — a prose mention in a docstring would not make the table
    reachable, so a substring check would not prove the stop condition is gone.
    """
    creating = sorted(
        name
        for name, text in _revision_sources().items()
        if re.search(
            r"(?is)create\s+table\s+if\s+not\s+exists\s+(?:public\.)?file_state", text
        )
    )
    assert creating, (
        "no Alembic revision creates file_state; MVR-05A's AC-1 becomes "
        "unprovable again (see #3859's stop report)."
    )

    # And the revision is genuinely on the chain the PG lane upgrades to, not an
    # orphaned file: it must be an ancestor of the single head.
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single Alembic head, got {heads}"
    ancestry = {
        revision.revision
        for revision in script.iterate_revisions(heads[0], "base")
    }
    assert FILE_STATE_OWNING_REVISION in ancestry, (
        f"{FILE_STATE_OWNING_REVISION} is not an ancestor of head {heads[0]}; "
        "`alembic upgrade head` would never reach file_state."
    )


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
        "file_state PG surface",
    ),
)
FILE_STATE_PG_TARGETS = (
    "tests/migrations/test_file_state_adoption.py",
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


def test_file_state_pg_targets_run_in_both_pg_lanes() -> None:
    """The adoption and rekey guards must actually execute in CI, not just exist.

    Five of #4543's six machine-checkable acceptance criteria are `pg`-marked.
    If these paths are not inside a pg lane's own pytest invocation, a
    forward-only migration on a live table is proven once, by hand, and then
    never again — and the CI-coverage sentence in `docs/DB_SCHEMA.md` becomes
    false-green evidence.
    """
    for workflow_path, step_fragment in PG_LANES:
        workflow = workflow_path.read_text(encoding="utf-8")
        invocation = _pytest_invocation_after(workflow, step_fragment)
        missing = [target for target in FILE_STATE_PG_TARGETS if target not in invocation]
        assert missing == [], (
            f"{missing} are pg-marked but absent from the {step_fragment!r} pytest "
            f"invocation in {workflow_path.name}; they would not run in that lane."
        )

    for target in FILE_STATE_PG_TARGETS:
        assert (REPO_ROOT / target).exists(), f"{target} is listed in CI but does not exist"


def test_the_pr_path_pg_lane_is_triggered_by_the_sources_it_guards() -> None:
    """The PR-path lane is paths-filtered, so its filter must name what it guards.

    Listing the tests in the run step is not enough: `ci-smoke / index_pg` only
    executes when its paths filter matches, so a change to the migration or to
    `vault_sync.py` that never touches a listed test file would skip the lane
    entirely and merge unverified.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml").read_text(encoding="utf-8")
    guarded_sources = (
        "app/alembic/versions/c7f4b1a83d29_mvr05a0_file_state_binding_key.py",
        "app/db/db.py",
        "app/db/migrations_obsidian.sql",
        "app/services/vault_sync.py",
    )
    missing = [source for source in guarded_sources + FILE_STATE_PG_TARGETS
               if f"'{source}'" not in workflow]
    assert missing == [], (
        f"{missing} are not in the ci-smoke index_pg paths filter, so editing them "
        "would skip the PR-path pg lane."
    )
