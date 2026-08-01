"""Producer parity for the standing media-capture consent grant (#4492).

The grant is a **runtime precondition**: without it every governed media
admission refuses with the named 409 `consent_refused`. `AGENTS.md ::
Required rules` (invariant -> producers) therefore requires every producer of it
to ship in the same change, and this test is what keeps them from drifting
afterwards. The producers are:

1. `app/alembic/versions/a9f3c2d7b6e1_heim_media_capture_consent_grant.py` --
   the Postgres production seed;
2. `app/heimdal/consent_ledger.py :: _media_capture_seed_row` -- the in-process
   memory-backend seed (`_MemoryConsentLedger._seed`, and therefore
   `reset_memory_consent_ledger`);
3. the `STORE_SCHEMA_AUTOCREATE` branch of `consent_ledger._bootstrap_pg` --
   the Postgres test-fixture seed, which builds its row from the same tuple as
   (2).

The migration is asserted by **running its real `upgrade()`** against a
capturing `op` and reading the SQL it emits, so this needs no Postgres and
therefore runs in the required `Unit tests (not pg)` job, which is where drift
has to be caught. Checking only that the migration's module constants match the
ledger's is not sufficient: the constants can be right while the
`INSERT ... SELECT` binds them to the wrong columns or hardcodes a literal over
one, and on an append-only, forward-only table the resulting row can never be
removed. Schema parity for the underlying table is owned by `c4f7a1b2d9e3` and
is not re-asserted here -- this migration is data-only.

Not covered here: applying the migration to a real database. Nothing in
`integration-nightly.yaml`'s bounded pg lane exercises the consent ledger
either, so the emitted-SQL assertions below are the only automated guard on
this seed.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app.heimdal import consent_ledger
from app.heimdal.consent_ledger import (
    MEDIA_CAPTURE_BASIS,
    MEDIA_CAPTURE_GRANT_REF,
    MEDIA_CAPTURE_MODALITIES,
    MEDIA_CAPTURE_SCOPE,
    SELF_RECORD_GRANT_REF,
    _media_capture_seed_row,
    _STANDING_SEED_ROW_BUILDERS,
    list_active_grants,
    reset_memory_consent_ledger,
)

pytestmark = pytest.mark.not_pg

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = (
    REPO_ROOT
    / "app"
    / "alembic"
    / "versions"
    / "a9f3c2d7b6e1_heim_media_capture_consent_grant.py"
)


def _migration_module_constants() -> dict[str, object]:
    """Read the migration's module-level literals without importing alembic."""
    tree = ast.parse(MIGRATION_PATH.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            only = node.targets[0]
            if isinstance(only, ast.Name):
                target, value = only.id, node.value
        if target is None or value is None:
            continue
        try:
            values[target] = ast.literal_eval(value)
        except ValueError:
            continue
    return values


class _CapturingOp:
    """Stands in for `alembic.op` so `upgrade()` can be run without a database."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, sql: object) -> None:
        self.statements.append(str(sql))


def _rendered_upgrade_sql() -> str:
    """The SQL the migration's real `upgrade()` emits.

    Runs the actual function with a capturing `op`, rather than reasoning about
    the source. Comparing the migration's module *constants* to the ledger's
    constants is not enough: the constants can be correct while the
    `INSERT … SELECT` binds them to the wrong columns, hardcodes a literal in
    place of one, or misspells a value — none of which a constants-only
    comparison can see.
    """
    spec = importlib.util.spec_from_file_location(
        "heimdal_media_capture_migration_under_test", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    capturing = _CapturingOp()
    module.op = capturing  # type: ignore[attr-defined]
    module.upgrade()
    assert len(capturing.statements) == 1, (
        f"expected exactly one statement from upgrade(), got {len(capturing.statements)}"
    )
    return capturing.statements[0]


def _split_sql_list(text: str) -> list[str]:
    """Split a SQL comma list at depth 0, respecting parens and quoted literals.

    The seed's JSON literals contain commas, so a naive `str.split(",")`
    mis-aligns every column after `capture_profile`.
    """
    items: list[str] = []
    depth = 0
    in_quote = False
    current: list[str] = []
    for char in text:
        if char == "'":
            in_quote = not in_quote
        elif not in_quote and char == "(":
            depth += 1
        elif not in_quote and char == ")":
            depth -= 1
        elif char == "," and depth == 0 and not in_quote:
            items.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _seeded_columns() -> dict[str, str]:
    """Map each INSERTed column name to the value expression bound to it."""
    sql = _rendered_upgrade_sql()
    match = re.search(
        r"INSERT INTO heimdal_consent_grant\s*\((?P<cols>[^)]*)\)\s*"
        r"SELECT\s*(?P<vals>.*?)\s*WHERE NOT EXISTS",
        sql,
        re.S,
    )
    assert match is not None, "could not parse the seed INSERT ... SELECT"
    columns = [c.strip() for c in match.group("cols").split(",") if c.strip()]
    values = _split_sql_list(match.group("vals"))
    assert len(columns) == len(values), (
        f"column/value arity mismatch: {len(columns)} columns vs {len(values)} values"
    )
    return dict(zip(columns, values))


class _RecordingCursor:
    """Minimal DB-API cursor stand-in that records what was executed.

    `fetchone()` returns None so every standing-grant existence probe reports
    "not seeded yet" and the bootstrap takes its INSERT branch for each one —
    which is the branch under test.
    """

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple | None = None) -> None:
        self.executed.append((sql, params or ()))

    def fetchone(self) -> None:
        return None

    def seeded_identities(self) -> set[tuple[str, str, str]]:
        """`(grant_ref, basis, scope)` of every row this bootstrap INSERTed.

        Positions 1/2/3 of the bound parameters, matching the column order in
        `consent_ledger._bootstrap_pg`'s INSERT. All three, not `grant_ref`
        alone: a producer that emitted the right ref under the wrong scope
        would seed a grant no admission can resolve.
        """
        return {
            (params[1], params[2], params[3])
            for sql, params in self.executed
            if "INSERT INTO" in sql and len(params) > 3
        }


class _RecordingConn:
    def __init__(self) -> None:
        self.cursor_obj = _RecordingCursor()

    def cursor(self) -> _RecordingCursor:
        return self.cursor_obj


def test_every_producer_seeds_the_same_media_capture_grant() -> None:
    """The migration and the in-process seed agree on the grant's identity.

    Identity is `grant_ref` + `basis` + `scope` + `capture_profile`: those are
    what a consumer resolves and what gets stamped onto a raw record, so a
    divergence between backends would mean the same deployment answers
    differently about what the operator consented to.
    """
    constants = _migration_module_constants()
    assert constants["revision"] == "a9f3c2d7b6e1"

    assert constants["_MEDIA_CAPTURE_GRANT_REF"] == MEDIA_CAPTURE_GRANT_REF
    assert constants["_MEDIA_CAPTURE_BASIS"] == MEDIA_CAPTURE_BASIS
    assert constants["_MEDIA_CAPTURE_SCOPE"] == MEDIA_CAPTURE_SCOPE

    memory_seed = _media_capture_seed_row(0)

    # Correct constants are not enough — assert the row the migration actually
    # EMITS binds each of them to its declared column. A swapped basis/scope
    # pair, a hardcoded profile, or a typo'd scope literal all leave the
    # constants intact while seeding a grant that resolves for nothing; on an
    # append-only, forward-only table that row can never be removed.
    seeded = _seeded_columns()
    assert seeded["grant_ref"] == f"'{MEDIA_CAPTURE_GRANT_REF}'"
    assert seeded["basis"] == f"'{MEDIA_CAPTURE_BASIS}'"
    assert seeded["scope"] == f"'{MEDIA_CAPTURE_SCOPE}'"
    assert seeded["granted_by"] == "'operator'"
    assert seeded["expiry"] == "NULL"
    assert seeded["revokes_grant_ref"] == "NULL"

    def _emitted_json(column: str) -> object:
        return json.loads(seeded[column].removesuffix("::jsonb").strip("'"))

    emitted_profile = _emitted_json("capture_profile")
    assert emitted_profile == memory_seed.capture_profile, (
        "the migration must emit the same capture_profile the in-process seed builds"
    )
    assert emitted_profile["modalities"] == list(MEDIA_CAPTURE_MODALITIES)

    # The B-shaped consent-posture columns too, not just identity. The migration
    # docstring promises "the same v1-inert B-shaped defaults"; without these,
    # flipping `erasure.supported` to true, widening `third_party_policy` to
    # 'allow', swapping vad_gate/third_party, or setting a retention bound each
    # seeds a production row whose consent posture silently diverges from
    # `_default_b_shaped_fields()` — and on an append-only, forward-only table
    # that row cannot be corrected except by another migration.
    assert seeded["third_party_policy"] == f"'{memory_seed.third_party_policy}'"
    assert _emitted_json("vad_gate") == memory_seed.vad_gate
    assert _emitted_json("third_party") == memory_seed.third_party
    assert _emitted_json("retention") == memory_seed.retention
    assert _emitted_json("erasure") == memory_seed.erasure
    # The payload is provenance prose rather than posture, so only its shape is
    # pinned — it must be an object carrying a note, not silently empty.
    assert isinstance(_emitted_json("payload"), dict)
    assert "note" in _emitted_json("payload")  # type: ignore[operator]

    # Every column the INSERT declares is now asserted, so a later column can
    # not be added to the seed without this test being extended too.
    assert set(seeded) == {
        "id", "grant_ref", "basis", "scope", "granted_by", "granted_at",
        "expiry", "capture_profile", "third_party_policy", "vad_gate",
        "third_party", "retention", "erasure", "revokes_grant_ref", "payload",
    }

    # The memory seed's own identity fields match the module constants too, so
    # neither producer can be "fixed" by editing only the other.
    assert memory_seed.grant_ref == MEDIA_CAPTURE_GRANT_REF
    assert memory_seed.basis == MEDIA_CAPTURE_BASIS
    assert memory_seed.scope == MEDIA_CAPTURE_SCOPE
    assert memory_seed.granted_by == "operator"
    assert memory_seed.expiry is None
    assert memory_seed.revokes_grant_ref is None


def test_migration_seed_is_idempotent_and_forward_only() -> None:
    """A rerun must not duplicate the standing grant, and the row cannot be
    un-seeded: `heimdal_consent_grant` is append-only (HEIM-1) with a trigger
    rejecting DELETE, so a downgrade path would be a false promise."""
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    constants = _migration_module_constants()

    assert constants["reversibility"] == "forward-only"
    assert re.search(r"def downgrade\(\)[\s\S]*raise RuntimeError", source), (
        "downgrade must raise rather than silently no-op"
    )
    # Guarded insert, same shape as c4f7a1b2d9e3's self_record seed. The guard
    # must key on *this* migration's grant_ref: a guard naming any already-seeded
    # ref (e.g. the self-record grant) is true on every database, so the insert
    # would silently never happen, alembic_version would still advance, and
    # media ingress would 409 forever. Substring-checking "WHERE NOT EXISTS"
    # alone does not catch that, so assert the subquery's predicate.
    assert "INSERT INTO heimdal_consent_grant" in source
    # Anchored on the closing paren: a prefix match would accept an appended
    # `OR TRUE` (guard always true -> the insert never fires while
    # alembic_version still advances -> media ingress 409s forever) or
    # `AND 1 = 0` (guard never true -> a duplicate grant on every rerun).
    guard = re.search(
        r"WHERE NOT EXISTS\s*\(\s*SELECT 1 FROM heimdal_consent_grant\s*"
        r"WHERE grant_ref = '\{(?P<ref_const>\w+)\}'\s*\)",
        source,
    )
    assert guard is not None, (
        "the seed must be guarded by NOT EXISTS on a grant_ref predicate"
    )
    assert constants[guard.group("ref_const")] == MEDIA_CAPTURE_GRANT_REF, (
        "the idempotency guard must name this migration's own grant_ref; naming an "
        "already-seeded ref makes the guard true everywhere and the insert dead"
    )
    # Data-only: the table, its indexes, and its append-only trigger belong to
    # c4f7a1b2d9e3 and must not be redefined here.
    for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE TRIGGER"):
        assert ddl not in source, f"{ddl} does not belong in a data-only seed migration"


def test_in_process_producers_share_one_builder_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both in-process producers actually seed **both** standing grants.

    Asserted **behaviorally**, by running each producer and reading what it
    emitted — not by checking that its source mentions
    `_STANDING_SEED_ROW_BUILDERS`. A source-text assertion cannot distinguish a
    producer that iterates the shared tuple from one that iterates it and then
    filters a grant back out (`if grant_ref != SELF_RECORD_GRANT_REF: continue`),
    which is exactly the regression this test exists to catch.
    """
    builders = dict(_STANDING_SEED_ROW_BUILDERS)
    assert builders.keys() == {SELF_RECORD_GRANT_REF, MEDIA_CAPTURE_GRANT_REF}
    assert builders[MEDIA_CAPTURE_GRANT_REF] is _media_capture_seed_row

    # Producer 1: the memory backend. Drive the real reset hook and read the
    # ledger's own active grants.
    reset_memory_consent_ledger()
    memory_refs = {grant.grant_ref for grant in list_active_grants()}
    assert memory_refs == {SELF_RECORD_GRANT_REF, MEDIA_CAPTURE_GRANT_REF}

    # Producer 2: the STORE_SCHEMA_AUTOCREATE Postgres bootstrap. Driven
    # against a stub connection, so this needs no Postgres and therefore runs
    # in the required `Unit tests (not pg)` job, where drift must be caught.
    monkeypatch.setenv("STORE_SCHEMA_AUTOCREATE", "1")
    conn = _RecordingConn()
    consent_ledger._bootstrap_pg(conn)
    seeded = conn.cursor_obj.seeded_identities()
    assert {ref for ref, _basis, _scope in seeded} == {
        SELF_RECORD_GRANT_REF,
        MEDIA_CAPTURE_GRANT_REF,
    }, "the autocreate bootstrap must INSERT every standing grant"
    # ...and under the right scope: a grant seeded against the wrong scope
    # resolves for nothing, which no grant_ref-only assertion would catch.
    assert (MEDIA_CAPTURE_GRANT_REF, MEDIA_CAPTURE_BASIS, MEDIA_CAPTURE_SCOPE) in seeded
