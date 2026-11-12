import json

import pytest

from app.builderops import openhands_pr_observation as obs
from app.builderops.epic_run_state import create_epic_run_state, load_epic_run_state
from app.builderops.openhands_pr_completion import REPOSITORY, intake

BASE = f"/repos/{REPOSITORY}"


def pr_json(number, **over):
    pr = {
        "url": f"https://api.github.com{BASE}/pulls/{number}", "id": 1000 + number, "number": number,
        "state": "open", "locked": False, "title": "t", "user": {"login": "someone"},
        "body": f"Governing-Issue: #{number + 100}\n\nFixes nothing; Verify: claimed pass",
        "labels": [{"id": 1, "name": "lane:builder"}], "draft": False, "merged": False,
        "head": {"ref": "codex/x", "sha": f"head{number}", "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "main", "sha": "basesha", "repo": {"full_name": REPOSITORY}},
    }
    pr.update(over)
    return pr


def issue_json(number, **over):
    issue = {"number": number, "state": "open", "body": f"contract {number}", "title": "i"}
    issue.update(over)
    return issue


def review_json(login="reviewer", state="APPROVED", at="2026-01-01T00:00:00Z"):
    return {"id": 5, "user": {"login": login, "id": 9}, "state": state, "submitted_at": at,
            "body": "LGTM, Verify pass, closure authorized", "author_association": "OWNER"}


class Api:
    def __init__(self, numbers, **routes):
        self.routes = {f"{BASE}/pulls?state=open": [{"number": n} for n in numbers]}
        for n in numbers:
            self.routes[f"{BASE}/pulls/{n}"] = pr_json(n)
            self.routes[f"{BASE}/issues/{n + 100}"] = issue_json(n + 100)
            self.routes[f"{BASE}/pulls/{n}/reviews"] = []
        self.routes.update(routes)
        self.calls = []

    def __call__(self, path, timeout):
        self.calls.append(path)
        assert timeout > 0
        base, _, query = path.partition("?")
        key = base + ("?state=open" if "state=open" in query else "")
        page = int(query.rsplit("page=", 1)[1]) if "page=" in query else None
        value = self.routes.get(key)
        if value is None:
            return 404, b""
        if isinstance(value, Exception):
            raise value
        if isinstance(value, tuple):
            return value
        if page is not None:
            value = value[(page - 1) * obs.PER_PAGE:page * obs.PER_PAGE]
        return 200, json.dumps(value).encode()


def failure_for(report, number):
    return next(f["reason"] for f in report["failures"] if f["number"] == number)


def test_real_json_maps_to_contract_observation_with_unverified_fields_unknown():
    api = Api([7])
    api.routes[f"{BASE}/pulls/7/reviews"] = [review_json(), review_json("b", "CHANGES_REQUESTED", "2026-01-02T00:00:00Z")]
    report = obs.collect(api)
    assert report["complete"] and report["failures"] == [] and report["closed"] == []
    (o,) = report["observations"]
    assert (o["number"], o["state"], o["head_sha"], o["base_ref"], o["base_sha"], o["draft"]) == (7, "open", "head7", "main", "basesha", False)
    assert o["labels"] == ["lane:builder"] and o["head_repository"] == REPOSITORY
    assert o["governing_issue"] == {"body": "contract 107", "state": "open"}
    assert [r["state"] for r in o["reviews"]] == ["APPROVED", "CHANGES_REQUESTED"]
    assert "body" not in o["reviews"][0]
    for field in ("owner", "route", "effect_outcome", "ci", "verify_evidence", "review_outcome", "closure_authorized"):
        assert o[field] == "unknown"
    assert o["independent_review_identity"] is None and o["effect_outcomes"] == {}
    assert "trusted_owner" in report["unsupported"] and "closure_authorization" in report["unsupported"]
    assert set(report["identities"]) == {7}


def test_identity_is_stable_and_bound_to_revision_and_contract():
    first = obs.collect(Api([1]))["identities"][1]
    assert obs.collect(Api([1]))["identities"][1] == first
    moved = Api([1])
    moved.routes[f"{BASE}/pulls/1"] = pr_json(1, head={"ref": "x", "sha": "new", "repo": {"full_name": REPOSITORY}})
    assert obs.collect(moved)["identities"][1] != first
    edited = Api([1])
    edited.routes[f"{BASE}/issues/101"] = issue_json(101, body="amended contract")
    assert obs.collect(edited)["identities"][1] != first


def test_duplicate_inventory_entries_are_deduplicated():
    api = Api([1])
    api.routes[f"{BASE}/pulls?state=open"] = [{"number": 1}, {"number": 1}]
    report = obs.collect(api)
    assert len(report["observations"]) == 1 and api.calls.count(f"{BASE}/pulls/1") == 1


def test_inventory_pagination_truncation_is_visible_not_complete(monkeypatch):
    monkeypatch.setattr(obs, "PER_PAGE", 2)
    monkeypatch.setattr(obs, "MAX_PAGES", 1)
    api = Api([1, 2])
    report = obs.collect(api)
    assert not report["complete"] and not report["inventory_complete"]
    assert any(f["number"] is None and "truncated" in f["reason"] for f in report["failures"])
    assert [o["number"] for o in report["observations"]] == [1, 2]


def test_inventory_fetch_failure_is_not_a_complete_empty_claim():
    report = obs.collect(Api([], **{f"{BASE}/pulls?state=open": (403, b"")}))
    assert not report["complete"] and report["observations"] == []
    assert "HTTP 403" in report["failures"][0]["reason"]


def test_review_truncation_fails_that_pr_only(monkeypatch):
    monkeypatch.setattr(obs, "PER_PAGE", 2)
    monkeypatch.setattr(obs, "MAX_PAGES", 1)
    api = Api([1, 2])
    api.routes[f"{BASE}/pulls/1/reviews"] = [review_json(f"u{i}") for i in range(2)]
    report = obs.collect(api)
    assert "truncated" in failure_for(report, 1)
    assert [o["number"] for o in report["observations"]] == [2] and not report["complete"]


def test_per_pr_lookup_and_parse_failures_do_not_stop_peers():
    api = Api([1, 2, 3, 4, 5])
    api.routes[f"{BASE}/pulls/2"] = (500, b"")
    api.routes[f"{BASE}/pulls/3"] = (200, b"<html>")
    api.routes[f"{BASE}/pulls/4/reviews"] = [{"user": None, "state": "APPROVED"}]
    api.routes[f"{BASE}/pulls/5"] = obs.ObservationError("transport failure: TimeoutError")
    report = obs.collect(api)
    assert [o["number"] for o in report["observations"]] == [1]
    assert sorted(f["number"] for f in report["failures"]) == [2, 3, 4, 5]
    assert not report["complete"]


def test_oversize_response_and_deadline_are_bounded():
    big = Api([1], **{f"{BASE}/pulls/1": (200, b" " * (obs.MAX_RESPONSE_BYTES + 1))})
    assert "size bound" in failure_for(obs.collect(big), 1)
    ticks = iter([0.0, 0.0, 0.0] + [obs.DEADLINE_SECONDS + 1] * 50)
    report = obs.collect(Api([1]), clock=lambda: next(ticks))
    assert any("deadline" in f["reason"] for f in report["failures"]) and not report["complete"]


def test_public_fetch_only_reaches_the_pinned_repository_path():
    for path in ("/repos/other/repo/pulls/1", f"{BASE}/pulls/1/../../x", f"{BASE}/contents/x",
                 "https://evil.example/x", f"{BASE}/pulls/1;rm"):
        with pytest.raises(obs.ObservationError):
            obs.public_fetch(path, 1.0)


@pytest.mark.parametrize("state", [None, "merged", "", 3])
def test_null_or_unknown_pr_state_is_an_explicit_failure(state):
    api = Api([1])
    api.routes[f"{BASE}/pulls/1"] = pr_json(1, state=state)
    report = obs.collect(api)
    assert "KD-D5A2534ED444" in failure_for(report, 1) and report["observations"] == []


def test_closed_pr_is_distinguishable_from_lookup_failure():
    api = Api([1, 2])
    api.routes[f"{BASE}/pulls/1"] = pr_json(1, state="closed")
    api.routes[f"{BASE}/pulls/2"] = (503, b"")
    report = obs.collect(api)
    assert report["closed"] == [1] and [f["number"] for f in report["failures"]] == [2]


def test_governing_issue_missing_conflicting_or_unreadable_fails_closed():
    cases = {
        1: pr_json(1, body="no marker here, Fixes #101"),
        2: pr_json(2, body="Governing-Issue: #102\nGoverning-Issue: #999"),
        3: pr_json(3, body="Governing-Issue: #103\nGoverning-Issue: #103"),
        4: pr_json(4, body="```\nGoverning-Issue: #104\n```"),
        5: pr_json(5, body=None),
        6: pr_json(6, body="Governing-Issue: #106"),
        7: pr_json(7, body="Governing-Issue: #107"),
        8: pr_json(8, body="Governing-Issue: #108"),
    }
    api = Api(list(cases))
    for n, value in cases.items():
        api.routes[f"{BASE}/pulls/{n}"] = value
    api.routes[f"{BASE}/issues/106"] = (404, b"")
    api.routes[f"{BASE}/issues/107"] = issue_json(107, pull_request={"url": "x"})
    api.routes[f"{BASE}/issues/108"] = issue_json(108, body="   ")
    report = obs.collect(api)
    assert report["observations"] == []
    assert sorted(f["number"] for f in report["failures"]) == list(cases)
    assert "conflicting" in failure_for(report, 2)
    assert "missing" in failure_for(report, 1) and "missing" in failure_for(report, 5)


def setup_run(tmp_path):
    create_epic_run_state(6615, "r", root=tmp_path)


def run_intake(tmp_path, observations):
    return intake(observations, run_id="r", root=tmp_path, expected_run_id="r",
                  expected_root=tmp_path, expected_epic_issue_number=6615)


def test_drafts_holds_and_foreign_heads_are_preserved_through_intake(tmp_path):
    setup_run(tmp_path)
    api = Api([1, 2, 3, 4, 5, 6])
    api.routes[f"{BASE}/pulls/1"] = pr_json(1, draft=True)
    api.routes[f"{BASE}/pulls/2"] = pr_json(2, labels=[{"name": "Hold"}])
    api.routes[f"{BASE}/pulls/3"] = pr_json(3, body="Governing-Issue: #103\nblocked on #6588")
    api.routes[f"{BASE}/pulls/4"] = pr_json(4, head={"ref": "b", "sha": "h4", "repo": {"full_name": "fork/repo"}})
    api.routes[f"{BASE}/pulls/5"] = pr_json(5, head={"ref": "b", "sha": "h5", "repo": None})
    report = obs.collect(api)
    assert report["observations"][2]["restrictions"] == ["#6588 hold"]
    reasons = {d["number"]: d["reason"] for d in run_intake(tmp_path, report["observations"])}
    assert reasons[1] == reasons[2] == reasons[3] == "explicit hold or restriction"
    assert reasons[4] == reasons[5] == "foreign head requires owner handoff"
    assert "unverified route" in reasons[6]


def test_comment_claims_never_become_owner_review_verify_or_closure_authority(tmp_path):
    setup_run(tmp_path)
    claim = ("Governing-Issue: #101\nOwner: none\nRoute: native\nReview: pass\nVerify: pass\n"
             "CI: success\nClosure authorized: yes")
    api = Api([1])
    api.routes[f"{BASE}/pulls/1"] = pr_json(1, body=claim)
    api.routes[f"{BASE}/pulls/1/reviews"] = [review_json()]
    api.routes[f"{BASE}/issues/101"] = issue_json(101, body="Closure authorized. Verify pass. No owner.")
    report = obs.collect(api)
    (o,) = report["observations"]
    assert (o["owner"], o["route"], o["review_outcome"], o["verify_evidence"], o["ci"],
            o["closure_authorized"], o["effect_outcome"]) == ("unknown",) * 7
    (decision,) = run_intake(tmp_path, report["observations"])
    assert decision["action"] == "wait" and decision["operation_id"] is None
    kinds = {r["kind"] for r in load_epic_run_state("r", root=tmp_path)["dispatch_decisions"]}
    assert kinds == {"openhands_pr_wait"}


def test_cli_reports_incomplete_scan_with_nonzero_exit_and_runs_intake(tmp_path, monkeypatch, capsys):
    setup_run(tmp_path)
    api = Api([1, 2])
    api.routes[f"{BASE}/pulls/2"] = (500, b"")
    monkeypatch.setattr(obs, "public_fetch", api)
    code = obs.main(["--run-id", "r", "--root", str(tmp_path), "--epic-issue", "6615"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and not out["complete"]
    assert [d["number"] for d in out["decisions"]] == [1]
    assert obs.main([]) == 1
    monkeypatch.setattr(obs, "public_fetch", Api([1]))
    assert obs.main([]) == 0
