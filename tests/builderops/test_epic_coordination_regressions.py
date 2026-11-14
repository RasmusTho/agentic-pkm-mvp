"""Regression probes for the #6619 review; external engine and HTTP are simulated."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.builderops import epic_coordination as coord
from app.builderops import epic_run_state as rs
from app.builderops import epic_workspace as ew


RECEIPT = ("receipt: blocker_action.v1\naction: action:human-decision\nowner: owner\n"
           "next_action: Owner chooses retention\nunblocks_when: Owner decision recorded\n"
           "last_verified_at: 2026-11-13T00:00:00Z\n")


class Harness:
    def __init__(self, root: Path, *, count: int = 1):
        self.root = root
        self.epic = 9000001
        self.layout = ew.Layout(root, self.epic)
        self.layout.run_state_dir.mkdir(parents=True)
        (self.layout.epic_dir / "control").mkdir()
        rs.create_epic_run_state(self.epic, self.layout.run_id, root=self.layout.run_state_dir)
        self.ids = {}
        self.cids = {}
        self.events = {}
        self.posts = []
        self.requests = []
        self.owner_stop = False
        self.pr_mismatch = False
        self.inspect_change = None
        self.conversation_change = None
        self.execution = "idle"
        self.block_first = False
        self.saved, self.release = threading.Event(), threading.Event()
        for i in range(count):
            issue, worker = 9000002 + i, f"worker-{i}"
            checkout = self.layout.checkout(worker)
            checkout.mkdir(parents=True)
            (self.layout.epic_dir / "control" / f"{worker}.key").write_text("OH_SESSION_API_KEYS_0=" + "x" * 40 + "\n")
            cid, container = str(uuid.uuid4()), f"{i + 1:064x}"
            self.ids[container] = worker
            self.cids[issue] = cid
            self.events[cid] = []
            ew._record_worker(self.layout, issue, worker=worker, state="running", runtime="openhands",
                              container_id=container, port=18700 + i, checkout=str(checkout), branch=f"b/{issue}",
                              conversation={"id": cid, "status": "created"}, next_action="finish assigned issue")

    def runner(self, argv, **kwargs):
        if argv[:2] != ["docker", "inspect"]:
            raise AssertionError(argv)
        container = argv[-1]
        worker = self.ids[container]
        issue = 9000002 + int(worker.rsplit("-", 1)[1])
        info = {"Id": container, "Config": {"Labels": {ew.LABEL_EPIC: str(self.epic), ew.LABEL_WORKER: worker}},
                "State": {"Status": "running", "OOMKilled": False, "ExitCode": 0},
                "NetworkSettings": {"Ports": {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": str(18700 + issue - 9000002)}]}},
                "Mounts": [{"Type": "bind", "Source": str(self.layout.checkout(worker)), "Destination": "/workspace"}]}
        if self.inspect_change:
            self.inspect_change(info)
        return subprocess.CompletedProcess(argv, 0, json.dumps(info), "")

    def http(self, method, port, key, path, body, timeout):
        self.requests.append((method, port, path))
        cid = path.split("/")[2].split("?")[0]
        issue = next(i for i, value in self.cids.items() if value == cid)
        worker = f"worker-{issue - 9000002}"
        if method == "POST":
            self.posts.append(cid)
            text = body["content"][0]["text"]
            self.events[cid].append({"id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
                                     "kind": "MessageEvent", "source": "user",
                                     "llm_message": {"role": "user", "content": [{"type": "text", "text": text}]}})
            if self.block_first and len(self.posts) == 1:
                self.saved.set()
                if not self.release.wait(15):
                    raise TimeoutError("local regression synchronization failed")
                return 429, None
            return 200, {"success": True}
        if "/events/search" in path:
            return 200, {"items": list(reversed(self.events[cid]))}
        info = {"id": cid, "execution_status": self.execution,
                "tags": {"epic": str(self.epic), "issue": str(issue), "worker": worker},
                "workspace": {"working_dir": "/workspace"}}
        if self.conversation_change:
            self.conversation_change(info)
        return 200, info

    def fetch(self, path, timeout):
        if "/pulls?" in path:
            rows = []
            if self.pr_mismatch:
                rows = [{"number": 1, "state": "open", "draft": False, "body": "Governing-Issue: #9999999",
                         "head": {"ref": "b/9000002", "sha": "a" * 40,
                                  "repo": {"full_name": coord.github_read.REPOSITORY}}}]
            return 200, json.dumps(rows).encode()
        if "/comments?" in path:
            return 200, json.dumps([{"body": RECEIPT, "author_association": "OWNER"}] if self.owner_stop else []).encode()
        issue = int(path.rsplit("/", 1)[-1])
        labels = ["agent:needs-human", "action:human-decision"] if self.owner_stop else ["type:task"]
        return 200, json.dumps({"number": issue, "state": "open", "labels": [{"name": x} for x in labels]}).encode()

    def blocker(self, issue, summary="technical dependency"):
        path = self.layout.checkout(f"worker-{issue - 9000002}") / coord.BLOCKER_FILE
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": summary}))

    def run(self, tick, apply=True):
        return coord.coordinate(self.layout, tick=tick, stall_limit=1, runner=self.runner, http=self.http,
                                fetch=self.fetch, apply=apply)

    def state(self):
        return ew._load_state(self.layout)


@pytest.fixture
def make_harness(tmp_path, monkeypatch):
    monkeypatch.setattr(coord, "_checkout_digest", lambda *args: "unchanged")
    monkeypatch.setattr(coord, "STALL_SECONDS", 0.0)
    return lambda count=1: Harness(tmp_path / "owned", count=count)


def test_delayed_429_survives_overlapping_observation_and_peer_continues(make_harness):
    h = make_harness(2)
    h.blocker(9000002)
    h.blocker(9000003)
    h.block_first = True
    errors = []
    def first():
        try:
            h.run("A")
        except BaseException as exc:
            errors.append(exc)
    thread = threading.Thread(target=first)
    thread.start()
    try:
        assert h.saved.wait(8)
        result = h.run("B")
        assert h.posts.count(h.cids[9000002]) == 1
        assert h.posts.count(h.cids[9000003]) == 1
        # The overlapping pass cannot open this worker's endpoint while pass A owns its lifecycle.
        assert result["items"][0]["state"] == "held_lifecycle_busy"
    finally:
        h.release.set()
        thread.join(12)
    assert not thread.is_alive() and not errors
    effect = next(r for r in h.state()["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect" and r["issue"] == 9000002)
    assert effect["event_id"] and effect["post_status"] == 429 and effect["outcome"] == "delivered_run_deferred"
    h.run("C")
    assert h.posts.count(h.cids[9000002]) == 1


def test_authority_stop_on_replay_and_pr_gap_fence_sends(make_harness):
    h = make_harness()
    h.run("A", apply=False)
    assert h.run("B", apply=False)["items"][0]["action"] == "change_approach"
    h.owner_stop = True
    before = len(h.requests)
    item = h.run("B")["items"][0]
    assert item["state"] == "authority_stop" and not h.posts and len(h.requests) == before
    assert any(s.get("stop") == "authority_stop" for s in h.state()["stop_conditions"])
    h.owner_stop = False
    h.blocker(9000002)
    h.pr_mismatch = True
    item = h.run("C")["items"][0]
    assert item["evidence_gaps"]["pr"] == "unavailable" and not h.posts


def test_unannounced_authority_stop_is_read_without_worker_declaration(make_harness):
    h = make_harness()
    h.owner_stop = True
    item = h.run("A")["items"][0]
    assert item["state"] == "authority_stop" and not h.requests


@pytest.mark.parametrize("wrong", ["id", "port", "mount", "tags", "workspace", "conversation"])
def test_actual_endpoint_and_conversation_binding_fails_closed(make_harness, wrong):
    h = make_harness()
    h.blocker(9000002)
    def inspect(info):
        if wrong == "id":
            info["Id"] = "f" * 64
        elif wrong == "port":
            info["NetworkSettings"]["Ports"]["8000/tcp"][0]["HostPort"] = "18799"
        elif wrong == "mount":
            info["Mounts"][0]["Source"] = "/wrong/checkout"
    def conversation(info):
        if wrong == "tags":
            info["tags"]["issue"] = "9999999"
        elif wrong == "workspace":
            info["workspace"]["working_dir"] = "/other"
        elif wrong == "conversation":
            info["id"] = str(uuid.uuid4())
    h.inspect_change = inspect
    h.conversation_change = conversation
    h.run("A")
    assert not h.posts
    if wrong in {"id", "port", "mount"}:
        assert not h.requests  # no session key went to the mismatched endpoint
    else:
        assert all("/events" not in path for _, _, path in h.requests)


def test_missing_key_is_not_created_and_symlink_ancestor_is_rejected(make_harness, tmp_path):
    h = make_harness()
    key = h.layout.epic_dir / "control" / "worker-0.key"
    key.unlink()
    h.run("A")
    assert not key.exists() and not h.requests
    mapping = h.state()["issue_mappings"]["9000002"]
    alias = tmp_path / "alias"
    alias.symlink_to(h.layout.worker_dir("worker-0"), target_is_directory=True)
    aliased = ew.Layout(tmp_path, 9000010)
    (aliased.workers).mkdir(parents=True)
    (aliased.workers / "worker-0").symlink_to(alias, target_is_directory=True)
    assert ew._checkout_mount_identity(aliased, "worker-0", {**mapping, "checkout": str(aliased.checkout("worker-0"))}) is None


def test_fifo_and_checkout_symlink_do_not_block_or_escape(tmp_path):
    checkout = tmp_path / "checkout"
    (checkout / ".codex-tmp").mkdir(parents=True)
    os.mkfifo(checkout / coord.BLOCKER_FILE)
    probe = "from pathlib import Path; from app.builderops.epic_coordination import _read_declared_blocker; import sys; assert _read_declared_blocker(Path(sys.argv[1]))[1] == 'malformed'"
    subprocess.run([sys.executable, "-c", probe, str(checkout)], check=True, timeout=3)
    outside = tmp_path / "outside"
    outside.write_text("outside")
    (checkout / "linked").symlink_to(outside)
    assert coord._read_bounded(checkout, "linked", 100)[0] is None


def test_out_of_order_replays_and_error_churn_do_not_reset_or_advance(make_harness):
    h = make_harness()
    results = [h.run(tick, apply=False)["items"][0] for tick in ("A", "B", "A", "B", "A")]
    assert [item["stage"] for item in results] == [0, 1, 1, 1, 1]
    for i in range(3):
        h.events[h.cids[9000002]] = [{"kind": "ConversationErrorEvent", "detail": f"failure {i}"}]
        item = h.run(f"E{i}", apply=False)["items"][0]
        assert item["state"] != "progressing" and "failure" not in item["changed_parts"]


def test_active_work_and_elapsed_backoff_guard_directives(make_harness, monkeypatch):
    h = make_harness()
    h.execution = "running"
    for tick in ("A", "B", "C"):
        h.run(tick)
    assert not h.posts
    diagnoses = [r for r in h.state()["dispatch_decisions"] if r.get("action") == "bounded_diagnosis"]
    assert len(diagnoses) == 1 and "without interrupting" in diagnoses[0]["next_responsible_action"]["step"]
    h.execution = "idle"
    monkeypatch.setattr(coord, "STALL_SECONDS", 3600.0)
    item = h.run("D")["items"][0]
    assert item["state"] == "waiting_active_or_backoff" and not h.posts


def test_lost_post_reply_with_visible_event_remains_fenced(make_harness):
    h = make_harness()
    h.blocker(9000002)
    original = h.http
    def lost(method, port, key, path, body, timeout):
        response = original(method, port, key, path, body, timeout)
        if method == "POST":
            raise OSError("synthetic lost reply")
        return response
    h.http = lost
    h.run("A")
    effect = next(r for r in h.state()["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect")
    assert effect["event_id"] and effect["post_status"] == 0 and effect["outcome"] == "unknown"
    h.run("B")
    assert len(h.posts) == 1 and h.state()["dispatch_decisions"][-1]["outcome"] == "unknown"


def test_authority_change_after_reservation_prevents_the_post(make_harness):
    h = make_harness()
    h.blocker(9000002)
    original = h.fetch
    reads = 0
    def changing(path, timeout):
        nonlocal reads
        if path.endswith("/issues/9000002"):
            reads += 1
            if reads == 4:
                h.owner_stop = True
        return original(path, timeout)
    h.fetch = changing
    item = h.run("A")["items"][0]
    assert not h.posts and reads >= 4
    assert item["effects"][0]["outcome"] == "refused"
    effect = next(r for r in h.state()["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect")
    assert effect["attempts"] == 0
    assert h.run("B")["items"][0]["state"] == "authority_stop"
    h.owner_stop = False
    h.fetch = original
    h.run("C")
    assert h.posts == [h.cids[9000002]]
    effect = next(r for r in h.state()["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect")
    assert effect["outcome"] == "delivered" and effect["attempts"] == 1 and effect["previous_refusal"]


def test_fifo_blocker_does_not_hold_independent_peer(make_harness):
    h = make_harness(2)
    bad = h.layout.checkout("worker-0") / coord.BLOCKER_FILE
    bad.parent.mkdir()
    os.mkfifo(bad)
    h.blocker(9000003)
    result = h.run("A")
    assert result["items"][0]["evidence_gaps"]["blocker"] == "malformed"
    assert h.posts == [h.cids[9000003]]


def test_accepted_send_has_backoff_even_if_server_still_appears_idle(make_harness, monkeypatch):
    h = make_harness(2)
    monkeypatch.setattr(coord, "STALL_SECONDS", 60.0)
    h.blocker(9000002, "first dependency")
    h.blocker(9000003, "peer dependency")
    h.run("A")
    assert h.posts == [h.cids[9000002], h.cids[9000003]]
    h.blocker(9000002, "different dependency")
    result = h.run("B")
    assert h.posts.count(h.cids[9000002]) == 1
    assert result["items"][0]["evidence_gaps"]["directive_backoff"] == "awaiting_run_observation"


def test_assignment_change_during_authority_read_never_reaches_the_old_endpoint(make_harness):
    h = make_harness()
    h.blocker(9000002)
    original = h.fetch
    changed = False
    def changing(path, timeout):
        nonlocal changed
        response = original(path, timeout)
        if path.endswith("/issues/9000002") and not changed:
            changed = True
            ew._record_worker(h.layout, 9000002, port=18799)
        return response
    h.fetch = changing
    item = h.run("A")["items"][0]
    assert item["state"] == "held_assignment_changed" and not h.requests


def test_stop_after_post_prevents_followup_session_access(make_harness):
    h = make_harness()
    h.blocker(9000002)
    original = h.http
    def stop_after_send(method, port, key, path, body, timeout):
        response = original(method, port, key, path, body, timeout)
        if method == "POST":
            h.owner_stop = True
        return response
    h.http = stop_after_send
    h.run("A")
    assert h.posts == [h.cids[9000002]]
    assert h.requests[-1][0] == "POST"
    effect = next(r for r in h.state()["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect")
    assert effect["post_status"] == 200 and effect["outcome"] == "unknown"
    before = len(h.requests)
    assert h.run("B")["items"][0]["state"] == "authority_stop"
    assert len(h.requests) == before
