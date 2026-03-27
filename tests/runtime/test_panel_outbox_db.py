from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.agents.panel_agent.runtime import execute_panel_intent
from app.events.panel import NoteRef, PanelActionMapping, PanelInfo, PanelIntentAction, PanelIntentEvent, PanelIntentPayload
from app.services import outbox as outbox_service
from app.db.dsn import resolve_dsn
from app.vault.paths import get_vault_inbox_dir_rel


def _pg_available() -> bool:
    try:
        from tests.stores.test_store_contract_pg import _pg_available as helper
    except Exception:
        return False
    return helper()


@pytest.mark.pg
def test_panel_runtime_enqueues_db_outbox(monkeypatch, tmp_path) -> None:
    if not _pg_available():
        pytest.skip("Postgres backend not available")

    dsn = resolve_dsn() or os.getenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:15432/app")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("STORE_BACKEND", "pg")
    audit_path = tmp_path / "index-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(audit_path))
    monkeypatch.setenv("VAULT_ROOT", str(tmp_path / "vault"))
    system_dir = Path(os.environ["VAULT_ROOT"]) / "⚙️ System"
    system_dir.mkdir(parents=True)
    (system_dir / "vault.layout.md").write_text(
        "---\n"
        "version: '1'\n"
        "system_folder: ⚙️ System\n"
        "inbox_folder: 📥 Inbox\n"
        "desk_folder: 🛠️ Workbench\n"
        "---\n",
        encoding="utf-8",
    )

    outbox_service.bootstrap()
    conn = outbox_service._open_conn()
    try:
        cur = conn.cursor()
        cur.execute("delete from outbox")
        conn.commit()
    finally:
        conn.close()

    note_path = Path(get_vault_inbox_dir_rel(Path(os.environ["VAULT_ROOT"]))) / "_alpha_e2e" / "runtime.md"
    note = NoteRef(uuid=uuid4().hex, path=note_path.as_posix())
    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        downstream_event="promote.intent.created",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(id="promote.evergreen", label="Promote", checked=True, mapping=mapping)
    payload = PanelIntentPayload(
        note=note,
        panel=PanelInfo(panel_id="panel-1", instruction="Promote this"),
        actions=[action],
    )
    intent = PanelIntentEvent(payload=payload, trace_id=uuid4().hex)

    execute_panel_intent(intent)

    conn = outbox_service._open_conn()
    try:
        cur = conn.cursor()
        cur.execute("select count(*) from outbox where topic = %s", ("promote.intent.created",))
        row = cur.fetchone()
        assert row and int(row[0]) >= 1
    finally:
        conn.close()
