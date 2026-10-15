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
    assert capped["requests"] == []
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
