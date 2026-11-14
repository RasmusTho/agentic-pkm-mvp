"""Assignment / endpoint-lifetime invariant for the #6619 coordinator (five-P1 repair).

Production callers run for real: ``coordinate``, ``stop_worker``, ``start_openhands_worker``,
``start_conversation``, ``reconcile_worker_conversation``, ``conversation_status`` and the live
fixture script. Simulated boundaries, labelled: the Docker CLI (``runner``), the agent-server REST
port (``http``; one test uses a real loopback listener instead) and public GitHub (``fetch``).
"Concurrent" lifecycle operations run in another thread, as another controller process would; a
"direct writer" updates run-state without the lifecycle lock to exercise the conditional writes.
Passing here proves no real OpenHands, model or worker behaviour.
"""
from __future__ import annotations

import http.server
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.builderops import epic_coordination as coord
from app.builderops import epic_coordination_effects as effects
from app.builderops import epic_workspace as ew
from scripts import epic_coordination_live_fixture as fixture
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _seed_repo

RECEIPT = ("receipt: blocker_action.v1\naction: action:human-decision\nowner: owner\n"
           "next_action: Owner chooses retention\nunblocks_when: Owner decision recorded\n"
           "last_verified_at: 2026-11-13T00:00:00Z\n")
ISSUE = 9000002


class Harness:
    def __init__(self, root: Path, count: int = 1, prefix: str = "worker-"):
        self.root = root
        self.epic = 9000001
        self.engine = FakeEngine()
        self.layout = ew.init_workspace(root, self.epic, _seed_repo(root.parent), runner=self.engine)
        self.workers, self.cids, self.events = {}, {}, {}
        self.ports = self.engine.ports
        self.posts, self.payloads, self.requests = [], [], []
        self.execution = "idle"
        self.hold: set[int] = set()
        self.fetch_down = False
        self.get_hook = self.event_hook = self.post_hook = self.ready_hook = self.fetch_hook = None
        self.post_mode = "ok"
        for i in range(count):
            issue, worker = ISSUE + i, f"{prefix}{i}"
            self.workers[issue] = worker
            ew.create_worker(self.layout, worker, issue=issue, branch=f"b/{issue}", next_action="finish assigned issue",
                             runner=self.engine)
            control = self.layout.epic_dir / "control"
            control.mkdir(mode=0o700, exist_ok=True)
            (control / f"{worker}.key").write_text("OH_SESSION_API_KEYS_0=" + "x" * 40 + "\n")
            ew.start_openhands_worker(self.layout, worker, runner=self.runner, http=self.http)
            ew.start_conversation(self.layout, worker, engine="codex", model="gpt-6.1-terra", prompt="synthetic",
                                  runner=self.runner, http=self.http)
        self.requests.clear()

    # -- simulated Docker CLI
    def runner(self, argv, **kwargs):
        return self.engine(argv, **kwargs)

    # -- simulated agent-server REST port
    def info(self, issue, cid):
        return {"id": cid, "execution_status": self.execution, "workspace": {"working_dir": "/workspace"},
                "tags": {"epic": str(self.epic), "issue": str(issue), "worker": self.workers[issue]}}

    def http(self, method, port, key, path, body, timeout):
        self.requests.append((method, port, path))
        if path == "/conversations/search?limit=1":
            if self.ready_hook:
                self.ready_hook()
            return 200, {"items": []}
        if path == "/conversations" and method == "POST":
            issue = int(body["tags"]["issue"])
            self.cids[issue] = body["conversation_id"]
            self.events[body["conversation_id"]] = []
            return 201, self.info(issue, body["conversation_id"])
        cid = path.split("/")[2].split("?")[0]
        issue = next(i for i, c in self.cids.items() if c == cid) if cid in self.cids.values() else ISSUE
        if method == "POST":
            self.posts.append(cid)
            self.payloads.append(body)
            self.events.setdefault(cid, []).append({
                "id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(), "kind": "MessageEvent",
                "source": "user", "llm_message": {"role": "user", "content": body["content"]}})
            if self.post_hook:
                self.post_hook(cid)
            if self.post_mode == "lost":
                raise OSError("synthetic lost reply")
            return (429, None) if self.post_mode == "full" else (200, {"success": True})
        if "/events/search" in path:
            if self.event_hook:
                self.event_hook(issue, cid)
            return 200, {"items": list(reversed(self.events.get(cid, [])))}
        if self.get_hook:
            self.get_hook(issue, cid)
        return 200, self.info(issue, cid)

    # -- simulated public GitHub
    def fetch(self, path, timeout):
        if self.fetch_hook:
            self.fetch_hook(path)
        if self.fetch_down:
            return 503, b""
        if "/pulls?" in path:
            return 200, b"[]"
        if "/comments?" in path:
            issue = int(path.split("/issues/")[1].split("/")[0])
            return 200, json.dumps([{"body": RECEIPT, "author_association": "OWNER"}] if issue in self.hold else []).encode()
        issue = int(path.rsplit("/", 1)[-1])
        labels = ["agent:needs-human", "action:human-decision"] if issue in self.hold else ["type:task"]
        return 200, json.dumps({"number": issue, "state": "open", "labels": [{"name": v} for v in labels]}).encode()

    def blocker(self, issue, summary="unsupported technical dependency"):
        path = self.layout.checkout(self.workers[issue]) / coord.BLOCKER_FILE
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": summary}))

    def run(self, tick, apply=True):
        return coord.coordinate(self.layout, tick=tick, stall_limit=1, runner=self.runner, http=self.http, fetch=self.fetch, apply=apply)

    def state(self):
        return ew._load_state(self.layout)

    def mapping(self, issue=ISSUE):
        return self.state()["issue_mappings"][str(issue)]

    def effects(self, issue=ISSUE):
        return [r for r in self.state()["dispatch_decisions"] if r.get("kind") == effects.EFFECT_KIND and r["issue"] == issue]

    def stop(self, worker="worker-0"):
        return ew.stop_worker(self.layout, worker, reason="synthetic verified stop", runner=self.runner)

    def replace(self, worker="worker-0", issue=ISSUE):
        """Production stop -> start -> conversation-start with a new container (no pass running)."""
        self.stop(worker)
        ew.takeover(self.layout, worker, reason="synthetic verified handoff", runner=self.runner)
        ew.start_openhands_worker(self.layout, worker, budget=ew.Budget("0.7", "1500m", 256), runner=self.runner, http=self.http)
        return ew.start_conversation(self.layout, worker, engine="codex", model="gpt-6.1-terra", prompt="successor",
                                     runner=self.runner, http=self.http)["id"]


