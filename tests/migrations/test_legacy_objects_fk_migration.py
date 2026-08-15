"""Fail-loud migration coverage for #3510."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CUTOVER_REVISION = "4d1e0c9a3329"
PRE_BINDING_REKEY_REVISION = "d1e8a0c5f37b"
COMPATIBILITY_BINDING_ID = "legacy-compatibility-binding"

SUPPORTED_STORE_OBJECT_CONSUMERS = {
    ("chunks", "object_id"),
    ("embeddings", "object_id"),
    ("relations", "src_id"),
    ("relations", "dst_id"),
    ("membership", "object_id"),
    ("membership", "set_id"),
    ("decisions", "object_id"),
    ("audit", "object_id"),
}


def _admin_dsn() -> str:
    from app.db.dsn import resolve_dsn

    dsn = resolve_dsn()
    if not dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    return dsn


@pytest.fixture
def scratch_dsn(monkeypatch: pytest.MonkeyPatch):
    admin_dsn = _admin_dsn()
    try:
        probe = psycopg.connect(admin_dsn, connect_timeout=2)
    except Exception as exc:
        pytest.skip(f"Postgres unavailable: {exc}")
    probe.close()
    name = f"scratch_legacy_fk_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')
    base, _, _ = admin_dsn.rpartition("/")
    dsn = f"{base}/{name}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.delenv("DB_DSN", raising=False)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    try:
        yield dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _upgrade(revision: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    command.upgrade(cfg, revision)


def _use_retained_historical_membership_identity(conn: psycopg.Connection) -> None:
    """Make the fixture match the supported pre-MVR-05A3 membership lineage."""
    primary_key = conn.execute(
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid = 'public.membership'::regclass AND contype = 'p'"
    ).fetchone()[0]
    conn.execute(f'ALTER TABLE public.membership DROP CONSTRAINT "{primary_key}"')
    conn.execute("ALTER TABLE public.membership DROP COLUMN id")
    conn.execute("ALTER TABLE public.membership ADD PRIMARY KEY (object_id, set_id)")


def _store_object_fk_inventory(conn: psycopg.Connection) -> dict[tuple[str, str], dict]:
    rows = conn.execute(
        """
        SELECT child.relname AS table_name,
               child_att.attname AS endpoint,
               array_agg(all_child_att.attname ORDER BY ck.ordinality) AS child_columns,
               array_agg(parent_att.attname ORDER BY ck.ordinality) AS parent_columns,
               c.confupdtype::text,
               c.confdeltype::text,
               c.condeferrable,
               c.condeferred,
               COALESCE((
                   SELECT array_agg(set_att.attname ORDER BY sk.ordinality)
                   FROM unnest(c.confdelsetcols) WITH ORDINALITY sk(attnum, ordinality)
                   JOIN pg_attribute set_att
                     ON set_att.attrelid = c.conrelid AND set_att.attnum = sk.attnum
               ), ARRAY[]::name[]) AS delete_set_columns
          FROM pg_constraint c
          JOIN pg_class child ON child.oid = c.conrelid
          JOIN unnest(c.conkey) WITH ORDINALITY ck(attnum, ordinality) ON true
          JOIN pg_attribute all_child_att
            ON all_child_att.attrelid = c.conrelid AND all_child_att.attnum = ck.attnum
          JOIN pg_attribute parent_att
            ON parent_att.attrelid = c.confrelid
           AND parent_att.attnum = c.confkey[ck.ordinality]
          JOIN pg_attribute child_att
            ON child_att.attrelid = c.conrelid
           AND child_att.attname <> 'vault_binding_id'
           AND child_att.attnum = ANY(c.conkey)
         WHERE c.contype = 'f'
           AND c.confrelid = 'public.store_objects'::regclass
         GROUP BY c.oid, child.relname, child_att.attname
        """
    ).fetchall()
    return {
        (str(row[0]), str(row[1])): {
            "child_columns": list(row[2]),
            "parent_columns": list(row[3]),
            "update": row[4],
            "delete": row[5],
            "deferrable": row[6],
            "deferred": row[7],
            "delete_set_columns": list(row[8]),
        }
        for row in rows
    }


def test_every_supported_store_objects_child_fk_is_binding_keyed(scratch_dsn: str) -> None:
    """The historical eighth endpoint is converted only on that lineage."""
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        _use_retained_historical_membership_identity(conn)
        fk_name = conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'public.membership'::regclass AND contype = 'f' "
            "AND conkey = ARRAY[(SELECT attnum FROM pg_attribute "
            "WHERE attrelid = 'public.membership'::regclass AND attname = 'set_id')]::smallint[]"
        ).fetchone()[0]
        conn.execute(f'ALTER TABLE public.membership DROP CONSTRAINT "{fk_name}"')
        conn.execute(
            "ALTER TABLE public.membership ADD CONSTRAINT membership_set_id_fkey "
            "FOREIGN KEY (set_id) REFERENCES public.objects(id) ON DELETE CASCADE"
        )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        inventory = _store_object_fk_inventory(conn)
    assert set(inventory) == SUPPORTED_STORE_OBJECT_CONSUMERS
    for endpoint, shape in inventory.items():
        assert shape["child_columns"] == ["vault_binding_id", endpoint[1]]
        assert shape["parent_columns"] == ["vault_binding_id", "object_id"]


def test_binding_rekey_rejects_known_consumer_targeting_wrong_parent_column(
    scratch_dsn: str,
) -> None:
    """A familiar child name cannot make an alternate parent key supported."""
    _upgrade(PRE_BINDING_REKEY_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute("ALTER TABLE store_objects ADD COLUMN alternate_id uuid UNIQUE")
        fk_name = conn.execute(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'public.decisions'::regclass AND contype = 'f' "
            "AND confrelid = 'public.store_objects'::regclass"
        ).fetchone()[0]
        conn.execute(f'ALTER TABLE decisions DROP CONSTRAINT "{fk_name}"')
        conn.execute(
            "ALTER TABLE decisions ADD CONSTRAINT decisions_object_id_fkey "
            "FOREIGN KEY (object_id) REFERENCES store_objects(alternate_id) ON DELETE SET NULL"
        )

    with pytest.raises(Exception, match=r"store_objects\.alternate_id"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        target = conn.execute(
            "SELECT referenced.attname FROM pg_constraint c "
            "JOIN pg_attribute referenced ON referenced.attrelid = c.confrelid "
            "AND referenced.attnum = c.confkey[1] "
            "WHERE c.conrelid = 'public.decisions'::regclass AND c.contype = 'f'"
        ).fetchone()[0]
        binding_column = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'store_objects' "
            "AND column_name = 'vault_binding_id'"
        ).fetchone()
    assert target == "alternate_id"
    assert binding_column is None


def test_composite_store_object_fk_rejects_cross_binding_reference(
    scratch_dsn: str,
) -> None:
    _upgrade("head")
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO store_objects "
                "(vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, 'note', '{}'::jsonb)",
                [("binding-a", object_id), ("binding-b", object_id)],
            )
            cur.executemany(
                "INSERT INTO decisions (vault_binding_id, object_id, key, value) "
                "VALUES (%s, %s, 'review', '{}'::jsonb)",
                [("binding-a", object_id), ("binding-b", object_id)],
            )
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO decisions (vault_binding_id, object_id, key, value) "
                    "VALUES ('binding-c', %s, 'review', '{}'::jsonb)",
                    (object_id,),
                )
        assert conn.execute(
            "SELECT count(*) FROM decisions WHERE object_id = %s", (object_id,)
        ).fetchone() == (2,)


@pytest.mark.parametrize("failure_mode", ["zero-parent", "many-parent", "endpoint", "meta"])
def test_binding_backfill_is_parent_provable_or_fails_before_conversion(
    scratch_dsn: str,
    failure_mode: str,
) -> None:
    _upgrade(PRE_BINDING_REKEY_REVISION)
    first = uuid.uuid4()
    second = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        if failure_mode == "zero-parent":
            conn.execute(
                "INSERT INTO store_objects (object_id, kind, payload) "
                "VALUES (%s, 'note', '{}'::jsonb)",
                (first,),
            )
        elif failure_mode == "many-parent":
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO objects (id, uuid, kind, payload, vault_binding_id) "
                    "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                    [(first, first, "binding-a"), (first, first, "binding-b")],
                )
            conn.execute(
                "INSERT INTO store_objects (object_id, kind, payload) "
                "VALUES (%s, 'note', '{}'::jsonb)",
                (first,),
            )
        elif failure_mode == "endpoint":
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO objects (id, uuid, kind, payload, vault_binding_id) "
                    "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                    [(first, first, "binding-a"), (second, second, "binding-b")],
                )
                cur.executemany(
                    "INSERT INTO store_objects (object_id, kind, payload) "
                    "VALUES (%s, 'note', '{}'::jsonb)",
                    [(first,), (second,)],
                )
            conn.execute(
                "INSERT INTO store_relations (src_id, dst_id, rel) VALUES (%s, %s, 'links')",
                (first, second),
            )
        else:
            conn.execute(
                "INSERT INTO vector_index_meta (id, identity_json) VALUES (1, '{}')"
            )

    with pytest.raises(Exception, match=r"MVR-05A3"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        binding_column = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'store_objects' "
            "AND column_name = 'vault_binding_id'"
        ).fetchone()
        pk = conn.execute(
            "SELECT array_agg(a.attname ORDER BY k.ordinality) "
            "FROM pg_constraint c "
            "JOIN unnest(c.conkey) WITH ORDINALITY k(attnum, ordinality) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum "
            "WHERE c.conrelid = 'public.store_objects'::regclass AND c.contype = 'p'"
        ).fetchone()[0]
        quarantine = conn.execute("SELECT to_regclass('public.mvr05a3_quarantine')").fetchone()[0]
    assert binding_column is None
    assert list(pk) == ["object_id"]
    assert quarantine is None


def test_binding_keyed_fks_preserve_actions_and_nullable_receipt_provenance(
    scratch_dsn: str,
) -> None:
    _upgrade(PRE_BINDING_REKEY_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        before = {
            key: (value["update"], value["delete"], value["deferrable"], value["deferred"])
            for key, value in _store_object_fk_inventory(conn).items()
        }
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload, vault_binding_id) "
            "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
            (object_id, object_id, COMPATIBILITY_BINDING_ID),
        )
        conn.execute(
            "INSERT INTO store_objects (object_id, kind, payload) "
            "VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO decisions (object_id, key, value) VALUES (%s, 'review', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO audit (id, object_id, agent, action) VALUES (%s, %s, 'test', 'read')",
            (uuid.uuid4(), object_id),
        )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        after = _store_object_fk_inventory(conn)
        assert {
            key: (value["update"], value["delete"], value["deferrable"], value["deferred"])
            for key, value in after.items()
        } == before
        assert after[("decisions", "object_id")]["delete_set_columns"] == ["object_id"]
        assert after[("audit", "object_id")]["delete_set_columns"] == ["object_id"]
        conn.execute(
            "DELETE FROM store_objects WHERE vault_binding_id = %s AND object_id = %s",
            (COMPATIBILITY_BINDING_ID, object_id),
        )
        decision = conn.execute(
            "SELECT vault_binding_id, object_id FROM decisions"
        ).fetchone()
        audit = conn.execute("SELECT vault_binding_id, object_id FROM audit").fetchone()
    assert decision == (COMPATIBILITY_BINDING_ID, None)
    assert audit == (COMPATIBILITY_BINDING_ID, None)


def test_legacy_objects_fk_migration_fails_loudly_on_unsupported_state(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "CREATE TABLE unreviewed_consumer ("
            "id uuid PRIMARY KEY, object_id uuid REFERENCES objects(id))"
        )

    with pytest.raises(Exception, match="unaccounted objects FK"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        row = conn.execute(
            "SELECT confrelid = 'public.objects'::regclass "
            "FROM pg_constraint WHERE conrelid = 'public.unreviewed_consumer'::regclass "
            "AND contype = 'f'"
        ).fetchone()
    assert row == (
        True,
    ), "failed migration must roll back without partially retargeting constraints"


def test_legacy_objects_fk_migration_rejects_objects_uuid_fk_even_for_known_consumer(
    scratch_dsn: str,
) -> None:
    """A known child table is not safe unless it references ``objects.id``."""
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "ALTER TABLE objects ADD CONSTRAINT objects_uuid_unique_for_3510 UNIQUE (uuid)"
        )
        conn.execute("ALTER TABLE decisions DROP CONSTRAINT decisions_object_id_fkey")
        conn.execute(
            "ALTER TABLE decisions ADD CONSTRAINT decisions_object_id_fkey "
            "FOREIGN KEY (object_id) REFERENCES objects(uuid) ON DELETE SET NULL"
        )

    with pytest.raises(Exception, match=r"objects FK must reference objects\.id"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        target = conn.execute(
            "SELECT referenced.attname FROM pg_constraint c "
            "JOIN pg_attribute referenced ON referenced.attrelid = c.confrelid "
            "AND referenced.attnum = c.confkey[1] "
            "WHERE c.conrelid = 'public.decisions'::regclass "
            "AND c.conname = 'decisions_object_id_fkey'"
        ).fetchone()
    assert target == ("uuid",), "rejection must roll back before retargeting the child FK"


def test_legacy_objects_fk_migration_rejects_duplicate_child_foreign_keys(
    scratch_dsn: str,
) -> None:
    """One reviewed child column must not become two canonical constraints."""
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "ALTER TABLE decisions ADD CONSTRAINT decisions_object_id_duplicate_fk "
            "FOREIGN KEY (object_id) REFERENCES objects(id) ON DELETE SET NULL"
        )

    with pytest.raises(Exception, match="duplicate legacy foreign keys"):
        _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        targets = conn.execute(
            "SELECT confrelid = 'public.objects'::regclass "
            "FROM pg_constraint WHERE conrelid = 'public.decisions'::regclass "
            "AND contype = 'f' ORDER BY conname"
        ).fetchall()
    assert targets == [(True,), (True,)], "rejection must precede every FK retarget"


def test_legacy_objects_fk_migration_backfills_existing_parents(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute("ALTER TABLE objects DROP COLUMN IF EXISTS updated_at")
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) "
            "VALUES (%s, 'note', '{\"title\": \"Legacy\"}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO decisions (object_id, key, value) VALUES (%s, 'review', '{}'::jsonb)",
            (object_id,),
        )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        parent = conn.execute(
            "SELECT kind, source_ref, payload, created_at, updated_at FROM store_objects WHERE object_id = %s",
            (object_id,),
        ).fetchone()
        fk_target = conn.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conrelid = 'public.decisions'::regclass AND contype = 'f'"
        ).fetchone()
    assert parent[0:3] == ("note", None, {"title": "Legacy"})
    assert parent[3] == parent[4]
    assert fk_target == ("store_objects",)


def test_legacy_objects_fk_migration_preserves_row_level_locator_and_payload(
    scratch_dsn: str,
) -> None:
    """Backfill uses source_ref first, then watcher path, without payload loss."""
    _upgrade(PRE_CUTOVER_REVISION)
    path_only_id = uuid.uuid4()
    explicit_source_id = uuid.uuid4()
    null_locator_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        from app.db.db import ensure_schema

        ensure_schema(conn)
        conn.execute("ALTER TABLE objects ADD COLUMN IF NOT EXISTS source_ref text")
        conn.execute("ALTER TABLE objects ADD COLUMN IF NOT EXISTS path text")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO objects (id, uuid, kind, payload, source_ref, path) "
                "VALUES (%s, %s, %s, %s::jsonb, %s, %s)",
                [
                    (
                        path_only_id,
                        path_only_id,
                        "note",
                        '{"title":"Watcher","nested":{"kept":true}}',
                        None,
                        "/vault/retained-watcher-note.md",
                    ),
                    (
                        explicit_source_id,
                        explicit_source_id,
                        "artifact",
                        '{"title":"Explicit"}',
                        "/source/explicit.md",
                        "/vault/different.md",
                    ),
                    (
                        null_locator_id,
                        null_locator_id,
                        "note",
                        "{}",
                        None,
                        None,
                    ),
                ],
            )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        path_only = conn.execute(
            "SELECT kind, source_ref, payload FROM store_objects WHERE object_id = %s",
            (path_only_id,),
        ).fetchone()
        explicit = conn.execute(
            "SELECT kind, source_ref, payload FROM store_objects WHERE object_id = %s",
            (explicit_source_id,),
        ).fetchone()
        null_locator = conn.execute(
            "SELECT source_ref FROM store_objects WHERE object_id = %s",
            (null_locator_id,),
        ).fetchone()

    assert path_only == (
        "note",
        "/vault/retained-watcher-note.md",
        {"title": "Watcher", "nested": {"kept": True}},
    )
    assert explicit == ("artifact", "/source/explicit.md", {"title": "Explicit"})
    assert null_locator == (None,)


def test_unchanged_post_migration_sync_heals_incomplete_canonical_locator(
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Presence alone cannot cement a NULL canonical watcher locator."""
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "retained-watcher-note.md"
    frontmatter = {"uuid": str(object_id), "title": "Retained watcher note"}
    body = "unchanged body\n"
    note.write_text(
        f"---\nuuid: {object_id}\ntitle: Retained watcher note\n---\n\n{body}",
        encoding="utf-8",
    )

    from app.services import vault_sync

    with psycopg.connect(scratch_dsn) as conn:
        from app.db.db import ensure_schema

        ensure_schema(conn)
        conn.execute("ALTER TABLE objects ADD COLUMN IF NOT EXISTS source_ref text")
        conn.execute("ALTER TABLE objects ADD COLUMN IF NOT EXISTS path text")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS file_state ("
            "path text PRIMARY KEY, uuid text, fm_hash text, body_hash text, "
            "mtime timestamptz, last_seen timestamptz DEFAULT now())"
        )
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload, source_ref, path) "
            "VALUES (%s, %s, 'note', '{}'::jsonb, NULL, %s)",
            (object_id, object_id, str(note.resolve())),
        )
        conn.execute(
            "INSERT INTO file_state (path, uuid, fm_hash, body_hash, mtime, last_seen) "
            "VALUES (%s, %s, %s, %s, now(), now())",
            (
                str(note.resolve()),
                str(object_id),
                vault_sync._hash_dict(frontmatter),
                vault_sync._hash_text(body),
            ),
        )

    _upgrade("head")
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute(
            "SELECT source_ref FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone() == (str(note.resolve()),)
        conn.execute(
            "UPDATE store_objects SET source_ref = NULL "
            "WHERE vault_binding_id = %s AND object_id = %s",
            (COMPATIBILITY_BINDING_ID, object_id),
        )

    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    monkeypatch.setattr(vault_sync, "active_edit", lambda path: False)
    result = vault_sync.sync_markdown(str(note))
    assert result["status"] == "ok"

    with psycopg.connect(scratch_dsn) as conn:
        healed = conn.execute(
            "SELECT source_ref, payload->>'content' " "FROM store_objects WHERE object_id = %s",
            (object_id,),
        ).fetchone()
        metadata_events = conn.execute(
            "SELECT count(*) FROM outbox WHERE topic = 'ingest.object.metadata'"
        ).fetchone()
    assert healed == (str(note.resolve()), body)
    assert metadata_events == (1,)


def test_active_decision_writer_preflights_before_receipt_on_pre_cutover_schema(
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production writer rejects pre-#3510 schema before its commit point."""
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects (object_id, kind, payload) "
            "VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("STORE_BACKEND", "pg")

    import app.receipts.decision_receipt_log as receipt_log
    from app.services.decisions import (
        DecisionsSchemaMigrationRequired,
        _resolved_backend,
        insert_decision,
    )

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    _resolved_backend.cache_clear()

    with pytest.raises(
        DecisionsSchemaMigrationRequired,
        match=r"#3510.*alembic upgrade head",
    ):
        insert_decision(
            str(object_id),
            "classification",
            {"type": "note"},
            trace_id="pre-cutover",
        )

    assert receipt_log.iter_decision_receipts(vault) == []
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone() == (0,)


def test_legacy_pg_decisions_writer_rejects_set_null_objects_parent_before_row(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deprecated adapter must not accept the pre-#3510 SET NULL FK."""
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )

    from app.stores.postgres import PgDecisions

    monkeypatch.setenv("DATABASE_URL", scratch_dsn)
    with pytest.raises(RuntimeError, match=r"alembic upgrade head.*Schema shape is stale"):
        PgDecisions().put(
            object_id=str(object_id),
            agent="test",
            kind="classification",
            key="type",
            value={"type": "note"},
        )

    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone() == (0,)


def test_decisions_projection_rebuild_rejects_legacy_parent_before_truncate(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Projection replay must fail with the migration hint before destructive work."""
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO decisions (object_id, key, value) VALUES (%s, 'keep', '{}'::jsonb)",
            (object_id,),
        )

    import app.db.db as db
    from app.jobs import decisions_projection

    monkeypatch.setenv("DATABASE_URL", scratch_dsn)
    monkeypatch.setattr(db, "_SCHEMA_INITIALIZED", True)
    monkeypatch.setattr(decisions_projection, "iter_decision_receipts", lambda _root: [])

    with pytest.raises(RuntimeError, match=r"alembic upgrade head.*Schema shape is stale"):
        decisions_projection.rebuild_decisions_projection()

    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT key FROM decisions").fetchall() == [("keep",)]


def test_decisions_producers_reject_additional_legacy_foreign_key(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonical FK plus any extra legacy FK is not migration-complete.

    Since MVR-05A1 (#4560) rekeyed `objects` to `(vault_binding_id, id)`, `id`
    alone is no longer a unique key, so this FK can no longer be created against
    the shipped schema at all — and the rekey itself refuses to run on a database
    that still has one, so the state simulated here is now unreachable through
    the migration path. The single-column unique index below exists only to make
    the fixture constructible, keeping the decisions-producer staleness guard
    (the actual subject of this test) covered as defence in depth.
    """
    _upgrade("head")
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "CREATE UNIQUE INDEX objects_id_legacy_fixture_idx ON public.objects(id)"
        )
        conn.execute(
            "ALTER TABLE decisions ADD CONSTRAINT decisions_object_id_legacy_extra_fk "
            "FOREIGN KEY (object_id) REFERENCES objects(id) ON DELETE SET NULL"
        )

    from app.stores.postgres import PgDecisions

    monkeypatch.setenv("DATABASE_URL", scratch_dsn)
    with pytest.raises(RuntimeError, match=r"alembic upgrade head.*Schema shape is stale"):
        PgDecisions().put(
            object_id=str(uuid.uuid4()),
            agent="test",
            kind="classification",
            key="type",
            value={"type": "note"},
        )

    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM decisions").fetchone() == (0,)


def test_deferred_then_unchanged_sync_materializes_canonical_parent(
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An active-edit baseline cannot bypass the watcher object producer."""
    _upgrade("head")
    object_id = uuid.uuid4()
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "deferred-note.md"
    note.write_text(
        f"---\nuuid: {object_id}\ntitle: Deferred note\n---\n\nunchanged body\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("STORE_BACKEND", "pg")

    from app.services import vault_sync

    active_states = iter((True, False))
    monkeypatch.setattr(vault_sync, "active_edit", lambda path: next(active_states))

    first = vault_sync.sync_markdown(str(note))
    assert first["status"] == "deferred"
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM file_state").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM objects").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM store_objects").fetchone() == (0,)

    second = vault_sync.sync_markdown(str(note))
    assert second["status"] == "ok"
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM objects WHERE id = %s", (object_id,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM store_objects WHERE object_id = %s", (object_id,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM outbox WHERE topic = 'ingest.object.created'"
        ).fetchone() == (1,)

    import app.receipts.decision_receipt_log as receipt_log
    from app.services.decisions import _resolved_backend, insert_decision

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD,
        "assert_writes_allowed",
        lambda action: None,
    )
    _resolved_backend.cache_clear()
    insert_decision(
        str(object_id),
        "classification",
        {"type": "note"},
        trace_id="deferred-then-unchanged",
    )
    with psycopg.connect(scratch_dsn) as conn:
        assert conn.execute(
            "SELECT count(*) FROM decisions WHERE object_id = %s", (object_id,)
        ).fetchone() == (1,)


def test_watcher_keeps_distinct_legacy_id_as_canonical_parent_through_lifecycle(
    scratch_dsn: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retained ``objects.id != objects.uuid`` never creates a split parent."""
    _upgrade(PRE_CUTOVER_REVISION)
    canonical_id = uuid.uuid4()
    watcher_uuid = uuid.uuid4()
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "retained-id.md"
    note.write_text(
        f"---\nuuid: {watcher_uuid}\ntitle: Retained id\n---\n\nwatcher body\n",
        encoding="utf-8",
    )
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute("ALTER TABLE objects ADD COLUMN IF NOT EXISTS path text")
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload, path) "
            "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
            (canonical_id, watcher_uuid, str(note.resolve())),
        )

    _upgrade("head")
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    monkeypatch.setenv("STORE_BACKEND", "pg")
    from app.services import vault_sync

    monkeypatch.setattr(vault_sync, "active_edit", lambda path: False)
    synced = vault_sync.sync_markdown(str(note))
    assert synced["id"] == str(canonical_id)

    import app.receipts.decision_receipt_log as receipt_log
    from app.services.decisions import _resolved_backend, insert_decision

    monkeypatch.setattr(
        receipt_log.DEFAULT_WRITE_GUARD, "assert_writes_allowed", lambda action: None
    )
    _resolved_backend.cache_clear()
    insert_decision(str(canonical_id), "classification", {"type": "note"}, trace_id="retained-id")

    renamed = vault / "renamed-retained-id.md"
    note.rename(renamed)
    assert vault_sync.handle_rename(str(note), str(renamed))["updated"] is True
    renamed.unlink()
    assert vault_sync.delete_note(str(renamed), uuid_value=str(watcher_uuid)) is True

    with psycopg.connect(scratch_dsn) as conn:
        canonical = conn.execute(
            "SELECT source_ref FROM store_objects WHERE object_id = %s", (canonical_id,)
        ).fetchone()
        split_parent = conn.execute(
            "SELECT count(*) FROM store_objects WHERE object_id = %s", (watcher_uuid,)
        ).fetchone()
        decision = conn.execute(
            "SELECT object_id FROM decisions WHERE object_id = %s", (canonical_id,)
        ).fetchone()
        mirror = conn.execute(
            "SELECT id, uuid FROM objects WHERE uuid = %s", (watcher_uuid,)
        ).fetchone()
    assert canonical == (None,)
    assert split_parent == (0,)
    assert decision == (canonical_id,)
    assert mirror == (canonical_id, watcher_uuid)


def test_runtime_identity_resolver_preserves_distinct_legacy_id(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vault-alpha and fallback tombstones resolve the migrated canonical key."""
    _upgrade(PRE_CUTOVER_REVISION)
    canonical_id = uuid.uuid4()
    vault_uuid = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (canonical_id, vault_uuid),
        )
    _upgrade("head")

    monkeypatch.setenv("DATABASE_URL", scratch_dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    from app.objects import resolve_canonical_object_id

    assert resolve_canonical_object_id(str(vault_uuid)) == str(canonical_id)


def test_runtime_identity_resolver_rejects_post_cutover_cross_key_collision(
    scratch_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later canonical write must not turn a retained UUID into a silent alias."""
    _upgrade(PRE_CUTOVER_REVISION)
    canonical_id = uuid.uuid4()
    vault_uuid = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (canonical_id, vault_uuid),
        )
    _upgrade("head")

    monkeypatch.setenv("DATABASE_URL", scratch_dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    from app.objects import resolve_canonical_object_id

    assert resolve_canonical_object_id(str(vault_uuid)) == str(canonical_id)

    # Identity is mutable across processes. A resolver must re-check the live
    # cross-key collision invariant after an earlier successful lookup.
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO store_objects (vault_binding_id, object_id, kind, payload) "
            "VALUES (%s, %s, 'note', '{}'::jsonb)",
            (COMPATIBILITY_BINDING_ID, vault_uuid),
        )

    with pytest.raises(RuntimeError, match="cross-key identity collision"):
        resolve_canonical_object_id(str(vault_uuid))


def test_migration_rejects_ambiguous_retained_uuid_mapping(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    duplicate_uuid = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (uuid.uuid4(), duplicate_uuid),
        )
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (uuid.uuid4(), duplicate_uuid),
        )

    with pytest.raises(Exception, match="duplicate non-null objects.uuid"):
        _upgrade("head")


