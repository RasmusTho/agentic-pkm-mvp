from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from app.calibration.premortem_admission import admit_decision_history
from app.receipts.outcome_receipt_log import build_receipt

SELECTED_OBJECT = UUID("11111111-1111-4111-8111-111111111111")
SELECTED_UUID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
HISTORY_OBJECT = UUID("22222222-2222-4222-8222-222222222222")
HISTORY_UUID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


def _identity(object_id: UUID = SELECTED_OBJECT, decision_uuid: UUID = SELECTED_UUID) -> dict:
    return {"object_id": str(object_id), "decision_uuid": str(decision_uuid)}


def _candidate(
    *,
    object_id: UUID = SELECTED_OBJECT,
    decision_uuid: UUID = SELECTED_UUID,
    scope_id: str = "scope:current",
    corpus: str = "personal",
    title: str = "Selected decision",
    excerpt: str = "Selected rationale",
    citation_handle: str = "decision:selected",
) -> dict:
    return {
        "identity": _identity(object_id, decision_uuid),
        "object_type": "decision_record",
        "scope_id": scope_id,
        "corpus": corpus,
        "title": title,
        "excerpt": excerpt,
        "citation_handle": citation_handle,
    }


def _resolver(object_id: str) -> str | None:
    return {
        str(SELECTED_OBJECT): str(SELECTED_UUID),
        str(HISTORY_OBJECT): str(HISTORY_UUID),
    }.get(object_id)


def _admit(*, selection=None, candidates=None, receipts=None, citations=None):  # type: ignore[no-untyped-def]
    return admit_decision_history(
        selected_identities=selection if selection is not None else [_identity()],
        candidates=candidates if candidates is not None else [_candidate()],
        current_scope_id="scope:current",
        identity_resolver=_resolver,
        outcome_reader=lambda: list(receipts or []),
        citation_resolver=lambda handle: handle in set(citations or {"decision:selected"}),
    )


@pytest.mark.parametrize(
    ("selection", "candidates", "diagnostic"),
    [
        ([], [_candidate()], "selected_identity_count_invalid"),
        (
            [_identity(), _identity(HISTORY_OBJECT, HISTORY_UUID)],
            [_candidate()],
            "selected_identity_count_invalid",
        ),
        (
            [{"object_id": "not-a-uuid", "decision_uuid": str(SELECTED_UUID)}],
            [_candidate()],
            "selected_identity_malformed",
        ),
        ([_identity()], [_candidate(decision_uuid=HISTORY_UUID)], "selected_identity_stale"),
        (
            [_identity()],
            [_candidate(), _candidate(title="duplicate")],
            "selected_identity_ambiguous",
        ),
        (
            [_identity()],
            [
                _candidate(),
                {**_candidate(title="malformed duplicate"), "corpus": "invalid"},
            ],
            "selected_identity_ambiguous",
        ),
    ],
)
def test_selected_decision_identity_fails_closed(selection, candidates, diagnostic) -> None:  # type: ignore[no-untyped-def]
    result = _admit(selection=selection, candidates=candidates)
    assert result.coverage.status == "blocked"
    assert result.coverage.diagnostic == diagnostic
    assert result.decisions == []
    assert result.outcomes == []


