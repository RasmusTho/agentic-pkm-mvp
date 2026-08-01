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

The migration's identity fields are asserted by parsing the migration source,
so this runs without Postgres: a `pg`-only parity test would not run in the
required `Unit tests (not pg)` job, which is exactly where drift needs to be
caught. Schema parity for the underlying table is owned by `c4f7a1b2d9e3` and
is not re-asserted here -- this migration is data-only.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from app.heimdal.consent_ledger import (
    MEDIA_CAPTURE_BASIS,
    MEDIA_CAPTURE_GRANT_REF,
    MEDIA_CAPTURE_MODALITIES,
    MEDIA_CAPTURE_SCOPE,
    _media_capture_seed_row,
    _STANDING_SEED_ROW_BUILDERS,
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


def _producer_sources() -> dict[str, str]:
    """Exact source of each in-process seed producer, via the AST.

    Returns `{"_MemoryConsentLedger._seed": ..., "_bootstrap_pg": ...}`. Each
    value spans only that definition's own lines, so a mention of the shared
    tuple *outside* the definition cannot be mistaken for use inside it.
    """
    path = REPO_ROOT / "app" / "heimdal" / "consent_ledger.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_MemoryConsentLedger":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "_seed":
                    segment = ast.get_source_segment(source, item)
                    assert segment is not None
                    found["_MemoryConsentLedger._seed"] = segment
        elif isinstance(node, ast.FunctionDef) and node.name == "_bootstrap_pg":
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            found["_bootstrap_pg"] = segment
    assert set(found) == {"_MemoryConsentLedger._seed", "_bootstrap_pg"}, (
        f"expected both in-process producers to be found, got {sorted(found)}"
    )
    return found


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

    migration_profile = json.loads(str(constants["_MEDIA_CAPTURE_CAPTURE_PROFILE"]))
    memory_seed = _media_capture_seed_row(0)
    assert migration_profile == memory_seed.capture_profile
    assert migration_profile["modalities"] == list(MEDIA_CAPTURE_MODALITIES)

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
    # Guarded insert, same shape as c4f7a1b2d9e3's self_record seed.
    assert "WHERE NOT EXISTS" in source
    assert "INSERT INTO heimdal_consent_grant" in source
    # Data-only: the table, its indexes, and its append-only trigger belong to
    # c4f7a1b2d9e3 and must not be redefined here.
    for ddl in ("CREATE TABLE", "ALTER TABLE", "DROP TABLE", "CREATE TRIGGER"):
        assert ddl not in source, f"{ddl} does not belong in a data-only seed migration"


def test_in_process_producers_share_one_builder_tuple() -> None:
    """`_MemoryConsentLedger._seed` and the `_bootstrap_pg` autocreate branch
    both iterate `_STANDING_SEED_ROW_BUILDERS`, so a standing grant cannot land
    in one in-process producer and not the other."""
    builders = dict(_STANDING_SEED_ROW_BUILDERS)
    assert MEDIA_CAPTURE_GRANT_REF in builders
    assert builders[MEDIA_CAPTURE_GRANT_REF] is _media_capture_seed_row

    # Extract each producer's source via the AST rather than a regex span: a
    # regex bounded by "the next def" also swallows any comment sitting between
    # the two definitions, which would let this assertion pass vacuously on a
    # hardcoded producer that merely *mentions* the tuple nearby.
    for name, body in _producer_sources().items():
        assert "_STANDING_SEED_ROW_BUILDERS" in body, (
            f"{name} must iterate the shared builder tuple, not a hardcoded grant list"
        )
