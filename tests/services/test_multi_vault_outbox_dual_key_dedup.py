from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from app.events.models import new_event
from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.services.outbox import (
    derive_binding_scoped_idempotency_key,
    derive_idempotency_key,
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
