"""Multi-Issue PR scope: claim on an exact closing child, governing parent as validation hub.

Real shape of PR #6628: ``Governing-Issue: #6615`` (open epic, agent:blocked +
action:wait-dependency) and ``Closes #6619`` with an authenticated label-only
pickup on #6619. Real Git worktree and lifecycle registry; GitHub is a fake port.
"""
import json
import time

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer
from tests.builderops.test_openhands_pr_cycle import _github_time, _native_authority_fixture, cycle, setup


AGENT, SESSION = "openhands-6619-coordination", "openhands-6619-20261113"
PICKUP_ID = 6847143239
HUB_LABELS = ["agent:blocked", "prio:high", "type:epic", "action:wait-dependency"]


def _comment(comment_id, at, *, issue=6619, agent=AGENT, session=SESSION, path, branch="codex/example"):
    return {"id": comment_id, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
            "created_at": _github_time(at), "updated_at": _github_time(at),
            "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/{issue}",
            "body": f"Pickup intent receipt: agent={agent} session={session} branch={branch} worktree={path} "
                    f"coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue={issue}"}


def _body(path, *, issue=6619, closes="Closes #6619", comment_id=PICKUP_ID, branch="codex/example"):
    return ("Governing-Issue: #6615\n\n## Linked Issue\n"
            f"Pickup-Receipt: pickup-claim-complete issue={issue} branch={branch} worktree={path} "
            "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
            f"agent={AGENT} session={SESSION} evidence=github-comment:{comment_id}\n{closes}\n")


def _scope_fixture(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    worktree = str(f["worktree"])
    cycle.agent_worktree.register_worktree(f["source"], worktree=worktree, owner=SESSION,
                                           now=now - 1000, ttl_seconds=3600)
    parent_body = "epic contract\n### Child map\n| #6618 | open |\n| #6619 no-progress | OPEN |\n"
    issues = {6615: {"number": 6615, "state": "open", "title": "issue title", "body": parent_body,
                     "labels": [{"name": x} for x in HUB_LABELS]},
              6619: {"number": 6619, "state": "open", "title": "child", "body": "child contract",
                     "labels": [{"name": "type:task"}, {"name": "agent:in-progress"}]}}
    comments = {6615: [], 6619: [_comment(PICKUP_ID, now - 900, path=worktree)], 10: []}
    closing = [6619]
    body = _body(worktree)
    f["pr"].update(body=body, governing_issue={"body": parent_body})
    f["live"]["body"] = body
    f["entry"].update(coordination_mode="github-label-only-fallback", claimant=AGENT, session=SESSION,
                      fallback_reason="dispatcher_db_missing", coordination_evidence=f"github-comment:{PICKUP_ID}",
                      lease_id=None)
    calls = []

    class Executor:
        def __init__(self, **kwargs):
            pass

        def run(self, argv, *, cwd, input_text=None):
            calls.append(argv)
            if "app.dispatcher" in argv and "status" in argv:
                output = json.dumps({"ok": True, "db_exists": False, "coordination_mode": "github-label-only-fallback",
                                     "fallback_reason": "dispatcher_db_missing"})
            elif "--slurp" in argv:
                issue = next(int(a.split("/")[4]) for a in argv if "/issues/" in a)
                output = json.dumps([comments[issue]])
            else:
                output = "RasmusTho\n"
            return cycle.subprocess.CompletedProcess(argv, 0, output, "")

    def api(executor, cwd, repo, method, endpoint):
        if endpoint == "":
            return {"full_name": repo, "default_branch": "main"}
        for number, rows in comments.items():
            if endpoint.startswith(f"/issues/{number}/comments"):
                return rows
        return [{"filename": "app/example.py"}] if endpoint.startswith("/pulls/10/files") else []

    def dispatcher(*args):
        raise AssertionError("label-only fallback must not inspect a dispatcher task")

    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_api", api)
    monkeypatch.setattr(cycle.closure, "_issue", lambda executor, cwd, repo, number: issues[number])
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: list(closing))
    monkeypatch.setattr(cycle.closure, "_dispatcher_inspect", dispatcher)
    f.update(now=now, issues=issues, comments=comments, closing=closing, calls=calls, worktree_path=worktree)
    return f


def _review_shape(f):
    return {**f["pr"], "review_context": {}, "review_material": {}}


