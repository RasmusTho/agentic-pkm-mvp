from __future__ import annotations

import json
from pathlib import Path

from app.events.types import PROMOTE_DONE, PROMOTION_TRANSITION_APPLIED
from app.receipts.promotion_receipts import PromotionReceiptQuery, query_promotion_receipts


def _write_jsonl(path: Path, *records: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def _transition_record(
    *,
    event_id: str = "evt-receipt-1",
    trace_id: str = "trace-1",
    timestamp: str = "2026-05-30T12:00:00Z",
    note_uuid: str = "00000000-0000-0000-0000-000000001403",
    note_path: str = "notes/receipt.md",
    intent_event_id: str = "intent-1",
    family: str = "promotion",
    target_maturity: str = "evergreen",
    status: str = "applied",
    review_state: str = "reviewed",
    maturity: str = "evergreen",
) -> dict:
    return {
        "event": PROMOTION_TRANSITION_APPLIED,
        "event_id": event_id,
        "trace_id": trace_id,
        "source": "promotion.consumer",
        "timestamp": timestamp,
        "payload": {
            "intent_event_id": intent_event_id,
            "source_event": intent_event_id,
            "trace_id": trace_id,
            "note_uuid": note_uuid,
            "note_path": note_path,
            "transition_family": family,
            "target_maturity": target_maturity,
            "executor": "promotion.consumer",
            "authority": {
                "mode": "governed_execution",
                "component": "panel_agent.runtime",
                "executor": "promotion.consumer",
            },
            "basis": {
                "source_event": intent_event_id,
                "intent_type": "promotion",
            },
            "outcome": {
                "status": status,
                "review_state": review_state,
                "maturity": maturity,
            },
            "artifact_linkage": {
                "note_uuid": note_uuid,
                "note_path": note_path,
            },
        },
    }


def test_query_projects_transition_applied_records(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    _write_jsonl(
        outbox,
        {
            "event": PROMOTE_DONE,
            "event_id": "evt-done",
            "trace_id": "trace-done",
            "timestamp": "2026-05-30T11:00:00Z",
            "payload": {"note_uuid": "ignored", "review_state": "reviewed"},
        },
        _transition_record(),
    )

    result = query_promotion_receipts(vault_root=tmp_path, outbox_path=outbox)

    assert result.source_available is True
    assert result.non_authoritative_records == ()
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.receipt_id == "evt-receipt-1"
    assert row.source_event_id == "intent-1"
    assert row.trace_id == "trace-1"
    assert row.timestamp == "2026-05-30T12:00:00Z"
    assert row.artifact_uuid == "00000000-0000-0000-0000-000000001403"
    assert row.artifact_path == "notes/receipt.md"
    assert row.transition_family == "promotion"
    assert row.target_maturity == "evergreen"
    assert row.review_state == "reviewed"
    assert row.maturity == "evergreen"
    assert row.authority["component"] == "panel_agent.runtime"
    assert row.basis["source_event"] == "intent-1"
    assert row.outcome["status"] == "applied"
    assert row.artifact_linkage["note_path"] == "notes/receipt.md"
    assert row.executor == "promotion.consumer"
    assert row.source == "promotion.consumer"
    assert row.triggering_intent_event_id == "intent-1"


def test_query_filters_and_orders_promotion_receipts(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox.jsonl"
    first_uuid = "00000000-0000-0000-0000-000000001401"
    second_uuid = "00000000-0000-0000-0000-000000001402"
    _write_jsonl(
        outbox,
        _transition_record(
            event_id="evt-late",
            trace_id="trace-late",
            timestamp="2026-05-30T12:10:00Z",
            note_uuid=second_uuid,
            note_path="notes/later.md",
            intent_event_id="intent-late",
            target_maturity="seedling",
            status="failed",
            review_state="draft",
            maturity="seedling",
        ),
        _transition_record(
            event_id="evt-early",
            trace_id="trace-early",
            timestamp="2026-05-30T12:00:00Z",
            note_uuid=first_uuid,
            note_path="notes/early.md",
            intent_event_id="intent-early",
        ),
    )

    all_rows = query_promotion_receipts(vault_root=tmp_path, outbox_path=outbox).rows
    assert [row.receipt_id for row in all_rows] == ["evt-early", "evt-late"]

    queries = [
        PromotionReceiptQuery(artifact_uuid=first_uuid),
        PromotionReceiptQuery(artifact_path="notes/early.md"),
        PromotionReceiptQuery(receipt_or_source_event_id="evt-early"),
        PromotionReceiptQuery(receipt_or_source_event_id="intent-early"),
        PromotionReceiptQuery(trace_id="trace-early"),
        PromotionReceiptQuery(target_maturity="evergreen"),
        PromotionReceiptQuery(outcome_status="applied"),
    ]
    for query in queries:
        result = query_promotion_receipts(query, vault_root=tmp_path, outbox_path=outbox)
        assert [row.receipt_id for row in result.rows] == ["evt-early"]

    by_family = query_promotion_receipts(
        PromotionReceiptQuery(transition_family="promotion"),
        vault_root=tmp_path,
        outbox_path=outbox,
    )
    assert [row.receipt_id for row in by_family.rows] == ["evt-early", "evt-late"]

    failed = query_promotion_receipts(
        PromotionReceiptQuery(outcome_status="failed"),
        vault_root=tmp_path,
        outbox_path=outbox,
    )
    assert [row.receipt_id for row in failed.rows] == ["evt-late"]


def test_query_distinguishes_unavailable_empty_and_non_authoritative_sources(
    tmp_path: Path,
) -> None:
    missing = query_promotion_receipts(
        vault_root=tmp_path,
        outbox_path=tmp_path / "missing.jsonl",
    )
    assert missing.source_available is False
    assert missing.rows == ()
    assert missing.non_authoritative_records == ()

    empty_outbox = tmp_path / "empty.jsonl"
    empty_outbox.write_text("", encoding="utf-8")
    empty = query_promotion_receipts(vault_root=tmp_path, outbox_path=empty_outbox)
    assert empty.source_available is True
    assert empty.rows == ()
    assert empty.non_authoritative_records == ()

    non_authoritative_outbox = tmp_path / "non-authoritative.jsonl"
    _write_jsonl(
        non_authoritative_outbox,
        {
            "event": PROMOTION_TRANSITION_APPLIED,
            "event_id": "evt-no-authority",
            "trace_id": "trace-no-authority",
            "timestamp": "2026-05-30T12:00:00Z",
            "payload": {
                "note_uuid": "00000000-0000-0000-0000-000000001404",
                "note_path": "notes/non-authoritative.md",
                "outcome": {"status": "applied"},
                "artifact_linkage": {"note_path": "notes/non-authoritative.md"},
            },
        },
        {
            "event": PROMOTE_DONE,
            "event_id": "evt-done-only",
            "trace_id": "trace-done-only",
            "timestamp": "2026-05-30T12:01:00Z",
            "payload": {
                "note_uuid": "00000000-0000-0000-0000-000000001405",
                "note_path": "notes/done.md",
                "promotion": {"review_state": "reviewed"},
            },
        },
    )
    non_authoritative = query_promotion_receipts(
        vault_root=tmp_path,
        outbox_path=non_authoritative_outbox,
    )
    assert non_authoritative.source_available is True
    assert non_authoritative.rows == ()
    assert non_authoritative.non_authoritative_records == (
        {
            "event_id": "evt-no-authority",
            "trace_id": "trace-no-authority",
            "reason": "missing_authority",
        },
    )
