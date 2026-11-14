"""Freshness at the real coordinator/effect boundary with synthetic external ports."""
from __future__ import annotations

import json
import time
import uuid
from unittest.mock import patch

import pytest

from app.builderops import epic_coordination as coord
from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_coordination_assignment_fence import Harness, ISSUE


@pytest.fixture(autouse=True)
def short_stall_for_fixture(monkeypatch):
    monkeypatch.setattr(coord, "STALL_SECONDS", 0.0)


def _failure(event_id, detail):
    return {"id": event_id, "kind": "ConversationErrorEvent", "code": "ToolError", "detail": detail}


@pytest.mark.parametrize(
    ("details", "unrelated", "expected"),
    [
        (("pytest tests/test_alpha.py::test_case_1", "pytest tests/test_alpha.py::test_case_2"), False, None),
        (("pytest tests/test_alpha.py::test_case_A", "pytest tests/test_alpha.py::test_case_B"), False, None),
        (("process failed (pid 1234)", "process failed (pid 1235)"), False, None),
        (("pytest tests/test_alpha.py::test_case_1", "pytest tests/test_alpha.py::test_case_1"), True, None),
        (("pytest tests/test_alpha.py::test_case_1", "pytest tests/test_alpha.py::test_case_1"), False, "active_failure_review"),
    ],
)
def test_active_error_identity_and_current_operation(tmp_path, monkeypatch, details, unrelated, expected):
    # Production guard and three-tick ladder, with a synthetic clock as in the original probe.
    monkeypatch.setattr(coord, "STALL_SECONDS", 60.0)
    h = Harness(tmp_path / "owned")
    h.execution = "running"
    cid = h.cids[ISSUE]
    base = time.time()
    count = 0

    def tick(name):
        nonlocal count
        with patch.object(coord.time, "time", return_value=base + 61 * count):
            result = coord.coordinate(h.layout, tick=name, stall_limit=3, runner=h.runner,
                                      http=h.http, fetch=h.fetch, apply=True)["items"][0]
        count += 1
        return result

    for name in ("baseline", "wait-1", "wait-2", "diagnosis"):
        tick(name)
    h.events[cid].append(_failure("failure-1", details[0]))
    tick("failure-1")
    h.events[cid].append(_failure("failure-2", details[1]))
    tick("failure-2")
    if unrelated:
        h.events[cid].append({"id": "new-operation", "kind": "ActionEvent", "source": "agent"})
    result = tick("current")
    assert result["action"] == expected and h.posts == []
    evidence = h.mapping()["coordination"]
    if unrelated:
        assert evidence["failure_events"] == [] and evidence["failure_signature"] is None
    if expected:
        assert result["state"] == "stopped_active_unconfirmed"
        assert evidence["failure_events"] == ["failure-1", "failure-2"]
        assert any(row.get("stop") == "active_failure_review" for row in h.state()["stop_conditions"])


@pytest.mark.parametrize("intervening", [
    {"id": "new-operation", "kind": "ActionEvent", "source": "agent"},
    _failure("different-error", "different error"),
])
def test_intervening_unobserved_event_invalidates_error_history(tmp_path, intervening):
    h = Harness(tmp_path / "owned")
    h.execution = "running"
    cid = h.cids[ISSUE]
    h.run("baseline")
    h.events[cid].append(_failure("first", "same error"))
    h.run("diagnosis")
    h.events[cid].extend([intervening, _failure("second", "same error")])
    item = h.run("later-error")["items"][0]
    assert item["action"] is None and not h.posts
    assert h.mapping()["coordination"]["failure_events"] == ["second"]


def _pr(h):
    return [{"number": 6628, "state": "open", "draft": False,
             "body": f"Governing-Issue: #{h.epic}\nFixes #{ISSUE}",
             "head": {"ref": f"b/{ISSUE}", "sha": "a" * 40,
                      "repo": {"full_name": coord.github_read.REPOSITORY}},
             "base": {"repo": {"full_name": coord.github_read.REPOSITORY}}}]


@pytest.mark.parametrize("change", ["checkout", "tests", "validation", "pr", "event", "execution", "unreadable"])
def test_fresh_applied_decision_rechecks_real_evidence_after_reservation(tmp_path, change):
    h = Harness(tmp_path / "owned")
    h.run("baseline")
    reads = 0
    changed = []
    original_fetch = h.fetch
    new_pr = False

    def fetch(path, timeout):
        nonlocal reads, new_pr
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 4:
                assert not h.posts and any(e["outcome"] == "reserved" for e in h.effects())
                if change == "checkout":
                    (h.layout.checkout("worker-0") / "fresh_work.py").write_text("new work\n")
                elif change == "tests":
                    cache = h.layout.checkout("worker-0") / coord.TEST_CACHE_FILE
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"tests/test_x.py::test_1": True}))
                elif change == "validation":
                    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                        expected_epic_issue_number=h.epic,
                        updater=lambda state: _validation_update(state))
                elif change == "pr":
                    new_pr = True
                elif change == "event":
                    h.events[h.cids[ISSUE]].append({"id": "new-operation", "kind": "ActionEvent", "source": "agent"})
                elif change == "execution":
                    h.execution = "running"
                else:
                    (h.layout.checkout("worker-0") / "unreadable.py").symlink_to(tmp_path / "outside")
                changed.append(True)
        if "/pulls?" in path and new_pr:
            return 200, json.dumps(_pr(h)).encode()
        return original_fetch(path, timeout)

    h.fetch = fetch
    item = h.run("fresh-applied")["items"][0]
    assert changed and h.posts == [] and item["effects"][0]["outcome"] == "refused"
    assert h.effects()[0]["attempts"] == 0
    if change in {"checkout", "tests", "validation", "pr"}:
        next_item = h.run("observe-progress")["items"][0]
        assert next_item["state"] == "progressing" and change in next_item["changed_parts"]
    elif change in {"event", "execution"}:
        # The refused send does not strand the item: the existing bounded ladder continues.
        next_item = h.run("diagnose-after-refusal")["items"][0]
        assert next_item["action"] == "bounded_diagnosis" and h.posts == []


