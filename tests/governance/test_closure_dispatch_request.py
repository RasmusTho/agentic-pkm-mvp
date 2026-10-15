from __future__ import annotations

from scripts.build_closure_dispatch_request import build_request


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
MERGE_SHA = "a" * 40


def _pr() -> dict[str, object]:
    return {
        "number": 6113,
        "merged": True,
        "merged_at": "2026-10-15T07:00:00Z",
        "merge_commit_sha": MERGE_SHA,
    }


def _classification() -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "merged_pr_number": 6113,
        "merged_pr_sha": MERGE_SHA,
        "artifact_name": "post-merge-docs-classifier-6113",
        "impact_classification": "no_change_likely",
    }


def test_schema_and_merge_idempotency_are_deterministic() -> None:
    event = {
        "repository": {"full_name": REPOSITORY},
        "pull_request": {"merged_at": "2026-10-15T07:00:00Z"},
    }
    first = build_request(event=event, pr=_pr(), classification=_classification())
    recovery = build_request(
        event={"repository": {"full_name": REPOSITORY}, "generated_at": "2026-10-15T08:00:00Z"},
        pr=_pr(),
        classification=_classification(),
        source="bounded_recovery",
    )
    assert first is not None and recovery is not None
    assert first["contract_version"] == "closure_dispatch_request.v1"
    assert first["stage"] == "closure"
    assert first["merge_sha"] == MERGE_SHA
    assert first["idempotency_key"] == recovery["idempotency_key"]
    assert first["source"] != recovery["source"]


def test_closed_unmerged_pr_emits_no_request() -> None:
    pr = _pr()
    pr["merged"] = False
    assert build_request(
        event={"repository": {"full_name": REPOSITORY}},
        pr=pr,
        classification=_classification(),
    ) is None


def test_foreign_or_mismatched_classification_is_rejected() -> None:
    classification = _classification()
    classification["repository"] = "other/repository"
    assert build_request(
        event={"repository": {"full_name": REPOSITORY}},
        pr=_pr(),
        classification=classification,
    ) is None
