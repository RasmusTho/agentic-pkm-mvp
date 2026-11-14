"""Evidence-based progress judgement through the running epic coordinator (#6619).

Production entrypoint: ``epic_workspace coordinate [--apply]`` (``ew.main``) over a real run-state
file and real worker git checkouts. Simulated boundaries, labelled: the container engine
(``FakeEngine``, git runs for real), the OpenHands agent-server REST surface
(``PerConversationServer``: the POST/search message semantics follow upstream 1.62.0
``event_router``), the public GitHub REST read (``FakeGitHub``) and the worker's reaction to a
directive (``Epic.react``). Passing here does not show that a real model changes behavior.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import re

import pytest

from app.builderops import epic_coordination as coord
from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_observation as github_read
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer

EPIC = 6615
STALLED, FALSE_BLOCKER, AUTHORITY, PEER, MALFORMED, UNREACHABLE, RECOVERS = 7001, 7002, 7003, 7004, 7005, 7006, 7007
ERROR = {"kind": "ConversationErrorEvent", "code": "ToolError", "detail": "pytest failed: 3 failed in 12.4s (pid 4242)"}
HUMAN_RECEIPT = (
    "receipt: blocker_action.v1\naction: action:human-decision\nowner: owner\n"
    "next_action: Owner chooses the retention policy\nunblocks_when: Owner decision recorded on the Issue\n"
    "last_verified_at: 2026-11-13T00:00:00Z\n"
)


@pytest.fixture(autouse=True)
def _short_backoff_for_simulated_passes(monkeypatch):
    monkeypatch.setattr(coord, "STALL_SECONDS", 0.0)


class PerConversationServer(FakeAgentServer):
    """Agent-server stand-in: an event stream per conversation, upstream message semantics, outages."""

    def __init__(self) -> None:
        super().__init__()
        self.streams: dict[str, list[dict]] = {}
        self.down: set[int] = set()
        self.post_mode: dict[str, str] = {}  # per conversation: ok | lost_reply | drop | full
        self.event_down: set[str] = set()
        self.on_post = None
        self.messages: list[tuple[str, str]] = []

    def __call__(self, method, port, key, path, body, timeout):
        if port in self.down:
            raise OSError("agent-server unreachable")
        parts = path.split("?")[0].split("/")
        if method == "POST" and path == "/conversations":
            response = super().__call__(method, port, key, path, body, timeout)
            self.conversations[body["conversation_id"]]["execution_status"] = "idle"
            return response
        if method == "POST" and path.endswith("/events") and len(parts) == 4:
            cid = parts[2]
            text = body["content"][0]["text"]
            self.messages.append((cid, text))
            if self.on_post:
                self.on_post(cid, text)
            mode = self.post_mode.get(cid, "ok")
            if mode != "drop":
                self.streams[cid].append({"id": f"evt-{len(self.streams[cid])}", "timestamp": datetime.now(timezone.utc).isoformat(), "kind": "MessageEvent", "source": "user",
                                          "llm_message": {"role": "user", "content": [{"type": "text", "text": text}]}})
            if mode in ("lost_reply", "drop"):
                raise OSError("reply lost")
            return (429, None) if mode == "full" else (200, {"success": True})
        if method == "GET" and "/events/search" in path:
            if parts[2] in self.event_down:
                return 503, None
            self.events = self.streams.get(parts[2], [])
        return super().__call__(method, port, key, path, body, timeout)

    def directives(self, cid=None):
        return [t for c, t in self.messages if cid in (None, c)]


class CoordinationEngine(FakeEngine):
    """Simulate Docker's read-only inspect; git still runs against real fixture checkouts."""
    def __init__(self, epic=EPIC):
        super().__init__()
        self.epic = epic
        self.runtime_states = {}

    def __call__(self, argv, **kwargs):
        if argv[:2] == ["docker", "inspect"] and "{{json .}}" in argv:
            name = next((name for name, cid in self.ids.items() if cid == argv[-1]), "")
            worker = self.worker_for_name(name)
            status, oom, code = self.runtime_states.get(worker, ("running", "false", 0))
            result = super().__call__(argv, **kwargs)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                info["State"] = {"Status": status, "OOMKilled": oom == "true", "ExitCode": code}
                result.stdout = json.dumps(info)
            return result
        return super().__call__(argv, **kwargs)


class FakeGitHub:
    """Public read-only GitHub REST stand-in: Issue labels and comments."""

    def __init__(self) -> None:
        self.issues: dict[int, dict] = {}
        self.pulls: list[dict] = []
        self.calls: list[str] = []
        self.down = False

    def __call__(self, path, timeout):
        self.calls.append(path)
        if self.down:
            raise OSError("github unreachable")
        if path.startswith(f"/repos/{github_read.REPOSITORY}/pulls?"):
            return 200, json.dumps(self.pulls).encode()
        m = re.fullmatch(rf"/repos/{re.escape(github_read.REPOSITORY)}/issues/([0-9]+)(/comments)?(\?.*)?", path)
        issue = self.issues.get(int(m.group(1))) if m else None
        if issue is None:
            return 404, b""
        if m.group(2):
            return 200, json.dumps(issue["comments"]).encode()
        return 200, json.dumps({"number": int(m.group(1)), "state": "open", "labels": [{"name": n} for n in issue["labels"]]}).encode()

    def block(self, number, labels, receipt):
        self.issues[number] = {"labels": labels, "comments": [{"body": receipt, "author_association": "OWNER"}] if receipt else []}