def test_migration_rejects_cross_key_canonical_identity_collision(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    retained_id = uuid.uuid4()
    vault_uuid = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (retained_id, vault_uuid),
        )
        conn.execute(
            "INSERT INTO store_objects (object_id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)",
            (vault_uuid,),
        )

    with pytest.raises(Exception, match="retained vault UUID already names a different canonical"):
        _upgrade("head")


def test_migration_rejects_legacy_alias_that_collides_with_another_id(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
    other_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, NULL, 'note', '{}'::jsonb)",
            (other_id,),
        )
        conn.execute(
            "INSERT INTO objects (id, uuid, kind, payload) VALUES (%s, %s, 'note', '{}'::jsonb)",
            (uuid.uuid4(), other_id),
        )

    with pytest.raises(Exception, match="retained vault UUID collides with another objects.id"):
        _upgrade("head")


def test_migration_locks_both_identity_producer_tables() -> None:
    migration = (
        REPO_ROOT
        / "app"
        / "alembic"
        / "versions"
        / "7e4f2a1c9d30_migrate_legacy_objects_fk_consumers.py"
    ).read_text(encoding="utf-8")

    assert "LOCK TABLE public.objects, public.store_objects IN SHARE ROW EXCLUSIVE MODE" in migration


def test_binding_rekey_snapshots_fk_inventory_only_after_full_lock() -> None:
    migration = (
        REPO_ROOT
        / "app"
        / "alembic"
        / "versions"
        / "e6c4a2b8d1f3_mvr05a3_store_object_binding_keys.py"
    ).read_text(encoding="utf-8")

    lock = migration.index("LOCK TABLE\n                public.objects")
    snapshot = migration.index("CREATE TEMP TABLE mvr05a3_fk_snapshot ON COMMIT DROP AS")
    inventory_check = migration.index("MVR-05A3 unaccounted store_objects FK consumer")
    assert lock < snapshot < inventory_check


