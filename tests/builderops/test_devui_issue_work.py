from __future__ import annotations

from copy import deepcopy

import pytest

from app.builderops import cockpit_github_plane as github
from app.builderops.devui_focus import compose_focus_view
from app.builderops.devui_focus_inputs import read_focus_inputs
from app.builderops.devui_issue_work import read_issue_focus_results
from tests.builderops.test_devui_runtime import managed_sources as managed_sources


REPO = "example/fixture"
SUBJECT = f"github:{REPO}#501"
STAMP = "2026-09-24T12:00:00Z"


def _issue():
    return {
        "number": 501, "title": "Useful work", "state": "open",
        "labels": [{"name": "agent:ready"}],
        "html_url": f"https://github.com/{REPO}/issues/501", "updated_at": STAMP,
        "body": "## Context\nPreserve my context.\n\n## Scope\nOne change.\n",
    }


def _read(issue=None):
    return read_focus_inputs(
        SUBJECT, repository=REPO, issue_reader=lambda *_: issue or _issue(),
        owner_fact_reader=lambda: {}, issue_result_reader=read_issue_focus_results,
    )


def _pull(number=502, *, repo=REPO, body="Governing-Issue: #501", merged=False):
    return {
        "number": number, "html_url": f"https://github.com/{repo}/pull/{number}",
        "base": {"repo": {"full_name": repo}}, "head": {"sha": "d" * 40},
        "state": "closed" if merged else "open", "merged": merged,
        "merged_at": STAMP if merged else None, "merge_commit_sha": "e" * 40,
        "updated_at": STAMP, "body": body,
    }


def _event(number=502, repo=REPO):
    return {"event": "cross-referenced", "source": {"issue": {
        "html_url": f"https://github.com/{repo}/pull/{number}", "pull_request": {"url": "source-marker"},
    }}}


@pytest.mark.parametrize("state,labels,expected", [
    ("open", ["agent:ready"], "eligible and unclaimed"),
    ("open", ["agent:in-progress"], "valid ownership"),
    ("open", ["agent:blocked"], "Do not claim implementation"),
    ("open", ["agent:needs-human"], "Do not claim implementation"),
    ("closed", [], "Do not reopen or reimplement"),
    ("closed", ["agent:ready"], "active agent label remains"),
    ("open", [], "establish readiness"),
    (None, None, "missing or contradictory"),
    ({"unexpected": "open"}, [], "missing or contradictory"),
    (["open"], [], "missing or contradictory"),
    ("open", ["agent:ready", "agent:in-progress"], "missing or contradictory"),
])
def test_issue_state_and_handoff_preserve_authority(monkeypatch, state, labels, expected):
    monkeypatch.setattr(github, "_run_gh", lambda *_: [])
    issue = _issue()
    issue.update(state=state, labels=[{"name": label} for label in labels] if labels is not None else None)
    issue["title"] = "$(touch /tmp/unsafe)"
    result = compose_focus_view(**_read(issue))
    step = result["next_legal_step"]
    assert step["legality"] == "unavailable"
    assert step["actor_class"] == "owner"
    assert expected in step["reason"]
    assert issue["html_url"] in step["reason"]
    assert STAMP in step["reason"]
    assert result["subject"]["authority_ref"]["content_hash"] in step["reason"]
    assert issue["title"] not in step["reason"]
    assert "not approval" in step["reason"]
    assert result["conversation_port"]["availability"] == "unsupported"
    assert result["execution_observations"] == []


def test_selected_issue_results_require_exact_governed_relation(monkeypatch):
    calls = []
    pulls = {
        502: _pull(merged=True),
        503: _pull(503, body="Mentions #501\nFixes #501"),
        504: _pull(504, body="```\nGoverning-Issue: #501\n```"),
        505: _pull(505, body="Governing-Issue: #501\nGoverning-Issue: #999"),
        506: _pull(506, repo="foreign/repo"),
    }
    def api(args):
        calls.append(args)
        if args[1].endswith("/timeline"):
            return [_event(502), _event(502), _event(88, "foreign/repo"), *[_event(n) for n in range(503, 507)]]
        return pulls[int(args[1].split("/")[-1])]
    monkeypatch.setattr(github, "_run_gh", api)
    result = compose_focus_view(**_read())
    claims = [item for item in result["evidence"] if item["claim_id"].startswith("issue-pr:")]
    assert len(claims) == 1
    assert "PR #502 is merged" in claims[0]["claim"]
    assert "d" * 40 in claims[0]["claim"] and "e" * 40 in claims[0]["claim"]
    assert "https://github.com/example/fixture/pull/502/checks" in claims[0]["claim"]
    assert "not assessed" in claims[0]["claim"]
    assert result["receipts"][0]["correlation"]["authority_ref"] == result["subject"]["authority_ref"]
    assert not any("foreign" in str(call) for call in calls)
    assert sum(call[1].endswith("/pulls/502") for call in calls) == 1
    assert all(call[call.index("--method") + 1] == "GET" for call in calls)


