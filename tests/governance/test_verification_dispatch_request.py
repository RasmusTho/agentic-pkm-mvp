from __future__ import annotations

import json

import pytest

from scripts.build_verification_dispatch_request import (
    build_request,
    resolve_issue_contract,
    resolve_pr_number,
)


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
HEAD_SHA = "a" * 40


def _event(
    *,
    conclusion: str = "success",
    event_name: str = "pull_request",
    head_sha: str = HEAD_SHA,
) -> dict[str, object]:
    return {
        "repository": {"full_name": REPOSITORY},
        "artifact_workflow_run": {"id": 123, "repository_id": 456},
        "workflow_run": {
            "id": 987654,
            "run_attempt": 2,
            "name": "CI",
            "event": event_name,
            "conclusion": conclusion,
            "head_sha": head_sha,
            "updated_at": "2026-07-13T12:00:00Z",
            "pull_requests": [{"number": 3602}],
        },
    }


def _pr(*, head_sha: str = HEAD_SHA, state: str = "open") -> dict[str, object]:
    return {
        "number": 3602,
        "state": state,
        "body": "Governing-Issue: #3602\n\nFixes #3602",
        "base": {"ref": "main"},
        "head": {"ref": "codex/issue-3602", "sha": head_sha},
    }


def _issue() -> dict[str, object]:
    return {"number": 3602, "state": "open"}


def test_request_schema_and_idempotency_are_deterministic() -> None:
    first = build_request(event=_event(), pr=_pr(), issue=_issue())
    second = build_request(event=_event(), pr=_pr(), issue=_issue())

    assert first == second
    assert first is not None
    assert first == json.loads(json.dumps(first, sort_keys=True))
    assert first["contract_version"] == "verification_dispatch_request.v1"
    assert first["stage"] == "verification"
    assert first["repository"] == REPOSITORY
    assert first["pr_number"] == 3602
    assert first["linked_issue"] == 3602
    assert first["supporting_issues"] == []
    assert "base_ref" not in first
    assert "head_ref" not in first
    assert first["current_head_sha"] == HEAD_SHA
    assert first["source_workflow"] == {
        "name": "CI",
        "run_id": 987654,
        "run_attempt": 2,
        "head_sha": HEAD_SHA,
    }
    assert first["artifact_provenance"] == {
        "workflow_run_id": 123,
        "repository_id": 456,
        "artifact_name": f"verification-dispatch-3602-{HEAD_SHA}",
    }
    assert first["generated_at"] == "2026-07-13T12:00:00Z"
    assert len(first["idempotency_key"]) == 64


def test_non_eligible_events_are_noops() -> None:
    assert build_request(event=_event(conclusion="failure"), pr=_pr(), issue=_issue()) is None
    assert build_request(event=_event(conclusion="cancelled"), pr=_pr(), issue=_issue()) is None
    assert build_request(event=_event(conclusion="skipped"), pr=_pr(), issue=_issue()) is None
    assert build_request(event=_event(event_name="push"), pr=_pr(), issue=_issue()) is None
    assert build_request(event=_event(), pr={}, issue={}) is None
    assert (
        build_request(event=_event(), pr=_pr(head_sha="b" * 40), issue=_issue())
        is None
    )


def test_multi_issue_pr_selects_explicit_governing_issue() -> None:
    pr = _pr()
    pr["body"] = (
        "Governing-Issue: #3603\n\nRefs #3603\nFixes #3626\n"
        "Fixes #3698\nFixes #3699\nFixes #3700\nFixes #3705"
    )

    request = build_request(event=_event(), pr=pr, issue={"number": 3603})

    assert request is not None
    assert request["linked_issue"] == 3603
    assert request["supporting_issues"] == [3626, 3698, 3699, 3700, 3705]


def test_crlf_authority_is_canonicalized_before_request_emission() -> None:
    pr = _pr()
    pr["body"] = "Governing-Issue: #3602\r\nRefs #3603\r\nFixes #3602\r\n"

    request = build_request(event=_event(), pr=pr, issue=_issue())

    assert resolve_issue_contract(pr["body"]) == (3602, (3603,))
    assert request is not None
    assert request["linked_issue"] == 3602
    assert request["supporting_issues"] == [3603]


def test_ambiguous_governing_issue_emits_no_request() -> None:
    missing = _pr()
    missing["body"] = "Fixes #3626\nFixes #3603"
    conflicting = _pr()
    conflicting["body"] = "Governing-Issue: #3603\nGoverning-Issue: #3626"
    mismatched = _pr()
    mismatched["body"] = "Governing-Issue: #3603\nFixes #3626"
    folded = _pr()
    folded["body"] = "Governing-Issue:\n#3603\nFixes #3603"

    assert resolve_issue_contract(missing["body"]) is None
    assert resolve_issue_contract(conflicting["body"]) is None
    assert resolve_issue_contract(folded["body"]) is None
    assert build_request(event=_event(), pr=missing, issue={"number": 3603}) is None
    assert build_request(event=_event(), pr=conflicting, issue={"number": 3603}) is None
    assert build_request(event=_event(), pr=folded, issue={"number": 3603}) is None
    assert build_request(event=_event(), pr=mismatched, issue={"number": 3626}) is None