class Epic:
    def __init__(self, tmp_path, capsys):
        self.root, self.engine, self.server, self.github = tmp_path / "ws", CoordinationEngine(), PerConversationServer(), FakeGitHub()
        self.layout = ew.Layout(self.root.resolve(), EPIC)
        self.cid: dict[int, str] = {}
        self.ticks = 0
        self.busy: set[int] = set()  # workers that keep producing new work every pass
        prompt = tmp_path / "prompt.md"
        prompt.write_text("Implement the slice")
        assert _cli(self.root, EPIC, self.engine, "init", "--repo-url", _seed_repo(tmp_path)) == 0
        for issue in (STALLED, FALSE_BLOCKER, AUTHORITY, PEER, MALFORMED, UNREACHABLE, RECOVERS):
            self.github.block(issue, ["type:task"], None)
            worker = f"w-{issue}"
            assert _cli(self.root, EPIC, self.engine, "worker-create", "--worker", worker, "--issue", str(issue), "--branch", f"b/{issue}", "--next-action", "implement") == 0
            assert self.main("openhands-start", "--worker", worker) == 0
            assert self.main("conversation-start", "--worker", worker, "--prompt-file", str(prompt)) == 0
            self.cid[issue] = ew._load_state(self.layout)["issue_mappings"][str(issue)]["conversation"]["id"]
            self.server.streams[self.cid[issue]] = []
        capsys.readouterr()

    def main(self, *args):
        return ew.main(["--root", str(self.root), "--epic", str(EPIC), *args], runner=self.engine, http=self.server, fetch=self.github)

    def state(self):
        return ew._load_state(self.layout)

    def tick(self, capsys, limit=2, name=None, apply=False):
        self.ticks += 1
        for issue in self.busy:
            self.write(issue, "work.py", f"pass {self.ticks}\n")
        capsys.readouterr()
        assert self.main("coordinate", "--tick", name or f"t{self.ticks}", "--stall-limit", str(limit), *(["--apply"] if apply else [])) == 0
        out = json.loads(capsys.readouterr().out)
        return out, {item["issue"]: item for item in out["items"]}

    def write(self, issue, name, text):
        path = self.layout.checkout(f"w-{issue}") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def heartbeat(self, issue, error=True):
        """Events that change without any work: tool-call chatter, narration, heartbeats."""
        stream = self.server.streams[self.cid[issue]]
        stream.extend([{"kind": "ActionEvent", "source": "agent"}, {"kind": "ObservationEvent", "source": "environment"},
                       {"kind": "MessageEvent", "source": "agent", "llm_message": {"content": f"retrying attempt {len(stream)}"}}])
        if error:
            stream.append(dict(ERROR, detail=ERROR["detail"].replace("12.4", f"{len(stream)}.1")))

    def others_busy(self, *except_issues):
        self.busy = {i for i in self.cid if i not in except_issues}

    def react(self, issue, text="a different approach\n"):
        """SIMULATED worker reaction to a directive: new work. Only a real model run can prove this."""
        self.write(issue, "reaction.py", text)

    def record(self, **updates):
        epic_run_state.update_epic_run_state(self.layout.run_id, root=self.layout.run_state_dir, expected_epic_issue_number=EPIC, **updates)


def _decisions(state, issue, kind=None):
    return [d for d in state["dispatch_decisions"] if d.get("kind") == coord.KIND and d["issue"] == issue and (kind is None or d["action"] == kind)]


def _stops(state, issue):
    return [s for s in state["stop_conditions"] if s.get("kind") == coord.KIND and s["issue"] == issue]