@pytest.mark.parametrize("body", [
    "```text <!-- example -->\nGoverning-Issue: #501\n```",
    "```text\n<!--\n```\nGoverning-Issue: #999\nGoverning-Issue: #501",
    "<!--\n```\nGoverning-Issue: #501\n```\n-->",
    "Governing-Issue: #501\nGoverning-Issue:  #999",
    "Governing-Issue: #501\n Governing-Issue: #999",
    "Governing-Issue: #501\nGoverning-Issue: #501",
    "> Governing-Issue: #501",
    "Governing-Issue: #501\nGoverning-Issue:  #999 <!-- conflicting marker -->",
    "<!-- example --> <!--\nGoverning-Issue: #501\n-->",
    "<!-- example --> Governing-Issue: #501",
])
def test_result_relation_ignores_markdown_examples_and_conflicts(monkeypatch, body):
    monkeypatch.setattr(github, "_run_gh", lambda args: [_event()] if args[1].endswith("/timeline") else _pull(body=body))
    result = compose_focus_view(**_read())
    assert result["receipts"] == []
    assert not any(item["claim_id"].startswith("issue-pr:") for item in result["evidence"])


def test_result_relation_preserves_real_marker_after_comments(monkeypatch):
    body = "<!-- first --> <!-- second -->\n<!-- multiline\nGoverning-Issue: #999\n-->\nGoverning-Issue: #501\n```text <!--\nGoverning-Issue: #999\n```"
    monkeypatch.setattr(github, "_run_gh", lambda args: [_event()] if args[1].endswith("/timeline") else _pull(body=body))
    assert len(compose_focus_view(**_read())["receipts"]) == 1


@pytest.mark.parametrize("failure", ["unavailable", "malformed", "capped", "one_pull", "invalid_identity", "pull_cap"])
def test_result_failure_preserves_issue_context(monkeypatch, failure):
    def api(args):
        if args[1].endswith("/timeline"):
            if failure == "unavailable":
                raise github.GithubReadError("secret must not escape")
            if failure == "malformed":
                return {"unexpected": []}
            if failure == "capped":
                return [_event()] * 100
            if failure == "pull_cap":
                return [_event(n) for n in range(502, 508)]
            return [_event(502), _event(503)]
        number = int(args[1].split("/")[-1])
        if number == 503 and failure == "one_pull":
            raise github.GithubReadError("secret must not escape")
        result = _pull(number)
        if number == 503 and failure == "invalid_identity":
            result["html_url"] += "?foreign=1"
        return result
    monkeypatch.setattr(github, "_run_gh", api)
    result = compose_focus_view(**_read())
    assert "Preserve my context" in result["owner_intent"]["summary"]
    assert any(row["kind"] == "issue_results_unassessed" for row in result["limitations"])
    assert "secret must not escape" not in str(result)
    assert result["next_legal_step"]["legality"] == "unavailable"
    if failure in {"one_pull", "invalid_identity"}:
        assert len(result["receipts"]) == 1
        assert result["receipts"][0]["receipt_ref"].endswith("/502")
    elif failure == "pull_cap":
        assert len(result["receipts"]) == 5
    else:
        assert result["receipts"] == []


def test_managed_focus_refreshes_work_and_results(request):
    source = request.getfixturevalue("managed_sources")
    source.gh_mode.write_text("work_ready")
    with source.client() as client:
        response = client.get("/api/devui/focus", params={"subject": SUBJECT})
        assert response.status_code == 200, response.text
        ready = response.json()
        assert "eligible and unclaimed" in ready["next_legal_step"]["reason"]
        assert any("PR #502 is open" in row.get("claim", "") for row in ready["evidence"])
        source.gh_mode.write_text("work_merged")
        merged = client.get("/api/devui/focus", params={"subject": SUBJECT}).json()
        assert "Do not reopen or reimplement" in merged["next_legal_step"]["reason"]
        assert any("PR #502 is merged" in row.get("claim", "") for row in merged["evidence"])
        assert merged["receipts"] != ready["receipts"]
        source.gh_mode.write_text("work_result_unavailable")
        unavailable = client.get("/api/devui/focus", params={"subject": SUBJECT}).json()
        assert "Fixture owner intent" in unavailable["owner_intent"]["summary"]
        assert unavailable["receipts"] == []
        assert any(row["kind"] == "issue_results_unassessed" for row in unavailable["limitations"])
        previous = deepcopy(source.http_calls)
        assert client.post("/api/devui/focus", params={"subject": SUBJECT}).status_code == 405
        assert source.http_calls == previous
        assert all(method == "GET" for method, _ in source.http_calls)
