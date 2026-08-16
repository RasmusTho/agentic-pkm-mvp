from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from app.episodes import vault_activity_stream
from app.events.models import new_event
from app.events.types import INGEST_VAULT_CHANGED
from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.services.outbox import (
    count_deferred_outbox_rows,
    derive_binding_scoped_idempotency_key,
    derive_idempotency_key,
    poll_outbox_one,
    write_outbox_event,
)

pytestmark = pytest.mark.pg


@contextmanager
def _isolated_outbox(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn
    from app.services.outbox import bootstrap

    base_dsn = resolve_dsn()
    schema = f"mvr05a7_{uuid4().hex}"
    with psycopg.connect(base_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn = f"{base_dsn}?options=-csearch_path%3D{schema}"
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("DB_DSN", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            bootstrap(conn)
            yield conn
    finally:
        with psycopg.connect(base_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def _event(source_id: str):
    return new_event(event_type="mvr.test", payload={"source_id": source_id}, source="test")


def test_binding_keyed_producer_suppresses_against_pending_and_delivered_legacy_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_outbox(monkeypatch) as conn:
        for delivered in (False, True):
            source_id = f"legacy-{delivered}"
            legacy_key = derive_idempotency_key("mvr.test", source_id, "same")
            conn.execute(
                "INSERT INTO outbox "
                "(id, legacy_key, vault_binding_id, topic, payload, delivered_at) "
                "VALUES (%s, %s, %s, %s, '{}'::jsonb, "
                "CASE WHEN %s THEN now() ELSE NULL END)",
                (
                    legacy_key,
                    legacy_key,
                    COMPATIBILITY_BINDING_ID,
                    "mvr.test",
                    delivered,
                ),
            )

            assert (
                write_outbox_event(
                    _event(source_id),
                    conn,
                    idempotency_key=legacy_key,
                    vault_binding_id=COMPATIBILITY_BINDING_ID,
                )
                == ""
            )
            count = conn.execute(
                "SELECT count(*) FROM outbox WHERE legacy_key = %s", (legacy_key,)
            ).fetchone()
            assert count == (1,)

        # Partially upgraded rows with no provable binding are collision
        # evidence. Any binding must fail safe against their legacy key.
        legacy_key = derive_idempotency_key("mvr.test", "partial", "same")
        conn.execute(
            "INSERT INTO outbox "
            "(id, legacy_key, vault_binding_id, topic, payload) "
            "VALUES (%s, %s, %s, %s, '{}'::jsonb)",
            (uuid4(), legacy_key, OUTBOX_QUARANTINE_BINDING_ID, "mvr.test"),
        )
        assert (
            write_outbox_event(
                _event("partial"),
                conn,
                idempotency_key=legacy_key,
                vault_binding_id="binding-a",
            )
            == ""
        )
        count = conn.execute(
            "SELECT count(*) FROM outbox WHERE legacy_key = %s", (legacy_key,)
        ).fetchone()
        assert count == (1,)


def test_distinct_bindings_do_not_dedup_against_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_outbox(monkeypatch) as conn:
        legacy_key = derive_idempotency_key("mvr.test", "shared-logical-event", "same")
        conn.execute(
            "INSERT INTO outbox "
            "(id, legacy_key, vault_binding_id, topic, payload) "
            "VALUES (%s, %s, %s, %s, '{}'::jsonb)",
            (legacy_key, legacy_key, COMPATIBILITY_BINDING_ID, "mvr.test"),
        )

        scoped_id = write_outbox_event(
            _event("shared-logical-event"),
            conn,
            idempotency_key=legacy_key,
            vault_binding_id="binding-b",
        )
        assert scoped_id == derive_binding_scoped_idempotency_key(
            "mvr.test", "binding-b", legacy_key
        )
        assert (
            write_outbox_event(
                _event("shared-logical-event"),
                conn,
                idempotency_key=legacy_key,
                vault_binding_id="binding-b",
            )
            == ""
        )
        rows = conn.execute(
            "SELECT vault_binding_id, legacy_key FROM outbox ORDER BY vault_binding_id"
        ).fetchall()
        assert rows == [
            ("binding-b", UUID(legacy_key)),
            (COMPATIBILITY_BINDING_ID, UUID(legacy_key)),
        ]


def test_quarantined_pending_row_cannot_dispatch_or_block_later_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_outbox(monkeypatch) as conn:
        quarantined_id = uuid4()
        conn.execute(
            "INSERT INTO outbox "
            "(id, legacy_key, vault_binding_id, topic, payload, created_at) "
            "VALUES (%s, %s, %s, %s, '{}'::jsonb, '2000-01-01T00:00:00Z')",
            (
                quarantined_id,
                uuid4(),
                OUTBOX_QUARANTINE_BINDING_ID,
                "mvr.quarantined",
            ),
        )
        legacy_key = derive_idempotency_key("mvr.dispatchable", "later", "same")
        dispatchable_id = write_outbox_event(
            _event("later"),
            conn,
            idempotency_key=legacy_key,
            vault_binding_id="binding-a",
        )

        handled: list[tuple[str, dict]] = []
        message = poll_outbox_one(
            conn,
            handler=lambda topic, payload: handled.append((topic, payload)),
        )

        assert message is not None
        assert message["id"] == dispatchable_id
        assert message["vault_binding_id"] == "binding-a"
        assert handled == [("mvr.test", {"source_id": "later"})]
        quarantined = conn.execute(
            "SELECT delivered_at FROM outbox WHERE id = %s", (quarantined_id,)
        ).fetchone()
        assert quarantined == (None,)


def test_stale_binding_row_remains_pending_while_later_global_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stamp = {
        "vault_binding_id": "binding-a",
        "binding_authority": "allow",
        "binding_authorization_epoch": "epoch-current",
        "binding_revision": 8,
        "vault_root": "/vault/current",
    }
    stale = new_event(
        event_type="mvr.test",
        payload={"source_id": "stale"},
        source="test",
        meta={**stamp, "binding_revision": 7},
    )
    global_event = new_event(
        event_type="mvr.test", payload={"source_id": "global"}, source="test"
    )
    with _isolated_outbox(monkeypatch) as conn:
        stale_id = uuid4()
        foreign_id = uuid4()
        global_id = uuid4()
        conn.execute(
            "INSERT INTO outbox (id, legacy_key, vault_binding_id, topic, payload, created_at) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, '2000-01-01T00:00:00Z'), "
            "(%s, %s, %s, %s, %s::jsonb, '2000-01-01T12:00:00Z'), "
            "(%s, %s, %s, %s, %s::jsonb, '2000-01-02T00:00:00Z')",
            (
                stale_id,
                uuid4(),
                "binding-a",
                "mvr.test",
                stale.model_dump_json(),
                foreign_id,
                uuid4(),
                "binding-b",
                "mvr.test",
                stale.model_copy(
                    update={
                        "meta": {
                            **dict(stale.meta or {}),
                            "vault_binding_id": "binding-b",
                        }
                    }
                ).model_dump_json(),
                global_id,
                uuid4(),
                OUTBOX_GLOBAL_BINDING_ID,
                "mvr.test",
                global_event.model_dump_json(),
            ),
        )

        message = poll_outbox_one(
            conn,
            eligible_binding_ids=(
                "binding-a",
                COMPATIBILITY_BINDING_ID,
                OUTBOX_GLOBAL_BINDING_ID,
            ),
            required_binding_stamp=stamp,
        )
        assert message is not None
        assert message["id"] == str(global_id)
        assert count_deferred_outbox_rows(
            conn=conn, required_binding_stamp=stamp
        ) == 2
        assert conn.execute(
            "SELECT delivered_at FROM outbox WHERE id = ANY(%s)",
            ([stale_id, foreign_id],),
        ).fetchall() == [(None,), (None,)]


def test_quarantined_vault_activity_row_cannot_reach_episode_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _isolated_outbox(monkeypatch) as conn:
        quarantined_id = uuid4()
        conn.execute(
            "INSERT INTO outbox "
            "(id, legacy_key, vault_binding_id, topic, payload, created_at) "
            "VALUES (%s, %s, %s, %s, '{}'::jsonb, '2000-01-01T00:00:00Z')",
            (
                quarantined_id,
                uuid4(),
                OUTBOX_QUARANTINE_BINDING_ID,
                INGEST_VAULT_CHANGED,
            ),
        )
        valid_event = new_event(
            event_type=INGEST_VAULT_CHANGED,
            payload={"relative_path": "later.md", "mtime": 1.0},
            source="test",
        )
        legacy_key = derive_idempotency_key(INGEST_VAULT_CHANGED, "later.md", "same")
        dispatchable_id = write_outbox_event(
            valid_event,
            conn,
            idempotency_key=legacy_key,
            vault_binding_id="binding-a",
        )

        @contextmanager
        def _existing_connection():
            yield conn

        monkeypatch.setattr(vault_activity_stream, "conn_rw", _existing_connection)
        monkeypatch.setattr(
            vault_activity_stream,
            "get_vault_activity_cursor",
            lambda _consumer_id: (None, None),
        )

        rows = vault_activity_stream.read_vault_activity_for_consumer(
            "quarantine-proof", limit=1
        )

        assert [row.id for row in rows] == [dispatchable_id]
        assert all(row.id != str(quarantined_id) for row in rows)
