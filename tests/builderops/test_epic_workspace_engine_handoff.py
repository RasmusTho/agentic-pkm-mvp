"""Synthetic external ports; real coordinator, run-state locks, Git preservation and assembly.

No test here proves native model identity or real container/process containment. The synthetic
agent-server's reaction is labelled fixture behavior, not a model completion.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_coordination import (
    HUMAN_RECEIPT, CoordinationEngine, FakeGitHub, PerConversationServer,
)
from tests.builderops.test_epic_workspace_isolation import _cli, _seed_repo
from tests.builderops.test_epic_workspace_lifecycle import _ckpt, _git

EPIC, ISSUE, PEER = 6615, 6617, 6619
QUOTA = "You've hit your weekly limit · resets 2am (UTC)"
TASK_ACTION = "add guard to parser.py then rerun test_parser_before_publication"
CONTRACT = """## Context
Finish the assigned slice.
## Scope
Preserve the work and implement the behavior.
## Acceptance Criteria
- [ ] The continuation finishes its useful step.
  - Verify: `tests/example.py::test_step`
"""


class SyntheticEngine(CoordinationEngine):
    def __init__(self):
        super().__init__()
        self.refuse_stop = False
        self.unknown_stop = False
        self.lose_container_create = False
        self.stop_observer = None

    def __call__(self, argv, **kwargs):
        if list(argv)[:2] == ["docker", "rm"] and "--force" in argv and self.stop_observer:
            self.stop_observer(list(argv))
        if (list(argv)[:2] == ["docker", "create"] and "--rm" not in argv
                and self.lose_container_create):
            self.lose_container_create = False
            super().__call__(argv, **kwargs)  # the synthetic engine accepted the request
            raise OSError("synthetic lost container-create response")
        if list(argv)[:2] == ["docker", "rm"] and self.refuse_stop and "--force" in argv:
            self.calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, "", "")
        if (list(argv)[:2] == ["docker", "ps"] and self.unknown_stop
                and any(str(part).startswith("id=") for part in argv)):
            raise OSError("synthetic engine readback unavailable")
        return super().__call__(argv, **kwargs)


class SyntheticGitHub(FakeGitHub):
    def __init__(self):
        super().__init__()
        self.engine = None
        self.predecessor_id = None
        self.inventory_writer_present = []
        self.inventory_down = False

    def __call__(self, path, timeout):
        if "/pulls?" in path and self.inventory_down:
            raise OSError("synthetic PR inventory outage")
        if "/pulls?" in path and self.engine is not None and self.predecessor_id is not None:
            self.inventory_writer_present.append(self.predecessor_id in self.engine.ids.values())
        status, body = super().__call__(path, timeout)
        if status == 200 and "/issues/" in path and "/comments" not in path:
            data = json.loads(body)
            data.update(title="Implement the slice", body=CONTRACT)
            body = json.dumps(data).encode()
        return status, body


class SyntheticServer(PerConversationServer):
    def __init__(self, engine):
        super().__init__()
        self.engine = engine
        self.old_id = None
        self.checkout = None
        self.absence_at_successor = []
        self.hold_create = False
        self.react = True

    def __call__(self, method, port, key, path, body, timeout):
        if method == "POST" and path == "/conversations":
            settings = body["agent_settings"]
            codex = settings["acp_server"] == "codex"
            if codex:
                self.absence_at_successor.append(not ew._id_present(self.old_id, self.engine))
            if codex and self.hold_create:
                self.calls.append((method, port, path, body))
                raise OSError("synthetic lost create response")
            response = super().__call__(method, port, key, path, body, timeout)
            info = self.conversations[body["conversation_id"]]
            info["agent"] = {"kind": "ACPAgent", "acp_server": settings["acp_server"], "acp_model": settings["acp_model"]}
            info["current_model_id"] = settings["acp_model"]
            # Synthetic reaction to the successor prompt; this is not a real model execution.
            if codex and self.react:
                (self.checkout / "continued.txt").write_text("synthetic useful continuation\n")
            return response
        return super().__call__(method, port, key, path, body, timeout)


class Harness:
    def __init__(self, tmp_path, capsys, *, peer=False, start_conversation=True, codex_on_predecessor=False):
        self.root = tmp_path / "workspace-root"
        self.layout = ew.Layout(self.root.resolve(), EPIC)
        self.engine, self.github = SyntheticEngine(), SyntheticGitHub()
        self.server = SyntheticServer(self.engine)
        self.codex = tmp_path / "synthetic-codex-home"
        self.codex.mkdir(mode=0o700)
        assert _cli(self.root, EPIC, self.engine, "init", "--repo-url", _seed_repo(tmp_path)) == 0
        for issue, worker, branch in [(ISSUE, "w-a", "b/a"), *(([(PEER, "w-b", "b/b")] if peer else []))]:
            self.github.block(issue, ["type:task"], None)
            assert _cli(self.root, EPIC, self.engine, "worker-create", "--worker", worker, "--issue", str(issue),
                        "--branch", branch, "--next-action", "finish the bounded implementation") == 0
            start_args = ["openhands-start", "--worker", worker]
            if worker == "w-a" and codex_on_predecessor:
                start_args.extend(["--codex-home", str(self.codex)])
            assert self.main(*start_args) == 0
            if start_conversation:
                prompt = tmp_path / f"{worker}.txt"
                prompt.write_text("Implement the bounded issue")
                assert self.main("conversation-start", "--worker", worker, "--engine", "claude-code",
                                 "--prompt-file", str(prompt)) == 0
                cid = self.mapping(issue)["conversation"]["id"]
                self.server.streams[cid] = []
        ew._record_worker(self.layout, ISSUE, lifecycle_owner="owner-6618", builder_session="builder-session-6618",
                          last_meaningful_progress="partial implementation")
        self.old_id = self.mapping()["container_id"]
        self.old_conversation = self.mapping()["conversation"]["id"] if start_conversation else None
        self.server.old_id = self.old_id
        self.server.checkout = self.layout.checkout("w-a")
        self.github.engine, self.github.predecessor_id = self.engine, self.old_id
        self.tick_number = 0
        capsys.readouterr()

    def main(self, *args):
        return ew.main(["--root", str(self.root), "--epic", str(EPIC), *args], runner=self.engine,
                       http=self.server, fetch=self.github)

    def mapping(self, issue=ISSUE):
        return ew._load_state(self.layout)["issue_mappings"][str(issue)]

    def tick(self, capsys):
        self.tick_number += 1
        assert self.main("coordinate", "--tick", f"pass-{self.tick_number}", "--apply",
                         "--codex-home", str(self.codex)) == 0
        out = json.loads(capsys.readouterr().out)
        return {item["issue"]: item for item in out["items"]}

    def failure(self, detail=QUOTA, *, kind="ConversationErrorEvent"):
        self.server.streams[self.old_conversation] = [{"id": "error-1", "kind": kind, "detail": detail}]

    def posts(self):
        return [call for call in self.server.calls if call[0] == "POST" and call[2] == "/conversations"]



def reserve_fixture_decision(h, decision, observed):
    """Persist the synthetic decision required by the current reservation fence."""
    from app.builderops import epic_coordination_effects as effects, epic_run_state

    def update(state):
        state["dispatch_decisions"].append(dict(decision))
        state["issue_mappings"][str(ISSUE)]["coordination"] = {"last_result": {"decision_id": decision["id"]}}
        return state

    epic_run_state.update_epic_run_state(h.layout.run_id, root=h.layout.run_state_dir,
                                        updater=update, expected_epic_issue_number=h.layout.epic)
    return effects._reserve(h.layout, ISSUE, "w-a", decision, "prior-pass", observed)


def test_quota_exhaustion_hands_off_to_terra_without_competing_writers(tmp_path, capsys):
    h = Harness(tmp_path, capsys, peer=True)
    ew._record_worker(h.layout, ISSUE, next_action=TASK_ACTION)
    peer_at_stop = []
    h.engine.stop_observer = lambda argv: peer_at_stop.append(h.mapping(PEER).get("coordination")) if h.old_id in argv else None
    checkout = h.layout.checkout("w-a")
    (checkout / "README.md").write_text("stashed predecessor work\n")
    _git(checkout, "stash", "push", "-m", "keep")
    stash = _git(checkout, "rev-parse", "refs/stash")
    _git(checkout, "update-ref", "refs/heads/retained-extra", stash)
    (checkout / ".gitignore").write_text("private.txt\n")
    (checkout / "private.txt").write_text("ignored predecessor work\n")
    (checkout / "partial.py").write_text("def unfinished():\n")
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    op = json.loads(capsys.readouterr().out)["id"]
    head = _git(checkout, "rev-parse", "HEAD")
    h.github.pulls = [{"number": 44, "state": "open", "draft": False, "html_url": "https://example.invalid/44",
                       "body": "Governing-Issue: #6615\nCloses #6617", "head": {"ref": "b/a", "sha": head,
                       "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}}]
    h.failure()
    result = h.tick(capsys)
    assert result[ISSUE]["handoff"]["state"] == "continued"
    assert result[PEER]["state"] == "baseline"
    assert peer_at_stop and isinstance(peer_at_stop[0], dict)
    mapping = h.mapping()
    assert mapping["engine_handoff"]["context"]["next_action"] == TASK_ACTION
    assert h.server.absence_at_successor == [True]
    assert h.github.inventory_writer_present[0] is True and h.github.inventory_writer_present[-1] is False
    assert mapping["lifecycle_owner"] == "owner-6618" and mapping["builder_session"] == "builder-session-6618"
    assert mapping["conversation"]["engine"] == "codex" and mapping["conversation"]["model"] == "gpt-6.1-terra"
    assert mapping["conversation"]["id"] != h.old_conversation
    assert mapping["conversation_history"][-1]["id"] == h.old_conversation
    assert mapping["takeover"]["stop_id"] == mapping["engine_handoff"]["stop_intent"]["stop_id"]
    assert _ckpt(h.root, "w-a", "show", "refs/checkpoints/ckpt-0001:partial.py") == "def unfinished():"
    assert _ckpt(h.root, "w-a", "show", "refs/checkpoints/ckpt-0001:private.txt") == "ignored predecessor work"
    assert _git(checkout, "rev-parse", "refs/stash") == stash == _git(checkout, "rev-parse", "refs/heads/retained-extra")
    assert (checkout / "partial.py").read_text() == "def unfinished():\n"
    assert (checkout / "continued.txt").read_text() == "synthetic useful continuation\n"
    assert next(row for row in mapping["publication_ops"] if row["id"] == op)["result"]["number"] == 44
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    capsys.readouterr()
    payload = h.posts()[-1][3]
    assert payload["tags"] == {"epic": "6615", "issue": "6617", "worker": "w-a"}
    prompt = payload["initial_message"]["content"][0]["text"]
    assert all(text in prompt for text in ("Issue #6617", "remaining_ac", "test_step", "owner-6618", "builder-session-6618", "partial implementation"))
    h.tick(capsys)
    assert len(h.posts()) == 3  # two predecessors and exactly one successor


@pytest.mark.parametrize("detail,kind", [
    ("authentication required", "ConversationErrorEvent"),
    ("ECONNRESET", "ConversationErrorEvent"),
    ("prompt is too long", "ConversationErrorEvent"),
    ("pytest exited 1", "ConversationErrorEvent"),
    ("credit balance is too low", "ConversationErrorEvent"),
    ("authentication required: You've hit your weekly limit", "ConversationErrorEvent"),
    ("billing error: You've hit your weekly limit", "ConversationErrorEvent"),
    ("ECONNRESET: You've hit your weekly limit", "ConversationErrorEvent"),
    ("prompt is too long: You've hit your weekly limit", "ConversationErrorEvent"),
    ("tool call failed: You've hit your weekly limit", "ConversationErrorEvent"),
    ("429 Too Many Requests", "ConversationErrorEvent"),
    (QUOTA, "AgentErrorEvent"),
])
def test_non_quota_failures_do_not_switch_engine(tmp_path, capsys, detail, kind):
    h = Harness(tmp_path, capsys)
    h.failure(detail, kind=kind)
    h.tick(capsys)
    assert h.mapping()["conversation"]["id"] == h.old_conversation
    assert h.mapping()["container_id"] == h.old_id
    assert len(h.posts()) == 1 and not h.server.absence_at_successor


@pytest.mark.parametrize("code,detail,classification,expected", [
    ("UsagePolicyRefusal", f"content policy refusal: {QUOTA}", {"kind": "quota"}, "policy"),
    ("ACPPromptError", f"usage policy refusal: {QUOTA}", {"kind": "config"}, "policy"),
    ("ACPAuthRequired", QUOTA, None, "authentication"),
    ("LLMContextWindowExceedError", QUOTA, None, "context_exhausted"),
    ("ACPStartupTimeout", QUOTA, None, "transient_network"),
    ("ACPSpawnError", QUOTA, None, "task_failure"),
    ("MaxBudgetReached", QUOTA, {"kind": "quota"}, "policy"),
    ("ACPPromptError", QUOTA, {"kind": "auth"}, "authentication"),
    ("ACPPromptError", QUOTA, {"kind": "transient"}, "transient_network"),
])
def test_typed_or_conflicting_failure_cannot_trigger_quota_handoff(tmp_path, capsys, code, detail, classification, expected):
    h = Harness(tmp_path, capsys)
    h.server.streams[h.old_conversation] = [{"id": "error-1", "kind": "ConversationErrorEvent",
                                              "code": code, "detail": detail, "classification": classification}]
    result = h.tick(capsys)[ISSUE]
    assert result["failure_class"] == expected
    assert h.mapping()["conversation"]["id"] == h.old_conversation
    assert h.mapping()["container_id"] == h.old_id
    assert len(h.posts()) == 1 and not h.server.absence_at_successor


def test_conflicting_error_in_same_failure_episode_blocks_handoff_until_new_activity(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.server.streams[h.old_conversation] = [
        {"id": "policy", "kind": "ConversationErrorEvent", "code": "UsagePolicyRefusal", "detail": "refused"},
        {"id": "quota", "kind": "ConversationErrorEvent", "code": "ACPPromptError", "detail": QUOTA},
    ]
    result = h.tick(capsys)[ISSUE]
    assert result["failure_class"] == "policy" and h.mapping()["container_id"] == h.old_id
    assert len(h.posts()) == 1
    h.server.streams[h.old_conversation].extend([
        {"id": "new-work", "kind": "ActionEvent"},
        {"id": "new-quota", "kind": "ConversationErrorEvent", "code": "ACPPromptError", "detail": QUOTA,
         "classification": {"kind": "config"}},
    ])
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert h.server.absence_at_successor == [True] and len(h.posts()) == 2


@pytest.mark.parametrize("failure", ["refuse_stop", "unknown_stop"])
def test_failed_or_unknown_stop_and_restart_preserve_exact_writer(tmp_path, capsys, failure):
    h = Harness(tmp_path, capsys, peer=True)
    (h.layout.checkout("w-a") / "partial.py").write_text("retain\n")
    h.failure()
    setattr(h.engine, failure, True)
    items = h.tick(capsys)
    assert items[ISSUE]["handoff"]["state"] == "held" and items[PEER]["state"] == "baseline"
    assert len(h.posts()) == 2
    marker = h.mapping()["engine_handoff"]
    assert marker["status"] == "pending"
    setattr(h.engine, failure, False)
    items = h.tick(capsys)  # fresh coordinator pass uses the persisted exact stop intent
    assert items[ISSUE]["handoff"]["state"] == "continued"
    assert h.mapping()["takeover"]["stop_id"] == marker["stop_intent"]["stop_id"]
    assert h.server.absence_at_successor == [True]


def test_lost_create_response_is_reconciled_without_a_second_create(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.server.hold_create = True
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "unknown_create"
    record = h.mapping()["conversation"]
    assert record["status"] == "unknown"
    h.tick(capsys)
    assert len(h.posts()) == 2 and h.mapping()["conversation"]["id"] == record["id"]
    h.server.conversations[record["id"]] = {"id": record["id"], "execution_status": "idle",
        "workspace": {"working_dir": "/workspace"}, "tags": {"epic": "6615", "issue": "6617", "worker": "w-a"},
        "agent": {"kind": "ACPAgent", "acp_server": "codex", "acp_model": "gpt-6.1-terra"},
        "current_model_id": "gpt-6.1-terra"}
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert len(h.posts()) == 2 and h.mapping()["engine_handoff"]["status"] == "complete"


def test_unconfirmed_or_codex_quota_does_not_trigger_handoff(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.server.conversations[h.old_conversation]["execution_status"] = "running"
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    assert len(h.posts()) == 1 and h.mapping()["container_id"] == h.old_id
    h.server.conversations[h.old_conversation]["execution_status"] = "idle"
    h.server.conversations[h.old_conversation]["agent"] = {"kind": "ACPAgent", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
    h.server.conversations[h.old_conversation]["current_model_id"] = "gpt-6.1-terra"
    prior = h.mapping()["conversation"]
    ew._record_worker(h.layout, ISSUE, conversation={**prior, "engine": "codex", "model": "gpt-6.1-terra"})
    h.tick(capsys)
    assert len(h.posts()) == 1 and h.mapping()["container_id"] == h.old_id


def test_new_activity_after_old_quota_error_does_not_stop_the_worker(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.server.streams[h.old_conversation].append({"id": "later-action", "kind": "ActionEvent"})
    result = h.tick(capsys)[ISSUE]
    # Later activity removes the stale quota failure before a handoff is reserved.
    assert result.get("action") != "engine_quota" and "handoff" not in result
    assert h.mapping()["container_id"] == h.old_id and len(h.posts()) == 1


def test_new_activity_after_interrupted_stop_does_not_use_stale_quota(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    h.engine.refuse_stop = False
    h.server.streams[h.old_conversation].append({"id": "later-action", "kind": "ActionEvent"})
    result = h.tick(capsys)[ISSUE]
    assert result["handoff"]["state"] == "held" and "newer activity" in result["handoff"]["error"]
    assert h.mapping()["container_id"] == h.old_id and len(h.posts()) == 1


def test_existing_terra_assignment_finishes_before_the_shared_login_is_reused(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.github.block(PEER, ["type:task"], None)
    assert _cli(h.root, EPIC, h.engine, "worker-create", "--worker", "w-b", "--issue", str(PEER),
                "--branch", "b/b", "--next-action", "complete peer") == 0
    assert h.main("openhands-start", "--worker", "w-b", "--codex-home", str(h.codex)) == 0
    peer_prompt = tmp_path / "peer.txt"
    peer_prompt.write_text("finish peer")
    h.server.react = False
    assert h.main("conversation-start", "--worker", "w-b", "--engine", "codex", "--prompt-file", str(peer_prompt)) == 0
    peer_id = h.mapping(PEER)["container_id"]
    peer_conversation = h.mapping(PEER)["conversation"]["id"]
    h.server.streams[peer_conversation] = []
    h.server.absence_at_successor.clear()
    capsys.readouterr()
    h.failure()
    result = h.tick(capsys)
    assert result[ISSUE]["handoff"]["state"] == "held" and h.mapping()["state"] == "stopped_verified"
    assert not ew._id_present(h.old_id, h.engine)
    assert h.mapping(PEER)["container_id"] == peer_id and h.mapping(PEER)["state"] == "running"
    h.server.conversations[peer_conversation]["execution_status"] = "finished"
    assert h.main("worker-stop", "--worker", "w-b", "--reason", "synthetic peer finished") == 0
    capsys.readouterr()
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert h.server.absence_at_successor == [True]


def test_predecessor_can_release_its_own_codex_mount_for_handoff(tmp_path, capsys):
    h = Harness(tmp_path, capsys, codex_on_predecessor=True)
    assert h.mapping()["credentials"]["codex"] == "chatgpt-login-dir"
    h.failure()
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert h.server.absence_at_successor == [True]
    assert h.mapping()["conversation"]["engine"] == "codex"


def test_owner_change_fences_interrupted_handoff(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    ew._record_worker(h.layout, ISSUE, lifecycle_owner="different-owner")
    h.engine.refuse_stop = False
    result = h.tick(capsys)[ISSUE]
    assert result["handoff"]["state"] == "held" and "owner" in result["handoff"]["error"]
    assert len(h.posts()) == 1 and h.mapping()["container_id"] == h.old_id


def test_new_authority_hold_fences_an_interrupted_handoff(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    h.engine.refuse_stop = False
    h.github.block(ISSUE, ["agent:needs-human", "action:human-decision"], HUMAN_RECEIPT)
    assert h.tick(capsys)[ISSUE]["state"] == "authority_stop"
    assert len(h.posts()) == 1 and h.mapping()["container_id"] == h.old_id
    h.github.block(ISSUE, ["type:task"], None)
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"


def test_interrupted_checkpoint_resumes_the_same_stop_generation(tmp_path, capsys, monkeypatch):
    h = Harness(tmp_path, capsys)
    h.failure()
    (h.layout.checkout("w-a") / "partial.py").write_text("preserve me\n")
    checkpoint = ew._checkpoint
    def interrupted(*args, **kwargs):
        raise ew.EpicWorkspaceError("synthetic interruption before checkpoint")
    monkeypatch.setattr(ew, "_checkpoint", interrupted)
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    assert h.mapping()["state"] == "stopped_verified" and len(h.posts()) == 1
    stop_id = h.mapping()["engine_handoff"]["stop_intent"]["stop_id"]
    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert h.mapping()["takeover"]["stop_id"] == stop_id
    assert _ckpt(h.root, "w-a", "show", "refs/checkpoints/ckpt-0001:partial.py") == "preserve me"


def test_unknown_publication_quarantines_only_that_effect(tmp_path, capsys):
    h = Harness(tmp_path, capsys, peer=True)
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    operation = json.loads(capsys.readouterr().out)["id"]
    h.failure()
    result = h.tick(capsys)
    assert result[ISSUE]["handoff"]["state"] == "continued" and result[PEER]["state"] == "baseline"
    assert h.mapping()["publication_ops"][0]["status"] == "quarantined"
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    capsys.readouterr()
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert "Do NOT attempt" in prompt and operation in prompt
    assert (h.layout.checkout("w-a") / "continued.txt").exists()


def test_unavailable_pr_inventory_quarantines_publication_but_allows_continuation(tmp_path, capsys):
    h = Harness(tmp_path, capsys, peer=True)
    ew._record_worker(h.layout, ISSUE, next_action=TASK_ACTION)
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 0
    operation = json.loads(capsys.readouterr().out)["id"]
    h.github.inventory_down = True
    h.failure()
    result = h.tick(capsys)
    assert result[ISSUE]["handoff"]["state"] == "continued"
    assert h.mapping()["publication_ops"][0]["status"] == "quarantined"
    assert h.main("publication-begin", "--worker", "w-a", "--kind", "pr_create") == 2
    capsys.readouterr()
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert operation in prompt and "Do NOT attempt" in prompt and h.server.absence_at_successor == [True]
    assert TASK_ACTION in prompt and h.mapping()["engine_handoff"]["context"]["next_action"] == TASK_ACTION
    assert result[PEER]["state"] in ("baseline", "unknown")


def test_unknown_old_directive_does_not_block_preserved_quota_continuation(tmp_path, capsys):
    from app.builderops import epic_coordination_effects as effects

    h = Harness(tmp_path, capsys)
    observed = ew.assignment_of(h.mapping())
    decision = {"id": "synthetic-quota-prior-directive", "action": "change_approach", "assignment": observed}
    effect = reserve_fixture_decision(h, decision, observed)
    assert effect is not None and effects._pending(ew._load_state(h.layout), ISSUE)
    h.failure()
    result = h.tick(capsys)[ISSUE]
    assert result["handoff"]["state"] == "continued" and h.server.absence_at_successor == [True]
    assert not effects._pending(ew._load_state(h.layout), ISSUE)
    record = next(row for row in ew._load_state(h.layout)["dispatch_decisions"] if row.get("id") == effect["id"])
    assert record["outcome"] == "reserved" and record["conversation_id"] == h.old_conversation
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert effect["id"] in prompt and "pending_directives" in prompt and not h.server.messages


def test_task_action_survives_unknown_directive_and_interrupted_quota_handoff(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    checkout = h.layout.checkout("w-a")
    (checkout / "partial.py").write_text("unfinished task work\n")
    ew._record_worker(h.layout, ISSUE, next_action=TASK_ACTION)
    observed = ew.assignment_of(h.mapping())
    decision = {"id": "quota-unknown-directive-with-task", "action": "change_approach", "assignment": observed}
    effect = reserve_fixture_decision(h, decision, observed)
    assert effect is not None
    assert TASK_ACTION in ew.continuation_brief(h.layout, "w-a")["prompt"]
    h.failure()
    h.server.streams[h.old_conversation].insert(0, {
        "id": "old-chat", "kind": "MessageEvent", "source": "agent",
        "llm_message": {"role": "assistant", "content": [{"type": "text", "text": "PRIVATE-CHAT-SENTINEL"}]},
    })
    h.engine.refuse_stop = True
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "held"
    saved = h.mapping()["engine_handoff"]
    assert saved["context"]["next_action"] == TASK_ACTION
    assert saved["context"]["pending_directives"][0]["id"] == effect["id"]
    h.engine.refuse_stop = False
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    mapping = h.mapping()
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert TASK_ACTION in prompt and effect["id"] in prompt
    assert "PRIVATE-CHAT-SENTINEL" not in prompt and "do not resend" in prompt
    assert mapping["lifecycle_owner"] == "owner-6618" and mapping["builder_session"] == "builder-session-6618"
    assert mapping["branch"] == "b/a" and (checkout / "partial.py").read_text() == "unfinished task work\n"
    record = next(row for row in ew._load_state(h.layout)["dispatch_decisions"] if row.get("id") == effect["id"])
    assert record["outcome"] == "reserved" and not h.server.messages and len(h.posts()) == 2
    h.tick(capsys)  # a fresh pass rebuilds its view from persisted state
    assert TASK_ACTION in ew.continuation_brief(h.layout, "w-a")["prompt"]
    assert not h.server.messages and len(h.posts()) == 2


def test_new_task_action_supersedes_an_older_diagnostic_snapshot(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.github.inventory_down = True
    h.tick(capsys)  # a gap records its diagnostic before the task changes
    ew._record_worker(h.layout, ISSUE, next_action=TASK_ACTION)
    observed = ew.assignment_of(h.mapping())
    decision = {"id": "updated-task-with-directive", "action": "change_approach", "assignment": observed}
    assert reserve_fixture_decision(h, decision, observed) is not None
    h.failure()
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    assert h.mapping()["engine_handoff"]["context"]["next_action"] == TASK_ACTION
    assert TASK_ACTION in h.posts()[-1][3]["initial_message"]["content"][0]["text"]


def test_interrupted_successor_container_create_uses_a_new_fenced_stop(tmp_path, capsys):
    h = Harness(tmp_path, capsys)
    h.failure()
    (h.layout.checkout("w-a") / "partial.py").write_text("retain across both stops\n")
    h.engine.lose_container_create = True
    result = h.tick(capsys)[ISSUE]
    assert result["handoff"]["state"] == "held"
    assert h.mapping()["state"] == "starting" and len(h.posts()) == 1
    original_stop = h.mapping()["engine_handoff"]["stop_intent"]["stop_id"]
    assert h.tick(capsys)[ISSUE]["handoff"]["state"] == "continued"
    mapping = h.mapping()
    recovery = mapping["engine_handoff"]["recovery_stop_intent"]
    assert recovery["previous_stop_id"] == original_stop and recovery["stop_id"] != original_stop
    assert mapping["takeover"]["stop_id"] == recovery["stop_id"]
    assert (h.layout.checkout("w-a") / "partial.py").read_text() == "retain across both stops\n"
    assert h.server.absence_at_successor == [True] and len(h.posts()) == 2


def test_pr_review_continuation_reuses_cycle_prompt_and_operation(tmp_path, capsys, monkeypatch):
    from app.builderops import openhands_pr_cycle as cycle

    h = Harness(tmp_path, capsys)
    h.server.react = False
    operation = "pr-completion-" + "a" * 64
    prior = h.mapping()["conversation"]
    ew._record_worker(h.layout, ISSUE, conversation={**prior, "operation_id": operation})
    h.failure()
    result = h.tick(capsys)
    assert result[ISSUE]["handoff"]["state"] == "awaiting_pr_cycle" and len(h.posts()) == 1
    # Substitute only Docker's external readback; checkout inspection, lifecycle reservation,
    # operation binding and the actual PR-cycle prompt assembly remain production code.
    def docker_read(argv, *, timeout):
        assert argv[:2] == ["docker", "inspect"]
        cid = h.mapping()["container_id"]
        row = {"Id": cid, "Name": "/" + h.layout.container_name("w-a"), "State": {"Running": True},
               "Config": {"Labels": {ew.LABEL_EPIC: str(EPIC), ew.LABEL_WORKER: "w-a"}}}
        return subprocess.CompletedProcess(argv, 0, json.dumps([row]), "")
    inspect = ew.inspect_checkout
    monkeypatch.setattr(cycle, "_command", docker_read)
    monkeypatch.setattr(cycle, "_worker_runner", h.engine)
    monkeypatch.setattr(ew, "inspect_checkout", lambda layout, worker: inspect(layout, worker, runner=h.engine))
    head = _git(h.layout.checkout("w-a"), "rev-parse", "HEAD")
    pr = {"number": 44, "head_sha": head, "body": "PR contract", "governing_issue": {"body": CONTRACT},
          "review_material": {"diff": "synthetic diff", "issues": {}, "paths": ["README.md"]}}
    admission = {"engine": "claude-code", "model": "claude-sonnet-5-5", "verify_targets": ["tests/example.py::test_step"]}
    started = cycle.start_or_reconcile_review(h.layout, "w-a", operation, pr, "identity", admission, http=h.server)
    assert started["engine"] == "codex" and started["model"] == "gpt-6.1-terra" and started["operation_id"] == operation
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert all(value in prompt for value in ("<BEGIN_PR_CYCLE_REPORT>", "tests/example.py::test_step",
                                              "owner-6618", "builder-session-6618", "partial implementation"))
    assert h.server.absence_at_successor == [True]
    assert h.mapping()["engine_handoff"]["status"] == "complete"
    h.tick(capsys)
    assert len(h.posts()) == 2


def test_actual_pr_cycle_advances_the_quota_continuation(tmp_path, capsys, monkeypatch):
    """Synthetic GitHub/Docker/OpenHands ports with real cycle intake and coordinator handoff."""
    from app.builderops import openhands_pr_cycle as cycle

    h = Harness(tmp_path, capsys, start_conversation=False)
    h.server.react = False
    checkout = h.layout.checkout("w-a")
    head = _git(checkout, "rev-parse", "HEAD")
    pr_gate = {"draft": False}
    def fetch(path, timeout):
        if "/pulls?" in path:
            data = [{"number": 44}]
        elif "/pulls/44/reviews" in path:
            data = []
        elif "/pulls/44" in path:
            data = {"number": 44, "state": "open", "body": "Governing-Issue: #6617", "draft": pr_gate["draft"],
                    "labels": [], "head": {"sha": head, "repo": {"full_name": cycle.completion.REPOSITORY}},
                    "base": {"sha": "b" * 40, "ref": "main"}}
        elif "/issues/6617" in path:
            data = {"number": ISSUE, "state": "open", "body": CONTRACT, "title": "Implement the slice", "labels": []}
        else:
            raise AssertionError(path)
        return 200, json.dumps(data).encode()
    def docker_read(argv, *, timeout):
        assert argv[:2] == ["docker", "inspect"]
        cid = h.mapping()["container_id"]
        row = {"Id": cid, "Name": "/" + h.layout.container_name("w-a"), "State": {"Running": True},
               "Config": {"Labels": {ew.LABEL_EPIC: str(EPIC), ew.LABEL_WORKER: "w-a"}}}
        return subprocess.CompletedProcess(argv, 0, json.dumps([row]), "")
    inspect = ew.inspect_checkout
    monkeypatch.setattr(cycle, "_command", docker_read)
    monkeypatch.setattr(cycle, "_worker_runner", h.engine)
    monkeypatch.setattr(cycle, "_review_context", lambda pr: (
        {"files_digest": "synthetic", "closing_issue_hashes": {}, "check_config_digest": "synthetic"},
        {"diff": "synthetic diff", "issues": {}, "paths": ["README.md"]}))
    monkeypatch.setattr(ew, "inspect_checkout", lambda layout, worker, **kw: inspect(layout, worker, runner=h.engine))
    admission = [{"number": 44, "head_sha": head, "worker": "w-a", "engine": "claude-code",
                  "model": "claude-sonnet-5-5", "native_session_owned": True,
                  "test_venv": "/synthetic/venv", "verify_targets": ["tests/example.py::test_step"]}]
    first = cycle.advance(h.layout, admission, fetch=fetch, http=h.server)
    assert first["results"][0]["action"] == "independent-review"
    operation = first["results"][0]["operation_id"]
    h.old_conversation = h.mapping()["conversation"]["id"]
    h.server.streams[h.old_conversation] = []
    h.failure("authentication required")
    auth = cycle.advance(h.layout, admission, fetch=fetch, http=h.server, codex_home=h.codex)
    assert "engine_handoff" not in auth["results"][0] and len(h.posts()) == 1
    h.failure()
    pr_gate["draft"] = True
    held = cycle.advance(h.layout, admission, fetch=fetch, http=h.server, codex_home=h.codex)
    assert "engine_handoff" not in held["results"][0] and len(h.posts()) == 1
    pr_gate["draft"] = False
    checkpoint = ew._checkpoint
    def interrupted(*args, **kwargs):
        raise ew.EpicWorkspaceError("synthetic checkpoint interruption")
    monkeypatch.setattr(ew, "_checkpoint", interrupted)
    second = cycle.advance(h.layout, admission, fetch=fetch, http=h.server, codex_home=h.codex)
    assert second["results"][0]["engine_handoff"]["state"] == "held" and h.mapping()["state"] == "stopped_verified"
    monkeypatch.setattr(ew, "_checkpoint", checkpoint)
    third = cycle.advance(h.layout, admission, fetch=fetch, http=h.server, codex_home=h.codex)
    assert third["results"][0]["engine_handoff"]["state"] == "awaiting_pr_cycle" and len(h.posts()) == 1
    fourth = cycle.advance(h.layout, admission, fetch=fetch, http=h.server, codex_home=h.codex)
    assert fourth["results"][0]["action"] == "reconcile"
    assert h.mapping()["conversation"]["operation_id"] == operation
    assert h.mapping()["conversation"]["engine"] == "codex" and len(h.posts()) == 2
    prompt = h.posts()[-1][3]["initial_message"]["content"][0]["text"]
    assert "<BEGIN_PR_CYCLE_REPORT>" in prompt and "owner-6618" in prompt and "remaining_ac" in prompt
    assert h.server.absence_at_successor == [True]
