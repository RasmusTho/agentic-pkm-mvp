"""MVR-05A2 (#4576): every durable table declares a binding classification.

MVR-05A stopped three times, twice on the same defect class found one table at
a time: a durable table nobody had classified, discovered only when a slice
tripped over it. This gate exists so that cannot recur, and the shape of the
gate is the whole point.

**It is a set difference, not a list.** The population comes from
``app/alembic/versions/**`` — the parsing idiom
``tests/architecture/test_durable_table_ownership.py`` already proved, widened
in ``durable_table_classification.py`` to read the f-string-over-a-constant
spelling three revisions and every replay producer actually use. The gate then
fails on ``discovered_durable_tables - classified_tables``. Revision 36 creating
table 44 fails this gate on the commit that adds the revision, with no test
edit, because the difference is computed against a population that grew.

A gate written the other way — ``assert classified ⊇ the forty-three tables
that exist today`` — is satisfied forever once cleared, and says nothing about
table forty-four. That is the gate this one replaces, and
``test_a_durable_table_added_by_a_later_revision_fails_until_classified``
proves the difference by *synthesizing* a revision rather than by editing an
expected list.

Three properties keep it from degrading back:

* **No default.** ``test_the_manifest_carries_no_default_and_no_wildcard_entry``
  removes each of the forty-three entries in turn and asserts the gate fails on
  exactly that table. A fallback classification anywhere in the loader would
  make forty-three of those assertions pass silently.
* **No wildcard.** Manifest keys must be literal table identifiers.
* **No ignore-list.** A durable statement whose table name the resolver cannot
  reduce to a literal raises rather than being skipped.

Source anchors:
    docs/MULTI_VAULT_RUNTIME/ROUTE_REQUESTS_THROUGH_ACTIVE_CONTEXT.md :: 05A child decomposition
    tests/architecture/durable_table_classification.py
    Issue #4576
"""

from __future__ import annotations

import json
import re
import shutil
from collections import Counter
from pathlib import Path

import pytest

from tests.architecture.durable_table_classification import (
    APP_ROOT,
    BINDING_KEY_STATES,
    CLASSIFICATIONS,
    ESCALATION_CONDITIONS,
    MANIFEST_PATH,
    REBUILD_MECHANISMS,
    REPO_ROOT,
    SEPARATE_SCHEMA_PLANES,
    _resolver,
    cutover_worklist,
    exempted_statement_sites,
    discover_durable_mutation_paths,
    discover_durable_tables,
    discover_runtime_ddl_seams,
    foreign_key_target_candidates,
    load_manifest,
    stale_classifications,
    stale_producer_entries,
    unclassified_mutation_paths,
    unclassified_tables,
    unresolvable_statement_sites,
)

pytestmark = pytest.mark.not_pg


def _substantial_sentences(reason: str) -> list[str]:
    """Sentences long enough to carry a classification claim.

    Ten words is the line: shorter than that is a shared citation
    ("Explicitly global per the MVR-05 acceptance criteria."), which is fine to
    repeat; longer than that is an argument, and an argument reused verbatim
    across a family of tables is not per-table evidence.
    """
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", reason)
        if len(sentence.split()) >= 10
    ]


RELATIONS_INIT_SQL = REPO_ROOT / "app" / "db" / "sql" / "relations_init.sql"
LEGACY_RELATION_INDEX = REPO_ROOT / "app" / "store" / "relation_index.py"


# --------------------------------------------------------------------------- #
# The population gate
# --------------------------------------------------------------------------- #


