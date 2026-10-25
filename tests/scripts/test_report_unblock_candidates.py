from pathlib import Path
from typing import Any

import pytest

from scripts.report_unblock_candidates import (
    classify_ref,
    collect,
    dependency_state,
    evaluate,
    parse_predicate,
    post_transition_labels,
    render_markdown,
)

REPO = "acme/repo"
REPO_ROOT = Path(__file__).resolve().parents[2]
READY_BODY = (REPO_ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md").read_text(encoding="utf-8")


def _receipt(refs: str = '["#10"]', *, owner: str = "builder", action: str = "action:wait-dependency", extra: str = "") -> dict[str, str]:
    return {"body": "\n".join([
        "```yaml",
        "receipt: blocker_action.v1",
        f"action: {action}",
        f"owner: {owner}",
        "next_action: deliver the dependency",
        "unblocks_when: the dependency is delivered",
        f"dependency_refs: {refs}",
        *([extra] if extra else []),
        "review_at: null",
        "last_verified_at: 2026-10-25T00:00:00Z",
        "```",
    ])}


def _issue(number: int = 1, *, labels: tuple[str, ...] = ("agent:blocked", "action:wait-dependency", "type:task"), body: str = READY_BODY) -> dict[str, Any]:
    return {"number": number, "title": f"issue {number}", "state": "open", "labels": [{"name": label} for label in labels], "body": body}


def _closed(reason: str = "completed") -> dict[str, Any]:
    return {"state": "closed", "state_reason": reason}


def _evaluate(issue: dict[str, Any], comments: list[dict[str, Any]], deps: dict[int, Any]) -> dict[str, Any]:
    return evaluate(issue, comments, REPO, deps.get)


def test_completed_dependencies_and_strict_readiness_make_a_candidate() -> None:
    result = _evaluate(_issue(), [_receipt('["#10", "#11"]')], {10: _closed(), 11: _closed()})
    assert result["verdict"] == "candidate"
    assert result["predicate_source"] == "derived"
    assert result["dependencies"] == {"#10": "completed", "#11": "completed"}
    assert result["readiness"] == "ready_candidate"


def test_open_dependency_keeps_the_issue_waiting() -> None:
    result = _evaluate(_issue(), [_receipt('["#10", "#11"]')], {10: _closed(), 11: {"state": "open"}})
    assert result["verdict"] == "waiting_on_dependencies"
    assert result["reasons"] == ["#11"]


@pytest.mark.parametrize("dependency", [_closed("not_planned"), None, {"state": "closed", "pull_request": {"merged_at": None}}])
def test_dependency_closed_without_completion_is_not_a_candidate(dependency: Any) -> None:
    result = _evaluate(_issue(), [_receipt()], {10: dependency})
    assert result["verdict"] == "dependency_not_completed"


def test_merged_pull_request_counts_as_completed() -> None:
    assert dependency_state({"state": "closed", "pull_request": {"merged_at": "2026-10-01T00:00:00Z"}}) == "completed"


def test_failed_strict_readiness_is_reported_with_guidance() -> None:
    result = _evaluate(_issue(body="## Context\nonly context\n"), [_receipt()], {10: _closed()})
    assert result["verdict"] == "readiness_failed"
    assert result["readiness"] != "ready_candidate"


def test_readiness_runs_against_post_transition_labels() -> None:
    assert post_transition_labels({"agent:blocked", "action:wait-dependency", "type:task", "prio:high"}) == ["prio:high", "type:task"]


@pytest.mark.parametrize(
    ("labels", "comments", "reason"),
    [
        (("agent:blocked", "action:wait-external"), [_receipt(action="action:wait-external")], "not_blocked_wait_dependency"),
        (("agent:ready",), [], "not_blocked_wait_dependency"),
        (("agent:blocked", "action:wait-dependency"), [_receipt(owner="owner")], "owner_owner"),
        (("agent:blocked", "action:wait-dependency"), [], "missing_or_invalid_blocker_action_receipt"),
        (("agent:blocked", "action:wait-dependency"), [_receipt(action="action:review-at")], "receipt_action_mismatch"),
    ],
)
def test_only_builder_owned_wait_dependency_with_bound_receipt_is_class_a(labels: tuple[str, ...], comments: list[dict[str, Any]], reason: str) -> None:
    result = _evaluate(_issue(labels=labels), comments, {10: _closed()})
    assert result["verdict"] == "not_class_a"
    assert reason in result["reasons"]


def test_newest_receipt_governs_even_when_an_older_one_named_other_refs() -> None:
    comments = [_receipt('["#10"]'), _receipt('["#11"]')]
    result = _evaluate(_issue(), comments, {10: _closed(), 11: {"state": "open"}})
    assert result["verdict"] == "waiting_on_dependencies"
    assert result["reasons"] == ["#11"]


def test_block_style_dependency_list_is_read() -> None:
    receipt = _receipt('\n  - "#10"\n  - https://github.com/acme/repo/issues/11')
    result = _evaluate(_issue(), [receipt], {10: _closed(), 11: _closed()})
    assert result["dependencies"] == {"#10": "completed", "#11": "completed"}


def test_comment_permalinks_are_evidence_and_foreign_refs_are_unresolvable() -> None:
    assert classify_ref("https://github.com/acme/repo/issues/9#issuecomment-123", REPO) == ("evidence", None)
    assert classify_ref("https://github.com/acme/repo/pull/9", REPO) == ("local", 9)
    assert classify_ref("other/repo#13", REPO) == ("unresolvable", None)
    assert classify_ref("https://github.com/other/repo/issues/9", REPO) == ("unresolvable", None)
    result = _evaluate(_issue(), [_receipt('["#10", "other/repo#13"]')], {10: _closed()})
    assert result["verdict"] == "unresolvable_refs"


def test_receipt_without_local_dependencies_cannot_be_checked() -> None:
    result = _evaluate(_issue(), [_receipt("[]")], {})
    assert result["verdict"] == "unresolvable_refs"
    assert result["reasons"] == ["no_local_dependency_refs"]


def test_self_reference_is_ignored() -> None:
    result = _evaluate(_issue(1), [_receipt('["#1", "#10"]')], {10: _closed()})
    assert result["dependencies"] == {"#10": "completed"}


def test_declared_predicate_replaces_dependency_refs() -> None:
    receipt = _receipt('["#10"]', extra='unblock_predicate: {"all_completed": ["#11"], "readiness": "strict"}')
    result = _evaluate(_issue(), [receipt], {10: {"state": "open"}, 11: _closed()})
    assert result["verdict"] == "candidate"
    assert result["predicate_source"] == "declared"


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("unblock_predicate: not json", "unblock_predicate_not_json"),
        ('unblock_predicate: {"all_completed": []}', "unblock_predicate_invalid"),
        ('unblock_predicate: {"all_completed": ["#1"], "readiness": "lenient"}', "unblock_predicate_invalid"),
        ('unblock_predicate: {"all_completed": ["#1"], "test_run": "x"}', "unblock_predicate_invalid"),
    ],
)
def test_invalid_predicate_fails_closed(line: str, error: str) -> None:
    assert parse_predicate(line) == (None, error)
    result = _evaluate(_issue(), [_receipt(extra=line)], {10: _closed()})
    assert result["verdict"] == "unresolvable_refs"
    assert result["reasons"] == [error]


def test_collect_pages_and_only_reads() -> None:
    calls: list[str] = []
    blocked_page = [_issue(n) for n in range(1, 101)]

    def fake_fetch(endpoint: str) -> Any:
        calls.append(endpoint)
        if endpoint.startswith(f"repos/{REPO}/issues?state=open&labels=agent:blocked"):
            return blocked_page if endpoint.endswith("page=1") else [_issue(101)]
        if "/comments" in endpoint:
            return [_receipt('["#500"]')]
        if endpoint == f"repos/{REPO}/issues/500":
            return _closed()
        raise AssertionError(endpoint)

    results = collect(REPO, [], fake_fetch)
    assert len(results) == 101
    assert all(item["verdict"] == "candidate" for item in results)
    # The shared dependency is read once, and no write endpoint is ever used.
    assert calls.count(f"repos/{REPO}/issues/500") == 1
    assert "| candidate | 101 |" in render_markdown(results)


def test_api_surface_is_get_only() -> None:
    source = (REPO_ROOT / "scripts/report_unblock_candidates.py").read_text(encoding="utf-8")
    assert '"--method", "GET"' in source
    for verb in ('"POST"', '"PATCH"', '"PUT"', '"DELETE"'):
        assert verb not in source