@pytest.mark.parametrize(
    "body",
    [
        "Governing-Issue: #3602",
        "Governing-Issue: #3602\nFixes #0",
        "Governing-Issue: #3602\nFixes #-1",
        "Governing-Issue: #3602\nFixes #abc",
        "Governing-Issue: #3602\nFixes\n#3602",
        "Governing-Issue: #3602\nGoverning-Issue : #456\nFixes #3602",
        "Governing-Issue: #3602\nGoverning-Issue:\n#456\nFixes #3602",
        "Governing-Issue: #3602\nGoverning-Issue: #0\nFixes #3602",
        "Governing-Issue: #3602\nFixes #3602é",
        "Governing-Issue: #3602\nFixeſ #3602",
        "Governıng-Issue: #3602\nFixes #3602",
        "Governing-Issue: #3602\rFixes #3602",
        "Governing-Issue: #3602\u2028Fixes #3602",
        "Governing-Issue: #3602\u2029Fixes #3602",
    ],
)
def test_invalid_closing_authority_emits_no_request(body: str) -> None:
    pr = _pr()
    pr["body"] = body

    assert resolve_issue_contract(body) is None
    assert build_request(event=_event(), pr=pr, issue=_issue()) is None


def test_associated_pr_must_still_be_open() -> None:
    assert build_request(event=_event(), pr=_pr(), issue=_issue()) is not None
    assert (
        build_request(event=_event(), pr=_pr(state="closed"), issue=_issue())
        is None
    )
    merged_pr = _pr(state="closed")
    merged_pr["merged_at"] = "2026-07-13T12:00:01Z"
    assert build_request(event=_event(), pr=merged_pr, issue=_issue()) is None


def test_replay_collapses_and_new_head_redispatches() -> None:
    replay_one = build_request(event=_event(), pr=_pr(), issue=_issue())
    replay_two = build_request(event=_event(), pr=_pr(), issue=_issue())
    new_head = "b" * 40
    redispatch = build_request(
        event=_event(head_sha=new_head),
        pr=_pr(head_sha=new_head),
        issue=_issue(),
    )

    assert replay_one is not None
    assert replay_two is not None
    assert redispatch is not None
    assert replay_one["idempotency_key"] == replay_two["idempotency_key"]
    assert replay_one["idempotency_key"] != redispatch["idempotency_key"]


def test_request_links_pr_evidence_and_live_truth_identifiers() -> None:
    request = build_request(event=_event(), pr=_pr(), issue=_issue())

    assert request is not None
    assert request["evidence_pack"] == {
        "contract": "pr_evidence_pack",
        "workflow_name": "PR Evidence Pack",
        "artifact_name": "pr-evidence-pack-3602",
        "repository": REPOSITORY,
        "pr_number": 3602,
        "head_sha": HEAD_SHA,
    }
    assert request["live_truth"] == {
        "repository": REPOSITORY,
        "pr_number": 3602,
        "current_head_sha": HEAD_SHA,
        "source_run_id": 987654,
    }


def test_empty_association_resolves_unique_current_head_pr() -> None:
    event = _event()
    event["workflow_run"]["pull_requests"] = []  # type: ignore[index]

    assert resolve_pr_number(
        event=event,
        candidates=[
            {
                "number": 3602,
                "state": "open",
                "head": {"sha": HEAD_SHA},
            },
            {
                "number": 3599,
                "state": "closed",
                "head": {"sha": HEAD_SHA},
            },
            {
                "number": 3598,
                "state": "open",
                "head": {"sha": "b" * 40},
            },
        ],
    ) == 3602


def test_empty_association_ambiguous_or_no_match_is_noop() -> None:
    event = _event()
    event["workflow_run"]["pull_requests"] = []  # type: ignore[index]
    matching = {
        "number": 3602,
        "state": "open",
        "head": {"sha": HEAD_SHA},
    }

    assert resolve_pr_number(event=event, candidates=[]) is None
    assert resolve_pr_number(
        event=event,
        candidates=[matching, {**matching, "number": 3603}],
    ) is None
    assert resolve_pr_number(
        event=event,
        candidates=[{**matching, "head": {"sha": "b" * 40}}],
    ) is None

    ambiguous_association = _event()
    ambiguous_association["workflow_run"]["pull_requests"] = [  # type: ignore[index]
        {"number": 3602},
        {"number": 3603},
    ]
    assert resolve_pr_number(event=ambiguous_association, candidates=[]) is None

    non_pr_event = _event(event_name="push")
    non_pr_event["workflow_run"]["pull_requests"] = []  # type: ignore[index]
    assert resolve_pr_number(event=non_pr_event, candidates=[matching]) is None


@pytest.mark.parametrize("malformed_number", [True, 0, -1])
def test_malformed_associated_pr_number_is_noop(malformed_number: object) -> None:
    event = _event()
    event["workflow_run"]["pull_requests"] = [  # type: ignore[index]
        {"number": malformed_number}
    ]

    assert resolve_pr_number(event=event, candidates=[]) is None


@pytest.mark.parametrize("malformed_number", [True, 0, -1])
def test_malformed_fallback_candidate_number_is_noop(
    malformed_number: object,
) -> None:
    event = _event()
    event["workflow_run"]["pull_requests"] = []  # type: ignore[index]

    assert resolve_pr_number(
        event=event,
        candidates=[
            {
                "number": malformed_number,
                "state": "open",
                "head": {"sha": HEAD_SHA},
            }
        ],
    ) is None


@pytest.mark.parametrize("malformed_number", [True, 0, -1])
def test_malformed_builder_pr_number_is_noop(malformed_number: object) -> None:
    pr = _pr()
    pr["number"] = malformed_number

    assert build_request(event=_event(), pr=pr, issue=_issue()) is None