def test_every_production_projection_schema_and_producer_is_classified() -> None:
    """``discovered_durable_tables - classified_tables`` is empty, both ways.

    The forward difference is the contract. The reverse difference
    (``classified - discovered``) is here so a table removed from the revision
    chain cannot leave a classification behind that keeps the population
    looking covered while nothing is checking it.
    """
    discovered = discover_durable_tables()
    manifest = load_manifest()

    unclassified = unclassified_tables(discovered, manifest)
    assert unclassified == frozenset(), (
        f"{sorted(unclassified)} are created by the Alembic revision chain but carry no "
        f"entry in {MANIFEST_PATH.name}. Every durable table must be classified "
        "`binding-scoped` or `explicitly-global` with a written reason before it can "
        "land: MVR-05A stopped twice on a durable table nobody had classified. "
        "`explicitly-global` is a claim, not a way to clear this list."
    )

    stale = stale_classifications(discovered, manifest)
    assert stale == frozenset(), (
        f"{sorted(stale)} are classified but no revision creates them. Remove the "
        "entry, or restore the revision it describes."
    )

    reasons_seen: dict[str, str] = {}
    sentences_seen: dict[str, str] = {}
    for table, entry in sorted(manifest.items()):
        assert entry["classification"] in CLASSIFICATIONS, (table, entry["classification"])
        assert entry["binding_key"] in BINDING_KEY_STATES, (table, entry["binding_key"])
        assert entry["rebuild_mechanism"] in REBUILD_MECHANISMS, table
        for sentence in _substantial_sentences(entry["reason"]):
            assert sentence not in sentences_seen, (
                f"{table} shares this sentence with {sentences_seen[sentence]}:\n"
                f"  {sentence}\n"
                "A paragraph reused across a family of tables is a template, and a "
                "template is how one wrong claim rides along with fifteen right ones — "
                "which is what happened to `heimdal_meeting_finalization_receipt`, whose "
                "`artifact_refs` column records the vault a session was materialized into "
                "while the shared paragraph claimed the whole family was vault-"
                "independent. Write this table's own evidence."
            )
            sentences_seen[sentence] = table
        assert entry["reason"] not in reasons_seen, (
            f"{table}'s reason is byte-identical to {reasons_seen[entry['reason']]}'s. A "
            "reason copied across a family of tables is a template, and a template is "
            "how one wrong claim rides along with fifteen right ones — which is what "
            "happened to `heimdal_meeting_finalization_receipt`, whose `artifact_refs` "
            "column records the vault a session was materialized into while the shared "
            "paragraph claimed the whole family was vault-independent."
        )
        reasons_seen[entry["reason"]] = table
        assert len(entry["reason"].split()) >= 12, (
            f"{table}'s classification reason is {entry['reason']!r}. The reason is the "
            "artifact a later slice reads to decide whether the classification is still "
            "true; a placeholder makes `explicitly-global` a default in everything but "
            "name."
        )
        assert (
            table in entry["reason"]
            or any(
                producer["module"].rsplit("/", 1)[-1][:-3] in entry["reason"]
                for producer in entry["producers"]
            )
            or entry["owning_revision"] in entry["reason"]
        ), (
            f"{table}'s reason names neither the table, its owning revision, nor a "
            "producer module, so it cannot be checked against the code it describes."
        )
        if entry["classification"] == "explicitly-global":
            assert entry["binding_key"] == "not-applicable", table
            assert entry["binding_column"] is None, table
        else:
            assert entry["binding_key"] in {"keyed", "pending"}, table
        if entry["binding_key"] == "keyed":
            owning = next(
                path
                for path in (REPO_ROOT / "app" / "alembic" / "versions").glob(
                    f"{entry['owning_revision']}_*.py"
                )
            )
            assert entry["binding_column"] in owning.read_text(encoding="utf-8"), (
                f"{table} is declared keyed by {entry['binding_column']!r}, but its "
                f"owning revision {owning.name} never mentions that column."
            )

        assert entry["owning_revision"] in {name.split("_", 1)[0] for name in discovered[table]}, (
            f"{table}'s owning revision {entry['owning_revision']} issues no DDL for it; "
            f"the chain's declaring revisions are {sorted(discovered[table])}."
        )


def test_the_manifest_carries_no_default_and_no_wildcard_entry() -> None:
    """Removing any single entry makes the gate fail on exactly that table.

    This is the mechanical proof that ``explicitly-global`` is not reachable by
    omission. If the loader grew ``manifest.get(table, {"classification":
    "explicitly-global"})`` — the single most tempting way to make a red suite
    green — forty-three of these assertions would go quiet at once.
    """
    discovered = discover_durable_tables()
    manifest = load_manifest()

    for key in manifest:
        assert re.fullmatch(r"[a-z_][a-z0-9_]*", key), (
            f"{key!r} is not a literal table identifier. Manifest keys are table names; "
            "a pattern, glob or catch-all key would classify tables nobody looked at."
        )
        assert key not in {"default", "_default", "__default__", "all"}, key

    for table in sorted(discovered):
        reduced = {name: entry for name, entry in manifest.items() if name != table}
        assert unclassified_tables(discovered, reduced) == frozenset({table}), (
            f"dropping {table} from the manifest did not make the gate fail on it, so "
            "something is supplying a classification the manifest does not contain."
        )