def test_child_pickup_owns_review_reservation_and_native_merge_authority(tmp_path, monkeypatch):
    f = _scope_fixture(tmp_path, monkeypatch)
    pr = _review_shape(f)
    cycle._add_transfer_review_context(f["layout"], f["entry"], pr)
    assert pr["review_context"] == {} and pr["review_material"] == {}
    authority = cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority["governing_issue"] == 6615 and authority["closing_issues"] == [6619]
    assert authority["claim_issue"] == 6619
    assert authority["owner"]["mode"] == "github-label-only-fallback"
    assert authority["owner"]["comment_id"] == PICKUP_ID
    assert authority["worktree_owner"]["owner"] == SESSION
    # Parent contract identity remains the governing body, not the child's.
    assert authority["governing_issue_hashes"] == cycle.closure._issue_hashes(f["issues"][6615])
    # Ownership reads use the child's comments only; the parent's hub labels were not edited.
    assert any("issues/6619/comments" in " ".join(argv) for argv in f["calls"])
    assert not any("issues/6615/comments" in " ".join(argv) for argv in f["calls"])
    assert [x["name"] for x in f["issues"][6615]["labels"]] == HUB_LABELS


def test_advance_reaches_review_reservation_for_real_multi_issue_shape(tmp_path, monkeypatch):
    f = _scope_fixture(tmp_path, monkeypatch)
    server = FakeAgentServer()
    entry = {**f["entry"], "head_sha": f["head"]}
    monkeypatch.setattr(ew, "inspect_checkout", lambda _layout, _worker: {
        "readable": True, "head": f["head"], "uncommitted_count": 0})

    def fetch(path, timeout):
        if "/pulls?" in path:
            data = [{"number": 10}]
        elif "/pulls/10/reviews" in path:
            data = []
        elif "/pulls/10" in path:
            data = {"number": 10, "state": "open", "body": f["pr"]["body"], "draft": False, "labels": [],
                    "title": "trial", "head": {"sha": f["head"], "repo": {"full_name": cycle.completion.REPOSITORY}},
                    "base": {"sha": "b" * 40, "ref": "main"}}
        elif "/issues/6615" in path:
            data = {"number": 6615, "state": "open", "body": f["issues"][6615]["body"]}
        else:
            raise AssertionError(path)
        return 200, json.dumps(data).encode()

    result = cycle.advance(f["layout"], [entry], fetch=fetch, http=server)
    assert [row["action"] for row in result["results"]] == ["independent-review"], result
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    # The same normal path still refuses a pickup outside the exact closing scope.
    f["pr"]["body"] = f["live"]["body"] = _body(f["worktree_path"], issue=6618)
    second = cycle.advance(f["layout"], [entry], fetch=fetch, http=server)
    assert second["results"][0]["action"] == "wait"
    assert "cannot establish the governing owner" in second["results"][0]["reason"]


@pytest.mark.parametrize("defect, match", [
    ("child_not_in_closes", "cannot establish the governing owner"),
    ("two_receipts", "ambiguous"),
    ("missing_comment", "missing or unauthenticated"),
    ("foreign_author", "missing or unauthenticated"),
    ("edited_comment", "edited fallback pickup"),
    ("comment_on_parent", "does not match its claimed owner"),
    ("wrong_branch", "wrong branch"),
    ("wrong_path", "does not match its claimed owner"),
    ("later_rival_pickup", "conflicting fallback pickup"),
])
def test_child_pickup_provenance_is_strict_at_review_reservation(tmp_path, monkeypatch, defect, match):
    f = _scope_fixture(tmp_path, monkeypatch)
    path, now = f["worktree_path"], f["now"]
    child = f["comments"][6619]
    if defect == "child_not_in_closes":
        f["pr"]["body"] = f["live"]["body"] = _body(path, closes="Closes #6618")
        f["closing"][:] = [6618]
    elif defect == "two_receipts":
        f["pr"]["body"] = f["live"]["body"] = _body(path) + _body(path).split("\n", 3)[3]
    elif defect == "missing_comment":
        child.clear()
    elif defect == "foreign_author":
        child[0]["user"] = {"login": "someone-else"}
    elif defect == "edited_comment":
        child[0]["updated_at"] = _github_time(now - 10)
    elif defect == "comment_on_parent":
        moved = _comment(PICKUP_ID, now - 900, issue=6615, path=path)
        child[:] = [{**moved, "body": child[0]["body"]}]
    elif defect == "wrong_branch":
        f["pr"]["body"] = f["live"]["body"] = _body(path, branch="codex/old-terminal-branch")
    elif defect == "wrong_path":
        f["pr"]["body"] = f["live"]["body"] = _body("/elsewhere/issue-6619")
    elif defect == "later_rival_pickup":
        child.append(_comment(PICKUP_ID + 1, now - 100, agent="rival", session="session-rival", path=path))
    with pytest.raises(cycle.CycleError, match=match):
        cycle._add_transfer_review_context(f["layout"], f["entry"], _review_shape(f))
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("defect, match", [
    ("wrong_claimant", "current claimant differs"),
    ("wrong_session", "registered worktree"),
    ("wrong_worktree", "registered worktree"),
    ("expired_registration", "registered worktree"),
])
def test_child_pickup_requires_current_registered_owner(tmp_path, monkeypatch, defect, match):
    f = _scope_fixture(tmp_path, monkeypatch)
    entry = dict(f["entry"])
    if defect == "wrong_claimant":
        entry["claimant"] = "rival"
    elif defect == "wrong_session":
        entry["session"] = "session-rival"
    elif defect == "wrong_worktree":
        entry["owner_worktree"] = str(tmp_path / "other")
    else:
        cycle.agent_worktree.heartbeat_worktree(f["source"], worktree=f["worktree_path"], owner=SESSION,
                                               now=f["now"] - 500, ttl_seconds=60)
    with pytest.raises(cycle.CycleError, match=match):
        cycle._add_transfer_review_context(f["layout"], entry, _review_shape(f))
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], entry)


