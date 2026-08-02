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

    # 2. Exactly one Alembic revision issues DDL against file_state. Matching any
    #    DDL verb — not just the exact `CREATE TABLE IF NOT EXISTS` spelling —
    #    is what stops a second revision from quietly co-owning the table with a
    #    bare `CREATE TABLE` or an `ALTER TABLE ... ADD COLUMN`.
    file_state_ddl = re.compile(
        r"(?is)\b(?:create\s+table|alter\s+table|drop\s+table|create(?:\s+unique)?\s+index)\b"
        r"[^\"';]*\b(?:public\.)?file_state\b"
    )
    file_state_owners = sorted(
        name for name, text in sources.items() if file_state_ddl.search(text)
    )
    assert len(file_state_owners) == 1, (
        f"expected exactly one Alembic revision to own file_state DDL, got {file_state_owners}"
    )
    assert file_state_owners[0].startswith(FILE_STATE_OWNING_REVISION), file_state_owners

    # 3. Exactly one Alembic revision owns objects.path.
    objects_path_owners = sorted(
        name
        for name, text in sources.items()
        if re.search(
            r"(?is)alter\s+table[^\"']*\bobjects\b[^\"']*add\s+column\s+if\s+not\s+exists\s+path",
            text,
        )
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