def test_a_durable_table_added_by_a_later_revision_fails_until_classified(
    tmp_path: Path,
) -> None:
    """A revision that does not exist today fails the gate when it is written.

    The proof synthesizes the revision instead of editing an expected list,
    because editing a list would prove only that the list is editable. All
    three spellings the chain actually uses are synthesized, so widening the
    gate's population source without widening its parser cannot pass this:

    * ``op.execute("CREATE TABLE IF NOT EXISTS public.<t> (...)")``
    * ``op.create_table("<t>", ...)``
    * ``op.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} (...)")``

    Nothing here can pass vacuously. If discovery missed a synthetic table the
    difference would be *smaller* than expected and the equality fails; if it
    invented one the difference would be larger and the equality fails. The
    control assertion against the real directory pins that the failure is
    caused by the added revision and not by pre-existing manifest drift.
    """
    manifest = load_manifest()
    assert unclassified_tables(discover_durable_tables(), manifest) == frozenset(), (
        "the control is not clean: the real revision chain already has unclassified "
        "tables, so this test could not attribute a failure to the synthetic revision"
    )

    versions = tmp_path / "versions"
    versions.mkdir()
    for path in (REPO_ROOT / "app" / "alembic" / "versions").glob("*.py"):
        shutil.copy2(path, versions / path.name)

    (versions / "aaaa000000aa_mvr05a2_synthetic_raw.py").write_text(
        "from alembic import op\n\n"
        'revision = "aaaa000000aa"\n'
        'down_revision = "d1e8a0c5f37b"\n\n\n'
        "def upgrade() -> None:\n"
        "    op.execute(\n"
        '        """\n'
        "        CREATE TABLE IF NOT EXISTS public.mvr05a2_synthetic_raw (\n"
        "            id uuid PRIMARY KEY\n"
        "        )\n"
        '        """\n'
        "    )\n",
        encoding="utf-8",
    )
    (versions / "aaaa000001aa_mvr05a2_synthetic_op_api.py").write_text(
        "import sqlalchemy as sa\n"
        "from alembic import op\n\n"
        'revision = "aaaa000001aa"\n'
        'down_revision = "aaaa000000aa"\n\n\n'
        "def upgrade() -> None:\n"
        "    op.create_table(\n"
        '        "mvr05a2_synthetic_op_api",\n'
        '        sa.Column("id", sa.Uuid(), primary_key=True),\n'
        "    )\n\n\n"
        "def downgrade() -> None:\n"
        '    op.drop_table("mvr05a2_synthetic_op_api")\n',
        encoding="utf-8",
    )
    (versions / "aaaa000002aa_mvr05a2_synthetic_interpolated.py").write_text(
        "from alembic import op\n\n"
        'revision = "aaaa000002aa"\n'
        'down_revision = "aaaa000001aa"\n'
        '_TABLE = "mvr05a2_synthetic_interpolated"\n\n\n'
        "def upgrade() -> None:\n"
        "    op.execute(\n"
        '        f"""\n'
        "        CREATE TABLE IF NOT EXISTS {_TABLE} (\n"
        "            id uuid PRIMARY KEY\n"
        "        )\n"
        '        """\n'
        "    )\n",
        encoding="utf-8",
    )

    synthetic = {
        "mvr05a2_synthetic_raw",
        "mvr05a2_synthetic_op_api",
        "mvr05a2_synthetic_interpolated",
    }
    discovered = discover_durable_tables(versions)
    assert synthetic <= set(discovered), (
        f"the gate did not discover {sorted(synthetic - set(discovered))} from the "
        "synthesized revisions, so a real revision written the same way would enter "
        "production unclassified while this gate reported green."
    )
    assert unclassified_tables(discovered, manifest) == frozenset(synthetic), (
        "the gate must fail on exactly the three tables the synthesized revisions "
        "create, and on nothing else"
    )

    # And classifying them clears it — the gate is satisfied by a human writing
    # a classification, never by the table simply existing for long enough.
    classified = dict(manifest)
    for table in synthetic:
        classified[table] = {"classification": "explicitly-global", "reason": "synthetic"}
    assert unclassified_tables(discovered, classified) == frozenset()