def test_no_progress_and_false_blocker_trigger_bounded_action(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    worker_lifecycle_calls = [c for c in epic.engine.calls if c[1] in ("create", "start")]
    assert len([c for c in worker_lifecycle_calls if c[1] == "create"]) == 7
    assert len([c for c in worker_lifecycle_calls if c[1] == "start"]) == 7
    # A malformed test result for one item (existing run-state field). The authority stop is read back from
    # the live Issue (simulated public REST): blocker lifecycle/action labels plus the matching receipt.
    epic.record(validation_status={str(MALFORMED): "garbled"})
    epic.github.block(AUTHORITY, ["agent:needs-human", "action:human-decision"], HUMAN_RECEIPT)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    epic.write(FALSE_BLOCKER, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "cannot proceed: needs a new migration framework"}))
    epic.write(AUTHORITY, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "waiting for retention policy"}))
    epic.server.down.add(int(epic.state()["issue_mappings"][str(UNREACHABLE)]["port"]))
    for issue in (STALLED, RECOVERS):
        epic.heartbeat(issue)

    # t1 baseline: nothing is judged on a first look; the authority stop is preserved immediately.
    out, items = epic.tick(capsys)
    assert {i["state"] for n, i in items.items() if n in (STALLED, PEER, RECOVERS, FALSE_BLOCKER)} == {"baseline"}
    assert items[AUTHORITY]["state"] == "authority_stop" and items[AUTHORITY]["action"] == "authority_stop"
    assert items[MALFORMED]["state"] == "baseline" and items[MALFORMED]["evidence_gaps"] == {"validation": "malformed"}
    assert items[UNREACHABLE]["evidence_gaps"] == {"failure": "conversation_unreachable"}
    assert out["held"] == [AUTHORITY] and AUTHORITY not in out["independent_work_continues"]
    assert set(out["independent_work_continues"]) == set(items) - {AUTHORITY}
    [stop] = _stops(epic.state(), AUTHORITY)
    assert stop["stop"] == "authority_stop" and stop["owner"] == "owner" and stop["declared_blocker"] == "waiting for retention policy"
    assert stop["next_action"] == "Owner chooses the retention policy"
    # The false blocker: no non-builder authority, so it is repaired through the owning workflow, once.
    [repair] = _decisions(epic.state(), FALSE_BLOCKER, "repair_technical_dependency")
    assert repair["next_responsible_action"]["workflow"] == coord.REPAIR_WORKFLOW and repair["source_authority"] is None
    assert items[FALSE_BLOCKER]["action"] == "repair_technical_dependency"
    assert epic.state()["issue_mappings"][str(FALSE_BLOCKER)]["next_action"].startswith("Repair the unsupported dependency")
    assert _stops(epic.state(), FALSE_BLOCKER) == []

    # t2: heartbeats, tool calls and narration keep arriving for STALLED, but evidence is identical.
    # PEER advances (new file content) and keeps being eligible while AUTHORITY is held.
    epic.write(PEER, "feature.py", "v1\n")
    epic.heartbeat(STALLED)
    epic.write(RECOVERS, "attempt.py", "same failing approach\n")
    _, items = epic.tick(capsys)
    assert items[STALLED]["state"] == "stalled" and items[STALLED]["unchanged_ticks"] == 1 and items[STALLED]["action"] is None
    assert items[PEER]["state"] == "progressing" and items[PEER]["action"] is None
    assert items[RECOVERS]["state"] == "progressing"  # a new file is a real change
    assert items[AUTHORITY]["state"] == "authority_stop"
    assert items[MALFORMED]["state"] == "unknown" and items[UNREACHABLE]["state"] == "unknown"
    assert items[UNREACHABLE]["unchanged_ticks"] == 0  # unknown never advances a ladder
    # The still-declared false blocker is not re-recorded on the next pass.
    assert len(_decisions(epic.state(), FALSE_BLOCKER, "repair_technical_dependency")) == 1 and items[FALSE_BLOCKER]["unchanged_ticks"] == 1

    # t3: still no new evidence for STALLED -> limit (2) reached -> recorded change of approach.
    epic.write(PEER, "feature.py", "v2\n")
    epic.heartbeat(STALLED)
    # The repair was carried out: the worker drops its declaration and resumes with real work.
    (epic.layout.checkout(f"w-{FALSE_BLOCKER}") / coord.BLOCKER_FILE).unlink()
    epic.busy.add(FALSE_BLOCKER)
    _, items = epic.tick(capsys)
    assert items[FALSE_BLOCKER]["state"] == "progressing" and items[FALSE_BLOCKER]["stage"] == 0
    assert items[STALLED]["action"] == "change_approach" and items[STALLED]["stage"] == 1
    [change] = _decisions(epic.state(), STALLED, "change_approach")
    assert change["bounded_by"] == {"stall_limit": 2, "step": 1, "of": 3} and change["failure_class"] == "task_failure"
    assert change["next_responsible_action"]["owner"] == "coordinator"
    assert epic.state()["issue_mappings"][str(STALLED)]["next_action"] == items[STALLED]["next_action"]
    assert items[PEER]["state"] == "progressing" and _decisions(epic.state(), PEER) == []

    # RECOVERS (unchanged since t2) gets a changed approach, then produces real evidence: the ladder resets and says so.
    epic.heartbeat(RECOVERS)
    _, items = epic.tick(capsys)  # t4
    assert items[RECOVERS]["action"] == "change_approach" and items[STALLED]["action"] is None
    epic.write(PEER, "feature.py", "v3\n")
    _, items = epic.tick(capsys)  # t5: STALLED, still without new evidence, moves to its single independent diagnosis
    assert items[STALLED]["action"] == "bounded_diagnosis" and items[RECOVERS]["action"] is None
    [diagnosis] = _decisions(epic.state(), STALLED, "bounded_diagnosis")
    assert "helper budget 0" in diagnosis["next_responsible_action"]["step"]
    epic.write(RECOVERS, "attempt.py", "different approach that works\n")
    epic.write(PEER, "feature.py", "v4\n")
    _, items = epic.tick(capsys)  # t6
    assert items[RECOVERS]["state"] == "progressing" and items[RECOVERS]["stage"] == 0
    assert [d["action"] for d in _decisions(epic.state(), RECOVERS)] == ["change_approach", "progress_resumed"]

    # STALLED continues down the bounded ladder and ends in a recorded stop, never an endless retry.
    for _ in range(1):  # t7 -> handoff (t6 was its first unchanged tick after the diagnosis)
        epic.heartbeat(STALLED)
        epic.write(PEER, "feature.py", f"v{epic.ticks}\n")
        _, items = epic.tick(capsys)
    assert items[STALLED]["action"] == "handoff"
    assert "verified absence" in _decisions(epic.state(), STALLED, "handoff")[0]["next_responsible_action"]["step"]
    for _ in range(2):  # t8, t9 -> exhausted
        epic.write(PEER, "feature.py", f"v{epic.ticks}\n")
        out, items = epic.tick(capsys)
    assert items[STALLED]["state"] == "stopped_no_progress" and items[STALLED]["action"] == "no_progress_exhausted"
    assert [s["stop"] for s in _stops(epic.state(), STALLED)] == ["no_progress_exhausted"]
    assert set(out["held"]) == {AUTHORITY, STALLED} and PEER in out["independent_work_continues"]
    assert items[PEER]["state"] == "progressing"

    # Final durable record: one bounded action per ladder step, one repair, one authority stop; no duplicates
    # across the repeated ticks, no decision for the unknown items, no manufactured statuses elsewhere.
    state = epic.state()
    assert [d["action"] for d in _decisions(state, STALLED)] == ["change_approach", "bounded_diagnosis", "handoff"]
    assert len(_decisions(state, FALSE_BLOCKER)) == 1 and len(_stops(state, AUTHORITY)) == 1
    for quiet in (PEER, MALFORMED, UNREACHABLE):
        assert _decisions(state, quiet) == [] and _stops(state, quiet) == []
    # Nothing was started, stopped or published by judging.
    assert [c for c in epic.engine.calls if c[1] == "rm"] == []
    assert [c for c in epic.engine.calls if c[1] in ("create", "start")] == worker_lifecycle_calls
    assert [c[0] for c in epic.server.calls].count("POST") == 7  # only the setup conversation creates


