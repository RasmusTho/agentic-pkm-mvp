"""MVR-05D: vault-bound outbox idempotency is keyed by the stable binding.

Runs against real PostgreSQL: the dedup is the choke point's atomic
``INSERT ... WHERE NOT EXISTS ... ON CONFLICT (id) DO NOTHING`` and cannot be
proved against a fake connection.
"""

from __future__ import annotations

from contextlib import contextmanager
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from app.events.models import new_event
from app.services.outbox import (
    derive_binding_scoped_idempotency_key,
    derive_idempotency_key,
    insert_object_and_outbox,
    payload_fingerprint,
    poll_outbox_one,
    write_outbox_event,
)
from app.services.outbox_producers import OUTBOX_ENVELOPE_VERSION

pytestmark = pytest.mark.pg


@contextmanager
def _isolated_outbox(monkeypatch: pytest.MonkeyPatch):
    from app.db.dsn import resolve_dsn
    from app.services.outbox import bootstrap

    base_dsn = resolve_dsn()
    schema = f"mvr05d_{uuid4().hex}"
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


_TOPIC = "mvr05d.vault_bound.test"


def test_duplicate_identity_events_are_deduplicated_per_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same logical identity: independent rows per binding, one row per binding retry."""

    payload = {"uuid": "shared-note", "relative_path": "shared.md"}
    with _isolated_outbox(monkeypatch) as conn:
        inserted: dict[str, str] = {}
        for binding in ("binding-a", "binding-b"):
            inserted[binding] = insert_object_and_outbox(
                payload,
                _TOPIC,
                conn=conn,
                observation="mtime-1",
                vault_binding_id=binding,
                producer="ingest.vault_sync",
            )
        # Both bindings persisted the duplicate logical identity independently.
        assert all(inserted.values())
        assert inserted["binding-a"] != inserted["binding-b"]

        rows = conn.execute(
            "SELECT id, legacy_key, vault_binding_id, payload FROM outbox ORDER BY vault_binding_id"
        ).fetchall()
        assert [row[2] for row in rows] == ["binding-a", "binding-b"]
        legacy_keys = {row[1] for row in rows}
        assert len(legacy_keys) == 1, "the unchanged producer key is shared across bindings"
        legacy_key = str(legacy_keys.pop())
        for row_id, _legacy, binding, stored in rows:
            # The row id folds the stable binding into the unchanged legacy key.
            assert str(row_id) == derive_binding_scoped_idempotency_key(_TOPIC, binding, legacy_key)
            meta = stored["meta"]
            assert meta["outbox_envelope"] == OUTBOX_ENVELOPE_VERSION
            assert meta["routing_class"] == "vault_bound"
            assert meta["vault_binding_id"] == binding
            assert meta["outbox_producer"] == "ingest.vault_sync"
            assert meta["idempotency"] == {
                "legacy_key": legacy_key,
                "binding_scoped_key": str(row_id),
            }

        # A same-binding retry of the same observation deduplicates in each binding.
        for binding in ("binding-a", "binding-b"):
            assert (
                insert_object_and_outbox(
                    payload,
                    _TOPIC,
                    conn=conn,
                    observation="mtime-1",
                    vault_binding_id=binding,
                    producer="ingest.vault_sync",
                )
                == ""
            )
        # Delivered history still suppresses a retry in that binding only.
        conn.execute(
            "UPDATE outbox SET delivered_at = now() WHERE vault_binding_id = 'binding-a'"
        )
        retry = new_event(event_type=_TOPIC, payload=dict(payload), source="test")
        assert write_outbox_event(
            retry, conn, idempotency_key=legacy_key, vault_binding_id="binding-a",
            producer="ingest.vault_sync",
        ) == ""
        # A new observation is a new logical emission, still per binding.
        assert insert_object_and_outbox(
            payload,
            _TOPIC,
            conn=conn,
            observation="mtime-2",
            vault_binding_id="binding-a",
            producer="ingest.vault_sync",
        )
        counts = conn.execute(
            "SELECT vault_binding_id, count(*) FROM outbox GROUP BY 1 ORDER BY 1"
        ).fetchall()
        assert counts == [("binding-a", 2), ("binding-b", 1)]
        assert legacy_key == derive_idempotency_key(
            _TOPIC,
            "shared-note",
            payload_fingerprint(
                {**payload, "event": _TOPIC, "__observation__": "mtime-1"}
            ),
        )


def test_poll_dispatches_complete_envelopes_and_skips_incomplete_current_binding_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable poll predicate enforces the MVR-05D envelope in PostgreSQL."""

    stamp = {
        "vault_binding_id": "binding-a",
        "binding_authority": "allow",
        "binding_authorization_epoch": "epoch-a",
        "binding_revision": 3,
        "vault_root": "/vault/a",
    }
    with _isolated_outbox(monkeypatch) as conn:
        legacy_key = derive_idempotency_key(_TOPIC, "n", "f")
        scoped = derive_binding_scoped_idempotency_key(_TOPIC, "binding-a", legacy_key)
        complete_meta = {
            **stamp,
            "outbox_envelope": OUTBOX_ENVELOPE_VERSION,
            "routing_class": "vault_bound",
            "outbox_producer": "ingest.vault_sync",
            "producer_context": {"kind": "binding_runtime"},
            "idempotency": {"legacy_key": legacy_key, "binding_scoped_key": scoped},
        }
        legacy_shape = new_event(event_type=_TOPIC, payload={"n": 1}, meta=dict(stamp))
        complete = new_event(event_type=_TOPIC, payload={"n": 2}, meta=complete_meta)
        legacy_id = uuid4()
        conn.execute(
            "INSERT INTO outbox (id, legacy_key, vault_binding_id, topic, payload, created_at) "
            "VALUES (%s, %s, 'binding-a', %s, %s::jsonb, '2000-01-01T00:00:00Z'), "
            "(%s, %s, 'binding-a', %s, %s::jsonb, '2000-01-02T00:00:00Z')",
            (
                legacy_id,
                uuid4(),
                _TOPIC,
                legacy_shape.model_dump_json(),
                UUID(scoped),
                UUID(legacy_key),
                _TOPIC,
                complete.model_dump_json(),
            ),
        )
        message = poll_outbox_one(
            conn,
            eligible_binding_ids=("binding-a",),
            required_binding_stamp=stamp,
        )
        assert message is not None
        assert message["id"] == scoped
        from app.services.outbox import count_deferred_outbox_rows

        assert count_deferred_outbox_rows(conn=conn, required_binding_stamp=stamp) == 1
