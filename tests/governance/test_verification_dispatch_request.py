from __future__ import annotations

import json

from scripts.build_verification_dispatch_request import build_request, resolve_pr_number


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
        "body": "Fixes #3602",
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
    assert first["base_ref"] == "main"
    assert first["head_ref"] == "codex/issue-3602"
    assert first["current_head_sha"] == HEAD_SHA
    assert first["source_workflow"] == {
        "name": "CI",
        "run_id": 987654,
        "run_attempt": 2,
        "head_sha": HEAD_SHA,
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
