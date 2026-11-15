"""Decision recovery through the coordinator with real Git/state and synthetic external ports."""
from __future__ import annotations

import copy

import pytest

from app.builderops import epic_coordination as coord
from app.builderops import epic_coordination_effects as effects
from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_coordination_assignment_fence import Harness, ISSUE


@pytest.fixture(autouse=True)
def no_stall_delay(monkeypatch):
    monkeypatch.setattr(coord, "STALL_SECONDS", 0.0)


def _at_final_authority(h, change):
    reads = 0

    def hook(path):
        nonlocal reads
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 4:
                assert any(row["outcome"] == "reserved" for row in h.effects())
                change()

    h.fetch_hook = hook


@pytest.mark.parametrize("change", ["event", "checkout", "checkout_reverted"])
def test_refused_blocker_gets_fresh_judgment_and_preserves_history(tmp_path, change):
    h = Harness(tmp_path / "owned")
    h.run("baseline")
    h.blocker(ISSUE)
    work = h.layout.checkout("worker-0") / "fresh.py"

    def mutate():
        if change == "event":
            h.events[h.cids[ISSUE]].append({"id": "new-event", "kind": "ActionEvent"})
        else:
            work.write_text("new work\n")

    _at_final_authority(h, mutate)
    first = h.run("first")["items"][0]
    assert first["effects"][0]["outcome"] == "refused" and not h.posts
    original = copy.deepcopy(h.effects()[0])
    assert original["attempts"] == 0 and original["pending_obligations"]
    h.fetch_hook = None
    if change == "checkout_reverted":
        work.unlink()  # a new judgment may equal the earlier snapshot without reusing its ID
    recovered = h.run("fresh")["items"][0]
    assert recovered["action"] == "repair_technical_dependency"
    assert recovered["effects"][0]["outcome"] == "delivered" and len(h.posts) == 1
    rows = h.effects()
    assert rows[0] == original and rows[1]["attempts"] == 1
    decisions = [r for r in h.state()["dispatch_decisions"] if r.get("kind") == coord.KIND
                 and r.get("action") == "repair_technical_dependency"]
    assert decisions[1]["supersedes_decision_id"] == decisions[0]["id"]
    if change == "checkout_reverted":
        assert decisions[0]["directive_evidence"] == decisions[1]["directive_evidence"]
    for tick in ("later-1", "later-2", "fresh"):
        h.run(tick)
    assert len(h.posts) == 1 and h.effects()[0] == original


def test_legacy_snapshot_replay_refuses_then_fresh_tick_recovers(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    h.run("legacy", apply=False)

    def remove_snapshot(state):
        next(r for r in state["dispatch_decisions"] if r.get("action") == "repair_technical_dependency").pop("directive_evidence")
        return state

    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                                        expected_epic_issue_number=h.epic, updater=remove_snapshot)
    replay = h.run("legacy")["items"][0]
    assert replay["replayed"] and replay["effects"][0]["outcome"] == "refused" and not h.posts
    old = copy.deepcopy(h.effects()[0])
    assert h.run("legacy")["items"][0]["effects"] == []
    assert h.run("fresh")["items"][0]["effects"][0]["outcome"] == "delivered"
    assert len(h.posts) == 1 and h.effects()[0] == old


