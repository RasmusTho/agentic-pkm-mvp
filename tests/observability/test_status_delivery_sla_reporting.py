from __future__ import annotations

import json

from app.observability.status_service import get_system_status
import app.observability.status_service as status_service


def test_status_exposes_delivery_sla_outcomes(monkeypatch, tmp_path) -> None:
    outbox = tmp_path / "status-sla-outbox.jsonl"
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(outbox))
    monkeypatch.setattr(status_service, "INDEX_OUTBOX_PATH", outbox, raising=False)

    records = [
        {
            "event": "orchestrator.step.finished",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"details": {"delivery_sla_state": "delivered"}},
        },
        {
            "event": "orchestrator.step.error",
            "timestamp": "2026-01-01T00:00:01Z",
            "payload": {"details": {"delivery_sla_state": "failed_terminal", "error_type": "handler_error"}},
        },
        {
            "event": "orchestrator.step.error",
            "timestamp": "2026-01-01T00:00:02Z",
            "payload": {"details": {"error_type": "plan_timeout"}},
        },
    ]
    outbox.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

    status = get_system_status()
    assert status.delivery_sla is not None
    assert status.delivery_sla.outcomes_total["delivered"] == 1
    assert status.delivery_sla.outcomes_total["failed_terminal"] == 1
    assert status.delivery_sla.outcomes_total["timeout_terminal"] == 1
    assert status.delivery_sla.source_path == str(outbox)
