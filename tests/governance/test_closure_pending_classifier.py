from __future__ import annotations

from scripts.reconcile_post_merge_closure import classify_pending


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
MERGE_SHA = "b" * 40


def _pr() -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "number": 6113,
        "merged": True,
        "merged_at": "2026-10-15T07:00:00Z",
        "merge_commit_sha": MERGE_SHA,
    }


def _receipt() -> dict[str, object]:
    return {
        "contract": "closure_delivery_receipt.v1",
        "repository": REPOSITORY,
        "pr_number": 6113,
        "merge_sha": MERGE_SHA,
        "status": "complete",
    }


def test_pending_and_terminal_cases_are_classified_from_evidence() -> None:
    pending = classify_pending(pr=_pr())
    terminal = classify_pending(pr=_pr(), authoritative_evidence={"closure_receipt": _receipt()})
    assert pending["status"] == "merged_closure_pending"
    assert terminal["status"] == "complete"


def test_missing_or_conflicting_evidence_cannot_prove_terminal() -> None:
    conflict = classify_pending(
        pr=_pr(),
        authoritative_evidence={"closure_receipt": _receipt(), "conflict": True},
    )
    malformed = classify_pending(
        pr={**_pr(), "merge_commit_sha": "not-a-sha"},
        authoritative_evidence={"closure_receipt": _receipt()},
    )
    assert conflict["status"] != "complete"
    assert malformed["status"] != "complete"


def test_conflicting_or_unavailable_receipts_cannot_prove_terminal() -> None:
    receipt = _receipt()
    conflicting = classify_pending(
        pr=_pr(),
        authoritative_evidence={"receipts": [receipt, {**receipt, "status": "pending"}]},
    )
    unavailable = classify_pending(
        pr=_pr(),
        issue_evidence=[{"repository": REPOSITORY, "unavailable": True}],
        authoritative_evidence={"closure_receipt": receipt},
    )
    assert conflicting["status"] != "complete"
    assert unavailable["status"] != "complete"