def test_fresh_checkout_change_with_production_stall_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(coord, "STALL_SECONDS", 60.0)
    h = Harness(tmp_path / "owned")
    base, reads = time.time(), 0
    with patch.object(coord.time, "time", return_value=base):
        h.run("baseline")

    def write_at_boundary(path):
        nonlocal reads
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 4:
                assert any(e["outcome"] == "reserved" for e in h.effects())
                (h.layout.checkout("worker-0") / "fresh_work.py").write_text("new work\n")

    h.fetch_hook = write_at_boundary
    with patch.object(coord.time, "time", return_value=base + 61):
        item = h.run("fresh-applied")["items"][0]
    assert reads == 4 and item["action"] == "change_approach"
    assert item["effects"][0]["outcome"] == "refused" and h.posts == []


def _validation_update(state):
    state["validation_status"][str(ISSUE)] = {"pytest": "failed"}
    return state


def test_unreadable_final_evidence_holds_only_affected_worker(tmp_path):
    h = Harness(tmp_path / "owned", count=2)
    h.run("baseline")
    reads = 0
    unavailable = False
    original_fetch, original_http = h.fetch, h.http

    def fetch(path, timeout):
        nonlocal reads, unavailable
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 4:
                assert any(e["outcome"] == "reserved" for e in h.effects())
                unavailable = True
        return original_fetch(path, timeout)

    def http(method, port, key, path, body, timeout):
        if unavailable and method == "GET" and "/events/search" in path and h.cids[ISSUE] in path:
            return 503, None
        return original_http(method, port, key, path, body, timeout)

    h.fetch, h.http = fetch, http
    items = {item["issue"]: item for item in h.run("final-gap")["items"]}
    assert items[ISSUE]["effects"][0]["outcome"] == "refused"
    assert h.posts == [h.cids[ISSUE + 1]]
    assert items[ISSUE + 1]["effects"][0]["outcome"] == "delivered"


def test_malformed_latest_event_is_unknown_instead_of_reusing_an_old_id(tmp_path):
    h = Harness(tmp_path / "owned")
    cid = h.cids[ISSUE]
    h.events[cid].extend([_failure("old", "failed"), {"kind": "ActionEvent"}])
    item = h.run("malformed")["items"][0]
    assert item["evidence_gaps"]["failure"] == "event_identity_unavailable"
    assert h.posts == []


def test_final_assignment_change_preserves_successor(tmp_path):
    h = Harness(tmp_path / "owned")
    h.run("baseline")
    reads = 0
    successor = {"id": str(uuid.uuid4()), "status": "created"}

    def change_on_final_authority(path):
        nonlocal reads
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 4:
                assert any(e["outcome"] == "reserved" for e in h.effects())
                ew._record_worker(h.layout, ISSUE, conversation=successor, next_action="successor owns this work")

    h.fetch_hook = change_on_final_authority
    item = h.run("changed-assignment")["items"][0]
    assert item["effects"][0]["outcome"] == "refused" and not h.posts
    assert h.mapping()["conversation"] == successor and h.mapping()["next_action"] == "successor owns this work"


def test_failure_projection_does_not_copy_error_or_native_message(tmp_path):
    h = Harness(tmp_path / "owned")
    h.execution = "running"
    cid = h.cids[ISSUE]
    private_text = "synthetic-private-message-and-secret-246810"
    h.events[cid].extend([
        {"id": "private-message", "kind": "MessageEvent", "source": "agent",
         "llm_message": {"role": "assistant", "content": [{"type": "text", "text": private_text}]}},
        _failure("error", private_text),
    ])
    h.run("baseline")
    state = json.dumps(h.state())
    assert private_text not in state and "x" * 40 not in state
    assert h.mapping()["coordination"]["parts"]["failure"] not in (None, "none")


@pytest.mark.parametrize("changed", [False, True])
def test_replayed_judgment_rechecks_evidence_at_effect(tmp_path, changed):
    h = Harness(tmp_path / "owned")
    h.run("baseline")
    assert h.run("judged", apply=False)["items"][0]["action"] == "change_approach"
    if changed:
        (h.layout.checkout("worker-0") / "new.py").write_text("work\n")
    item = h.run("judged")["items"][0]
    assert item["replayed"] is True
    assert item["effects"][0]["outcome"] == ("refused" if changed else "delivered")
    assert len(h.posts) == (0 if changed else 1)
    if changed:
        assert h.run("fresh")["items"][0]["state"] == "progressing"