def in_thread(fn):
    """Run ``fn`` the way another controller process would: on another thread, to completion."""
    box: dict = {}
    def run():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc
    thread = threading.Thread(target=run)
    thread.start()
    thread.join(10)
    assert not thread.is_alive()
    return box


def direct_write(h, issue=ISSUE, **fields):
    """A lock-bypassing writer: the conditional writes, not the lock, must keep this newer state."""
    ew._record_worker(h.layout, issue, **fields)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(coord, "STALL_SECONDS", 0.0)


@pytest.fixture
def harness(tmp_path):
    return lambda count=1, prefix="worker-": Harness(tmp_path / "owned", count, prefix)


# --------------------------------------------------------------------------- P1-1


def test_stale_observation_never_directs_a_successor(harness):
    h = harness()
    h.blocker(ISSUE)
    successor = {"id": str(uuid.uuid4()), "status": "created"}
    refused = []
    def replace_during_event_read(issue, cid):
        h.event_hook = None
        refused.append(in_thread(h.stop))  # a real concurrent stop is fenced by the item's lifecycle hold
        direct_write(h, container_id="e" * 64, conversation=successor, next_action="successor assignment")
    h.event_hook = replace_during_event_read
    item = h.run("stale")["items"][0]
    assert isinstance(refused[0].get("error"), ew.LifecycleBusy)
    assert item["state"] == "held_assignment_changed" and h.posts == []
    assert h.mapping()["next_action"] == "successor assignment"
    assert not [d for d in h.state()["dispatch_decisions"] if d.get("kind") == coord.KIND]


def test_assignment_change_between_judgement_and_reservation_refuses_without_touching_successor(harness):
    h = harness()
    h.blocker(ISSUE)
    h.run("base", apply=False)  # the declared blocker is judged now; apply follows on the replay
    successor = {"id": str(uuid.uuid4()), "status": "created"}
    fired = []
    def change_after_judgement(path):
        if path.endswith(f"/issues/{ISSUE}") and len(fired) == 1:  # the apply-time fresh-authority read
            direct_write(h, conversation=successor, next_action="successor assignment")
        if path.endswith(f"/issues/{ISSUE}"):
            fired.append(path)
    h.fetch_hook = change_after_judgement
    item = h.run("base")["items"][0]
    assert h.posts == [] and item["effects"][0]["outcome"] == "refused"
    assert h.mapping()["next_action"] == "successor assignment" and h.mapping()["conversation"] == successor


