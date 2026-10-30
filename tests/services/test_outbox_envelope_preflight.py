"""MVR-05D rollout preflight: no runtime activates over pre-envelope pending rows."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.events.models import new_event
from app.instance.binding_ids import (
    COMPATIBILITY_BINDING_ID,
    OUTBOX_GLOBAL_BINDING_ID,
    OUTBOX_QUARANTINE_BINDING_ID,
)
from app.services import outbox_envelope_preflight as preflight
from app.services.outbox import derive_idempotency_key, write_outbox_event

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Conn:
    def __init__(self, *, oid=1234, column=True, count=0) -> None:
        self.oid, self.column, self.count = oid, column, count
        self.statements: list[str] = []

    def execute(self, sql, params=()):
        self.statements.append(sql)
        normalized = " ".join(sql.lower().split())
        if "to_regclass" in normalized:
            value = (self.oid,)
        elif "from pg_attribute" in normalized:
            value = (1,) if self.column else None
        else:
            value = (self.count,)
        return type("Cursor", (), {"fetchone": lambda _self: value})()


@pytest.mark.not_pg
def test_preflight_refuses_activation_over_pre_envelope_rows_and_is_wired_before_runtime(
    monkeypatch, capsys
) -> None:
    assert preflight.evaluate(_Conn(oid=None))["status"] == "skipped"
    assert preflight.evaluate(_Conn(column=False))["reason"] == "pre_binding_schema"
    assert preflight.evaluate(_Conn(count=0)) == {
        "schema": preflight.PREFLIGHT_SCHEMA,
        "status": "ok",
        "incompatible_pending_count": 0,
    }
    blocked = _Conn(count=3)
    assert preflight.evaluate(blocked)["status"] == "blocked"
    assert all(not sql.lower().lstrip().startswith(("update", "delete", "insert")) for sql in blocked.statements)

    # The CLI fails loud (nonzero, operator guidance) so `set -e` stops the
    # migrate one-shot and no dependent runtime service starts.
    import psycopg

    class _Connect:
        def __enter__(self):
            return _Conn(count=2)

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(psycopg, "connect", lambda *_a, **_k: _Connect())
    monkeypatch.setenv("DATABASE_URL", "postgresql://preflight.invalid:5432/app")
    assert preflight.main() == preflight.BLOCKED_EXIT_CODE
    err = capsys.readouterr().err
    assert "2 pending live-binding outbox row(s)" in err and "drains them" in err

    script = (REPO_ROOT / "scripts/run_migrations.sh").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/bash") and "set -euo pipefail" in script
    gate = script.index("python -m app.services.outbox_envelope_preflight")
    assert script.index('if [[ "${MIGRATION_GATE_TOKEN_ONLY:-0}" == "1" ]]; then') < gate
    assert gate < script.index("alembic -c app/alembic.ini upgrade head")


@pytest.mark.pg
def test_preflight_counts_only_pending_pre_envelope_live_binding_rows(monkeypatch) -> None:
    from tests.services.test_multi_vault_outbox_idempotency import _isolated_outbox

    stamp_only = new_event(
        event_type="mvr05d.preflight", payload={}, meta={"vault_binding_id": "binding-a"}
    ).model_dump_json()
    with _isolated_outbox(monkeypatch) as conn:
        assert preflight.evaluate(conn)["status"] == "ok"
        # A complete-envelope row from the production choke point is compatible.
        write_outbox_event(
            new_event(event_type="mvr05d.preflight", payload={"n": 1}),
            conn,
            idempotency_key=derive_idempotency_key("mvr05d.preflight", "n", "1"),
            vault_binding_id="binding-a",
            producer="ingest.vault_sync",
        )
        rows = [
            ("binding-a", None),  # pending 05A-stamped live-binding row: incompatible
            ("binding-a", "now()"),  # already delivered: drained
            (COMPATIBILITY_BINDING_ID, None),
            (OUTBOX_GLOBAL_BINDING_ID, None),
            (OUTBOX_QUARANTINE_BINDING_ID, None),
        ]
        for binding, delivered in rows:
            conn.execute(
                "INSERT INTO outbox (id, legacy_key, vault_binding_id, topic, payload, delivered_at) "
                f"VALUES (%s, %s, %s, 'mvr05d.preflight', %s::jsonb, {delivered or 'NULL'})",
                (uuid4(), uuid4(), binding, stamp_only),
            )
        assert preflight.evaluate(conn) == {
            "schema": preflight.PREFLIGHT_SCHEMA,
            "status": "blocked",
            "incompatible_pending_count": 1,
        }
        conn.execute(
            "UPDATE outbox SET delivered_at = now() WHERE vault_binding_id = 'binding-a' "
            "AND payload #>> '{meta,outbox_envelope}' IS NULL"
        )
        assert preflight.evaluate(conn)["status"] == "ok"
