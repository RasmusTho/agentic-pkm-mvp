from __future__ import annotations

from scripts.reconcile_post_merge_closure import encode_cursor, recover


REPOSITORY = "RasmusTho/agentic-pkm-mvp"
MERGE_SHA = "c" * 40


def _pr(number: int = 6113) -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "number": number,
        "merged": True,
        "merged_at": "2026-10-15T07:00:00Z",
        "merge_commit_sha": MERGE_SHA,
    }


def _classification(number: int = 6113) -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "pr_number": number,
        "merge_sha": MERGE_SHA,
        "artifact_name": f"post-merge-docs-classifier-{number}",
    }


def test_bounded_recovery_rediscovers_orphaned_merge() -> None:
    result = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": _classification()},
        window_end="2026-10-15T08:00:00Z",
    )
    assert result["overflow"] is False
    assert len(result["requests"]) == 1
    assert result["requests"][0]["stage"] == "closure"
    assert result["pending"] == [{"pr_number": 6113, "reason": "terminal closure evidence is incomplete"}]
    replay = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": _classification()},
        window_end="2026-10-15T08:00:00Z",
    )
    assert replay["requests"][0]["idempotency_key"] == result["requests"][0]["idempotency_key"]
    assert replay["complete"] == []


def test_cursor_overflow_and_backoff_preserve_scan_bounds() -> None:
    cursor = encode_cursor(page=1, window_end="2026-10-15T08:00:00Z")
    result = recover(
        repository=REPOSITORY,
        pages=[[_pr(6113)], [_pr(6114)], [_pr(6115)]],
        classifications={"6113": _classification()},
        cursor=cursor,
        window_end="2026-10-15T08:00:00Z",
        max_pages=1,
        max_requests=1,
    )
    assert result["overflow"] is True
    assert result["continuation_cursor"]
    assert result["backoff"]["max_attempts"] == 3
    invalid = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": _classification()},
        cursor="invalid",
        window_end="2026-10-15T08:00:00Z",
    )
    assert invalid["overflow"] is True
    assert invalid["requests"] == []

    capped = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": _classification()},
        window_end="2026-10-15T08:00:00Z",
        rest_attempt=3,
    )
    assert len(capped["requests"]) == 1
    assert capped["pending"] == [{"pr_number": 6113, "reason": "terminal closure evidence is incomplete"}]
    assert capped["continuation_cursor"]
    assert capped["backoff"]["retry"] is False


def test_request_cap_cursor_resumes_within_a_page() -> None:
    prs = [_pr(number) for number in range(6113, 6153)]
    classifications = {str(pr["number"]): _classification(int(pr["number"])) for pr in prs}
    first = recover(
        repository=REPOSITORY,
        pages=[prs],
        classifications=classifications,
        window_end="2026-10-15T08:00:00Z",
        max_requests=30,
    )
    assert first["overflow"] is True
    assert len(first["requests"]) == 30
    second = recover(
        repository=REPOSITORY,
        pages=[prs],
        classifications=classifications,
        cursor=first["continuation_cursor"],
        window_end="2026-10-15T08:00:00Z",
        max_requests=30,
    )
    assert second["overflow"] is False
    assert len(second["requests"]) == 10


def test_recovery_skips_matching_terminal_receipt() -> None:
    classification = _classification()
    classification["impact_classification"] = "no_change_likely"
    classification["authoritative_evidence"] = {"closure_receipt": {
        "contract": "closure_delivery_receipt.v1",
        "repository": REPOSITORY,
        "pr_number": 6113,
        "merge_sha": MERGE_SHA,
        "status": "complete",
    }}
    result = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": classification},
        window_end="2026-10-15T08:00:00Z",
    )
    assert result["requests"] == []
    assert result["complete"] == [{"pr_number": 6113, "reason": "matching terminal closure receipt"}]


def test_invalid_offset_and_exhausted_backoff_preserve_continuation() -> None:
    classification = _classification()
    invalid = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": classification},
        cursor=encode_cursor(page=1, offset=999, window_end="2026-10-15T08:00:00Z"),
        window_end="2026-10-15T08:00:00Z",
    )
    assert invalid["overflow"] is True
    assert invalid["continuation_cursor"] is None
    assert "offset" in invalid["error"]
    exhausted = recover(
        repository=REPOSITORY,
        pages=[[_pr()]],
        classifications={"6113": classification},
        window_end="2026-10-15T08:00:00Z",
        rest_attempt=3,
    )
    assert exhausted["overflow"] is True
    assert exhausted["continuation_cursor"]


def test_retry_exhaustion_keeps_collected_pages_and_advances_cursor() -> None:
    pages = [[_pr(6113)], [_pr(6114)]]
    classifications = {str(number): _classification(number) for number in (6113, 6114)}
    result = recover(
        repository=REPOSITORY,
        pages=pages,
        classifications=classifications,
        window_end="2026-10-15T08:00:00Z",
        rest_attempt=3,
    )
    assert len(result["requests"]) == 2
    assert result["overflow"] is True
    assert result["error"] == "REST backoff cap reached"
    assert result["continuation_cursor"]
    resumed = recover(
        repository=REPOSITORY,
        pages=[[_pr(6115)]],
        classifications={"6115": _classification(6115)},
        cursor=result["continuation_cursor"],
        pages_start=3,
        window_end="2026-10-15T08:00:00Z",
    )
    assert len(resumed["requests"]) == 1


def test_foreign_repository_cannot_complete_from_terminal_receipt() -> None:
    foreign_repository = "other/example"
    foreign_pr = {**_pr(), "repository": foreign_repository}
    foreign_classification = {
        **_classification(),
        "repository": foreign_repository,
        "authoritative_evidence": {
            "closure_receipt": {
                "contract": "closure_delivery_receipt.v1",
                "repository": foreign_repository,
                "pr_number": 6113,
                "merge_sha": MERGE_SHA,
                "status": "complete",
            }
        },
    }
    result = recover(
        repository=REPOSITORY,
        pages=[[foreign_pr]],
        classifications={"6113": foreign_classification},
        window_end="2026-10-15T08:00:00Z",
    )
    assert result["complete"] == []
    assert result["requests"] == []
    assert result["pending"] == [{"pr_number": 6113, "reason": "foreign or missing repository evidence"}]