def test_assignment_change_inside_the_open_session_fails_the_reservation(harness):
    h = harness()
    h.blocker(ISSUE)
    h.run("base", apply=False)
    successor = {"id": str(uuid.uuid4()), "status": "created"}
    gets = []
    def change_on_apply_session_get(issue, cid):
        gets.append(cid)
        if len(gets) == 2:  # 1: observation read; 2: apply_item's in-session conversation read
            direct_write(h, conversation=successor, next_action="successor assignment")
    h.get_hook = change_on_apply_session_get
    item = h.run("base")["items"][0]
    assert len(gets) == 2 and h.posts == [] and item["effects"] == [] and h.effects() == []
    assert h.mapping()["next_action"] == "successor assignment" and h.mapping()["conversation"] == successor


def test_successor_gets_its_own_decision_and_one_directive(harness):
    h = harness()
    h.blocker(ISSUE)
    h.post_mode = "lost"
    h.run("old")
    [old] = h.effects()
    assert old["outcome"] == "unknown" and h.posts == [h.cids[ISSUE]]
    h.post_mode = "ok"
    new_cid = h.replace()
    h.execution = "idle"
    h.run("successor-1")
    h.run("successor-2")
    records = h.effects()
    assert h.posts.count(new_cid) == 1 and len(h.posts) == 2
    preserved = next(r for r in records if r["id"] == old["id"])
    assert preserved["outcome"] == "unknown" and preserved["conversation_id"] != new_cid  # old obligation kept as-is
    fresh = next(r for r in records if r["id"] != old["id"])
    assert fresh["decision_id"] != old["decision_id"] and fresh["conversation_id"] == new_cid
    assert fresh["assignment"] == ew.assignment_of(h.mapping())


# --------------------------------------------------------------------------- P1-2


@pytest.mark.parametrize("change", ["stop", "reassign"])
def test_late_conversation_reconcile_keeps_the_newer_state(harness, change):
    h = harness()
    old = h.mapping()["conversation"]
    direct_write(h, conversation={**old, "status": "unknown"})
    successor = {"id": str(uuid.uuid4()), "status": "created"}
    def newer(issue, cid):
        if change == "stop":
            direct_write(h, state="stopped_verified", conversation={**old, "status": ew.CONVERSATION_ENDED})
        else:
            direct_write(h, container_id="e" * 64, conversation=successor)
    h.get_hook = newer
    with pytest.raises(ew.EpicWorkspaceError, match="newer state is kept"):
        ew.reconcile_worker_conversation(h.layout, "worker-0", http=h.http, runner=h.runner)
    saved = h.mapping()
    if change == "stop":
        assert saved["state"] == "stopped_verified" and saved["conversation"]["status"] == ew.CONVERSATION_ENDED
    else:
        assert saved["conversation"] == successor


def test_concurrent_stop_during_reconcile_is_refused_and_reconcile_completes(harness):
    h = harness()
    old = h.mapping()["conversation"]
    direct_write(h, conversation={**old, "status": "unknown"})
    attempts = []
    h.get_hook = lambda issue, cid: attempts.append(in_thread(h.stop))
    assert ew.reconcile_worker_conversation(h.layout, "worker-0", http=h.http, runner=h.runner)["status"] == "created"
    assert isinstance(attempts[0].get("error"), ew.LifecycleBusy)
    h.get_hook = None
    h.stop()  # once the lifecycle is free the stop proceeds and wins
    assert h.mapping()["conversation"]["status"] == ew.CONVERSATION_ENDED


def test_readiness_never_overwrites_a_newer_stop(harness):
    h = harness()
    h.stop()
    ew.takeover(h.layout, "worker-0", reason="synthetic verified handoff", runner=h.runner)
    attempts = []
    def during_readiness():
        h.ready_hook = None
        attempts.append(in_thread(h.stop))
        direct_write(h, state="stopped_verified", next_action="newer stop")
    h.ready_hook = during_readiness
    with pytest.raises(ew.EpicWorkspaceError, match="newer state is kept"):
        ew.start_openhands_worker(h.layout, "worker-0", budget=ew.Budget("0.7", "1500m", 256), runner=h.runner, http=h.http)
    assert isinstance(attempts[0].get("error"), ew.LifecycleBusy)
    assert h.mapping()["state"] == "stopped_verified" and h.mapping()["next_action"] == "newer stop"


