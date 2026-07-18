"""Fail-loud migration coverage for #3510."""

from __future__ import annotations

import uuid
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.pg
REPO_ROOT = Path(__file__).resolve().parents[2]
PRE_CUTOVER_REVISION = "4d1e0c9a3329"


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


def test_legacy_objects_fk_migration_backfills_existing_parents(scratch_dsn: str) -> None:
    _upgrade(PRE_CUTOVER_REVISION)
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
            "SELECT kind, source_ref, payload FROM store_objects WHERE object_id = %s",
            (object_id,),
        ).fetchone()
        fk_target = conn.execute(
            "SELECT confrelid::regclass::text FROM pg_constraint "
            "WHERE conrelid = 'public.decisions'::regclass AND contype = 'f'"
        ).fetchone()
    assert parent == ("note", None, {"title": "Legacy"})
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
            "UPDATE store_objects SET source_ref = NULL WHERE object_id = %s",
            (object_id,),
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
    """A canonical FK plus any extra legacy FK is not migration-complete."""
    _upgrade("head")
    with psycopg.connect(scratch_dsn) as conn:
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
