"""MVR-05A5 decisions replay isolation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import pytest

from app.jobs.decisions_projection import rebuild_decisions_projection
from app.receipts.decision_receipt_log import append_decision_receipt
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    _upgrade,
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)


pytestmark = pytest.mark.pg


def test_decisions_rebuild_preserves_other_binding_rows_and_attribution(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    factory = request.getfixturevalue("scratch_db_factory")
    dsn = factory()
    _upgrade(dsn, monkeypatch, "head")
    object_id = uuid.uuid4()
    with psycopg.connect(dsn) as conn:
        for binding in ("binding-a", "binding-b"):
            conn.execute(
                "INSERT INTO store_objects(vault_binding_id,object_id,kind,payload) "
                "VALUES (%s,%s,'note','{}'::jsonb)",
                (binding, object_id),
            )

    monkeypatch.setattr(
        "app.receipts.decision_receipt_log.DEFAULT_WRITE_GUARD.assert_writes_allowed",
        lambda _action: None,
    )
    roots = {binding: tmp_path / binding for binding in ("binding-a", "binding-b")}
    for binding, root in roots.items():
        root.mkdir()
        append_decision_receipt(
            object_id=str(object_id),
            key="review",
            value={"binding": binding},
            trace_id=f"trace-{binding}",
            created_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
            vault_root=root,
            vault_uuid=None,
        )
        rebuild_decisions_projection(root, vault_binding_id=binding)

    empty_b = tmp_path / "empty-b"
    empty_b.mkdir()
    rebuild_decisions_projection(empty_b, vault_binding_id="binding-b")

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "SELECT vault_binding_id,object_id,value FROM decisions ORDER BY vault_binding_id"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "binding-a"
    assert rows[0][1] == object_id
    assert rows[0][2]["binding"] == "binding-a"
    assert rows[0][2]["trace_id"] == "trace-binding-a"