def test_replayed_tick_and_interrupted_pass_do_not_advance_the_ladder(tmp_path, capsys, monkeypatch):
    epic = Epic(tmp_path, capsys)
    epic.heartbeat(STALLED)
    epic.tick(capsys)  # t1 baseline
    epic.tick(capsys)  # t2 stalled 1
    path = epic_run_state.epic_run_state_path(epic.layout.run_id, root=epic.layout.run_state_dir)

    # A pass that dies partway through (after two items were recorded) is resumed by re-running the same tick id.
    real, calls = epic_run_state.update_epic_run_state, []

    def dying(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise KeyboardInterrupt
        return real(*args, **kwargs)

    monkeypatch.setattr(epic_run_state, "update_epic_run_state", dying)
    with pytest.raises(KeyboardInterrupt):
        epic.tick(capsys, name="t3")
    monkeypatch.setattr(epic_run_state, "update_epic_run_state", real)
    _, items = epic.tick(capsys, name="t3")
    assert items[STALLED]["action"] == "change_approach"
    settled = path.read_bytes()

    # Replaying the completed tick (e.g. after a coordinator restart) changes nothing and reports it as a replay.
    _, again = epic.tick(capsys, name="t3")
    assert path.read_bytes() == settled and all(i["replayed"] for i in again.values())
    assert len(_decisions(epic.state(), STALLED)) == 1 and epic.state()["issue_mappings"][str(STALLED)]["coordination"]["stall"] == 0

    # A pass id is required so that a replay cannot masquerade as a new tick.
    with pytest.raises(SystemExit) as refused:
        epic.main("coordinate", "--stall-limit", "2")
    assert refused.value.code == 2
    assert epic.main("coordinate", "--tick", "bad tick!") == 2


def test_builder_owned_receipt_is_repaired_but_external_owner_receipt_is_a_stop(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    builder = HUMAN_RECEIPT.replace("action:human-decision", "action:repair-contract").replace("owner: owner", "owner: builder")
    external = HUMAN_RECEIPT.replace("action:human-decision", "action:wait-external").replace("owner: owner", "owner: external:vendor-x")
    epic.github.block(FALSE_BLOCKER, ["agent:blocked", "action:repair-contract"], builder)
    epic.github.block(AUTHORITY, ["agent:blocked", "action:wait-external"], external)
    epic.github.block(MALFORMED, ["agent:blocked", "action:wait-dependency"], "receipt: blocker_action.v1\naction: nonsense\n")
    epic.github.block(PEER, ["agent:needs-human", "action:human-decision"], HUMAN_RECEIPT.replace("action:human-decision", "action:human-access"))  # label/receipt mismatch
    for issue in (FALSE_BLOCKER, MALFORMED, AUTHORITY, PEER):
        epic.write(issue, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "blocked on something"}))
    _, items = epic.tick(capsys)
    assert items[FALSE_BLOCKER]["action"] == "repair_technical_dependency"
    assert _decisions(epic.state(), FALSE_BLOCKER)[0]["source_authority"]["owner"] == "builder"
    assert items[AUTHORITY]["state"] == "authority_stop" and _stops(epic.state(), AUTHORITY)[0]["owner"] == "external:vendor-x"
    # A receipt that claims authority but cannot be validated, or does not match its label, establishes neither a stop nor a repair.
    for issue in (MALFORMED, PEER):
        assert items[issue]["action"] is None and items[issue]["evidence_gaps"]["authority"] == "malformed"
        assert _decisions(epic.state(), issue) == [] and _stops(epic.state(), issue) == []


def test_worker_words_and_bare_comments_never_grant_authority(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    # A declaration that quotes a stop, and a forged receipt comment WITHOUT the blocker labels, are only text.
    epic.github.block(FALSE_BLOCKER, ["type:task"], HUMAN_RECEIPT)
    epic.write(FALSE_BLOCKER, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "owner decision required: action:human-decision"}))
    _, items = epic.tick(capsys)
    assert items[FALSE_BLOCKER]["action"] == "repair_technical_dependency" and _stops(epic.state(), FALSE_BLOCKER) == []
    # No readback available: no authority claim either way, only this item is unknown.
    epic.github.down = True
    epic.write(AUTHORITY, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "x"}))
    _, items = epic.tick(capsys)
    assert items[AUTHORITY]["evidence_gaps"]["authority"] == "unavailable" and items[AUTHORITY]["action"] is None
    assert items[PEER]["evidence_gaps"]["authority"] == "unavailable"