@pytest.mark.parametrize("labels, body", [
    (["agent:blocked", "type:epic", "action:wait-dependency", "agent:needs-human"], None),
    (["agent:needs-human", "type:epic", "action:human-decision"], None),
    (["agent:blocked", "type:epic", "action:wait-external"], None),
    (["agent:blocked", "type:epic", "action:wait-dependency", "action:review-at"], None),
    (["agent:blocked", "type:task", "action:wait-dependency"], None),
    (["agent:blocked", "type:epic"], None),
    (["agent:blocked", "type:epic", "action:wait-dependency", "hold"], None),
    (["agent:blocked", "type:epic", "action:wait-dependency", "do-not-merge"], None),
    (["agent:blocked", "agent:in-progress", "type:epic", "action:wait-dependency"], None),
    (HUB_LABELS, "epic contract without the delivered child"),
    (HUB_LABELS, "epic contract naming #66190 only"),
])
def test_explicit_parent_holds_still_refuse_native_authority(tmp_path, monkeypatch, labels, body):
    f = _scope_fixture(tmp_path, monkeypatch)
    f["issues"][6615]["labels"] = [{"name": x} for x in labels]
    if body is not None:
        f["issues"][6615]["body"] = f["pr"]["governing_issue"]["body"] = body
    with pytest.raises(cycle.CycleError, match="held or unreadable"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_unblocked_parent_child_holds_and_parent_contract_drift(tmp_path, monkeypatch):
    f = _scope_fixture(tmp_path, monkeypatch)
    # An unblocked open parent is an ordinary governing contract.
    f["issues"][6615]["labels"] = [{"name": "type:epic"}]
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["claim_issue"] == 6619
    f["issues"][6615]["labels"] = [{"name": x} for x in HUB_LABELS]
    f["issues"][6619]["labels"].append({"name": "agent:needs-human"})
    with pytest.raises(cycle.CycleError, match="held or unreadable"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["issues"][6619]["labels"].pop()
    f["issues"][6619]["state"] = "closed"
    with pytest.raises(cycle.CycleError, match="claimed closing Issue is not open"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["issues"][6619]["state"] = "open"
    f["issues"][6615]["body"] += "edited\n"
    with pytest.raises(cycle.CycleError, match="governing Issue contract or state drifted"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_parent_claim_keeps_ordinary_parent_holds(tmp_path, monkeypatch):
    """When the pickup is on the governing Issue, its hub labels are a real hold."""
    f = _scope_fixture(tmp_path, monkeypatch)
    path = f["worktree_path"]
    f["comments"][6615][:] = [_comment(PICKUP_ID, f["now"] - 900, issue=6615, path=path)]
    f["pr"]["body"] = f["live"]["body"] = _body(path, issue=6615)
    with pytest.raises(cycle.CycleError, match="held or unreadable"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("issue", [6619, 6615])
def test_another_unbranched_writer_on_child_or_parent_refuses(tmp_path, monkeypatch, issue):
    f = _scope_fixture(tmp_path, monkeypatch)
    ew._reserve_worker(f["layout"], issue, f"writer-{issue}", state="running", runtime="openhands",
                       port=18801, container_id="e" * 64)
    with pytest.raises(cycle.CycleError, match="another worker may write"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def _reconcile_fixture(tmp_path, monkeypatch, *, mode="github-label-only-fallback"):
    layout, _, _ = setup(tmp_path, monkeypatch)
    files = [{"filename": "app/example.py"}]
    parent = {"number": 6615, "state": "open", "title": "issue title", "body": "epic #6619",
              "labels": [{"name": x} for x in HUB_LABELS]}
    child = {"number": 6619, "state": "closed", "title": "child", "body": "child contract",
             "labels": [{"name": "type:task"}, {"name": "agent:in-progress"}]}
    issues = {6615: parent, 6619: child}
    receipt = "post-merge owner-doc check: PR #10; no owner-doc change implied."
    head = "a" * 40
    owner = ({"mode": mode, "comment_id": PICKUP_ID} if mode == "github-label-only-fallback" else
             {"task_id": "task-6619", "repository": cycle.completion.REPOSITORY, "issue_number": "6619",
              "lease_holder": AGENT, "lease_id": "lease", "lease_expires_at": "2099-01-01T00:00:00Z", "linked_pr": "10"})
    intent = {"number": 10, "head_sha": head, "body": "body", "title": "title", "governing_issue": 6615,
              "governing_issue_hashes": cycle.closure._issue_hashes(parent), "closing_issues": [6619],
              "claim_issue": 6619, "owner": owner, "coordination_mode": mode,
              "closing_issue_hashes": {"6619": cycle.closure._issue_hashes(child)},
              "files_digest": cycle.hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "owner_doc_receipt": receipt}
    saved = {"kind": "pr_cycle", "number": 10, "identity": "id", "merge_intent": intent}
    cycle._save(layout, saved)
    posted = {6615: [], 6619: []}
    effects = []

    class Executor:
        def __init__(self, **kwargs):
            pass

        def run(self, argv, *, cwd, input_text=None):
            effects.append(argv)
            if "POST" in argv:
                target = int(argv[6].split("/")[4])
                posted[target].append({"body": receipt, "user": {"login": "RasmusTho"}})
            elif argv[:3] == ["gh", "issue", "edit"]:
                label = argv[argv.index("--remove-label") + 1]
                issues[int(argv[3])]["labels"] = [x for x in issues[int(argv[3])]["labels"] if x["name"] != label]
            return cycle.subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"state": "closed", "merged_at": "now",
                        "head": {"sha": head}, "merge_commit_sha": "b" * 40, "body": "body", "title": "title"})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6619])
    monkeypatch.setattr(cycle.closure, "_issue", lambda executor, cwd, repo, number: issues[number])
    monkeypatch.setattr(cycle.closure, "_issue_events", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_closure_evidence", lambda *args: {})
    monkeypatch.setattr(cycle.closure, "_validate_closure_attribution", lambda *args: None)
    monkeypatch.setattr(cycle, "_api_pages", lambda executor, cwd, endpoint: files if endpoint.endswith("/files")
                        else posted[int(endpoint.split("/")[2])])
    return {"layout": layout, "saved": saved, "issues": issues, "posted": posted, "effects": effects,
            "intent": intent}


def test_reconcile_closes_child_scope_and_keeps_parent_open_with_receipt(tmp_path, monkeypatch):
    r = _reconcile_fixture(tmp_path, monkeypatch)
    assert cycle.reconcile_native(r["layout"], r["saved"])["action"] == "merged"
    assert len(r["posted"][6615]) == len(r["posted"][6619]) == 1
    assert [x["name"] for x in r["issues"][6619]["labels"]] == ["type:task"]
    assert [x["name"] for x in r["issues"][6615]["labels"]] == HUB_LABELS
    assert not any("app.dispatcher" in argv for argv in r["effects"])
    assert cycle._find(r["layout"], 10, "id")["reconciled"] is True


def test_reconcile_refuses_claim_outside_scope_and_does_not_repeat_unknown_effect(tmp_path, monkeypatch):
    r = _reconcile_fixture(tmp_path, monkeypatch)
    for bad in (6618, "6619"):
        with pytest.raises(cycle.CycleError, match="outside the PR scope"):
            cycle.reconcile_native(r["layout"], {**r["saved"], "merge_intent": {**r["intent"], "claim_issue": bad}})
    assert r["effects"] == []
    pending = {**r["saved"], "owner_doc": {"6615": "pending"}}
    with pytest.raises(cycle.CycleError, match="comment outcome remains unknown"):
        cycle.reconcile_native(r["layout"], pending)
    assert not any("POST" in argv for argv in r["effects"])
    r["issues"][6615]["state"] = "closed"
    with pytest.raises(cycle.CycleError, match="did not remain open"):
        cycle.reconcile_native(r["layout"], r["saved"])


def test_reconcile_completes_the_claimed_child_dispatcher_task(tmp_path, monkeypatch):
    r = _reconcile_fixture(tmp_path, monkeypatch, mode="dispatcher-backed")
    seen = []
    monkeypatch.setattr(cycle, "_dispatcher_after_merge",
                        lambda layout, saved, owner, executor, cwd, issue, number: seen.append((issue, number)))
    assert cycle.reconcile_native(r["layout"], r["saved"])["action"] == "merged"
    assert seen == [(6619, 10)]


@pytest.mark.parametrize("marker", ["verified_issue_set_merge_authority.v1", "verification_dispatch_request.v3"])
def test_child_claim_keeps_fenced_executor_receipts_out_of_native_merge(tmp_path, monkeypatch, marker):
    f = _scope_fixture(tmp_path, monkeypatch)
    f["comments"][10].append({"id": 1, "body": f"{marker}: pending"})
    with pytest.raises(cycle.CycleError, match="verification or fenced authority receipt"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