def test_reuses_cal01_outcome_links_without_second_resolver() -> None:
    selected_receipt = build_receipt(
        decision_object_id=SELECTED_OBJECT,
        decision_uuid=SELECTED_UUID,
        rung_index=0,
        outcome="held",
        note="Observed result",
        created_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    duplicate_one = build_receipt(
        decision_object_id=HISTORY_OBJECT,
        decision_uuid=HISTORY_UUID,
        rung_index=1,
        outcome="partly_held",
        created_at=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )
    duplicate_two = {**duplicate_one, "outcome": "did_not_hold"}
    malformed_link = {
        **selected_receipt,
        "decision_object_id": str(HISTORY_OBJECT),
        "decision_uuid": str(SELECTED_UUID),
        "rung_index": 2,
    }
    candidates = [
        _candidate(),
        _candidate(
            object_id=HISTORY_OBJECT,
            decision_uuid=HISTORY_UUID,
            title="Historical decision",
            excerpt="Historical rationale",
            citation_handle="decision:history",
        ),
    ]
    result = _admit(
        candidates=candidates,
        receipts=[selected_receipt, duplicate_one, duplicate_two, malformed_link],
        citations={"decision:selected", "decision:history", f"decision-outcome:{SELECTED_UUID}:0"},
    )

    assert [(item.decision_uuid, item.rung_index, item.outcome) for item in result.outcomes] == [
        (SELECTED_UUID, 0, "held")
    ]
    assert result.coverage.exclusions["duplicate_outcome_link"] == 2
    assert result.coverage.exclusions["malformed_outcome_link"] == 1
    assert result.coverage.status == "partial"

    same_key_conflict = {
        **selected_receipt,
        "decision_object_id": str(HISTORY_OBJECT),
        "outcome": "did_not_hold",
    }
    conflicted = _admit(
        receipts=[selected_receipt, same_key_conflict],
        citations={"decision:selected", f"decision-outcome:{SELECTED_UUID}:0"},
    )
    assert conflicted.outcomes == []
    assert conflicted.coverage.exclusions["malformed_outcome_link"] == 1
    assert conflicted.coverage.exclusions["conflicting_outcome_link"] == 1


def test_admission_excludes_governance_and_denied_scope() -> None:
    candidates = [
        _candidate(),
        _candidate(
            object_id=HISTORY_OBJECT,
            decision_uuid=HISTORY_UUID,
            title="Allowed history",
            excerpt="Allowed excerpt",
            citation_handle="decision:history",
        ),
        _candidate(
            object_id=UUID("33333333-3333-4333-8333-333333333333"),
            decision_uuid=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
            corpus="governance",
            title="GOV secret title",
            excerpt="GOV secret body",
            citation_handle="decision:gov",
        ),
        _candidate(
            object_id=UUID("44444444-4444-4444-8444-444444444444"),
            decision_uuid=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
            scope_id="scope:denied",
            title="Denied title",
            excerpt="Denied body",
            citation_handle="decision:denied",
        ),
    ]
    result = _admit(
        candidates=candidates,
        citations={"decision:selected", "decision:history"},
    )

    assert [item.title for item in result.decisions] == ["Selected decision", "Allowed history"]
    assert result.coverage.exclusions["governance_corpus"] == 1
    assert result.coverage.exclusions["scope_denied"] == 1
    encoded = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    assert "GOV secret" not in encoded
    assert "Denied" not in encoded


def test_admission_returns_only_resolvable_nonleaking_citations() -> None:
    receipt = build_receipt(
        decision_object_id=SELECTED_OBJECT,
        decision_uuid=SELECTED_UUID,
        rung_index=0,
        outcome="unknown_yet",
        note="Private outcome note",
    )
    candidates = [
        _candidate(),
        _candidate(
            object_id=HISTORY_OBJECT,
            decision_uuid=HISTORY_UUID,
            title="Unresolvable title",
            excerpt="Unresolvable body",
            citation_handle="decision:missing",
        ),
    ]
    result = _admit(candidates=candidates, receipts=[receipt], citations={"decision:selected"})

    assert [item.citation_handle for item in result.decisions] == ["decision:selected"]
    assert result.outcomes == []
    assert result.coverage.exclusions["citation_unresolvable"] == 2
    encoded = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("Unresolvable title", "Unresolvable body", "Private outcome note"):
        assert forbidden not in encoded


def test_admission_is_read_only_and_noninferential(tmp_path: Path, monkeypatch) -> None:
    from app.receipts import outcome_receipt_log

    monkeypatch.setattr(
        outcome_receipt_log,
        "append_outcome_receipt",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("write path called")),
    )
    calls = {"identity": 0, "outcomes": 0, "citations": 0}

    def identity_resolver(object_id: str) -> str | None:
        calls["identity"] += 1
        return _resolver(object_id)

    def outcome_reader():  # type: ignore[no-untyped-def]
        calls["outcomes"] += 1
        return []

    def citation_resolver(handle: str) -> bool:
        calls["citations"] += 1
        return handle == "decision:selected"

    before = list(tmp_path.rglob("*"))
    result = admit_decision_history(
        selected_identities=[_identity()],
        candidates=[_candidate()],
        current_scope_id="scope:current",
        identity_resolver=identity_resolver,
        outcome_reader=outcome_reader,
        citation_resolver=citation_resolver,
    )

    assert result.decisions[0].excerpt == "Selected rationale"
    assert result.outcomes == []
    assert calls == {"identity": 1, "outcomes": 1, "citations": 1}
    assert list(tmp_path.rglob("*")) == before