def test_migration_local_temp_snapshot_is_not_a_durable_table_default(
    tmp_path: Path,
) -> None:
    """Only explicit TEMP syntax excludes a migration relation from the gate."""
    versions = tmp_path / "versions"
    versions.mkdir()
    (versions / "aaaa000003aa_temp_and_durable.py").write_text(
        "from alembic import op\n\n"
        'revision = "aaaa000003aa"\n'
        "down_revision = None\n\n\n"
        "def upgrade() -> None:\n"
        '    op.execute("""\n'
        "        CREATE TEMP TABLE mvr05a3_fk_snapshot (id uuid);\n"
        "        CREATE TABLE durable_control (id uuid);\n"
        '    """)\n',
        encoding="utf-8",
    )

    discovered = discover_durable_tables(versions)
    assert set(discovered) == {"durable_control"}
    assert "mvr05a3_fk_snapshot" not in discovered


# --------------------------------------------------------------------------- #
# The producer half
# --------------------------------------------------------------------------- #


def test_every_durable_mutation_path_resolves_to_a_classified_producer() -> None:
    """Every durable INSERT/UPDATE/DELETE/TRUNCATE resolves to a manifest entry.

    Both directions again: an undeclared producer fails, and a declared
    producer no statement supports fails too — otherwise a stale entry would
    keep a table looking owned after its writer moved.
    """
    tables = discover_durable_tables()
    manifest = load_manifest()

    undeclared = unclassified_mutation_paths(manifest, tables)
    assert undeclared == frozenset(), (
        "these durable mutation paths resolve to no classified producer entry:\n"
        + "\n".join(
            f"  {path.module} {path.verb.upper()} {path.table}"
            for path in sorted(undeclared, key=lambda item: (item.table, item.module, item.verb))
        )
    )

    stale = stale_producer_entries(manifest, tables)
    assert stale == frozenset(), (
        "these producer entries are declared but no statement under app/** supports "
        "them:\n"
        + "\n".join(
            f"  {path.module} {path.verb.upper()} {path.table}"
            for path in sorted(stale, key=lambda item: (item.table, item.module, item.verb))
        )
    )