def test_runtime_bootstrap_preserves_objects_primary_key_after_cutover(scratch_dsn: str) -> None:
    """Vault-sync bootstrap must not rebuild the legacy PK after FKs move away."""
    from app.db import db as db_module

    _upgrade("head")
    with psycopg.connect(scratch_dsn) as conn:
        before = conn.execute(
            "SELECT oid FROM pg_constraint "
            "WHERE conrelid = 'public.objects'::regclass AND contype = 'p'"
        ).fetchone()
        assert before is not None

        db_module.ensure_schema(conn)
        db_module.ensure_schema(conn)

        after = conn.execute(
            "SELECT oid FROM pg_constraint "
            "WHERE conrelid = 'public.objects'::regclass AND contype = 'p'"
        ).fetchone()

    assert after == before


def test_migration_retargets_every_reviewed_consumer_with_live_rows(scratch_dsn: str) -> None:
    """Seed a row through every reviewed objects(id) FK consumer, then cut over.

    Covers the structural cases the generic retarget loop must handle beyond the
    decisions-only seeds used elsewhere: two FK columns on one table
    (relations.src_id/dst_id), the composite-membership shape, and the CASCADE
    vs SET NULL delete-rule preservation across all eight reviewed pairs.
    """
    _upgrade(PRE_CUTOVER_REVISION)
    object_id = uuid.uuid4()
    other_id = uuid.uuid4()
    set_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        conn.execute(
            "INSERT INTO objects (id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO objects (id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)",
            (other_id,),
        )
        conn.execute("INSERT INTO sets (id, name) VALUES (%s, 'inventory-set')", (set_id,))
        conn.execute(
            "INSERT INTO chunks (id, object_id, idx, offset_start, offset_end, text) "
            "VALUES (%s, %s, 0, 0, 1, 'x')",
            (chunk_id, object_id),
        )
        conn.execute(
            "INSERT INTO embeddings (id, object_id, chunk_id, dim) VALUES (%s, %s, %s, 3)",
            (uuid.uuid4(), object_id, chunk_id),
        )
        conn.execute(
            "INSERT INTO relations (id, src_id, dst_id, type) VALUES (%s, %s, %s, 'refs')",
            (uuid.uuid4(), object_id, other_id),
        )
        conn.execute(
            "INSERT INTO membership (id, set_id, object_id) VALUES (%s, %s, %s)",
            (uuid.uuid4(), set_id, object_id),
        )
        conn.execute(
            "INSERT INTO decisions (object_id, key, value) VALUES (%s, 'review', '{}'::jsonb)",
            (object_id,),
        )
        conn.execute(
            "INSERT INTO audit (id, object_id, agent, action) VALUES (%s, %s, 'test', 'seed')",
            (uuid.uuid4(), object_id),
        )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        rows = conn.execute(
            "SELECT conrelid::regclass::text, a.attname, confrelid::regclass::text, c.confdeltype "
            "FROM pg_constraint c "
            "JOIN unnest(c.conkey) WITH ORDINALITY child_key(attnum, ordinality) ON true "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid "
            "AND a.attnum = child_key.attnum AND a.attname <> 'vault_binding_id' "
            "WHERE c.contype = 'f' "
            "  AND c.confrelid IN ('public.store_objects'::regclass, 'public.objects'::regclass) "
            "ORDER BY 1, 2"
        ).fetchall()
        counts = {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("chunks", "embeddings", "relations", "membership", "decisions", "audit")
        }
    retargeted = {(table, column): (target, rule) for table, column, target, rule in rows}
    assert retargeted[("chunks", "object_id")] == ("store_objects", "c")
    assert retargeted[("embeddings", "object_id")] == ("store_objects", "c")
    assert retargeted[("relations", "src_id")] == ("store_objects", "c")
    assert retargeted[("relations", "dst_id")] == ("store_objects", "c")
    assert retargeted[("membership", "object_id")] == ("store_objects", "c")
    assert retargeted[("decisions", "object_id")] == ("store_objects", "n")
    assert retargeted[("audit", "object_id")] == ("store_objects", "n")
    assert not any(target == "objects" for target, _ in retargeted.values())
    assert all(count == 1 for count in counts.values())