def test_refusal_before_reservation_retains_owning_workflow_and_recovers(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    reads = 0
    def unavailable_after_judgment(path):
        nonlocal reads
        if path.endswith(f"/issues/{ISSUE}"):
            reads += 1
            if reads == 2:
                h.fetch_down = True
    h.fetch_hook = unavailable_after_judgment
    assert h.run("unavailable")["items"][0]["effects"][0]["outcome"] == "refused"
    original = copy.deepcopy(h.effects()[0])
    assert original["attempts"] == 0 and coord.REPAIR_WORKFLOW in original["pending_obligations"][0]
    assert coord.REPAIR_WORKFLOW in h.mapping()["next_action"] and not h.posts
    h.fetch_down = False
    h.fetch_hook = None
    assert h.run("fresh")["items"][0]["effects"][0]["outcome"] == "delivered"
    assert h.effects()[0] == original and len(h.posts) == 1


def test_repeated_refusals_stop_and_work_evidence_reopens_the_same_assignment(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    for index in range(coord.BLOCKER_REFUSAL_LIMIT):
        _at_final_authority(h, lambda index=index: h.events[h.cids[ISSUE]].append(
            {"id": f"during-{index}", "kind": "ActionEvent"}))
        assert h.run(f"attempt-{index}")["items"][0]["effects"][0]["outcome"] == "refused"
    h.fetch_hook = None
    stopped = h.run("exhausted")["items"][0]
    assert stopped["state"] == "stopped_blocker_refusals" and not h.posts
    assert coord.REPAIR_WORKFLOW in stopped["next_action"]
    h.events[h.cids[ISSUE]].append({"id": "narration", "kind": "ActionEvent"})
    assert h.run("narration")["items"][0]["state"] == "stopped_blocker_refusals"
    (h.layout.checkout("worker-0") / "new_work.py").write_text("actual work\n")
    assert h.run("new-work")["items"][0]["effects"][0]["outcome"] == "delivered"
    stop = next(s for s in h.state()["stop_conditions"] if s.get("stop") == "blocker_refusals_exhausted")
    assert stop["resolved_tick"] == "new-work" and len(h.posts) == 1
    assert [e["outcome"] for e in h.effects()] == ["refused"] * 3 + ["delivered"]


@pytest.mark.parametrize("post_mode, expected", [("lost", "unknown"), ("full", "delivered_run_deferred"), ("ok", "delivered")])
def test_sent_or_uncertain_blocker_is_never_rebound_or_resent(tmp_path, post_mode, expected):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    h.post_mode = post_mode
    h.run("send")
    original = copy.deepcopy(h.effects()[0])
    assert original["outcome"] == expected and len(h.posts) == 1
    effects._update(h.layout, {"id": original["id"], "issue": ISSUE, "not_sent": True}, next_action="ignored")
    for tick in ("replay", "after-restart", "later"):
        h.run(tick)
    assert len(h.posts) == 1 and h.effects()[0]["outcome"] == expected and h.effects()[0]["attempts"] == 1
    assert len([r for r in h.state()["dispatch_decisions"] if r.get("root_decision_id")]) == 0


def test_reserved_crash_remains_pending_without_resend(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    h.run("judged", apply=False)
    decision = next(r for r in h.state()["dispatch_decisions"] if r.get("action") == "repair_technical_dependency")
    mapping = h.mapping()
    assert effects._reserve(h.layout, ISSUE, "worker-0", decision, "judged", ew.assignment_of(mapping))
    for tick in ("judged", "restart", "later"):
        h.run(tick)
    assert h.effects()[0]["outcome"] == "reserved" and h.effects()[0]["attempts"] == 1 and not h.posts


def test_observed_marker_without_post_response_cannot_become_not_sent(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    h.run("judged", apply=False)
    decision = next(r for r in h.state()["dispatch_decisions"] if r.get("action") == "repair_technical_dependency")
    reserved = effects._reserve(h.layout, ISSUE, "worker-0", decision, "judged", ew.assignment_of(h.mapping()))
    effects._update(h.layout, {"id": reserved["id"], "issue": ISSUE, "event_id": "observed"}, next_action="reconcile")
    effects._update(h.layout, {"id": reserved["id"], "issue": ISSUE, "not_sent": True}, next_action="reconcile")
    assert h.effects()[0]["outcome"] == "reserved" and h.effects()[0]["event_id"] == "observed"
    h.run("restart")
    assert not h.posts and h.effects()[0]["attempts"] == 1


@pytest.mark.parametrize("inconsistent", [{"post_status": 0}, {"event_id": "seen-marker"}, {"attempts": False}])
def test_inconsistent_legacy_refusal_cannot_authorize_a_new_decision(tmp_path, inconsistent):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    _at_final_authority(h, lambda: h.events[h.cids[ISSUE]].append({"id": "new", "kind": "ActionEvent"}))
    assert h.run("refused")["items"][0]["effects"][0]["outcome"] == "refused"
    h.fetch_hook = None
    def corrupt(state):
        next(row for row in state["dispatch_decisions"] if row.get("kind") == effects.EFFECT_KIND).update(inconsistent)
        return state
    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                                        expected_epic_issue_number=h.epic, updater=corrupt)
    for tick in ("fresh", "later"):
        item = h.run(tick)["items"][0]
        assert item["state"] == "unknown_effect" and "marker" in item["next_action"]
    (h.layout.checkout("worker-0") / coord.BLOCKER_FILE).unlink()
    assert h.run("blocker-removed")["items"][0]["state"] == "unknown_effect"
    assert not h.posts and len(h.effects()) == 1
    assert not any(row.get("root_decision_id") for row in h.state()["dispatch_decisions"])


def test_inconsistent_refusal_holds_its_worker_without_blocking_a_peer(tmp_path):
    h = Harness(tmp_path / "owned", count=2)
    h.blocker(ISSUE)
    _at_final_authority(h, lambda: h.events[h.cids[ISSUE]].append({"id": "new", "kind": "ActionEvent"}))
    h.run("refused")
    h.fetch_hook = None
    def corrupt(state):
        next(row for row in state["dispatch_decisions"] if row.get("kind") == effects.EFFECT_KIND)["post_status"] = 0
        return state
    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                                        expected_epic_issue_number=h.epic, updater=corrupt)
    h.blocker(ISSUE + 1)
    items = {item["issue"]: item for item in h.run("peer")["items"]}
    assert items[ISSUE]["state"] == "unknown_effect"
    assert h.posts == [h.cids[ISSUE + 1]] and items[ISSUE + 1]["effects"][0]["outcome"] == "delivered"


def test_delivered_blocker_directive_allows_work_to_resume(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    assert h.run("send")["items"][0]["effects"][0]["outcome"] == "delivered"
    (h.layout.checkout("worker-0") / "repaired.py").write_text("work resumed\n")
    (h.layout.checkout("worker-0") / coord.BLOCKER_FILE).unlink()
    item = h.run("worker-progress")["items"][0]
    assert item["state"] == "progressing" and "checkout" in item["changed_parts"]
    assert h.effects()[0]["result"]["state"] == "evidence_changed" and len(h.posts) == 1


@pytest.mark.parametrize("count", [None, True, -1, "0"])
def test_malformed_count_cannot_authorize_a_directive(tmp_path, count):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    original = h.http
    def http(method, port, key, path, body, timeout):
        if path.endswith("/events/count"):
            return 200, count
        return original(method, port, key, path, body, timeout)
    h.http = http
    item = h.run("malformed-count")["items"][0]
    assert item["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent" and not h.posts


@pytest.mark.parametrize("history", [70, 432, ew.EVENT_INTEGRITY_SCAN_LIMIT])
def test_unchanged_full_long_history_still_allows_a_directive(tmp_path, history):
    h = Harness(tmp_path / "owned")
    h.events[h.cids[ISSUE]].extend({"id": f"old-{i}", "kind": "ActionEvent"} for i in range(history))
    h.blocker(ISSUE)
    assert h.run("long-history")["items"][0]["effects"][0]["outcome"] == "delivered"
    assert len(h.posts) == 1


@pytest.mark.parametrize("history", [0, 70, 432])
def test_filtered_count_detects_omission_already_present_at_judgment(tmp_path, history):
    h = Harness(tmp_path / "owned")
    cid = h.cids[ISSUE]
    h.events[cid].extend({"id": f"old-{i}", "kind": "ActionEvent"} for i in range(history))
    h.events[cid].append({"id": "unreadable", "kind": "ActionEvent"})
    h.blocker(ISSUE)
    original = h.http
    def http(method, port, key, path, body, timeout):
        if "/events/count?timestamp__gte=" in path:
            return 200, len(h.events[cid]) - 1  # actual upstream filtered reader skips this entry
        return original(method, port, key, path, body, timeout)
    h.http = http
    item = h.run("preexisting-unreadable")["items"][0]
    assert item["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent"
    assert not h.posts and not h.effects()


@pytest.mark.parametrize("response", [(503, None), (200, None), (200, True), (200, "0"), (200, 1), "timeout"])
def test_unavailable_or_mismatched_filtered_count_holds_the_worker(tmp_path, response):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    original = h.http
    def http(method, port, key, path, body, timeout):
        if "/events/count?timestamp__gte=" in path:
            if response == "timeout":
                raise TimeoutError("synthetic filtered count timeout")
            return response
        return original(method, port, key, path, body, timeout)
    h.http = http
    item = h.run("bad-filtered-count")["items"][0]
    assert item["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent" and not h.posts


def test_over_limit_history_holds_before_starting_filtered_scan(tmp_path):
    h = Harness(tmp_path / "owned")
    cid = h.cids[ISSUE]
    h.events[cid].extend({"id": f"old-{i}", "kind": "ActionEvent"}
                         for i in range(ew.EVENT_INTEGRITY_SCAN_LIMIT + 1))
    h.blocker(ISSUE)
    item = h.run("over-limit")["items"][0]
    assert item["evidence_gaps"]["failure"] == "event_count_scan_limit_exceeded" and not h.posts
    assert not any("/events/count?timestamp__gte=" in path or "/events/search" in path for _, _, path in h.requests)


def test_filtered_count_unavailable_holds_only_affected_peer(tmp_path):
    h = Harness(tmp_path / "owned", count=2)
    h.blocker(ISSUE)
    h.blocker(ISSUE + 1)
    original = h.http
    def http(method, port, key, path, body, timeout):
        if h.cids[ISSUE] in path and "/events/count?timestamp__gte=" in path:
            raise TimeoutError("synthetic filtered count timeout")
        return original(method, port, key, path, body, timeout)
    h.http = http
    items = {item["issue"]: item for item in h.run("filter-timeout")["items"]}
    assert items[ISSUE]["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent"
    assert h.posts == [h.cids[ISSUE + 1]] and items[ISSUE + 1]["effects"][0]["outcome"] == "delivered"


def test_append_between_raw_and_filtered_counts_holds_the_worker(tmp_path):
    h = Harness(tmp_path / "owned")
    h.blocker(ISSUE)
    original = h.http
    appended = []
    def http(method, port, key, path, body, timeout):
        if "/events/count?timestamp__gte=" in path and not appended:
            h.events[h.cids[ISSUE]].append({"id": "during-count", "kind": "ActionEvent"})
            appended.append(True)
        return original(method, port, key, path, body, timeout)
    h.http = http
    item = h.run("count-race")["items"][0]
    assert appended and item["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent" and not h.posts


@pytest.mark.parametrize("hidden,long_history", [(True, False), (False, False), (True, True), (False, True)])
def test_indexed_append_before_final_search_refuses_with_full_or_short_page(tmp_path, hidden, long_history):
    h = Harness(tmp_path / "owned")
    cid = h.cids[ISSUE]
    if long_history:
        h.events[cid].extend({"id": f"old-{i}", "kind": "ActionEvent"} for i in range(70))
    h.run("baseline")
    h.blocker(ISSUE)
    original_http = h.http

    def http(method, port, key, path, body, timeout):
        status, response = original_http(method, port, key, path, body, timeout)
        if hidden and "/events/search" in path and "sort_order=TIMESTAMP_DESC" in path:
            # The upstream reader skips an unreadable entry and fills a bounded page from older ones.
            visible = [e for e in reversed(h.events[cid]) if e["id"] != "appended"]
            response = {"items": visible[:50]}
        return status, response

    h.http = http
    _at_final_authority(h, lambda: h.events[cid].append({"id": "appended", "kind": "ActionEvent"}))
    result = h.run("append")["items"][0]
    assert result["effects"][0]["outcome"] == "refused" and not h.posts


def test_count_race_and_unavailable_count_fail_closed_only_for_affected_peer(tmp_path):
    h = Harness(tmp_path / "owned", count=2)
    h.blocker(ISSUE)
    h.blocker(ISSUE + 1)
    original_http = h.http
    def http(method, port, key, path, body, timeout):
        if h.cids[ISSUE] in path and path.endswith("/events/count"):
            return 503, None
        return original_http(method, port, key, path, body, timeout)
    h.http = http
    items = {item["issue"]: item for item in h.run("unavailable")["items"]}
    assert items[ISSUE]["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent"
    assert h.posts == [h.cids[ISSUE + 1]]

    h2 = Harness(tmp_path / "other" / "owned")
    h2.blocker(ISSUE)
    def append_during_search(issue, cid):
        h2.event_hook = None
        h2.events[cid].append({"id": "during-search", "kind": "ActionEvent"})
    h2.event_hook = append_during_search
    result = h2.run("race")["items"][0]
    assert result["evidence_gaps"]["failure"] == "event_count_unavailable_or_inconsistent" and not h2.posts