def test_store_object_composite_key_producer_inventory_is_exact() -> None:
    """MVR-05A3's parent/child invariant covers every current SQL producer.

    This is intentionally derived from the same scanner as the repository-wide
    gate, narrowed to the atomic store-object mechanism so later changes cannot
    make this acceptance test pass by editing a hand-maintained expected list in
    only one direction.
    """
    mechanism_tables = {
        "store_objects",
        "store_vector_index",
        "store_relations",
        "store_relation_memberships",
        "vector_index_meta",
        "chunks",
        "embeddings",
        "relations",
        "membership",
        "decisions",
        "audit",
    }
    manifest = load_manifest()
    discovered = discover_durable_tables()
    tables = discovered
    actual = {
        (path.table, path.module, path.verb)
        for path in discover_durable_mutation_paths(discovered)
        if path.table in mechanism_tables
    }
    declared = {
        (table, producer["module"], operation)
        for table in mechanism_tables
        for producer in manifest[table]["producers"]
        for operation in producer["operations"]
    }
    assert actual == declared

    assert {path for path in actual if path[0] in {"chunks", "embeddings"}} == {
        ("chunks", "app/stores/pg.py", "delete"),
        ("embeddings", "app/stores/pg.py", "delete"),
    }, "the zero-writer child tables must remain zero-writer"
    assert not any(operation == "truncate" for _, _, operation in actual)
    for table in mechanism_tables:
        assert manifest[table]["binding_column"] == "vault_binding_id", table

    # The module/verb inventory deliberately deduplicates identical operations,
    # so an adjacent INSERT in an already-declared module could otherwise omit
    # the composite namespace without changing `actual`. Inspect every resolved
    # store_objects INSERT and pin both current writers, including the atomic
    # create-once seam added by #4111 while this branch was under review.
    pg_path = REPO_ROOT / "app" / "stores" / "pg.py"
    store_object_inserts = [
        statement
        for statement in _resolver(pg_path).sql_statements()
        if re.search(r"(?is)\binsert\s+into\s+store_objects\b", statement.text)
    ]
    assert {statement.function for statement in store_object_inserts} == {
        "put_object_with_connection",
        "put_object_if_absent_with_connection",
    }
    for statement in store_object_inserts:
        assert re.search(
            r"(?is)insert\s+into\s+store_objects\s*\(\s*vault_binding_id\s*,\s*object_id\b",
            statement.text,
        ), f"{statement.function} omits vault_binding_id from the canonical parent write"
        assert re.search(
            r"(?is)on\s+conflict\s*\(\s*vault_binding_id\s*,\s*object_id\s*\)",
            statement.text,
        ), f"{statement.function} retains a global object_id conflict target"

    binding_producers = {
        module
        for _, module, _ in actual
        if module
        not in {
            "app/stores/pg.py",
            "app/episodes/assignment.py",
        }
    }
    for module in binding_producers:
        source = (REPO_ROOT / module).read_text(encoding="utf-8")
        assert "vault_binding_id" in source or "COMPATIBILITY_BINDING_ID" in source, module

    # The producer half must also have no default: dropping any single declared
    # producer has to surface as an undeclared mutation path.
    for table, entry in sorted(manifest.items()):
        if not entry["producers"]:
            continue
        reduced = dict(manifest)
        reduced[table] = {**entry, "producers": entry["producers"][1:]}
        assert unclassified_mutation_paths(
            reduced, tables
        ), f"dropping {table}'s first producer entry did not fail the producer gate"


def test_post_cutover_store_fixture_mutations_are_binding_scoped() -> None:
    """Current-shape fixtures cannot silently retain global object identity.

    The only unbound mutations are the exact historical-lineage seeds that run
    before MVR-05A3 and prove its adoption/refusal behavior.  A new fixture is
    post-cutover by default and must name ``vault_binding_id``; adding another
    legacy seed requires an explicit update to this receipt and therefore a
    review of why the old shape is still needed.
    """
    object_identity_tables = (
        "store_objects",
        "store_vector_index",
        "store_relations",
        "store_relation_memberships",
        "vector_index_meta",
        "chunks",
        "embeddings",
        "relations",
        "membership",
        "decisions",
        "audit",
    )
    mutation = re.compile(
        r"(?is)\b(insert\s+into|update|delete\s+from)\s+"
        rf"(?:public\.)?({'|'.join(object_identity_tables)})\b"
    )
    observed: Counter[tuple[str, str | None, str, str]] = Counter()
    for path in sorted((REPO_ROOT / "tests").rglob("*.py")):
        for statement in _resolver(path).sql_statements():
            matches = list(mutation.finditer(statement.text))
            for index, match in enumerate(matches):
                next_mutation = (
                    matches[index + 1].start() if index + 1 < len(matches) else len(statement.text)
                )
                semicolon = statement.text.find(";", match.end())
                boundary = min(semicolon, next_mutation) if semicolon >= 0 else next_mutation
                mutation_text = statement.text[match.start() : boundary]
                if "vault_binding_id" in mutation_text.lower():
                    continue
                observed[
                    (
                        path.relative_to(REPO_ROOT).as_posix(),
                        statement.function,
                        " ".join(match.group(1).lower().split()),
                        match.group(2).lower(),
                    )
                ] += 1

    expected = Counter(
        {
            (
                "tests/integration/test_single_vault_compatibility.py",
                "test_file_state_rekey_preserves_single_vault_sync",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/integration/test_single_vault_compatibility.py",
                "test_objects_rekey_preserves_single_vault_behaviour",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_keyed_fks_preserve_actions_and_nullable_receipt_provenance",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_keyed_fks_preserve_actions_and_nullable_receipt_provenance",
                "insert into",
                "decisions",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_keyed_fks_preserve_actions_and_nullable_receipt_provenance",
                "insert into",
                "audit",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_legacy_objects_fk_migration_backfills_existing_parents",
                "insert into",
                "decisions",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_active_decision_writer_preflights_before_receipt_on_pre_cutover_schema",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_decisions_projection_rebuild_rejects_legacy_parent_before_truncate",
                "insert into",
                "decisions",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_migration_rejects_cross_key_canonical_identity_collision",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_backfill_counts_distinct_store_relation_assignments",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_backfill_counts_distinct_store_relation_assignments",
                "insert into",
                "store_relations",
            ): 1,
            **{
                (
                    "tests/migrations/test_legacy_objects_fk_migration.py",
                    "test_binding_backfill_counts_distinct_parent_assignments_not_child_rows",
                    "insert into",
                    table,
                ): 1
                for table in (
                    "store_objects",
                    "chunks",
                    "embeddings",
                    "relations",
                    "membership",
                    "decisions",
                    "audit",
                )
            },
            **{
                (
                    "tests/migrations/test_legacy_objects_fk_migration.py",
                    "test_migration_retargets_every_reviewed_consumer_with_live_rows",
                    "insert into",
                    table,
                ): 1
                for table in (
                    "chunks",
                    "embeddings",
                    "relations",
                    "membership",
                    "decisions",
                    "audit",
                )
            },
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_backfill_is_parent_provable_or_fails_before_conversion",
                "insert into",
                "store_objects",
            ): 3,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_backfill_is_parent_provable_or_fails_before_conversion",
                "insert into",
                "store_relations",
            ): 1,
            (
                "tests/migrations/test_legacy_objects_fk_migration.py",
                "test_binding_backfill_is_parent_provable_or_fails_before_conversion",
                "insert into",
                "vector_index_meta",
            ): 1,
            # MVR-05A4's retained-lineage proof deliberately reconstructs the
            # pre-binding membership/store_objects shape before upgrading it.
            (
                "tests/migrations/test_multi_vault_ingest_projection_keys.py",
                "test_retained_historical_membership_lineage_is_rekeyed",
                "insert into",
                "store_objects",
            ): 1,
            (
                "tests/migrations/test_multi_vault_ingest_projection_keys.py",
                "test_retained_historical_membership_lineage_is_rekeyed",
                "insert into",
                "membership",
            ): 1,
        }
    )
    assert observed == expected, (
        "every current-shape object-identity fixture mutation must name vault_binding_id; "
        f"unbound fixture delta: added={observed - expected}, removed={expected - observed}"
    )