def test_binding_backfill_counts_distinct_store_relation_assignments(
    scratch_dsn: str,
) -> None:
    """Several relation values for one endpoint pair are one binding proof."""
    _upgrade(PRE_BINDING_REKEY_REVISION)
    src_id = uuid.uuid4()
    dst_id = uuid.uuid4()
    with psycopg.connect(scratch_dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO objects "
                "(id, uuid, kind, payload, vault_binding_id) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                [
                    (src_id, src_id, COMPATIBILITY_BINDING_ID),
                    (dst_id, dst_id, COMPATIBILITY_BINDING_ID),
                ],
            )
            cur.executemany(
                "INSERT INTO store_objects (object_id, kind, payload) "
                "VALUES (%s, 'note', '{}'::jsonb)",
                [(src_id,), (dst_id,)],
            )
            cur.executemany(
                "INSERT INTO store_relations (src_id, dst_id, rel) "
                "VALUES (%s, %s, %s)",
                [(src_id, dst_id, "links"), (src_id, dst_id, "quotes")],
            )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        rows = conn.execute(
            "SELECT rel, vault_binding_id FROM store_relations "
            "WHERE src_id = %s AND dst_id = %s ORDER BY rel",
            (src_id, dst_id),
        ).fetchall()
    assert rows == [
        ("links", COMPATIBILITY_BINDING_ID),
        ("quotes", COMPATIBILITY_BINDING_ID),
    ]