@pytest.mark.parametrize("mode,status", [("ok", 200), ("full", 429), ("lost", 0)])
def test_late_post_outcome_stays_in_the_old_record(harness, mode, status):
    h = harness()
    h.blocker(ISSUE)
    h.post_mode = mode
    old = h.mapping()["conversation"]
    h.post_hook = lambda cid: direct_write(h, state="stopped_verified", conversation={**old, "status": ew.CONVERSATION_ENDED},
                                          next_action="verified stop action")
    h.run("late")
    [effect] = h.effects()
    assert effect["post_status"] == status and effect["assignment_superseded"] is True
    if mode == "full":
        assert any("/run" in o for o in effect["pending_obligations"])
    saved = h.mapping()
    assert saved["state"] == "stopped_verified" and saved["next_action"] == "verified stop action"
    assert h.posts == [old["id"]]


# --------------------------------------------------------------------------- P1-3


def test_stop_and_port_reuse_cannot_interleave_with_session_access(harness):
    h = harness(2)
    attempts = {}
    def during_session(issue, cid):
        h.get_hook = None
        attempts["stop"] = in_thread(h.stop)
        attempts["start"] = in_thread(lambda: ew.start_openhands_worker(
            h.layout, "worker-1", budget=ew.Budget("0.7", "1500m", 256), runner=h.runner, http=h.http))
    h.get_hook = during_session
    status = ew.conversation_status(h.layout, "worker-0", http=h.http, runner=h.runner)
    assert status["reachable"] is True
    assert isinstance(attempts["stop"].get("error"), ew.LifecycleBusy)
    assert isinstance(attempts["start"].get("error"), ew.LifecycleBusy)  # port selection waits for the session
    assert {port for _, port, _ in h.requests} == {18700}
    h.stop()
    before = len(h.requests)
    assert ew.conversation_status(h.layout, "worker-0", http=h.http, runner=h.runner)["reachable"] is False
    assert len(h.requests) == before  # a stopped endpoint is never contacted again


def test_busy_worker_is_held_without_contact_and_peer_continues(harness):
    h = harness(2)
    h.blocker(ISSUE)
    h.blocker(ISSUE + 1)
    entered, release = threading.Event(), threading.Event()
    def owner():
        with ew._worker_lifecycle_lock(h.layout, "worker-0"):
            entered.set()
            release.wait(10)
    thread = threading.Thread(target=owner)
    thread.start()
    try:
        assert entered.wait(5)
        result = h.run("busy")
    finally:
        release.set()
        thread.join(10)
    items = {i["issue"]: i for i in result["items"]}
    assert items[ISSUE]["state"] == "held_lifecycle_busy" and ISSUE in result["held"]
    assert h.posts == [h.cids[ISSUE + 1]] and not any(port == 18700 for _, port, _ in h.requests)
    before = len(h.requests)
    with ew._worker_lifecycle_lock(h.layout, "worker-0"):
        same_thread = h.run("same-thread")
    items = {i["issue"]: i for i in same_thread["items"]}
    assert items[ISSUE]["state"] == "held_lifecycle_busy"
    assert not any(port == 18700 for _, port, _ in h.requests[before:])