def test_no_executed_sql_statement_is_invisible_to_the_scan() -> None:
    """No SQL call under ``app/**`` resolves to nothing at all.

    The scans raise when a *matched* durable statement carries an unresolvable
    table name. This is the other half, and the quieter one: a call whose SQL
    argument resolves to no literal produces no statement to match, so it would
    drop out without any signal. Four such sites existed while this slice was
    being written — the `psycopg.sql.SQL(...).format(Identifier(t))` idiom in
    `app/db/__init__.py` and `app/stores/pg.py`, plus SQLAlchemy `text()` in
    `app/health.py`. All four happen to be `SELECT`s, so nothing durable was
    being missed; the resolver was widened anyway, because "they are all reads
    today" is not a property a gate can rely on.
    """
    sites = unresolvable_statement_sites()
    assert sites == (), (
        "these SQL calls resolve to no literal statement, so the classification "
        "and DDL scans cannot see them at all:\n  "
        + "\n  ".join(sites)
        + "\nWiden the resolver in tests/architecture/durable_table_classification.py "
        "rather than leaving a statement invisible: an INSERT written this way "
        "would never reach the producer gate."
    )


def test_the_separate_schema_planes_hold_no_durable_statement() -> None:
    """The BuilderOps / dispatcher exemption is bounded, and its cost is named.

    `app/builderops/**` and `app/dispatcher/**` carry their own schema lineage
    — `app/builderops/control_plane/migrations/**`, asserted to sit outside
    `app/alembic` by `tests/architecture/test_builderops_migration_boundary.py`
    — and their SQLite stores build statements in ways this resolver does not
    read. They are exempt from the unresolvable-expression failure.

    An exemption whose cost is not measured is an ignore-list. Three
    assertions bound it:

    1. no statement in either subtree resolves to a table the Alembic revision
       chain creates — the exemption may not hide a durable statement;
    2. every `.sql` file under them is a *registered* entry of the BuilderOps
       migration lineage, read from `MIGRATIONS` rather than from a path list
       here, so a new stray `.sql` file is not silently covered;
    3. the set of files it makes invisible is enumerated below, so growing it
       is a visible diff rather than a quiet widening.
    """
    tables = discover_durable_tables()

    durable_statements = [
        f"{path.module} {path.verb.upper()} {path.table}"
        for path in sorted(
            discover_durable_mutation_paths(tables),
            key=lambda item: (item.module, item.table),
        )
        if any(path.module.startswith(f"{plane}/") for plane in SEPARATE_SCHEMA_PLANES)
    ] + [
        f"{seam.path}:{seam.lineno} {seam.verb.upper()} {seam.table}"
        for seam in discover_runtime_ddl_seams(tables)
        if seam.owned_by_revision_chain
        and any(seam.path.startswith(f"{plane}/") for plane in SEPARATE_SCHEMA_PLANES)
    ]
    assert durable_statements == [], (
        f"{durable_statements} touch a durable table from a subtree this gate exempts. "
        "Either the statement moves, or the exemption is revoked — it must not become "
        "an ignore-list for durable statements."
    )

    from app.builderops.control_plane.migrations import MIGRATIONS

    registered = {path.resolve() for path in MIGRATIONS}
    stray = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for plane in SEPARATE_SCHEMA_PLANES
        for path in (REPO_ROOT / plane).rglob("*.sql")
        if path.resolve() not in registered
    )
    assert stray == [], (
        f"{stray} are SQL files inside an exempted subtree that the BuilderOps "
        "migration lineage does not register, so nothing governs their DDL."
    )

    # The exemption's measured cost, pinned per file **and per count**. A file
    # set alone is not a bound: a new invisible statement inside an
    # already-listed file changes nothing, and assertion 1 cannot see it
    # precisely because it is invisible. Counts move with any new blind spot;
    # line numbers would churn on every unrelated edit.
    invisible = dict(
        sorted(Counter(site.split(":", 1)[0] for site in exempted_statement_sites()).items())
    )
    assert invisible == {
        "app/builderops/ckm/query_service.py": 1,
        "app/builderops/ckm/semantic.py": 1,
        "app/builderops/ckm/store.py": 5,
        "app/builderops/control_plane/store.py": 1,
        "app/builderops/design_agent_adapters.py": 1,
        "app/builderops/design_run_governance.py": 1,
        "app/builderops/model_inquiry_runner.py": 1,
        "app/builderops/store.py": 1,
        "app/dispatcher/store.py": 2,
        "app/dispatcher/verification_dispatch.py": 1,
        "app/dispatcher/verification_runtime.py": 1,
    }, (
        "the statements the separate-plane exemption makes invisible changed:\n  "
        + "\n  ".join(f"{name}: {count}" for name, count in invisible.items())
        + "\nIf one went away, lower the count here. If one appeared, either widen the "
        "resolver so the statement is read, or record here why a new blind spot is "
        "acceptable. An `INSERT INTO store_objects` built this way inside an already-"
        "listed file is exactly what this count exists to surface."
    )


