from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4

import pytest

from app.workers import outbox_worker

pytestmark = pytest.mark.not_pg


class _TxnConn:
    def transaction(self):
        return nullcontext()


def test_worker_reemissions_inherit_the_source_row_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: list[str | None] = []

    def capture(*args, **kwargs):
        captured.append(kwargs.get("vault_binding_id"))
        return "stored"

    monkeypatch.setattr(outbox_worker, "write_outbox_event", capture)
    monkeypatch.setattr(outbox_worker, "append_jsonl_outbox_event", lambda *a, **k: True)
    monkeypatch.setattr(outbox_worker, "_use_db_outbox", lambda: True)
    monkeypatch.setattr(outbox_worker, "_draft_schema_violation_case", lambda **kwargs: None)
    binding = "binding-source-a"
    identity = str(uuid4())

    outbox_worker._emit_ka_consumer_signal(
        outbox_worker.KA_CANDIDATE_READY_FOR_TRIAGE,
        content_identity=identity,
        fingerprint="candidate:v1",
        payload={"content_identity": identity},
        trace_id="trace",
        source_vault_binding_id=binding,
    )
    outbox_worker._emit_retry_dead_letter(
        "panel.scan.requested",
        {"event_id": identity},
        note_path=tmp_path / "note.md",
        reason="missing_uuid",
        retry_count=3,
        trace_id="trace",
        original_event_id=identity,
        source_vault_binding_id=binding,
    )
    for conn in (None, _TxnConn()):
        outbox_worker._dead_letter_outbox_message(
            "panel.scan.requested",
            {"event_id": identity},
            message_id=identity,
            reason="poison",
            attempts=5,
            trace_id="trace",
            error="boom",
            conn=conn,
            source_vault_binding_id=binding,
        )
    assert outbox_worker._queue_transient_retry(
        "panel.scan.requested",
        {"event_id": identity},
        note_path=tmp_path / "note.md",
        reason="unstable",
        trace_id="trace",
        original_event_id=identity,
        source_vault_binding_id=binding,
    )

    assert captured == [binding, binding, binding, binding, binding]