def test_binding_backfill_counts_distinct_parent_assignments_not_child_rows(
    scratch_dsn: str,
) -> None:
    """Repeated children of one parent are not mistaken for many parents."""
    _upgrade(PRE_BINDING_REKEY_REVISION)
    object_id = uuid.uuid4()
    other_id = uuid.uuid4()
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]
    with psycopg.connect(scratch_dsn) as conn:
        _use_retained_historical_membership_identity(conn)
        with conn.cursor() as cur:
            membership_set_fk = cur.execute(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'public.membership'::regclass AND contype = 'f' "
                "AND conkey = ARRAY[(SELECT attnum FROM pg_attribute "
                "WHERE attrelid = 'public.membership'::regclass "
                "AND attname = 'set_id')]::smallint[]"
            ).fetchone()[0]
            cur.execute(
                f'ALTER TABLE membership DROP CONSTRAINT "{membership_set_fk}"'
            )
            cur.execute(
                "ALTER TABLE membership ADD CONSTRAINT membership_set_id_fkey "
                "FOREIGN KEY (set_id) REFERENCES store_objects(object_id) ON DELETE CASCADE"
            )
            cur.executemany(
                "INSERT INTO objects "
                "(id, uuid, kind, payload, vault_binding_id) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, %s)",
                [
                    (object_id, object_id, COMPATIBILITY_BINDING_ID),
                    (other_id, other_id, COMPATIBILITY_BINDING_ID),
                ],
            )
            cur.executemany(
                "INSERT INTO store_objects (object_id, kind, payload) "
                "VALUES (%s, 'note', '{}'::jsonb)",
                [(object_id,), (other_id,)],
            )
            cur.executemany(
                "INSERT INTO chunks "
                "(id, object_id, idx, offset_start, offset_end, text) "
                "VALUES (%s, %s, %s, 0, 1, 'x')",
                [
                    (chunk_ids[0], object_id, 0),
                    (chunk_ids[1], object_id, 1),
                ],
            )
            cur.executemany(
                "INSERT INTO embeddings (id, object_id, chunk_id, dim) "
                "VALUES (%s, %s, %s, 3)",
                [
                    (uuid.uuid4(), object_id, chunk_ids[0]),
                    (uuid.uuid4(), object_id, chunk_ids[1]),
                ],
            )
            cur.executemany(
                "INSERT INTO relations (id, src_id, dst_id, type) "
                "VALUES (%s, %s, %s, %s)",
                [
                    (uuid.uuid4(), object_id, other_id, "links"),
                    (uuid.uuid4(), object_id, other_id, "quotes"),
                ],
            )
            cur.executemany(
                "INSERT INTO membership (set_id, object_id) VALUES (%s, %s)",
                [
                    (other_id, object_id),
                    (object_id, object_id),
                ],
            )
            cur.executemany(
                "INSERT INTO decisions (object_id, key, value) "
                "VALUES (%s, %s, '{}'::jsonb)",
                [(object_id, "first"), (object_id, "second")],
            )
            cur.executemany(
                "INSERT INTO audit (id, object_id, agent, action) "
                "VALUES (%s, %s, 'test', %s)",
                [
                    (uuid.uuid4(), object_id, "first"),
                    (uuid.uuid4(), object_id, "second"),
                ],
            )

    _upgrade("head")

    with psycopg.connect(scratch_dsn) as conn:
        for table in (
            "chunks",
            "embeddings",
            "relations",
            "membership",
            "decisions",
            "audit",
        ):
            rows = conn.execute(
                f"SELECT count(*), count(DISTINCT vault_binding_id) FROM {table}"
            ).fetchone()
            assert rows == (2, 1), table
        bindings = conn.execute(
            "SELECT DISTINCT vault_binding_id FROM chunks"
        ).fetchall()
    assert bindings == [(COMPATIBILITY_BINDING_ID,)]