# --------------------------------------------------------------------------- #
# The derived worklist
# --------------------------------------------------------------------------- #


def test_binding_cutover_worklist_is_derived_from_the_manifest() -> None:
    """The worklist is a query over the manifest, not a second list.

    MVR-05A3/05A4/05A5 select their table membership from this rather than from
    a list re-typed into three Issue bodies, so the derivation itself is what
    has to hold: flipping a table's ``binding_key`` must move it, in the same
    commit, with no worklist edit.
    """
    manifest = load_manifest()
    worklist = cutover_worklist(manifest)

    expected = {
        table
        for table, entry in manifest.items()
        if entry["classification"] == "binding-scoped" and entry["binding_key"] == "pending"
    }
    assert {row.table for row in worklist} == expected

    for row in worklist:
        assert row.rebuild_mechanism in REBUILD_MECHANISMS, row
        assert set(row.escalation_conditions) <= set(ESCALATION_CONDITIONS), row
        assert len(set(row.escalation_conditions)) == len(row.escalation_conditions), row
        if "inbound-fk-target" in row.escalation_conditions:
            assert row.table in foreign_key_target_candidates(), (
                f"{row.table} claims the inbound-foreign-key escalation condition, but no "
                "revision in the chain ever points a REFERENCES clause at it."
            )
        assert set(row.write_producers) <= set(row.producers)

    # Derivation, proved by mutation rather than by inspection.
    pinned = next(row.table for row in worklist if row.write_producers)
    keyed = {**manifest, pinned: {**manifest[pinned], "binding_key": "keyed"}}
    assert pinned not in {row.table for row in cutover_worklist(keyed)}

    promoted = next(
        table for table, entry in manifest.items() if entry["classification"] == "explicitly-global"
    )
    joined = {
        **manifest,
        promoted: {
            **manifest[promoted],
            "classification": "binding-scoped",
            "binding_key": "pending",
        },
    }
    assert promoted in {row.table for row in cutover_worklist(joined)}

    # Every routing input the table-group children read is present per row.
    escalating = {row.table for row in worklist if row.escalates}
    assert escalating, "no pending table records an escalation condition"
    for row in worklist:
        if row.write_producers:
            assert row.rebuild_mechanism != "no-producer", row