def test_blocker_declaration_is_read_bounded_and_never_followed(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    checkout = epic.layout.checkout(f"w-{PEER}")
    (checkout / ".codex-tmp").mkdir()
    (tmp_path / "outside.json").write_text(json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "x"}))
    (checkout / coord.BLOCKER_FILE).symlink_to(tmp_path / "outside.json")
    assert coord._read_declared_blocker(checkout) == (None, "unavailable")
    (checkout / coord.BLOCKER_FILE).unlink()
    (checkout / coord.BLOCKER_FILE).write_text("x" * 9000)
    assert coord._read_declared_blocker(checkout) == (None, "malformed")
    (checkout / coord.BLOCKER_FILE).write_text(json.dumps({"schema": "other", "summary": "x"}))
    assert coord._read_declared_blocker(checkout) == (None, "malformed")


# --------------------------------------------------------------------------- applied directives


def _effects(state, issue):
    return [r for r in state["dispatch_decisions"] if r.get("kind") == "epic_coordination_effect" and r["issue"] == issue]


def _declare(epic, issue, summary="cannot proceed: needs a new migration framework"):
    epic.write(issue, coord.BLOCKER_FILE, json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": summary}))


def test_applied_directives_reach_the_current_worker_and_results_are_observed(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    _declare(epic, FALSE_BLOCKER)
    epic.others_busy(STALLED)
    epic.heartbeat(STALLED)

    # t1: the false blocker's repair directive is addressed to ITS conversation only, once, and read back.
    out, items = epic.tick(capsys, apply=True)
    [repair] = [m for m in epic.server.messages]
    assert repair[0] == epic.cid[FALSE_BLOCKER] and "simplest in-scope technical approach" in repair[1] and "new migration framework" in repair[1]
    [effect] = _effects(epic.state(), FALSE_BLOCKER)
    decision = _decisions(epic.state(), FALSE_BLOCKER, "repair_technical_dependency")[0]
    assert (effect["issue"], effect["worker"], effect["conversation_id"], effect["tick"], effect["decision_id"]) == (
        FALSE_BLOCKER, f"w-{FALSE_BLOCKER}", epic.cid[FALSE_BLOCKER], "t1", decision["id"])
    assert effect["outcome"] == "delivered" and effect["event_id"] and effect["result"] is None and effect["attempts"] == 1
    assert "issue-maintenance-change-control" in effect["pending_obligations"][0]  # the GitHub write stays a pending obligation
    assert items[FALSE_BLOCKER]["effects"] == [{"decision_id": decision["id"], "action": "repair_technical_dependency", "outcome": "delivered", "event_id": effect["event_id"]}]
    assert "not progress" in epic.state()["issue_mappings"][str(FALSE_BLOCKER)]["next_action"]
    assert epic.state()["issue_mappings"][str(FALSE_BLOCKER)]["coordination"]["last_result"]["state"] == "baseline"

    # Replaying the same pass id, and the next pass with the declaration still present, send nothing more.
    epic.ticks -= 1
    epic.tick(capsys, apply=True, name="t1")
    epic.tick(capsys, apply=True)  # t2: STALLED unchanged 1
    assert len(epic.server.messages) == 1

    # t3: STALLED reaches its limit -> change_approach is delivered; delivery alone is not progress.
    _, items = epic.tick(capsys, apply=True)
    [change] = [m for m in epic.server.messages if m[0] == epic.cid[STALLED]]
    assert "Do not repeat the same attempt" in change[1] and "worker-blocker.json" in change[1]
    [stalled_effect] = _effects(epic.state(), STALLED)
    assert stalled_effect["outcome"] == "delivered" and stalled_effect["result"] is None and items[STALLED]["state"] == "stalled"
    assert items[PEER]["state"] == "progressing" and all(m[0] in (epic.cid[FALSE_BLOCKER], epic.cid[STALLED]) for m in epic.server.messages)

    # SIMULATED reaction (a real model run is the parent's proof): new work and a re-run test cache.
    epic.react(STALLED)
    epic.write(STALLED, ".pytest_cache/v/cache/lastfailed", json.dumps({"tests/test_x.py::test_a": True}))
    _, items = epic.tick(capsys, apply=True)
    assert items[STALLED]["state"] == "progressing" and items[STALLED]["stage"] == 0
    [stalled_effect] = _effects(epic.state(), STALLED)
    assert stalled_effect["result"]["state"] == "evidence_changed" and {"checkout", "tests"} <= set(stalled_effect["result"]["changed_parts"])
    assert len(epic.server.messages) == 2 and "progress_resumed" in [d["action"] for d in _decisions(epic.state(), STALLED)]


def test_directive_effects_survive_lost_replies_restarts_and_unknown_outcomes(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    _declare(epic, FALSE_BLOCKER)
    epic.others_busy(STALLED, RECOVERS)
    for issue in (STALLED, RECOVERS):
        epic.heartbeat(issue)
    seen = []

    def at_post(cid, text):  # the attempt must already be durable when the request leaves
        marker = re.search(r"coordination-directive:[0-9a-f]{32}", text).group(0)
        seen.append([e["outcome"] for e in _effects(epic.state(), next(i for i, c in epic.cid.items() if c == cid)) if e["marker"] == marker])

    epic.server.on_post = at_post
    epic.server.post_mode[epic.cid[FALSE_BLOCKER]] = "full"        # saved, run slot full
    epic.server.post_mode[epic.cid[STALLED]] = "drop"             # request never lands, reply lost
    epic.server.post_mode[epic.cid[RECOVERS]] = "drop"
    epic.tick(capsys, apply=True)  # t1: repair directive, run deferred
    [deferred] = _effects(epic.state(), FALSE_BLOCKER)
    assert deferred["outcome"] == "delivered_run_deferred" and deferred["post_status"] == 429
    assert "run capacity was full" in epic.state()["issue_mappings"][str(FALSE_BLOCKER)]["next_action"].lower()
    epic.tick(capsys, apply=True)  # t2
    out, items = epic.tick(capsys, apply=True)  # t3: both stalled workers reach change_approach; neither lands
    for issue in (STALLED, RECOVERS):
        [effect] = _effects(epic.state(), issue)
        assert effect["outcome"] == "unknown" and effect["attempts"] == 1 and items[issue]["effects"][0]["outcome"] == "unknown"
        assert "do not resend" in epic.state()["issue_mappings"][str(issue)]["next_action"]
    assert seen[-2:] == [["reserved"], ["reserved"]]
    assert items[PEER]["state"] == "progressing" and PEER in out["independent_work_continues"]  # peers advance

    # A replay of the same pass and a restart-resumed pass never resend inside the unknown window.
    posts = len(epic.server.messages)
    epic.ticks -= 1
    epic.tick(capsys, apply=True, name="t3")
    assert len(epic.server.messages) == posts

    # Absence is not proof of non-delivery: new ticks never resend either unknown effect.
    epic.server.post_mode[epic.cid[STALLED]] = "ok"
    epic.tick(capsys, apply=True)  # t4
    [effect] = _effects(epic.state(), STALLED)
    assert effect["outcome"] == "unknown" and effect["attempts"] == 1
    [effect] = _effects(epic.state(), RECOVERS)
    assert effect["attempts"] == 1 and effect["outcome"] == "unknown"
    posts = len(epic.server.messages)
    for _ in range(2):
        epic.tick(capsys, apply=True)
    assert len(epic.server.messages) == posts and _effects(epic.state(), RECOVERS)[0]["attempts"] == 1

    # A late visible event proves only persistence, not that the lost POST finished.
    epic.react(STALLED, "work produced while event visibility was delayed\n")
    epic.tick(capsys, apply=True)
    assert _effects(epic.state(), STALLED)[0]["outcome"] == "unknown"
    text = next(t for c, t in epic.server.messages if c == epic.cid[STALLED])
    epic.server.streams[epic.cid[STALLED]].append({"id": "late-event", "kind": "MessageEvent", "source": "user",
        "llm_message": {"role": "user", "content": [{"type": "text", "text": text}]}})
    epic.tick(capsys, apply=True)
    [effect] = _effects(epic.state(), STALLED)
    assert effect["outcome"] == "unknown" and effect["event_id"] == "late-event" and effect["attempts"] == 1
    assert effect["result"] is None
    assert len(epic.server.messages) == posts

    # A deferred 429 keeps its run obligation and blocks another send for that issue.
    epic.server.post_mode[epic.cid[FALSE_BLOCKER]] = "lost_reply"
    _declare(epic, FALSE_BLOCKER, "second dependency: needs another framework")
    before = len(epic.server.messages)
    _, items = epic.tick(capsys, apply=True)
    assert len(_effects(epic.state(), FALSE_BLOCKER)) == 1 and len(epic.server.messages) == before


def test_directive_is_refused_for_an_unaddressable_conversation_and_never_sent(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.others_busy(STALLED)
    epic.heartbeat(STALLED)
    epic.tick(capsys)
    epic.tick(capsys)
    epic.tick(capsys)  # t3 judged without apply: change_approach is recorded, not delivered
    assert [d["action"] for d in _decisions(epic.state(), STALLED)] == ["change_approach"] and _effects(epic.state(), STALLED) == []
    conversation = epic.state()["issue_mappings"][str(STALLED)]["conversation"]
    ew._record_worker(epic.layout, STALLED, conversation={**conversation, "status": "unknown"})
    _, items = epic.tick(capsys, apply=True, name="t3")  # replayed pass id, now applied
    assert items[STALLED]["effects"][0]["outcome"] == "refused" and epic.server.directives() == []
    assert "no created conversation" in _effects(epic.state(), STALLED)[0]["reason"]
    # A stale decision from an earlier pass is never silently delivered later.
    epic.tick(capsys, apply=True)
    assert epic.server.directives() == []


def test_failure_classes_are_not_an_undifferentiated_task_failure_ladder(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    errors = {STALLED: "You've hit your weekly limit", FALSE_BLOCKER: "authentication required", AUTHORITY: "Credit balance is too low",
              MALFORMED: "prompt is too long", UNREACHABLE: "ECONNRESET", RECOVERS: "AssertionError in the agent loop"}
    epic.server.down.clear()
    for issue, detail in errors.items():
        epic.server.streams[epic.cid[issue]].append({"kind": "ConversationErrorEvent", "code": "", "detail": detail})
    epic.busy.add(PEER)
    epic.tick(capsys, apply=True)  # t1 baseline
    out, items = epic.tick(capsys, apply=True)  # t2
    assert items[STALLED]["state"] == "held_quota_exhausted" and items[STALLED]["action"] == "engine_quota"
    assert items[FALSE_BLOCKER]["state"] == "held_authentication" and items[AUTHORITY]["state"] == "held_policy"
    assert items[MALFORMED]["state"] == "held_context_exhausted" and items[UNREACHABLE]["state"] == "waiting_transient"
    assert items[RECOVERS]["state"] == "stalled" and items[RECOVERS]["action"] is None
    assert "#6618" in items[STALLED]["next_action"] and "do not switch engines" in items[FALSE_BLOCKER]["next_action"]
    assert "policy" in items[AUTHORITY]["next_action"] and "successor conversation" in items[MALFORMED]["next_action"]
    assert [s["stop"] for s in _stops(epic.state(), AUTHORITY)] == ["policy_error"]  # the only class that is a stop
    assert set(out["held"]) == {STALLED, FALSE_BLOCKER, AUTHORITY, MALFORMED} and PEER in out["independent_work_continues"]
    assert epic.server.directives() == [] and not any(d["action"] in ("change_approach", "bounded_diagnosis", "handoff") for d in _decisions(epic.state(), STALLED))
    # A transient network error waits a bounded number of passes, then holds; the task failure
    # (RECOVERS) gets its directive on its own limit. Nothing switches engine, model or conversation.
    out, items = epic.tick(capsys, apply=True)  # t3
    assert items[UNREACHABLE]["state"] == "held_transient_network" and items[RECOVERS]["action"] == "change_approach"
    assert [m[0] for m in epic.server.messages] == [epic.cid[RECOVERS]]
    epic.tick(capsys, apply=True)  # t4: wait spent
    out, items = epic.tick(capsys, apply=True)  # t5
    assert items[UNREACHABLE]["action"] == "transient_network"
    state = epic.state()
    assert all(state["issue_mappings"][str(i)]["engine"] == "claude-code" for i in errors if "engine" in state["issue_mappings"][str(i)])


def test_oom_retains_the_assignment_and_does_not_block_peer_work(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    ew._record_worker(epic.layout, STALLED, lifecycle_owner="fixture-owner", next_action="finish the bounded issue")
    epic.engine.runtime_states[f"w-{STALLED}"] = ("exited", "true", 137)
    epic.busy.add(PEER)
    out, items = epic.tick(capsys, apply=True)
    held = items[STALLED]
    assert held["state"] == "held_runtime_oom" and held["failure_class"] == "local_runtime_oom"
    assert held["lifecycle_owner"] == "fixture-owner" and held["remaining_outcome"] == "finish the bounded issue"
    assert held["checkout"] == str(epic.layout.checkout(f"w-{STALLED}"))
    assert "preserve" in held["next_action"].lower() and STALLED in out["held"]
    _, items = epic.tick(capsys, apply=True)
    assert items[STALLED]["remaining_outcome"] == "finish the bounded issue" and items[PEER]["state"] == "progressing"
    [hold] = _decisions(epic.state(), STALLED, "runtime_hold")
    assert hold["remaining_outcome"] == "finish the bounded issue" and hold["next_responsible_action"]["owner"] == "coordinator"
    assert not epic.server.directives(epic.cid[STALLED])
    assert not any(c[:2] == ["docker", "rm"] for c in epic.engine.calls)


def test_untrusted_receipt_and_mismatched_workspace_cannot_direct_worker(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.github.block(AUTHORITY, ["agent:needs-human", "action:human-decision"], HUMAN_RECEIPT)
    epic.github.issues[AUTHORITY]["comments"][0]["author_association"] = "CONTRIBUTOR"
    _declare(epic, AUTHORITY, "owner decision needed")
    _declare(epic, STALLED, "technical dependency")
    epic.github.block(STALLED, ["type:task"], None)
    ew._record_worker(epic.layout, STALLED, checkout=str(epic.layout.checkout(f"w-{PEER}")))
    epic.busy.add(PEER)
    _, items = epic.tick(capsys, apply=True)
    assert items[AUTHORITY]["evidence_gaps"]["authority"] == "malformed"
    assert items[STALLED]["state"] == "held_runtime_unknown"
    assert not epic.server.directives(epic.cid[AUTHORITY]) and not epic.server.directives(epic.cid[STALLED])
    assert not _stops(epic.state(), AUTHORITY)
    _, items = epic.tick(capsys, apply=True)
    assert items[PEER]["state"] == "progressing"


def test_unknown_old_effect_blocks_new_directives_but_not_peer(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    _declare(epic, FALSE_BLOCKER, "first technical dependency")
    epic.server.post_mode[epic.cid[FALSE_BLOCKER]] = "drop"
    epic.busy.add(PEER)
    epic.tick(capsys, apply=True)
    _declare(epic, FALSE_BLOCKER, "different technical dependency")
    for _ in range(4):
        out, items = epic.tick(capsys, apply=True)
        assert items[FALSE_BLOCKER]["state"] == "unknown_effect"
        assert items[PEER]["state"] == "progressing" and PEER in out["independent_work_continues"]
    [effect] = _effects(epic.state(), FALSE_BLOCKER)
    assert effect["attempts"] == 1 and effect["outcome"] == "unknown"
    assert len(epic.server.directives(epic.cid[FALSE_BLOCKER])) == 1
    assert not _stops(epic.state(), FALSE_BLOCKER)


def test_public_pr_readback_and_unavailable_event_stream_are_not_manual_status(tmp_path, capsys):
    epic = Epic(tmp_path, capsys)
    epic.others_busy(STALLED, UNREACHABLE)
    epic.server.event_down.add(epic.cid[UNREACHABLE])
    epic.tick(capsys, apply=True)
    epic.github.pulls = [{"number": 8001, "state": "open", "draft": False,
                          "body": f"Governing-Issue: #{STALLED}",
                          "head": {"ref": f"b/{STALLED}", "sha": "a" * 40,
                                   "repo": {"full_name": github_read.REPOSITORY}}}]
    _, items = epic.tick(capsys, apply=True)
    assert items[STALLED]["state"] == "progressing" and "pr" in items[STALLED]["changed_parts"]
    assert items[UNREACHABLE]["evidence_gaps"]["failure"] == "event_stream_unavailable"
    epic.github.pulls[0]["body"] = "Governing-Issue: #9999"
    _, items = epic.tick(capsys, apply=True)
    assert items[STALLED]["evidence_gaps"]["pr"] == "unavailable"
    assert not epic.server.directives(epic.cid[STALLED])


def test_reserved_attempt_after_interruption_is_reconciled_never_reposted(tmp_path, capsys, monkeypatch):
    from app.builderops import epic_coordination_effects as effects

    epic = Epic(tmp_path, capsys)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    _declare(epic, FALSE_BLOCKER)
    real_observe = effects._observe
    monkeypatch.setattr(effects, "_observe", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        epic.tick(capsys, apply=True)
    [effect] = _effects(epic.state(), FALSE_BLOCKER)
    assert effect["outcome"] == "unknown" and effect["post_status"] == 200 and effect["attempts"] == 1
    assert len(epic.server.directives(epic.cid[FALSE_BLOCKER])) == 1
    monkeypatch.setattr(effects, "_observe", real_observe)
    epic.tick(capsys, apply=True, name="t1")
    [effect] = _effects(epic.state(), FALSE_BLOCKER)
    assert effect["outcome"] == "delivered" and effect["event_id"] and effect["attempts"] == 1
    assert len(epic.server.directives(epic.cid[FALSE_BLOCKER])) == 1


def test_owned_live_fixture_drives_the_production_path_with_simulated_boundaries(tmp_path, capsys, monkeypatch):
    from scripts import epic_coordination_live_fixture as fixture

    epic, issue, worker = 9000001, 9000002, "fixture-worker"
    root, engine, server = tmp_path / "owned", CoordinationEngine(9000001), PerConversationServer()
    assert _cli(root, epic, engine, "init", "--repo-url", _seed_repo(tmp_path)) == 0
    assert _cli(root, epic, engine, "worker-create", "--worker", worker, "--issue", str(issue), "--branch", "fixture/a", "--next-action", "fixture") == 0
    call = lambda *a: ew.main(["--root", str(root), "--epic", str(epic), *a], runner=engine, http=server)  # noqa: E731
    assert call("openhands-start", "--worker", worker) == 0
    token = "a" * 32
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(fixture._run(["prompt", "--token", token])["prompt"])
    assert call("conversation-start", "--worker", worker, "--prompt-file", str(prompt)) == 0
    layout = ew.Layout(root.resolve(), epic)
    cid = ew._load_state(layout)["issue_mappings"][str(issue)]["conversation"]["id"]
    server.streams[cid] = []
    capsys.readouterr()
    # Exercise the repository's actual ignore rules in the disposable checkout.
    (layout.checkout(worker) / ".gitignore").write_text((Path(__file__).resolve().parents[2] / ".gitignore").read_text())
    args = ["--root", str(root), "--epic", str(epic), "--issue", str(issue), "--worker", worker, "--token", token]
    assert token not in prompt.read_text()
    fixture._run(["baseline", *args], runner=engine, http=server)
    def premature_response(_cid, text):
        marker = re.search(r"coordination-directive:[0-9a-f]{32}", text).group(0)
        (layout.checkout(worker) / fixture.RESULT).write_text(marker)
        (layout.checkout(worker) / "unrelated.py").write_text("unrelated\n")
    server.on_post = premature_response
    result = fixture._run(["apply", *args], runner=engine, http=server)
    assert result["result_absent_before"] and len(server.directives(cid)) == 1
    with pytest.raises(ValueError, match="after the directive event"):
        fixture._run(["verify", *args], runner=engine, http=server)
    # Simulate a later worker reaction. A real model run is separately required.
    marker = re.search(r"coordination-directive:[0-9a-f]{32}", server.directives(cid)[0]).group(0)
    (layout.checkout(worker) / fixture.RESULT).write_text(marker)
    verified = fixture._run(["verify", *args], runner=engine, http=server)
    assert verified["directive_event_id"] and "checkout" in verified["result_evidence"]["changed_parts"]
    with pytest.raises(ValueError, match="already exists"):
        fixture._run(["apply", *args], runner=engine, http=server)


def test_concurrent_reservation_allows_one_attempt_and_never_reposts_after_crash(tmp_path, capsys):
    from concurrent.futures import ThreadPoolExecutor
    from app.builderops import epic_coordination_effects as effects

    epic = Epic(tmp_path, capsys)
    epic.github.block(FALSE_BLOCKER, ["type:task"], None)
    _declare(epic, FALSE_BLOCKER)
    epic.tick(capsys)
    decision = _decisions(epic.state(), FALSE_BLOCKER, "repair_technical_dependency")[0]
    mapping = epic.state()["issue_mappings"][str(FALSE_BLOCKER)]
    expected = ew.assignment_of(mapping)  # the full observed assignment tuple the decision was judged for
    def reserve():
        return effects._reserve(epic.layout, FALSE_BLOCKER, f"w-{FALSE_BLOCKER}", decision, "t1", expected)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(result is not None for result in results) == 1
    _, items = epic.tick(capsys, apply=True, name="t1")
    assert items[FALSE_BLOCKER]["state"] == "unknown_effect"
    assert len(_effects(epic.state(), FALSE_BLOCKER)) == 1 and not epic.server.directives(epic.cid[FALSE_BLOCKER])


def test_worker_controlled_parent_symlink_is_not_followed(tmp_path):
    checkout = tmp_path / "checkout"
    outside = tmp_path / "outside"
    checkout.mkdir()
    outside.mkdir()
    (outside / "worker-blocker.json").write_text(json.dumps({"schema": coord.BLOCKER_SCHEMA, "summary": "outside"}))
    (checkout / ".codex-tmp").symlink_to(outside, target_is_directory=True)
    assert coord._read_declared_blocker(checkout) == (None, "unavailable")