def test_real_loopback_session_is_fenced_against_stop(harness, monkeypatch):
    """Actual HTTP over loopback: the stop is refused while the request is in flight."""
    h = harness()
    seen, attempts = [], []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append((self.path, self.headers.get("X-Session-API-Key")))
            if "/events/search" not in self.path:
                attempts.append(in_thread(h.stop))
                body = h.info(ISSUE, h.cids[ISSUE])
            else:
                body = {"items": []}
            raw = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args):
            pass
    server = None
    for port in ew.OPENHANDS_PORT_RANGE:
        try:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
            break
        except OSError:
            continue
    assert server is not None
    h.ports["worker-0"] = server.server_address[1]
    direct_write(h, port=server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status = ew.conversation_status(h.layout, "worker-0", runner=h.runner)
    finally:
        server.shutdown()
        server.server_close()
    assert status["reachable"] is True and status["events_reachable"] is True
    assert isinstance(attempts[0].get("error"), ew.LifecycleBusy)
    assert [key for _, key in seen] == ["x" * 40, "x" * 40] and h.mapping()["state"] == "running"


# --------------------------------------------------------------------------- P1-4


def _ladder(h):
    return [d for d in h.state()["dispatch_decisions"] if d.get("kind") == coord.KIND and d["issue"] == ISSUE]


def test_active_no_progress_executes_a_diagnosis_then_a_bounded_continuation(harness, monkeypatch):
    h = harness()
    h.execution = "running"
    h.run("base")
    h.run("diagnose")
    [diagnosis] = _ladder(h)
    assert diagnosis["action"] == "bounded_diagnosis" and diagnosis["diagnosis"]["tick"] == "diagnose"
    assert diagnosis["diagnosis"]["execution_status"] == "running" and "no new event" in diagnosis["diagnosis"]["finding"]
    assert "diagnosis executed" in h.mapping()["next_action"] and h.posts == []
    # A single long operation inside its budget is left alone; the wait names its bound.
    for n in range(4):
        item = h.run(f"wait{n}")["items"][0]
        assert item["state"] == "waiting_active_or_backoff" and "at most" in item["next_action"] and h.posts == []
    # Past the operation budget the changed-approach directive supersedes it: not a perpetual wait.
    monkeypatch.setattr(coord, "ACTIVE_OPERATION_SECONDS", 0.0)
    item = h.run("due")["items"][0]
    assert item["action"] == "change_approach" and h.posts == [h.cids[ISSUE]]
    assert h.payloads[0]["run"] is True and h.effects()[0]["while_active"] is True
    for n in range(3):
        h.run(f"after{n}")
    assert len(h.posts) == 1


def test_looping_active_worker_gets_the_directive_on_the_next_unchanged_pass(harness):
    h = harness()
    h.execution = "running"
    cid = h.cids[ISSUE]
    def step():
        h.events[cid].append({"id": str(uuid.uuid4()), "kind": "ActionEvent", "source": "agent",
                              "timestamp": datetime.now(timezone.utc).isoformat()})
    for tick in ("base", "diagnose", "loop"):
        step()
        h.run(tick)
    assert [d["action"] for d in _ladder(h)] == ["bounded_diagnosis", "change_approach"]
    assert "loop" in _ladder(h)[0]["diagnosis"]["finding"] or "steps" in _ladder(h)[0]["diagnosis"]["finding"]
    assert h.posts == [cid]


def test_progress_after_diagnosis_resets_the_ladder(harness):
    h = harness()
    h.execution = "running"
    h.run("base")
    h.run("diagnose")
    (h.layout.checkout("worker-0") / "work.py").write_text("real work\n")
    item = h.run("work")["items"][0]
    assert item["state"] == "progressing" and item["stage"] == 0
    assert [d["action"] for d in _ladder(h)] == ["bounded_diagnosis", "progress_resumed"] and h.posts == []


# --------------------------------------------------------------------------- P1-5


def _fixture_args(h, token):
    return ["--root", str(h.root), "--epic", str(h.epic), "--issue", str(ISSUE), "--worker", "fixture-0", "--token", token]


def test_fixture_apply_under_authority_stop_contacts_nothing(harness, monkeypatch):
    h = harness(prefix="fixture-")
    monkeypatch.setattr(fixture, "_fixture_fetch", lambda issue: h.fetch)
    args = _fixture_args(h, "b" * 32)
    fixture._run(["baseline", *args], runner=h.runner, http=h.http)
    for authority in ("stop", "unavailable"):
        h.hold, h.fetch_down = ({ISSUE}, False) if authority == "stop" else (set(), True)
        before = len(h.requests)
        result = fixture._run(["apply", *args], runner=h.runner, http=h.http)
        assert len(h.requests) == before and h.posts == []
        assert result["directive_pass"]["items"][0]["state"] in ("authority_stop", "unknown")
        assert "simulated" in result["authority_source"]


def test_fixture_verify_refuses_success_when_authority_stops(harness, monkeypatch):
    h = harness(prefix="fixture-")
    monkeypatch.setattr(fixture, "_fixture_fetch", lambda issue: h.fetch)
    checkout = h.layout.checkout("fixture-0")
    args = _fixture_args(h, "c" * 32)
    fixture._run(["baseline", *args], runner=h.runner, http=h.http)
    fixture._run(["apply", *args], runner=h.runner, http=h.http)
    marker = h.payloads[0]["content"][0]["text"].split("]")[0].lstrip("[")
    import time
    time.sleep(0.01)
    (checkout / fixture.RESULT).write_text(marker)
    assert fixture._run(["verify", *args], runner=h.runner, http=h.http)["directive_event_id"]  # positive control
    h.hold.add(ISSUE)
    before = len(h.requests)
    with pytest.raises(ValueError, match="authority"):
        fixture._run(["verify", *args], runner=h.runner, http=h.http)
    assert len(h.requests) == before
    # Authority that stops after the last session read still refuses the success result.
    h.hold.clear()
    def stop_after_marker_read(issue, cid):
        h.hold.add(ISSUE)
    h.event_hook = None
    original = h.http
    def http(method, port, key, path, body, timeout):
        response = original(method, port, key, path, body, timeout)
        if "body=" in path:
            stop_after_marker_read(ISSUE, None)
        return response
    with pytest.raises(ValueError, match="authority"):
        fixture._run(["verify", *args], runner=h.runner, http=http)