def test_orphaned_relation_artifacts_are_removed_or_classified() -> None:
    """`relations_init.sql` is gone; `relation_index.py` is classified instead.

    Two artifacts of the class MVR-05A0/05A1 retired, handled differently
    because the evidence differs:

    * ``app/db/sql/relations_init.sql`` had zero readers repo-wide and declared
      a primary-key-less ``relations`` shape that disagreed with its Alembic
      owner. Unreachability is provable — nothing names the file — so it is
      removed, and this test is the proof it cannot come back unnoticed.
        * ``app/store/relation_index.py`` is *not* removable on the same evidence.
      ``app/objects/__init__.py`` re-exports it as a compatibility shim (an
      allowlisted entry in
      ``tests/architecture/test_deprecated_store_callers.py``), so it is
      reachable from production. Its ``link()`` inserts six columns that do not
          exist on the Alembic-owned table. MVR-05A3 makes that compatibility
          seam fail before SQL so it cannot omit the new binding column;
          MVR-05A4 (#4578) still owns replacing or deleting it.
    """
    assert not RELATIONS_INIT_SQL.exists(), (
        "app/db/sql/relations_init.sql is back. It declared `relations` without a "
        "primary key, disagreeing with its Alembic owner "
        "(202510241200_sot41_amg_core.py), and no code read it."
    )
    # The unreachability evidence: no production module, packaging manifest, CI
    # workflow or operator script names the file. This test and the mechanism
    # module name it deliberately, as the record of why it went.
    searched = [
        *(REPO_ROOT / "app").rglob("*"),
        *(REPO_ROOT / "scripts").rglob("*"),
        *(REPO_ROOT / ".github").rglob("*"),
        REPO_ROOT / "pyproject.toml",
        REPO_ROOT / "MANIFEST.in",
    ]
    referrers = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in searched
        if path.is_file()
        and path.suffix in {".py", ".sh", ".sql", ".yaml", ".yml", ".toml", ".in", ".cfg"}
        and "relations_init" in path.read_text(encoding="utf-8", errors="ignore")
    )
    assert referrers == [], (
        f"{referrers} reference the retired relations_init.sql bootstrap; it was removed "
        "on the evidence that nothing reads it."
    )

    manifest = load_manifest()
    assert not LEGACY_RELATION_INDEX.exists()
    assert manifest["relations"]["classification"] in CLASSIFICATIONS
    assert all(
        producer["module"] != "app/store/relation_index.py"
        for producer in manifest["relations"]["producers"]
    ), "a seam that refuses before SQL is not a durable mutation producer"
    assert "retired" in manifest["relations"]["reason"]


def test_the_manifest_is_checked_in_and_machine_readable() -> None:
    """The manifest is a checked-in artifact the later slices can query."""
    assert MANIFEST_PATH.exists()
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert set(document) == {"tables"}
    assert MANIFEST_PATH.is_relative_to(REPO_ROOT)
    assert APP_ROOT.exists()
