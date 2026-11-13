import json
import time
from datetime import datetime, timezone

import pytest

from app.builderops import epic_run_state, epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _seed_repo


HEAD = "a" * 40
REAL_TEST_VENV_SOURCE = cycle._test_venv_source
ISSUE_HASHES = {"title_sha256": cycle.hashlib.sha256(b"issue title").hexdigest(),
                "body_sha256": cycle.hashlib.sha256(b"issue").hexdigest()}


def setup(tmp_path, monkeypatch):
    layout = ew.Layout(tmp_path, 6615)
    epic_run_state.create_epic_run_state(6615, layout.run_id, root=layout.run_state_dir)
    ew._reserve_worker(layout, 6618, "reviewer", state="running", runtime="openhands", port=18700,
                       container_id="d" * 64)
    ew._session_key_file(layout, "reviewer")
    monkeypatch.setattr(cycle, "_assert_live_container", lambda *args: None)
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: None)
    monkeypatch.setattr(cycle, "native_execution_proof", lambda layout, worker, op, *args, **kwargs:
                        {"operation_id": op, "conversation_id": cycle._mapping(layout, worker)["conversation"]["id"]})
    monkeypatch.setattr(ew, "inspect_checkout", lambda _layout, _worker: {"readable": True, "head": HEAD, "uncommitted_count": 0})
    monkeypatch.setattr(cycle, "_review_context", lambda pr: ({"files_digest": "test", "closing_issue_hashes": {}, "check_config_digest": "test"}, {"files": [], "issues": {}}))
    monkeypatch.setattr(cycle, "_test_venv_source", lambda layout, value: cycle.Path(value))
    config = [{"test_venv": "/approved/venv", "number": 10, "head_sha": HEAD, "worker": "reviewer", "engine": "codex",
               "model": "gpt-6.1-terra", "native_session_owned": True,
               "verify_targets": ["tests/example.py::test_example"]}]
    return layout, config, FakeAgentServer()


def fetch(path, timeout):
    if "/pulls?" in path:
        data = [{"number": 9}, {"number": 10}]
    elif "/pulls/9/reviews" in path or "/pulls/10/reviews" in path:
        data = []
    elif "/pulls/" in path:
        number = int(path.rsplit("/", 1)[1])
        data = {"number": number, "state": "open", "body": "Governing-Issue: #6618", "draft": number == 9,
                "labels": [], "head": {"sha": HEAD, "repo": {"full_name": cycle.completion.REPOSITORY}},
                "base": {"sha": "b" * 40, "ref": "main"}}
    elif "/issues/6618" in path:
        data = {"number": 6618, "state": "open", "body": "Issue contract"}
    else:
        raise AssertionError(path)
    return 200, json.dumps(data).encode()


def test_actual_collector_and_openhands_create_reconcile_across_restart(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    server.lose_next_create = True
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert [row["number"] for row in result["results"]] == [9, 10]
    assert result["results"][0]["action"] == "wait"
    assert result["results"][1]["action"] == "independent-review"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    second = cycle.advance(layout, config, fetch=fetch, http=server)
    assert second["results"][1]["action"] == "reconcile"
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    body = next(call[3] for call in server.calls if call[0] == "POST")
    assert body["agent_settings"] == {"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
    assert body["workspace"] == {"working_dir": "/workspace"}


def test_unknown_create_does_not_repost_and_changed_contract_cannot_reuse_reservation(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    server.lose_next_create = server.create_not_applied = True
    cycle.advance(layout, config, fetch=fetch, http=server)
    changed = lambda path, timeout: (lambda response: (response[0], response[1].replace(b"Issue contract", b"Changed contract")))(fetch(path, timeout))
    cycle.advance(layout, config, fetch=changed, http=server)
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert len([call for call in server.calls if call[0] == "POST"]) == 1


def test_admission_and_epic_owner_are_required(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    result = cycle.advance(layout, [], fetch=fetch, http=server)
    assert all(row["action"] == "wait" for row in result["results"])
    assert not server.calls
    with pytest.raises(ew.LaunchRefused):
        cycle.advance(layout, [{**config[0], "engine": "codex", "model": "astra"}], fetch=fetch, http=server)
    wrong = ew.Layout(tmp_path, 9999)
    wrong.run_state_dir.mkdir(parents=True)
    epic_run_state.create_epic_run_state(1, wrong.run_id, root=wrong.run_state_dir)
    with pytest.raises(cycle.CycleError, match="owner mismatch"):
        cycle.advance(wrong, config, fetch=fetch, http=server)


def test_finished_review_runs_sandbox_and_ci_but_does_not_infer_merge_authority(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    conversation = state["issue_mappings"]["6618"]["conversation"]
    record = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    cid = conversation["id"]
    server.conversations[cid]["execution_status"] = "finished"
    server.events = [{"kind": "MessageEvent", "source": "agent", "detail": json.dumps({
        "identity": record["identity"], "head_sha": HEAD, "verdict": "pass", "findings": [],
        "verify_targets": config[0]["verify_targets"], "owner_doc": {"paths": []}})}]
    server.final_responses[cid] = server.events[0]["detail"]
    calls = []
    def stop(layout, worker, *, reason, expected_container_id):
        calls.append("stop")
        ew._record_worker(layout, 6618, state="stopped_verified")
    def verify(layout, worker, head, targets, test_venv):
        calls.append("sandbox")
        return {"head_sha": head, "targets": targets, "passed": True, "exit_code": 0}
    monkeypatch.setattr(ew, "stop_worker", stop)
    monkeypatch.setattr(cycle, "sandbox_verify", verify)
    monkeypatch.setattr(cycle, "ci_once", lambda number, root: calls.append("ci") or {"exit_code": 0})
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == ["stop", "sandbox", "ci"]
    assert result["results"][1]["action"] == "wait"
    assert result["results"][1]["reason"] == "review execution or sandbox verification is incomplete"
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == ["stop", "sandbox", "ci", "ci"]
    assert len([c for c in server.calls if c[0] == "POST"]) == 1


def test_review_finding_releases_reviewer_but_does_not_run_checks(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    identity = next(r["identity"] for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    server.conversations[cid]["execution_status"] = "finished"
    server.events = [{"kind": "MessageEvent", "source": "agent", "detail": json.dumps({
        "identity": identity, "head_sha": HEAD, "verdict": "findings", "findings": ["repair"],
        "verify_targets": config[0]["verify_targets"], "owner_doc": {"paths": []}})}]
    server.final_responses[cid] = server.events[0]["detail"]
    stopped = []
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw:
                        stopped.append(worker) or ew._record_worker(layout, 6618, state="stopped_verified"))
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert stopped == ["reviewer"]
    assert result["results"][1]["reason"] == "review repair belongs to current owner"


def test_real_sandbox_command_and_skipped_tests_do_not_pass(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, state="stopped_verified", image="agent-server@sha256:" + "c" * 64)
    monkeypatch.setattr(ew, "_container_state", lambda *args: None)
    seen = []
    def command(args, *, timeout):
        seen.append(args)
        if "-c" in args:
            return cycle.subprocess.CompletedProcess(args, 0, "pytest-ready\n", "")
        return cycle.subprocess.CompletedProcess(args, 0, "1 passed, 1 skipped in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    result = cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py::test_example"], "/approved/venv")
    assert not result["passed"]
    assert "--network" in seen[0] and "none" in seen[0] and "--read-only" in seen[0]
    assert all("token" not in arg.casefold() for arg in seen[0])
    assert f"{cycle.CONTAINER_TEST_VENV}/bin/python" in seen[0]
    assert cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv")["exit_code"] == 0
    with pytest.raises(cycle.CycleError, match="pytest files"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["../../etc/passwd"], "/approved/venv")


def test_changed_check_configuration_does_not_reuse_old_conversation(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    modified = [{**config[0], "verify_targets": ["tests/example.py::test_other"]}]
    result = cycle.advance(layout, modified, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "reconcile"
    assert len([c for c in server.calls if c[0] == "POST"]) == 1


def test_real_container_identity_readback_refuses_wrong_labels(tmp_path, monkeypatch):
    layout = ew.Layout(tmp_path, 6615)
    ident = "d" * 64
    mapping = {"container_id": ident}
    response = [{"Id": ident, "Name": "/" + layout.container_name("reviewer"),
                 "State": {"Running": True}, "Config": {"Labels": {
                     ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "wrong"}}}]
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: cycle.subprocess.CompletedProcess(argv, 0, json.dumps(response), ""))
    with pytest.raises(cycle.CycleError, match="identity"):
        cycle._assert_live_container(layout, "reviewer", mapping)
    response[0]["Config"]["Labels"][ew.LABEL_WORKER] = "reviewer"
    cycle._assert_live_container(layout, "reviewer", mapping)


def test_assembled_cli_requires_controller_owned_config(tmp_path, monkeypatch, capsys):
    config = tmp_path / "admission.json"
    config.write_text(json.dumps({"admissions": []}))
    config.chmod(0o600)
    seen = []
    monkeypatch.setattr(cycle, "advance", lambda layout, admissions: seen.append((layout, admissions)) or
                        {"inventory_complete": True, "failures": [], "results": []})
    assert cycle.main(["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(config)]) == 0
    assert seen[0][0] == ew.Layout(tmp_path, 6615)
    assert json.loads(capsys.readouterr().out)["results"] == []
    config.chmod(0o666)
    assert cycle.main(["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(config)]) == 2


def test_native_execution_reads_real_boundaries_and_rejects_paid_environment(tmp_path, monkeypatch):
    layout = ew.Layout(tmp_path, 6615)
    epic_run_state.create_epic_run_state(6615, layout.run_id, root=layout.run_state_dir)
    cid = "e" * 64
    image = "openhands/agent-server:1.62.0@sha256:" + "f" * 64
    operation = "pr-completion-" + "9" * 64
    ew._reserve_worker(layout, 6618, "reviewer", state="running", runtime="openhands", port=18700,
                       container_id=cid, image=image, credentials={"codex": "chatgpt-login-dir"},
                       conversation={"id": "conv", "operation_id": operation, "engine": "codex",
                                     "model": "gpt-6.1-terra", "status": "created"})
    ew._session_key_file(layout, "reviewer")
    env = []
    observed_model = ["gpt-6.1-terra"]
    observed_effort = ["high"]
    login_text = ["Logged in using ChatGPT"]
    def command(argv, *, timeout):
        if argv[1] == "inspect":
            data = [{"Id": cid, "Image": "sha256:image", "Name": "/" + layout.container_name("reviewer"),
                     "State": {"Running": True}, "Config": {"Image": image, "Env": env,
                     "Labels": {ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "reviewer"}}}]
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
        if argv[1:3] == ["image", "inspect"]:
            return cycle.subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', "")
        if argv[-3:] == [cycle.CODEX_CLI, "login", "status"]:
            return cycle.subprocess.CompletedProcess(argv, 0, login_text[0], "")
        if len(argv) > 7 and argv[-2:] == ["codex", "conv"]:
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"engine": "codex", "conversation_id": "conv", "session_id": "native", "model": observed_model[0], "effort": observed_effort[0], "timestamp": "2026-11-13T00:00:00Z"}), "")
        return cycle.subprocess.CompletedProcess(argv, 0, "route-ok\n", "")
    monkeypatch.setattr(cycle, "_command", command)
    info = {"id": "conv", "execution_status": "finished", "agent_state": {"acp_session_id": "native", "acp_session_cwd": "/workspace"},
            "agent": {"kind": "ACPAgent", "acp_server": "codex", "acp_model": "gpt-6.1-terra", "acp_effort": None},
            "current_model_id": "gpt-6.1-terra", "current_effort": "high",
            "available_efforts": [{"value": "high", "name": "High"}, {"value": "xhigh", "name": "Xhigh"}]}
    def http(method, port, key, path, body, timeout):
        if "/events/search" in path:
            return 200, {"items": [{"kind": "MessageEvent", "source": "agent", "detail": "done"}]}
        return 200, info
    entry = {"engine": "codex", "model": "gpt-6.1-terra"}
    proof = cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    assert proof["model"] == "gpt-6.1-terra" and proof["effort"] == "high"
    info["current_effort"] = "xhigh"
    observed_effort[0] = "xhigh"
    assert cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)["effort"] == "xhigh"
    observed_effort[0] = "high"
    with pytest.raises(cycle.CycleError, match="does not match"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    info["current_effort"] = "high"
    for key, bad in (("agent", {"agent_kind": "acp", "acp_server": "codex"}),
                     ("agent", {"kind": "ACPAgent", "acp_server": "claude-code", "acp_model": "gpt-6.1-terra"}),
                     ("current_model_id", "wrong"), ("available_efforts", [])):
        original = info[key]
        info[key] = bad
        with pytest.raises(cycle.CycleError, match="conversation execution"):
            cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
        info[key] = original
    old_agent = info.pop("agent")
    info["agent_settings"] = {"agent_kind": "acp", "acp_server": "codex", "acp_model": "gpt-6.1-terra"}
    with pytest.raises(cycle.CycleError, match="conversation execution"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    info["agent"] = old_agent
    info["agent_state"]["acp_session_id"] = "stale-session"
    with pytest.raises(cycle.CycleError, match="does not match"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    info["agent_state"]["acp_session_id"] = "native"
    login_text[0] = "Logged in using an API key"
    with pytest.raises(cycle.CycleError, match="subscription authentication"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    login_text[0] = "Logged in using ChatGPT"
    observed_model[0] = "other"
    with pytest.raises(cycle.CycleError, match="does not match"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)
    env.append("OPENAI_API_KEY=not-printed")
    with pytest.raises(cycle.CycleError, match="credential environment"):
        cycle.native_execution_proof(layout, "reviewer", operation, entry, http=http)


def test_merge_intent_persists_before_effect_and_lost_response_never_repeats(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    saved = {"kind": "pr_cycle", "number": 10, "identity": "identity"}
    pr = {"number": 10, "head_sha": HEAD}
    calls = []
    monkeypatch.setattr(cycle, "_premerge", lambda *args: {"number": 10, "head_sha": HEAD})
    def lost(argv, *, timeout):
        assert cycle._find(layout, 10, "identity")["merge_intent"]["head_sha"] == HEAD
        calls.append(argv)
        raise cycle.CycleError("response lost")
    monkeypatch.setattr(cycle, "_command", lost)
    monkeypatch.setattr(cycle, "reconcile_native", lambda *args: (_ for _ in ()).throw(cycle.CycleError("unknown")))
    with pytest.raises(cycle.CycleError, match="unknown"):
        cycle.merge_once(layout, pr, {}, saved)
    saved = cycle._find(layout, 10, "identity")
    with pytest.raises(cycle.CycleError, match="unknown"):
        cycle.merge_once(layout, pr, {}, saved)
    assert len(calls) == 1
    assert "--match-head-commit" in calls[0] and "--admin" not in calls[0]


def test_host_authority_uses_real_contract_and_dispatcher_not_body_flags(tmp_path, monkeypatch):
    layout, config, _ = setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, state="stopped_verified")
    monkeypatch.setattr(ew, "_container_state", lambda *args: None)
    entry = {**config[0], "claimant": "codex-6618-pr-completion", "lease_id": "lease-54616511",
             "session": "sessioncodex-6618-20261112", "owner_worktree": str(tmp_path)}
    body = "Governing-Issue: #6618\nFixes #6618\nNative-Authority: pass\n"
    pr = {"number": 10, "head_sha": HEAD, "body": body, "title": "trial",
          "governing_issue": {"body": "issue"}}
    live = {"number": 10, "state": "open", "draft": False, "title": "trial", "body": body, "created_at": "2099-01-01T00:00:00Z",
            "head": {"sha": HEAD, "ref": "codex/example", "repo": {"full_name": cycle.completion.REPOSITORY}},
            "base": {"ref": "main"}}
    task_id = cycle.github_issue_task_id(cycle.completion.REPOSITORY, 6618)
    task = {"task_id": task_id, "repo": cycle.completion.REPOSITORY, "issue_number": 6618,
            "status": "claimed", "claimed_by": entry["claimant"], "lease_id": entry["lease_id"],
            "lease_expires_at": "2099-01-01T00:00:00Z", "linked_pr": 10}
    lease = {"lease_id": entry["lease_id"], "holder": entry["claimant"], "resource": "issue:6618",
             "expires_at": task["lease_expires_at"], "released_at": None}
    events = [{"task_id": task_id, "event_type": "task.claimed", "actor": entry["claimant"],
               "lease_id": entry["lease_id"], "timestamp": "2026-11-13T00:00:00Z",
               "payload": {"session": entry["session"], "ttl_minutes": 90}}]
    runs = []
    dispatcher_status = {"ok": True, "db_exists": False, "coordination_mode": "github-label-only-fallback",
                         "fallback_reason": "dispatcher_db_missing"}
    status_code = [0]
    status_malformed = [False]
    receipt = {"id": 123, "user": {"login": "RasmusTho"}, "author_association": "OWNER", "created_at": "2026-11-13T00:00:00Z",
               "updated_at": "2026-11-13T00:00:00Z",
               "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
               "body": (f"Pickup intent receipt: agent={entry['claimant']} session={entry['session']} "
                        f"branch=codex/example worktree={tmp_path} coordination_mode=github-label-only-fallback "
                        "fallback_reason=dispatcher_db_missing issue=6618")}
    comments = [receipt]
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            if "verification-status" in argv:
                output = json.dumps({"ok": True, "runs": runs})
            elif "status" in argv and "app.dispatcher" in argv:
                output = "not-json" if status_malformed[0] else json.dumps(dispatcher_status)
            elif "--slurp" in argv:
                output = json.dumps([comments])
            else:
                output = "RasmusTho\n"
            return cycle.subprocess.CompletedProcess(argv, status_code[0] if "app.dispatcher" in argv and "status" in argv else 0, output, "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_api", lambda executor, cwd, repo, method, endpoint:
                        {"full_name": repo, "default_branch": "main"} if endpoint == "" else
                        comments if endpoint.startswith("/issues/6618/comments") else
                        [{"filename": "app/example.py"}] if endpoint.startswith("/pulls/10/files") else [])
    def registered(layout, candidate, branch):
        if candidate.get("session") != entry["session"] or candidate.get("owner_worktree") != str(tmp_path):
            raise cycle.CycleError("current registered worktree owner mismatch")
        return ({"path": str(tmp_path), "branch": branch, "owner": entry["session"],
                 "generation": "1" * 32, "registered_at": 100.0, "expires_at": 9999999999.0}, {})
    monkeypatch.setattr(cycle, "_lifecycle_owner", registered)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: live)
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"number": 6618, "state": "open", "title": "issue title", "body": "issue", "labels": []})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    monkeypatch.setattr(cycle.closure, "_dispatcher_inspect", lambda *args: (task, events, lease))
    monkeypatch.setattr(cycle, "_assert_review_threads_clear", lambda *args: None)
    authority = cycle.native_authority(layout, pr, entry)
    assert authority["closing_issues"] == [6618]
    task["claimed_by"] = "another-owner"
    with pytest.raises(cycle.CycleError, match="native authority unavailable"):
        cycle.native_authority(layout, pr, entry)
    task["claimed_by"] = entry["claimant"]
    runs.append({"pr_number": 10, "repository": cycle.completion.REPOSITORY, "status": "failed"})
    with pytest.raises(cycle.CycleError, match="owns this PR"):
        cycle.native_authority(layout, pr, entry)
    runs.clear()
    fallback = {**entry, "coordination_mode": "github-label-only-fallback", "owner_worktree": str(tmp_path),
                "fallback_reason": "dispatcher_db_missing", "coordination_evidence": "github-comment:123"}
    fallback_body = (body + f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={tmp_path} "
                     + "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
                     + f"agent={entry['claimant']} session={entry['session']} evidence=github-comment:123")
    fallback_pr = {**pr, "body": fallback_body}
    live["body"] = fallback_body
    assert cycle.native_authority(layout, fallback_pr, fallback)["owner"]["mode"] == "github-label-only-fallback"
    child_body = (body.replace("Fixes #6618", "Fixes #6619")
                  + f"Pickup-Receipt: pickup-claim-complete issue=6619 branch=codex/example worktree={tmp_path} "
                  + "coordination_mode=dispatcher-backed fallback_reason=none task_id=child lease_id=child "
                  + "holder=child evidence=verified-dispatcher-lease")
    live["body"] = child_body
    child_pr = {**pr, "body": child_body}
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6619])
    assert cycle.native_authority(layout, child_pr, entry)["closing_issues"] == [6619]
    with pytest.raises(cycle.CycleError, match="transfer registration is unproved"):
        cycle.native_authority(layout, child_pr, fallback)
    live["body"] = fallback_body
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    status_code[0] = 1
    with pytest.raises(cycle.CycleError, match="status failed"):
        cycle.native_authority(layout, fallback_pr, fallback)
    status_code[0] = 0
    status_malformed[0] = True
    with pytest.raises(cycle.CycleError, match="malformed"):
        cycle.native_authority(layout, fallback_pr, fallback)
    status_malformed[0] = False
    receipt["user"]["login"] = "another-user"
    with pytest.raises(cycle.CycleError, match="unauthenticated"):
        cycle.native_authority(layout, fallback_pr, fallback)
    receipt["user"]["login"] = "RasmusTho"
    dispatcher_status["fallback_reason"] = "dispatcher_db_uninitialized"
    with pytest.raises(cycle.CycleError, match="ambiguous"):
        cycle.native_authority(layout, fallback_pr, fallback)
    dispatcher_status["fallback_reason"] = "dispatcher_db_missing"
    dispatcher_status.update(db_exists=True, coordination_mode="dispatcher-backed")
    with pytest.raises(cycle.CycleError, match="dispatcher is available"):
        cycle.native_authority(layout, fallback_pr, fallback)
    dispatcher_status.update(db_exists=False, coordination_mode="github-label-only-fallback")
    with pytest.raises(cycle.CycleError, match="registered worktree"):
        cycle.native_authority(layout, fallback_pr, {**fallback, "session": "wrong"})
    with pytest.raises(cycle.CycleError, match="registered worktree"):
        cycle.native_authority(layout, fallback_pr, {**fallback, "owner_worktree": str(tmp_path / "other")})
    dispatcher_status.pop("db_exists")
    with pytest.raises(cycle.CycleError, match="ambiguous"):
        cycle.native_authority(layout, fallback_pr, fallback)
    dispatcher_status["db_exists"] = False
    comments.append({**receipt, "id": 124, "created_at": "2026-11-13T00:01:00Z",
                     "updated_at": "2026-11-13T00:01:00Z"})
    with pytest.raises(cycle.CycleError, match="current claimant"):
        cycle.native_authority(layout, fallback_pr, fallback)
    live["body"] = body
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: (_ for _ in ()).throw(cycle.CycleError("writer unknown")))
    with pytest.raises(cycle.CycleError, match="writer unknown"):
        cycle.native_authority(layout, pr, entry)


def test_assembled_nonclosing_review_verify_merge_and_receipt(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "github_fetch", fetch)
    monkeypatch.setattr(cycle, "native_execution_proof", lambda layout, worker, op, entry, **kw:
                        {"operation_id": op, "engine": "codex", "model": "gpt-6.1-terra", "auth": "chatgpt",
                         "source": "native-session-metadata", "native_session_id": "native", "effort": "high",
                         "timestamp": "2026-11-13T00:00:00Z", "conversation_id": cycle._mapping(layout, worker)["conversation"]["id"]})
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    record = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid]["execution_status"] = "finished"
    server.events = [{"kind": "MessageEvent", "source": "agent", "detail": json.dumps({
        "identity": record["identity"], "head_sha": HEAD, "verdict": "pass", "findings": [],
        "verify_targets": config[0]["verify_targets"], "covered_sources": ["app/example.py"],
        "scope_assessment": {"acceptance": "covered", "verify_coverage": "covered", "limitations": []},
        "owner_doc": {"outcome": "no_change", "inspected_paths": ["docs/owner.md"], "rationale": "unchanged"}})}]
    server.final_responses[cid] = server.events[0]["detail"]
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw: ew._record_worker(layout, 6618, state="stopped_verified"))
    monkeypatch.setattr(cycle, "sandbox_verify", lambda layout, worker, head, targets, test_venv:
                        {"head_sha": head, "targets": targets, "passed": True})
    monkeypatch.setattr(cycle, "ci_once", lambda *args: {"exit_code": 0})
    authority = {"number": 10, "head_sha": HEAD, "body": "Governing-Issue: #6618", "title": "",
                 "closing_issues": [], "governing_issue": 6618, "governing_issue_hashes": ISSUE_HASHES, "owner": {}}
    monkeypatch.setattr(cycle, "native_authority", lambda *args: dict(authority))
    posted = []
    def pages(executor, cwd, endpoint):
        if endpoint.endswith("/files"):
            return [{"filename": "app/example.py"}]
        if endpoint.endswith("/commits"):
            return [{"commit": {"message": "Implement feature"}}]
        return [{"body": item, "user": {"login": "RasmusTho"}} for item in posted]
    monkeypatch.setattr(cycle, "_api_pages", pages)
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            if "POST" in argv:
                posted.append(next(value[5:] for value in argv if value.startswith("body=")))
            return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {
        "state": "closed", "merged_at": "now", "head": {"sha": HEAD}, "merge_commit_sha": "b" * 40,
        "body": authority["body"], "title": ""})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"state": "open", "title": "issue title", "body": "issue"})
    monkeypatch.setattr(cycle, "_dispatcher_after_merge", lambda *args: pytest.fail("parent stays open"))
    merges = []
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: merges.append(argv) or cycle.subprocess.CompletedProcess(argv, 0, "", ""))
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "merged"
    assert len(merges) == 1 and len(posted) == 1
    saved = cycle._find(layout, 10, record["identity"])
    assert saved["reconciled"] is True and saved["merged_sha"] == "b" * 40


def test_assembled_closing_fallback_reconciles_lost_merge_and_checks_each_criterion(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "github_fetch", fetch)
    monkeypatch.setattr(cycle, "native_execution_proof", lambda layout, worker, op, entry, **kw:
                        {"operation_id": op, "engine": "codex", "model": "gpt-6.1-terra", "auth": "chatgpt",
                         "source": "native-session-metadata", "native_session_id": "native", "effort": "xhigh",
                         "timestamp": "2026-11-13T00:00:00Z", "conversation_id": cycle._mapping(layout, worker)["conversation"]["id"]})
    target = layout.checkout("reviewer") / "tests" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_example(): pass\n")
    issue_body = ("## Acceptance Criteria\n- [ ] First outcome\n  Verify: tests/example.py::test_example\n"
                  "- [ ] Second outcome\n  Verify: tests/example.py::test_example\n")
    criteria = cycle.closure._acceptance_criteria(issue_body, repo_root=layout.checkout("reviewer"))
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    record = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid]["execution_status"] = "finished"
    assessment = {criteria[0]["criterion_sha256"]: {"assessment": "covered", "rationale": "first path checked"}}
    review = {"identity": record["identity"], "head_sha": HEAD, "verdict": "pass", "findings": [],
              "verify_targets": config[0]["verify_targets"], "covered_sources": ["app/example.py"],
              "scope_assessment": {"acceptance": "covered", "verify_coverage": "covered", "limitations": []},
              "closing_assessments": {"6618": {"acceptance": "covered", "verify_coverage": "covered",
                                               "limitations": [], "criteria": assessment}},
              "owner_doc": {"outcome": "no_change", "inspected_paths": ["docs/owner.md"], "rationale": "unchanged"}}
    server.events = [{"kind": "MessageEvent", "source": "agent", "detail": json.dumps(review)}]
    server.final_responses[cid] = server.events[0]["detail"]
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw: ew._record_worker(layout, 6618, state="stopped_verified"))
    monkeypatch.setattr(cycle, "sandbox_verify", lambda layout, worker, head, targets, test_venv:
                        {"head_sha": head, "targets": targets, "passed": True})
    monkeypatch.setattr(cycle, "ci_once", lambda *args: {"exit_code": 0})
    issue = {"number": 6618, "state": "open", "title": "issue title", "body": issue_body,
             "labels": [{"name": "agent:in-progress"}]}
    authority = {"number": 10, "head_sha": HEAD, "body": "Governing-Issue: #6618", "title": "",
                 "closing_issues": [6618], "governing_issue": 6618,
                 "governing_issue_hashes": cycle.closure._issue_hashes(issue),
                 "coordination_mode": "github-label-only-fallback", "owner": {"mode": "github-label-only-fallback"}}
    monkeypatch.setattr(cycle, "native_authority", lambda *args: dict(authority))
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: dict(issue))
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    monkeypatch.setattr(cycle.closure, "_issue_events", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_closure_evidence", lambda *args: {})
    monkeypatch.setattr(cycle.closure, "_validate_closure_attribution", lambda *args: None)
    monkeypatch.setattr(cycle, "_dispatcher_after_merge", lambda *args: pytest.fail("fallback has no lease"))
    comments, effects = [], []
    def pages(executor, cwd, endpoint):
        if endpoint.endswith("/files"):
            return [{"filename": "app/example.py"}]
        if endpoint.endswith("/commits"):
            return [{"commit": {"message": "Implement feature"}}]
        return [{"body": body, "user": {"login": "RasmusTho"}} for body in comments]
    monkeypatch.setattr(cycle, "_api_pages", pages)
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            if "POST" in argv:
                effects.append("comment")
                comments.append(next(value[5:] for value in argv if value.startswith("body=")))
            elif "--remove-label" in argv:
                effects.append("label")
                issue["labels"] = []
            return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    def merged_pr(*args):
        if issue["state"] == "closed" and "readback-lost" not in effects:
            effects.append("readback-lost")
            raise cycle.CycleError("merge readback unavailable")
        return {"state": "closed", "merged_at": "now", "head": {"sha": HEAD}, "merge_commit_sha": "b" * 40,
                "body": authority["body"], "title": ""}
    monkeypatch.setattr(cycle.closure, "_pr", merged_pr)
    def lost_merge(argv, *, timeout):
        effects.append("merge")
        assert cycle._find(layout, 10, record["identity"])["merge_intent"]["owner"]["mode"] == "github-label-only-fallback"
        issue["state"] = "closed"
        raise cycle.CycleError("lost response")
    monkeypatch.setattr(cycle, "_command", lost_merge)
    first = cycle.advance(layout, config, fetch=fetch, http=server)
    assert "acceptance" in first["results"][1]["reason"] and effects == []
    saved = cycle._find(layout, 10, record["identity"])
    saved["review"]["closing_assessments"]["6618"]["criteria"][criteria[1]["criterion_sha256"]] = {
        "assessment": "covered", "rationale": "second path checked"}
    cycle._save(layout, saved)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "wait"
    assert effects == ["merge", "readback-lost"]
    retained = cycle._find(layout, 10, record["identity"])
    retained["merge_intent"].pop("coordination_mode")  # retained pre-upgrade fallback snapshot
    cycle._save(layout, retained)
    def empty(path, timeout):
        return 200, b"[]"
    restarted = cycle.advance(layout, config, fetch=empty, http=server)
    assert restarted["results"][0]["action"] == "merged"
    cycle.advance(layout, config, fetch=empty, http=server)
    assert effects == ["merge", "readback-lost", "comment", "label"]
    assert cycle._find(layout, 10, record["identity"])["reconciled"] is True


@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("scenario", ["original", "lost_reclaim", "crash_after_reclaim", "lost_completion",
                                      "lost_replacement_completion", "already_completed", "conflict", "legacy_unknown",
                                      "legacy_missing_lineage"])
def test_reconcile_dispatcher_closing_governor_uses_recorded_lease(tmp_path, monkeypatch, retained, scenario):
    layout, _, _ = setup(tmp_path, monkeypatch)
    files = [{"filename": "app/example.py"}]
    issue = {"state": "closed", "title": "issue title", "body": "issue", "labels": []}
    receipt = "post-merge owner-doc check: PR #10; no owner-doc change implied."
    owner = {"task_id": "task", "repository": cycle.completion.REPOSITORY, "issue_number": "6618",
             "lease_holder": "holder", "lease_id": "lease", "lease_expires_at": "2000-01-01T00:00:00Z", "linked_pr": "10"}
    if scenario == "legacy_missing_lineage":
        owner.pop("repository")
    intent = {"number": 10, "head_sha": HEAD, "body": "body", "title": "title",
              "closing_issues": [6618], "governing_issue": 6618, "owner": owner,
              "closing_issue_hashes": {"6618": cycle.closure._issue_hashes(issue)},
              "files_digest": cycle.hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "owner_doc_receipt": receipt}
    if not retained:
        intent["coordination_mode"] = "dispatcher-backed"
    saved = {"kind": "pr_cycle", "number": 10, "identity": "id", "merge_intent": intent}
    if scenario == "legacy_unknown":
        saved["dispatcher_completion_intent"] = True
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"state": "closed", "merged_at": "now",
                        "head": {"sha": HEAD}, "merge_commit_sha": "b" * 40, "body": "body", "title": "title"})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: issue)
    monkeypatch.setattr(cycle.closure, "_issue_events", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_closure_evidence", lambda *args: {})
    monkeypatch.setattr(cycle.closure, "_validate_closure_attribution", lambda *args: None)
    monkeypatch.setattr(cycle, "_api_pages", lambda executor, cwd, endpoint: files if endpoint.endswith("/files")
                        else [{"body": receipt, "user": {"login": "RasmusTho"}}])
    task = {"task_id": "task", "repo": cycle.completion.REPOSITORY, "issue_number": 6618,
            "linked_pr": 10, "status": "claimed", "claimed_by": "holder", "lease_id": "lease",
            "lease_expires_at": owner["lease_expires_at"]}
    lease = {"lease_id": "lease", "holder": "holder", "resource": "issue:6618",
             "expires_at": owner["lease_expires_at"], "released_at": None}
    events = [{"task_id": "task", "event_type": "task.claimed", "actor": "holder", "lease_id": "lease"}]
    if scenario in ("lost_reclaim", "crash_after_reclaim", "lost_replacement_completion", "conflict", "legacy_unknown"):
        events.append({"task_id": "task", "event_type": "task.released", "actor": "janitor", "lease_id": "lease",
                       "timestamp": "2000-01-02T00:00:00Z", "payload": {"reason": "expired"}})
        task.update(status="ready", claimed_by=None, lease_id=None, lease_expires_at=None)
        lease = None
    if scenario == "already_completed":
        events.append({"task_id": "task", "event_type": "task.completed", "actor": "holder", "lease_id": "lease"})
        task.update(status="completed", claimed_by=None, lease_id=None, lease_expires_at=None)
        lease = None
    if scenario == "conflict":
        events.append({"task_id": "task", "event_type": "task.claimed", "actor": "rival", "lease_id": "other"})
        task.update(status="claimed", claimed_by="rival", lease_id="other", lease_expires_at="2099-01-01T00:00:00Z")
        lease = {"lease_id": "other", "holder": "rival", "resource": "issue:6618",
                 "expires_at": task["lease_expires_at"], "released_at": None}
    calls = []
    fail_once = [True]
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            nonlocal lease
            action = argv[3]
            if action == "show":
                return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"task": task, "events": events, "lease": lease}), "")
            calls.append(action)
            if action == "claim":
                assert cycle._find(layout, 10, "id")["dispatcher_reclaim_intent"]["original"] == owner
                task.update(status="claimed", claimed_by="holder", lease_id="replacement", lease_expires_at="2099-01-01T00:00:00Z")
                lease = {"lease_id": "replacement", "holder": "holder", "resource": "issue:6618",
                         "expires_at": task["lease_expires_at"], "released_at": None}
                events.append({"task_id": "task", "event_type": "task.claimed", "actor": "holder", "lease_id": "replacement"})
                if scenario == "lost_reclaim" and fail_once[0]:
                    fail_once[0] = False
                    raise cycle.CycleError("claim response lost")
                return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"task": task, "lease": lease}), "")
            assert action == "complete"
            persisted = cycle._find(layout, 10, "id")
            selected = persisted["dispatcher_completion_intent"]["lease"]
            assert selected["lease_id"] == task["lease_id"]
            if task["lease_id"] == "replacement":
                assert persisted["dispatcher_replacement"] == selected
            events.append({"task_id": "task", "event_type": "task.completed", "actor": "holder", "lease_id": task["lease_id"]})
            task.update(status="completed", claimed_by=None, lease_id=None, lease_expires_at=None)
            lease = None
            if scenario in ("lost_completion", "lost_replacement_completion") and fail_once[0]:
                fail_once[0] = False
                raise cycle.CycleError("completion response lost")
            return cycle.subprocess.CompletedProcess(argv, 0, "{}", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    real_save = cycle._save
    if scenario == "crash_after_reclaim":
        def crash_save(layout, state):
            if state.get("dispatcher_replacement") and fail_once[0]:
                fail_once[0] = False
                raise cycle.CycleError("crash after reclaim")
            real_save(layout, state)
        monkeypatch.setattr(cycle, "_save", crash_save)
    if scenario == "conflict":
        with pytest.raises(cycle.CycleError, match="not attributable"):
            cycle.reconcile_native(layout, saved)
        assert calls == []
        return
    if scenario == "legacy_missing_lineage":
        with pytest.raises(cycle.CycleError, match="lacks recovery lineage"):
            cycle.reconcile_native(layout, saved)
        assert calls == []
        return
    if scenario == "legacy_unknown":
        with pytest.raises(cycle.CycleError, match="reclaim outcome remains unknown"):
            cycle.reconcile_native(layout, saved)
        assert calls == []
        return
    if scenario in ("lost_reclaim", "crash_after_reclaim", "lost_completion", "lost_replacement_completion"):
        with pytest.raises(cycle.CycleError):
            cycle.reconcile_native(layout, saved)
        saved = cycle._find(layout, 10, "id")
    assert cycle.reconcile_native(layout, saved)["action"] == "merged"
    assert calls.count("claim") == (1 if scenario in ("lost_reclaim", "crash_after_reclaim", "lost_replacement_completion") else 0)
    assert calls.count("complete") == (0 if scenario == "already_completed" else 1)
    assert cycle._find(layout, 10, "id")["dispatcher_completion"]["status"] == "completed"


def test_lost_owner_doc_response_is_not_reposted(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    files = [{"filename": "app/example.py"}]
    digest = cycle.hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    body = "post-merge owner-doc check: PR #10; no owner-doc change implied."
    saved = {"kind": "pr_cycle", "number": 10, "identity": "id", "owner_doc": {"6618": "pending"},
             "merge_intent": {"number": 10, "head_sha": HEAD, "body": "body", "title": "title",
                              "closing_issues": [], "governing_issue": 6618,
                              "governing_issue_hashes": ISSUE_HASHES,
                              "files_digest": digest, "owner_doc_receipt": body}}
    cycle._save(layout, saved)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {
        "state": "closed", "merged_at": "now", "head": {"sha": HEAD}, "merge_commit_sha": "b" * 40,
        "body": "body", "title": "title"})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"state": "open", "title": "issue title", "body": "issue"})
    monkeypatch.setattr(cycle, "_api_pages", lambda executor, cwd, endpoint: files if endpoint.endswith("/files") else [])
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, *args, **kwargs):
            pytest.fail("must not repeat uncertain owner-doc comment")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    with pytest.raises(cycle.CycleError, match="comment outcome remains unknown"):
        cycle.reconcile_native(layout, saved)


def test_failed_sandbox_preflight_stops_before_test_execution(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, state="stopped_verified", image="agent-server@sha256:" + "c" * 64)
    monkeypatch.setattr(ew, "_container_state", lambda *args: None)
    calls = []
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: calls.append(argv) or
                        cycle.subprocess.CompletedProcess(argv, 1, "", "pytest missing"))
    with pytest.raises(cycle.CycleError, match="preflight failed"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv")
    assert len(calls) == 1 and "-m" not in calls[0]


def test_advance_reconciles_merged_intent_absent_from_open_inventory(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    files = [{"filename": "app/example.py"}]
    digest = cycle.hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    receipt = "post-merge owner-doc check: PR #10; no owner-doc change implied."
    saved = {"kind": "pr_cycle", "number": 10, "identity": "persisted", "merge_intent": {
        "number": 10, "head_sha": HEAD, "body": "body", "title": "title", "closing_issues": [],
        "governing_issue": 6618, "governing_issue_hashes": ISSUE_HASHES,
        "files_digest": digest, "owner_doc_receipt": receipt}}
    cycle._save(layout, saved)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {
        "number": 10, "state": "closed", "merged_at": "now", "head": {"sha": HEAD},
        "merge_commit_sha": "b" * 40, "body": "body", "title": "title"})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"state": "open", "title": "issue title", "body": "issue"})
    monkeypatch.setattr(cycle, "_api_pages", lambda executor, cwd, endpoint: files if endpoint.endswith("/files")
                        else [{"body": receipt, "user": {"login": "RasmusTho"}}])
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("must not repeat merge"))
    def empty_open(path, timeout):
        assert "/pulls?state=open" in path
        return 200, b"[]"
    result = cycle.advance(layout, config, fetch=empty_open, http=server)
    assert result["results"] == [{"number": 10, "action": "merged", "merge_sha": "b" * 40}]
    assert cycle._find(layout, 10, "persisted")["reconciled"] is True


def test_same_head_changed_verify_targets_cannot_reuse_completed_review_or_tests(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    old_identity, old_op = first["identity"], first["operation_id"]
    old = cycle._find(layout, 10, old_identity)
    old["review"] = {"verdict": "pass", "findings": []}
    old["verification"] = {"passed": True, "head_sha": HEAD, "targets": config[0]["verify_targets"]}
    cycle._save(layout, old)
    def complete(state):
        for record in state["dispatch_decisions"]:
            if record.get("operation_id") == old_op:
                record["outcome"] = "completed"
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir,
                                         expected_epic_issue_number=6615, updater=complete)
    started = []
    monkeypatch.setattr(cycle, "start_or_reconcile_review", lambda layout, worker, operation_id, pr, identity, entry, **kw:
                        started.append((operation_id, identity, entry["verify_targets"])) or {"id": "new", "status": "created"})
    monkeypatch.setattr(cycle, "sandbox_verify", lambda *args, **kwargs: pytest.fail("stale tests reused"))
    monkeypatch.setattr(cycle, "merge_once", lambda *args, **kwargs: pytest.fail("stale review authorized merge"))
    changed = [{**config[0], "verify_targets": ["tests/example.py::test_other"]}]
    result = cycle.advance(layout, changed, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "independent-review"
    assert result["identity"] != old_identity and result["operation_id"] != old_op
    assert started == [(result["operation_id"], result["identity"], changed[0]["verify_targets"])]


def test_engine_preference_and_peer_base_tip_do_not_invalidate_review_identity():
    pr = {"repository": cycle.completion.REPOSITORY, "number": 10, "head_sha": HEAD,
          "body": "contract", "draft": False, "labels": [], "base_ref": "main", "base_sha": "a",
          "governing_issue": {"body": "issue", "state": "open"}, "state": "open",
          "head_repository": cycle.completion.REPOSITORY, "restrictions": [], "route": "native",
          "check_config": {"verify_targets": ["tests/example.py"]}, "engine": "claude-code"}
    identity = cycle.completion.work_identity(pr)
    assert cycle.completion.work_identity({**pr, "base_sha": "new-peer-base", "engine": "codex"}) == identity
    assert cycle.completion.work_identity({**pr, "check_config": {"verify_targets": ["tests/other.py"]}}) != identity


def test_verified_stop_requires_recorded_container_absence_and_live_engine(tmp_path, monkeypatch):
    layout = ew.Layout(tmp_path, 6615)
    mapping = {"state": "stopped_verified", "container_id": "d" * 64}
    monkeypatch.setattr(ew, "_assert_engine", lambda *args: "docker")
    monkeypatch.setattr(ew, "_container_state", lambda *args: None)
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: cycle.subprocess.CompletedProcess(argv, 1, "", "Error: No such object"))
    cycle._assert_stopped(layout, "reviewer", mapping)
    monkeypatch.setattr(cycle, "_command", lambda argv, timeout: cycle.subprocess.CompletedProcess(argv, 1, "", "daemon unavailable"))
    with pytest.raises(cycle.CycleError, match="absence is not established"):
        cycle._assert_stopped(layout, "reviewer", mapping)


def test_authority_failure_for_one_admitted_pr_does_not_abort_peer(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    config.append({**config[0], "number": 9})
    def one(layout, pr, entry, *, http):
        if pr["number"] == 9:
            raise cycle.closure.ClosureError("unknown", "authority unavailable")
        return {"number": pr["number"], "action": "advanced"}
    monkeypatch.setattr(cycle, "_advance_one", one)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert [row["action"] for row in result["results"]] == ["wait", "advanced"]


def test_review_context_reads_diff_contract_and_check_rules(monkeypatch):
    data = {"base": "1" * 40, "patch": "-old\n+new", "child": "deliver red behavior", "rule": "check"}
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd):
            return cycle.subprocess.CompletedProcess(argv, 0, data["patch"], "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"head": {"sha": HEAD}, "base": {"sha": data["base"]}})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [2])
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"number": 2, "state": "open", "title": "child", "body": data["child"]})
    monkeypatch.setattr(cycle, "_api_pages", lambda *args: [{"filename": "app/a.py", "patch": data["patch"]}])
    def api(executor, cwd, repo, method, endpoint):
        if endpoint.startswith("/git/trees/"):
            return {"truncated": False, "tree": [{"path": ".github/workflows/ci.yml", "sha": "workflow", "type": "blob", "mode": "100644"}]}
        if endpoint == "/branches/main/protection":
            return {"checks": data["rule"]}
        if endpoint.startswith("/rulesets?"):
            return []
        raise AssertionError(endpoint)
    monkeypatch.setattr(cycle.closure, "_api", api)
    pr = {"number": 10, "head_sha": HEAD, "body": "Governing-Issue: #1\nFixes #2"}
    before, material = cycle._review_context(pr)
    assert material["issues"]["2"]["body"] == data["child"]
    data["base"] = "2" * 40
    assert cycle._review_context(pr)[0] == before
    data["patch"] = "-old\n+different"
    assert cycle._review_context(pr)[0] != before
    data["patch"] = "-old\n+new"
    data["child"] = "deliver blue behavior"
    assert cycle._review_context(pr)[0] != before
    data["child"] = "deliver red behavior"
    data["rule"] = "other check"
    assert cycle._review_context(pr)[0] != before


def test_production_review_identity_reacts_to_content_not_unrelated_base(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    state = {"base": "first", "diff": "same", "child": "contract"}
    monkeypatch.setattr(cycle, "_review_context", lambda pr: (
        {"diff_digest": state["diff"], "closing_issue_hashes": {"2": state["child"]}, "check_config_digest": "same"},
        {"issues": {"2": {"body": state["child"]}}, "diff": state["diff"]}))
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    state["base"] = "advanced"
    same = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert same["identity"] == first["identity"]
    state["diff"] = "different diff, same paths and head"
    changed = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert changed["identity"] != first["identity"]
    state["diff"] = "same"
    state["child"] = "changed acceptance"
    changed_child = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert changed_child["identity"] != first["identity"]


def test_each_child_criterion_needs_substantive_review():
    criteria = [{"criterion_sha256": "red", "verify_targets": ["tests/a.py"]},
                {"criterion_sha256": "blue", "verify_targets": ["tests/a.py"]}]
    child = {"acceptance": "covered", "verify_coverage": "covered", "limitations": [],
             "criteria": {"red": {"assessment": "covered", "rationale": "red path handles the input"}}}
    review = {"closing_assessments": {"2": child}}
    with pytest.raises(cycle.CycleError, match="acceptance"):
        cycle._assert_child_assessment(review, 2, criteria)
    child["criteria"]["blue"] = {"assessment": "covered", "rationale": "blue path persists the result"}
    cycle._assert_child_assessment(review, 2, criteria)
    child["criteria"]["blue"]["rationale"] = ""
    with pytest.raises(cycle.CycleError, match="acceptance"):
        cycle._assert_child_assessment(review, 2, criteria)


def _venv(path):
    (path / "bin").mkdir(parents=True)
    (path / "pyvenv.cfg").write_text("home = /usr/local/bin\n")
    (path / "bin" / "python").symlink_to("/usr/local/bin/python3.13")
    return path


def test_controller_venv_preflight_refuses_unsafe_sources(tmp_path):
    layout = ew.Layout(tmp_path / "workspaces", 6615)
    layout.root.mkdir()
    venv = _venv(tmp_path / "verification" / "venv")
    assert cycle._test_venv_source(layout, str(venv)) == venv
    (venv / ".env").write_text("placeholder")
    with pytest.raises(cycle.CycleError, match="credential-shaped"):
        cycle._test_venv_source(layout, str(venv))
    (venv / ".env").unlink()
    (venv / "escape").symlink_to("/etc/passwd")
    with pytest.raises(cycle.CycleError, match="symlink"):
        cycle._test_venv_source(layout, str(venv))
    # A model-writable venv could fake passing tests; a venv containing the
    # model root would mount that root. Both are refused before any inspection.
    model_written = _venv(layout.checkout("reviewer") / ".venv")
    with pytest.raises(cycle.CycleError, match="outside the model workspace root"):
        cycle._test_venv_source(layout, str(model_written))
    enclosing = ew.Layout(_venv(tmp_path / "enclosing") / "workspaces", 6615)
    with pytest.raises(cycle.CycleError, match="outside the model workspace root"):
        cycle._test_venv_source(enclosing, str(tmp_path / "enclosing"))
    with pytest.raises(cycle.CycleError, match="outside the model workspace root"):
        cycle._test_venv_source(ew.Layout(cycle.Path("/"), 6615), str(venv))


def test_sandbox_refuses_model_workspace_venv_before_container(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "_test_venv_source", REAL_TEST_VENV_SOURCE)
    ew._record_worker(layout, 6618, state="stopped_verified", image="agent-server@sha256:" + "c" * 64)
    monkeypatch.setattr(ew, "_container_state", lambda *args: None)
    monkeypatch.setattr(cycle, "_assert_stopped", lambda *args: None)
    seen = []
    monkeypatch.setattr(cycle, "_command", lambda args, *, timeout: seen.append(args))
    fake = _venv(layout.worker_dir("reviewer") / "home" / "venv")
    with pytest.raises(cycle.CycleError, match="outside the model workspace root"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], str(fake))
    assert seen == []


def test_claude_subscription_reaches_same_model_observation_boundary(tmp_path, monkeypatch):
    layout = ew.Layout(tmp_path, 6615)
    epic_run_state.create_epic_run_state(6615, layout.run_id, root=layout.run_state_dir)
    cid, operation = "e" * 64, "pr-completion-" + "9" * 64
    image = "openhands/agent-server:1.62.0@sha256:" + "f" * 64
    ew._reserve_worker(layout, 6618, "reviewer", state="running", runtime="openhands", port=18700,
                       container_id=cid, image=image, credentials={"claude": "oauth-token-env"},
                       conversation={"id": "conv", "operation_id": operation, "engine": "claude-code",
                                     "model": "claude-sonnet-5-5", "status": "created"})
    ew._session_key_file(layout, "reviewer")
    def command(argv, *, timeout):
        if argv[-1:] == [cycle.CLAUDE_STATUS]:
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"loggedIn": True, "authMethod": "oauth_token", "apiProvider": "firstParty"}), "")
        if len(argv) > 7 and argv[-2:] == ["claude-code", "conv"]:
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"engine": "claude-code", "conversation_id": "conv", "session_id": "native", "model": "claude-sonnet-5-5", "effort": None, "timestamp": "2026-11-13T00:00:00Z"}), "")
        if argv[1:3] == ["image", "inspect"]:
            data = [{"Id": "sha256:image"}]
        else:
            data = [{"Id": cid, "Image": "sha256:image", "Name": "/" + layout.container_name("reviewer"),
                     "State": {"Running": True}, "Config": {"Image": image,
                     "Env": ["CLAUDE_CODE_OAUTH_TOKEN=test-placeholder"],
                     "Labels": {ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "reviewer"}}}]
        return cycle.subprocess.CompletedProcess(argv, 0, json.dumps(data), "")
    monkeypatch.setattr(cycle, "_command", command)
    def http(method, port, key, path, body, timeout):
        if "/events/search" in path:
            return 200, {"items": [{"kind": "MessageEvent", "source": "agent", "detail": "done"}]}
        return 200, {"id": "conv", "execution_status": "finished", "agent_state": {"acp_session_id": "native", "acp_session_cwd": "/workspace"},
                     "agent": {"kind": "ACPAgent", "acp_server": "claude-code", "acp_model": "claude-sonnet-5-5", "acp_effort": None},
                     "current_model_id": "claude-sonnet-5-5", "current_effort": "default",
                     "available_efforts": [{"value": "default", "name": "Default"}]}
    proof = cycle.native_execution_proof(layout, "reviewer", operation,
                                         {"engine": "claude-code", "model": "claude-sonnet-5-5"}, http=http)
    assert proof["auth"] == "claude-subscription" and proof["model"] == "claude-sonnet-5-5"


@pytest.mark.parametrize("engine,model", [("codex", "gpt-6.1-terra"), ("claude-code", "claude-sonnet-5-5")])
def test_public_finish_drives_production_review_for_both_engines(tmp_path, monkeypatch, engine, model):
    live_assert = cycle._assert_live_container
    layout, config, server = setup(tmp_path, monkeypatch)
    entry = config[0]
    entry.update(engine=engine, model=model)
    ident = "d" * 64
    image = "openhands/agent-server:1.62.0@sha256:" + "f" * 64
    credentials = {"codex": "chatgpt-login-dir"} if engine == "codex" else {"claude": "oauth-token-env"}
    ew._record_worker(layout, 6618, image=image, credentials=credentials)
    monkeypatch.setattr(cycle, "_assert_live_container", live_assert)
    def command(argv, *, timeout):
        if argv[1] == "inspect":
            env = [] if engine == "codex" else ["CLAUDE_CODE_OAUTH_TOKEN=test-placeholder"]
            row = {"Id": ident, "Image": "sha256:image", "Name": "/" + layout.container_name("reviewer"),
                   "State": {"Running": True}, "Config": {"Image": image, "Env": env,
                   "Labels": {ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "reviewer"}}}
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps([row]), "")
        if argv[1:3] == ["image", "inspect"]:
            return cycle.subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', "")
        if argv[-3:] == [cycle.CODEX_CLI, "login", "status"]:
            return cycle.subprocess.CompletedProcess(argv, 0, "Logged in using ChatGPT", "")
        if argv[-1:] == [cycle.CLAUDE_STATUS]:
            return cycle.subprocess.CompletedProcess(argv, 0, '{"loggedIn":true,"authMethod":"oauth_token","apiProvider":"firstParty"}', "")
        if len(argv) > 7 and argv[-2] == engine:
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps({"engine": engine, "conversation_id": argv[-1],
                "session_id": "native", "model": model, "effort": "high" if engine == "codex" else None,
                "timestamp": "2026-11-13T00:00:00Z"}), "")
        return cycle.subprocess.CompletedProcess(argv, 0, "route-ok\n", "")
    monkeypatch.setattr(cycle, "_command", command)
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    record = next(row for row in state["compact_receipts"] if row.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid].update(execution_status="finished", agent_state={"acp_session_id": "native", "acp_session_cwd": "/workspace"},
        agent={"kind": "ACPAgent", "acp_server": engine, "acp_model": model}, current_model_id=model,
        current_effort="high" if engine == "codex" else "default",
        available_efforts=[{"value": "high" if engine == "codex" else "default"}])
    class PrivateGuard(dict):
        def get(self, key, *args):
            if key in ("reasoning_content", "thinking_blocks"):
                raise AssertionError("private reasoning was accessed")
            return super().get(key, *args)
    server.events = [PrivateGuard(kind="MessageEvent", source="agent", llm_message=PrivateGuard(content=[{"text": ""}],
        reasoning_content="private sentinel", thinking_blocks=["private sentinel"])),
        {"kind": "MessageEvent", "source": "agent", "llm_message": {"content": [{"text": "Public progress"}]}},
        {"kind": "ActionEvent", "source": "agent", "tool_name": "finish",
         "action": {"kind": "FinishAction", "message": "public finish"}}]
    report = {"identity": record["identity"], "head_sha": HEAD, "verdict": "findings", "findings": ["repair"],
              "verify_targets": entry["verify_targets"], "owner_doc": {"paths": []}}
    public = json.dumps(report)
    invalid = ["", "not json", "x" * 65537, public + "\n" + public,
               '<BEGIN_PR_CYCLE_REPORT>' + public + '<END_PR_CYCLE_REPORT>' + public,
               json.dumps({**report, "identity": "wrong"}), '{"identity":"x","identity":"y"}',
               json.dumps({**report, "unexpected": "extra"}), public.replace('"repair"', 'NaN'),
               '{"nested":' * 25 + '0' + '}' * 25]
    stopped = []
    def stop(layout, worker, **kwargs):
        saved = cycle._find(layout, 10, record["identity"])
        assert saved["review"] == report and saved["execution_proof"]["conversation_id"] == cid
        assert saved["stop_intent"]["container_id"] == ident
        stopped.append(worker)
        ew._record_worker(layout, 6618, state="stopped_verified")
    monkeypatch.setattr(ew, "stop_worker", stop)
    for text in invalid:
        server.final_responses[cid] = text
        cycle.advance(layout, config, fetch=fetch, http=server)
        assert stopped == []
    server.final_responses[cid] = public
    server.conversations[cid]["id"] = "different-conversation"
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert stopped == []
    server.conversations[cid]["id"] = cid
    server.final_responses[cid] = "Builder closeout complete.\n<BEGIN_PR_CYCLE_REPORT>\n" + public + "\n<END_PR_CYCLE_REPORT>"
    server.events[-1]["action"]["message"] = server.final_responses[cid]
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["reason"] == "review repair belongs to current owner"
    assert stopped == ["reviewer"]
    assert any(call[2] == f"/conversations/{cid}/agent_final_response" for call in server.calls)


def test_findings_unknown_stop_reconciles_absence_and_releases_actual_capacity_guard(tmp_path, monkeypatch):
    actual_stopped = cycle._assert_stopped
    layout, config, server = setup(tmp_path / "workspace", monkeypatch)
    monkeypatch.setattr(cycle, "_assert_stopped", actual_stopped)
    codex_dir = tmp_path / "codex-home"
    codex_dir.mkdir(mode=0o700)
    class Engine(FakeEngine):
        def __init__(self):
            super().__init__()
            self.lost = True
        def __call__(self, argv, **kwargs):
            if argv[1] == "inspect" and "--format" not in argv:
                self.calls.append(list(argv))
                if "reviewer" in self.containers:
                    return cycle.subprocess.CompletedProcess(argv, 0, "[]", "")
                return cycle.subprocess.CompletedProcess(argv, 1, "", "No such object")
            if argv[1] == "rm" and argv[-1] == "d" * 64:
                self.calls.append(list(argv))
                self.containers.pop("reviewer", None)
                return cycle.subprocess.CompletedProcess(argv, 0, "", "")
            if (argv[1] == "ps" and f"id={'d' * 64}" in argv and self.lost
                    and "reviewer" not in self.containers):
                # The removal happened, but its absence readback is lost before the record.
                self.lost = False
                raise OSError("stop response lost")
            return super().__call__(argv, **kwargs)
    engine = Engine()
    engine.containers.update(reviewer="running", repair="running")
    engine.ids["epicws-6615-reviewer"] = "d" * 64
    engine.labels["reviewer"] = ["epic-workspace.codex-home=1", f"{ew.LABEL_EPIC}=6615", f"{ew.LABEL_WORKER}=reviewer"]
    engine.labels["repair"] = []
    with pytest.raises(ew.LaunchRefused, match="already mounted"):
        ew._validate_codex_home(codex_dir, layout, engine)
    real_stop = ew.stop_worker
    monkeypatch.setattr(cycle.subprocess, "run", engine)
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw: real_stop(layout, worker, runner=engine, **kw))
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    record = next(row for row in state["compact_receipts"] if row.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid]["execution_status"] = "finished"
    report = {"identity": record["identity"], "head_sha": HEAD, "verdict": "findings", "findings": ["repair"],
              "verify_targets": config[0]["verify_targets"], "owner_doc": {"paths": []}}
    server.final_responses[cid] = json.dumps(report)
    first = cycle.advance(layout, config, fetch=fetch, http=server)
    assert first["results"][1]["action"] == "wait"
    saved = cycle._find(layout, 10, record["identity"])
    assert saved["review"] == report and saved["execution_proof"]["conversation_id"] == cid
    assert saved["stop_intent"]["container_id"] == "d" * 64 and not saved.get("stop_verified")
    assert ew._load_state(layout)["issue_mappings"]["6618"]["state"] == "running"
    second = cycle.advance(layout, config, fetch=fetch, http=server)
    assert second["results"][1]["reason"] == "review repair belongs to current owner"
    assert cycle._find(layout, 10, record["identity"])["stop_verified"] is True
    assert ew._validate_codex_home(codex_dir, layout, engine) == [(str(codex_dir.resolve()), ew.CODEX_HOME_TARGET)]
    assert engine.containers == {"repair": "running"}
    assert len([call for call in engine.calls if call[1] == "rm"]) == 1


T0 = datetime(2026, 11, 13, tzinfo=timezone.utc).timestamp()


def _event_time(seconds):
    """Dispatcher event time as ``app.dispatcher.leases._utc_now`` writes it."""
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="microseconds")


def _github_time(seconds):
    """GitHub server comment time: whole seconds, ``Z`` suffix."""
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _handoff(f, *, predecessor, successor, registration, prior_lease, pickup_lease, holder=None):
    """Acknowledged lifecycle record in the encoding documented in DEV_WORKFLOW.md."""
    agent, session = successor
    release = {"status": "released"}
    if prior_lease is not None:
        release.update(task_id=f["task_id"], lease_id=prior_lease, holder=holder or predecessor[0],
                       readback={"status": "ready", "claimed_by": None, "lease_id": None})
    return {"issue": 6618, "current_lifecycle_owner": {"agent": predecessor[0], "session": predecessor[1]},
            "successor": {"agent": agent, "session": session}, "branch": "codex/example", "base": "main",
            "writable_worktree": str(f["worktree"]), "unpublished_candidate_head": f["head"],
            "changed_files": ["app/example.py"], "current_validation": "bound to head",
            "current_review_receipt_evidence": "bound to head", "blockers": "none",
            "residual_risk": "review required", "next_authorized_action": "continue",
            "successor_acknowledgment": {
                "agent": agent, "session": session, "prior_coordination_release": release,
                "successor_pickup": {"mode": "dispatcher-backed", "agent": agent, "session": session,
                                     "lease_id": pickup_lease},
                "prior_worktree_release": {"status": "released", "path": str(f["worktree"]), "owner": predecessor[1],
                                           "branch": "codex/example", "generation": registration["generation"]},
                "successor_registration": {"path": str(f["worktree"]), "branch": "codex/example", "owner": session,
                                           "generation": registration["generation"]},
                "candidate_readback": {"branch": "codex/example", "base": "main", "head": f["head"],
                                       "changed_files": ["app/example.py"]}}}


def _comment(comment_id, record, created, updated=None):
    return {"id": comment_id, "created_at": _github_time(created), "updated_at": _github_time(updated or created),
            "author_association": "OWNER", "user": {"login": "RasmusTho"},
            "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
            "body": json.dumps({"lifecycle_handoff_receipt.v1": record})}


def _two_phase(record, *, receipt_at, ack_at, receipt_updated=None, first_id=41):
    """The receipt posted before the release, then the acknowledgment as a new comment."""
    pending = {k: v for k, v in record.items() if k != "successor_acknowledgment"}
    return [_comment(first_id, pending, receipt_at, receipt_updated), _comment(first_id + 1, record, ack_at)]


def _prepare_and_pin(f, record, *, receipt_at, ack_at, first_id=41):
    pending = _two_phase(record, receipt_at=receipt_at, ack_at=ack_at, first_id=first_id)[0]
    readbacks = cycle.agent_worktree.prepare_transfer_registration(
        f["source"], worktree=f["worktree"], owner=record["successor"]["session"], issue=6618, pr=10,
        pending_comment=pending, base_sha=f["live"]["base"]["sha"], workspace_root=f["layout"].root, now=ack_at - 10)
    record["successor_acknowledgment"].update(readbacks)
    comments = _two_phase(record, receipt_at=receipt_at, ack_at=ack_at, first_id=first_id)
    cycle.agent_worktree.pin_transfer_registration(
        f["source"], worktree=f["worktree"], owner=record["successor"]["session"], issue=6618, pr=10,
        pending_comment=comments[0], ack_comment=comments[1], workspace_root=f["layout"].root, now=ack_at + 2)
    return comments


def _native_authority_fixture(tmp_path, monkeypatch):
    """Real lifecycle registry and Git worktree; GitHub and dispatcher are fake ports."""
    layout, config, _ = setup(tmp_path / "workers", monkeypatch)
    source = cycle.Path(_seed_repo(tmp_path))
    worktree = tmp_path / "owner-checkout"
    cycle.subprocess.run(["git", "-C", str(source), "worktree", "add", "-b", "codex/example", str(worktree)],
                         check=True, capture_output=True, text=True)
    base = cycle.subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    (worktree / "app").mkdir()
    (worktree / "app" / "example.py").write_text("candidate\n")
    cycle.subprocess.run(["git", "-C", str(worktree), "add", "app/example.py"], check=True, capture_output=True, text=True)
    cycle.subprocess.run(["git", "-C", str(worktree), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                          "commit", "-m", "candidate"], check=True, capture_output=True, text=True)
    head = cycle.subprocess.run(["git", "-C", str(worktree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    entry = {**config[0], "lifecycle_repo": str(source), "owner_worktree": str(worktree),
             "claimant": "original", "session": "session-original", "lease_id": "old-lease"}
    task_id = cycle.github_issue_task_id(cycle.completion.REPOSITORY, 6618)
    body = ("Governing-Issue: #6618\nFixes #6618\n"
            f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={worktree} "
            f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} lease_id=old-lease "
            "holder=original evidence=verified-dispatcher-lease")
    pr = {"number": 10, "head_sha": head, "body": body, "title": "trial", "governing_issue": {"body": "issue"}}
    live = {"number": 10, "state": "open", "draft": False, "title": "trial", "body": body, "created_at": "2099-01-01T00:00:00Z",
            "head": {"sha": head, "ref": "codex/example", "repo": {"full_name": cycle.completion.REPOSITORY}},
            "base": {"ref": "main", "sha": base}}
    task = {"task_id": task_id, "repo": cycle.completion.REPOSITORY, "issue_number": 6618, "status": "claimed",
            "claimed_by": "original", "lease_id": "old-lease", "lease_expires_at": "2099-01-01T00:00:00Z", "linked_pr": 10}
    lease = {"lease_id": "old-lease", "holder": "original", "resource": "issue:6618",
             "expires_at": task["lease_expires_at"], "released_at": None}
    events = [{"task_id": task_id, "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
               "timestamp": _event_time(T0), "payload": {"session": "session-original", "ttl_minutes": 90}}]
    comments = []
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            output = ('{"ok":true,"runs":[]}' if "verification-status" in argv else
                      '{"ok":true,"db_exists":false,"coordination_mode":"github-label-only-fallback",'
                      '"fallback_reason":"dispatcher_db_missing"}' if "app.dispatcher" in argv and "status" in argv else
                      json.dumps([comments]) if "--slurp" in argv else "RasmusTho\n")
            return cycle.subprocess.CompletedProcess(argv, 0, output, "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_api", lambda executor, cwd, repo, method, endpoint:
                        {"full_name": repo, "default_branch": "main"} if endpoint == "" else
                        comments if endpoint.startswith("/issues/6618/comments") else
                        [{"filename": "app/example.py"}] if endpoint.startswith("/pulls/10/files") else [])
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: live)
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"state": "open", "title": "issue title", "body": "issue", "labels": []})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    monkeypatch.setattr(cycle.closure, "_dispatcher_inspect", lambda *args: (task, events, lease))
    monkeypatch.setattr(cycle, "_assert_review_threads_clear", lambda *args: None)
    return {"layout": layout, "source": source, "worktree": worktree, "head": head, "entry": entry,
            "pr": pr, "live": live, "task_id": task_id, "task": task, "lease": lease,
            "events": events, "comments": comments}


def _authority_transfer_fixture(tmp_path, monkeypatch, *, pin=True):
    """A canonical transfer with real Git/registry and simulated remote ports."""
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    old = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                  owner="session-original", now=now - 1000, ttl_seconds=3600)
    cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 400)
    new = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                  owner="session-successor", now=now - 300, ttl_seconds=3600)
    f["events"][:] = [
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 900), "payload": {"session": "session-original", "ttl_minutes": 90}},
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 600), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 500), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ]
    f["task"].update(claimed_by="successor", lease_id="new-lease")
    f["lease"].update(holder="successor", lease_id="new-lease")
    f["entry"].update(claimant="successor", session="session-successor", lease_id="new-lease")
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=new, prior_lease="old-lease", pickup_lease="new-lease")
    f["comments"][:] = (_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)
                        if pin else _two_phase(record, receipt_at=now - 700, ack_at=now - 100))
    f.update(now=now, old=old, new=new, record=record)
    return f


def test_native_authority_reads_registered_current_owner_and_migration_handoff(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    with pytest.raises(cycle.CycleError, match="lifecycle authority"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 800)
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "old-lease"
    original_body = f["pr"]["body"]
    f["pr"]["body"] = f["live"]["body"] = original_body.replace(f["task_id"], "wrong-task")
    with pytest.raises(cycle.CycleError, match="wrong branch or task"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["pr"]["body"] = f["live"]["body"] = original_body
    # A fresh registration time after PR creation is not a session change.
    f["live"]["created_at"] = _github_time(now - 700)
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 600)
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "old-lease"
    # A different session cannot borrow the same claim even before PR creation.
    cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 500)
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-successor", now=now - 400)
    f["live"]["created_at"] = _github_time(now - 300)
    f["entry"]["session"] = "session-successor"
    with pytest.raises(cycle.CycleError, match="claim lacks the registered Builder session"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_dispatcher_migration_requires_released_predecessor_lease_not_borrowed(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["owner"]["lease_id"] == "new-lease"
    # The release and claim cannot be ordered by random event IDs at equal timestamps.
    f["events"][1]["timestamp"] = f["events"][2]["timestamp"]
    with pytest.raises(cycle.CycleError, match="ordering is ambiguous"):
        authority()
    f["events"][1]["timestamp"] = _event_time(f["now"] - 600)
    f["events"][1]["actor"] = "rival"
    with pytest.raises(cycle.CycleError, match="release is not authenticated"):
        authority()
    f["events"][1]["actor"] = "original"
    f["events"][0]["payload"]["ttl_minutes"] = 4
    f["events"][1].update(actor="dispatcher-gc", payload={"reason": "expired"})
    assert authority()["owner"]["lease_id"] == "new-lease"
    f["events"][0]["payload"]["ttl_minutes"] = 90
    with pytest.raises(cycle.CycleError, match="predates the lease expiry"):
        authority()
    f["events"][1].update(actor="original", payload={"reason": "manual"})
    # A subsequent same-session reclaim must retain the transfer evidence.
    f["events"][2]["payload"]["ttl_minutes"] = 7
    f["events"].extend([
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "dispatcher-gc", "lease_id": "new-lease",
         "timestamp": _event_time(f["now"] - 80), "payload": {"reason": "expired"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "reclaim",
         "timestamp": _event_time(f["now"] - 60), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ])
    f["task"]["lease_id"] = f["lease"]["lease_id"] = f["entry"]["lease_id"] = "reclaim"
    assert authority()["owner"]["lease_id"] == "reclaim"
    # The original lease id and its claim timestamp are part of provenance.
    f["events"][0]["timestamp"] = "malformed"
    with pytest.raises(cycle.CycleError, match="timestamp"):
        authority()


def test_dispatcher_migration_cutover_is_the_pre_release_receipt(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["owner"]["lease_id"] == "new-lease"
    # Entire receipt must be identical, including blockers and next action.
    ack = json.loads(f["comments"][-1]["body"])
    ack["lifecycle_handoff_receipt.v1"]["blockers"] = "unresolved P1"
    f["comments"][-1]["body"] = json.dumps(ack)
    with pytest.raises(cycle.CycleError, match="every acknowledged field"):
        authority()
    f["comments"][:] = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 350)
    with pytest.raises(cycle.CycleError, match="pinned lifecycle handoff was changed"):
        authority()
    f["comments"][:] = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 100)
    f["events"][2]["payload"]["ttl_minutes"] = 5
    with pytest.raises(cycle.CycleError, match="not live through acknowledgment"):
        authority()
    f["events"][2]["payload"]["ttl_minutes"] = 90
    f["comments"][:] = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 100,
                                   receipt_updated=f["now"] - 699)
    with pytest.raises(cycle.CycleError, match="edited"):
        authority()
    # GC may release well after expiry; the receipt must still precede expiry.
    f["comments"][:] = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 100)
    f["events"][0]["payload"]["ttl_minutes"] = 1
    with pytest.raises(cycle.CycleError, match="predecessor lease was live"):
        authority()
    f["events"][0]["payload"]["ttl_minutes"] = 90
    # A receipt touching a release in the same GitHub second has unknown order.
    f["comments"][:] = _two_phase(f["record"], receipt_at=f["now"] - 600, ack_at=f["now"] - 100)
    with pytest.raises(cycle.CycleError, match="predecessor lease was live"):
        authority()


@pytest.mark.parametrize("broken", ["missing-release", "duplicate-release", "duplicate-claim", "wrong-origin-holder",
                                    "sessionless-predecessor", "bad-claim-time", "bad-release-time", "wrong-prior-path",
                                    "successor-as-prior-lease"])
def test_native_authority_refuses_conflicting_dispatcher_history(tmp_path, monkeypatch, broken):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    if broken == "missing-release":
        f["events"].pop(1)
    elif broken == "duplicate-release":
        duplicate = dict(f["events"][1], timestamp=_event_time(f["now"] - 550))
        f["events"].insert(2, duplicate)
    elif broken == "duplicate-claim":
        duplicate = dict(f["events"][0], timestamp=_event_time(f["now"] - 800))
        f["events"].insert(1, duplicate)
    elif broken == "wrong-origin-holder":
        f["events"][0]["actor"] = "rival"
    elif broken == "sessionless-predecessor":
        f["events"][0]["payload"].pop("session")
    elif broken == "bad-claim-time":
        f["events"][-1]["timestamp"] = "not-a-timestamp"
    elif broken == "bad-release-time":
        f["events"][1]["timestamp"] = "2026-11-13T00:00:00"
    else:
        ack = json.loads(f["comments"][-1]["body"])
        readbacks = ack["lifecycle_handoff_receipt.v1"]["successor_acknowledgment"]
        if broken == "wrong-prior-path":
            readbacks["prior_worktree_release"]["path"] = "/wrong/path"
        else:
            readbacks["prior_coordination_release"]["lease_id"] = "new-lease"
        f["comments"][-1]["body"] = json.dumps(ack)
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_legacy_fresh_pickup_and_heartbeat_window(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 1000)
    f["events"][0]["timestamp"] = _event_time(now - 900)
    f["events"][0]["payload"] = {"ttl_minutes": 90}
    with pytest.raises(cycle.CycleError, match="claim lacks the registered Builder session"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["events"].extend([
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 800), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "fresh",
         "timestamp": _event_time(now - 700), "payload": {"session": "session-original", "ttl_minutes": 90}},
    ])
    f["task"]["lease_id"] = f["lease"]["lease_id"] = f["entry"]["lease_id"] = "fresh"
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "fresh"
    release_event = f["events"].pop(1)
    with pytest.raises(cycle.CycleError, match="session history is unbound"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["events"].insert(1, release_event)
    # This fresh pickup does not certify an unknown prior transfer.
    cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 600)
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-new", now=now - 500)
    f["entry"]["session"] = "session-new"
    with pytest.raises(cycle.CycleError, match="registered Builder session"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["events"][-1]["payload"]["session"] = "session-new"
    with pytest.raises(cycle.CycleError, match="session history is unbound"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_allows_proven_same_session_stale_takeover(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 1000)
    f["events"][0]["timestamp"] = _event_time(now - 900)
    f["events"].append({"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original",
                        "lease_id": "new-lease", "timestamp": _event_time(now - 500),
                        "payload": {"session": "session-original", "ttl_minutes": 90,
                                    "takeover": {"previous_lease_id": "old-lease", "previous_holder": "original",
                                                 "previous_expires_at": _event_time(now - 600)}}})
    f["task"]["lease_id"] = f["lease"]["lease_id"] = f["entry"]["lease_id"] = "new-lease"
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"
    f["events"][0]["payload"]["session"] = "session-other"
    with pytest.raises(cycle.CycleError, match="predecessor release"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("field", ["current_validation", "current_review_receipt_evidence", "blockers", "residual_risk", "next_authorized_action"])
def test_native_authority_rejects_changed_receipt_fields(tmp_path, monkeypatch, field):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    ack = json.loads(f["comments"][-1]["body"])
    ack["lifecycle_handoff_receipt.v1"][field] = "different"
    f["comments"][-1]["body"] = json.dumps(ack)
    with pytest.raises(cycle.CycleError, match="every acknowledged field"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_heartbeat_extends_predecessor_lease_window(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    now = f["now"]
    f["events"][0]["payload"]["ttl_minutes"] = 3
    f["events"].insert(1, {"task_id": f["task_id"], "event_type": "task.heartbeat", "actor": "original",
                           "lease_id": "old-lease", "timestamp": _event_time(now - 750)})
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"
    f["events"][1]["timestamp"] = _event_time(now - 650)
    with pytest.raises(cycle.CycleError, match="predecessor lease was live"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_fallback_to_dispatcher_checks_real_origin_comment(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    fallback = {"id": 7, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
                "created_at": _github_time(now - 950), "updated_at": _github_time(now - 950),
                "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
                "body": f"Pickup intent receipt: agent=original session=session-original branch=codex/example worktree={f['worktree']} "
                        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=6618"}
    body = ("Governing-Issue: #6618\nFixes #6618\n"
            f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={f['worktree']} "
            "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
            "agent=original session=session-original evidence=github-comment:7")
    f["pr"]["body"] = f["live"]["body"] = body
    f["events"][:] = [f["events"][-1]]
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease=None, pickup_lease="new-lease")
    f["comments"][:] = [fallback, *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"
    f["comments"].pop(0)
    with pytest.raises(cycle.CycleError, match="fallback pickup comment"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["comments"].insert(0, {**fallback, "updated_at": _github_time(now - 940)})
    with pytest.raises(cycle.CycleError, match="edited fallback"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["comments"][0] = {**fallback, "user": {"login": "foreign"}}
    with pytest.raises(cycle.CycleError, match="unauthenticated"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["comments"][0] = {**fallback, "body": fallback["body"].replace("session-original", "session-other")}
    with pytest.raises(cycle.CycleError, match="does not match"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_dispatcher_to_remote_fallback(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    new = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                  owner="session-successor", now=now - 300, ttl_seconds=3600)
    remote = "/remote/mac/previous-worktree"
    f["pr"]["body"] = f["live"]["body"] = f["pr"]["body"].replace(str(f["worktree"]), remote)
    f["entry"].update(claimant="successor", session="session-successor", coordination_mode="github-label-only-fallback",
                      fallback_reason="dispatcher_db_missing", coordination_evidence="github-comment:7")
    fallback = {"id": 7, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
                "created_at": _github_time(now - 500), "updated_at": _github_time(now - 500),
                "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
                "body": f"Pickup intent receipt: agent=successor session=session-successor branch=codex/example worktree={f['worktree']} "
                        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=6618"}
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=new, prior_lease="old-lease", pickup_lease="unused")
    record["predecessor_registration"] = {"path": remote, "owner": "session-original", "branch": "codex/example",
                                            "generation": "f" * 32, "status": "active",
                                            "observed_at": now - 800, "expires_at": now + 1200}
    record["predecessor_dispatcher"] = {"task_id": f["task_id"], "lease_id": "old-lease", "holder": "original",
                                        "session": "session-original", "claimed_at": _event_time(now - 900),
                                        "observed_at": _event_time(now - 800), "expires_at": _event_time(now + 1200),
                                        "history_reconciled": True}
    ack = record["successor_acknowledgment"]
    ack["successor_pickup"] = {"mode": "github-label-only-fallback", "agent": "successor", "session": "session-successor", "evidence": "github-comment:7"}
    ack["prior_worktree_release"].update(path=remote, generation="f" * 32, released_at=now - 400)
    ack["prior_coordination_release"]["released_at"] = _event_time(now - 600)
    f["comments"][:] = [fallback, *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["mode"] == "github-label-only-fallback"
    prior_body = f["pr"]["body"]
    f["pr"]["body"] = f["live"]["body"] = prior_body.replace("lease_id=old-lease", "lease_id=older-lease")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["mode"] == "github-label-only-fallback"
    f["pr"]["body"] = f["live"]["body"] = "Governing-Issue: #6618\nFixes #6618\n"
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["mode"] == "github-label-only-fallback"
    saved_comments = f["comments"][:]
    f["comments"][:] = [fallback]
    with pytest.raises(cycle.CycleError, match="pinned pending handoff|pinned handoff comment|lacks authenticated lifecycle handoff"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    f["comments"][:] = saved_comments
    f["pr"]["body"] = f["live"]["body"] = prior_body
    fallback["created_at"] = fallback["updated_at"] = _github_time(now - 200)
    with pytest.raises(cycle.CycleError, match="pickup does not precede successor registration"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    fallback["created_at"] = fallback["updated_at"] = _github_time(now - 500)
    ack["prior_worktree_release"]["generation"] = "0" * 32
    f["comments"][-1]["body"] = json.dumps({"lifecycle_handoff_receipt.v1": record})
    with pytest.raises(cycle.CycleError, match="pinned lifecycle handoff was changed"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    ack["prior_worktree_release"]["generation"] = "f" * 32
    ack["prior_coordination_release"]["lease_id"] = "rival"
    f["comments"][-1]["body"] = json.dumps({"lifecycle_handoff_receipt.v1": record})
    with pytest.raises(cycle.CycleError, match="pinned lifecycle handoff was changed"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_multiple_hops_and_same_session_reclaim(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    repo, path = f["source"], f["worktree"]
    cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-original", now=now - 2000, ttl_seconds=3600)
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-original", now=now - 1600)
    second = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-second", now=now - 1500, ttl_seconds=3600)
    first = _handoff(f, predecessor=("original", "session-original"), successor=("original", "session-second"),
                     registration=second, prior_lease="old-lease", pickup_lease="lease-2")
    first_comments = _prepare_and_pin(f, first, receipt_at=now - 1800, ack_at=now - 1400)
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-second", now=now - 400)
    third = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-third", now=now - 300, ttl_seconds=3600)
    def claimed(lease, session, at):
        return {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": lease,
                "timestamp": _event_time(at), "payload": {"session": session, "ttl_minutes": 90}}
    def released(lease, at):
        return {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": lease,
                "timestamp": _event_time(at), "payload": {"reason": "manual"}}
    f["events"][:] = [claimed("old-lease", "session-original", now - 1900), released("old-lease", now - 1700),
                       claimed("lease-2", "session-second", now - 1650), released("lease-2", now - 600),
                       claimed("lease-3", "session-third", now - 500)]
    f["task"]["lease_id"] = f["lease"]["lease_id"] = f["entry"]["lease_id"] = "lease-3"
    f["entry"]["session"] = "session-third"
    latest = _handoff(f, predecessor=("original", "session-second"), successor=("original", "session-third"),
                      registration=third, prior_lease="lease-2", pickup_lease="lease-3")
    f["comments"][:] = [*first_comments,
                         *_prepare_and_pin(f, latest, receipt_at=now - 700, ack_at=now - 100, first_id=51)]
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["owner"]["lease_id"] == "lease-3"
    # The predecessor's anchor does not make an already expired first lease valid.
    f["events"][0]["payload"]["ttl_minutes"] = 1
    with pytest.raises(cycle.CycleError, match="predecessor lease was live"):
        authority()
    f["events"][0]["payload"]["ttl_minutes"] = 90
    stale = json.loads(json.dumps(latest))
    stale["current_lifecycle_owner"]["session"] = "session-original"
    f["comments"][2:] = _two_phase(stale, receipt_at=now - 700, ack_at=now - 100, first_id=51)
    with pytest.raises(cycle.CycleError, match="pinned lifecycle handoff was changed"):
        authority()
    latest["successor_acknowledgment"]["prior_worktree_release"]["generation"] = "0" * 32
    f["comments"][2:] = _two_phase(latest, receipt_at=now - 700, ack_at=now - 100, first_id=51)
    with pytest.raises(cycle.CycleError, match="pinned lifecycle handoff was changed"):
        authority()
    latest["successor_acknowledgment"]["prior_worktree_release"]["generation"] = second["generation"]
    f["comments"][2:] = _two_phase(latest, receipt_at=now - 700, ack_at=now - 100, first_id=51)
    f["events"].extend([released("lease-3", now - 80), claimed("lease-4", "session-third", now - 60)])
    f["task"]["lease_id"] = f["lease"]["lease_id"] = f["entry"]["lease_id"] = "lease-4"
    assert authority()["owner"]["lease_id"] == "lease-4"


def test_native_authority_refuses_expired_registry_window(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    repo, path = f["source"], f["worktree"]
    cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-original", now=now - 1000, ttl_seconds=100)
    cycle.agent_worktree.heartbeat_worktree(repo, worktree=path, owner="session-original", now=now - 800, ttl_seconds=3600)
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-original", now=now - 400)
    current = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-successor", now=now - 300, ttl_seconds=3600)
    f["events"][:] = [
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 950), "payload": {"session": "session-original", "ttl_minutes": 90}},
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 600), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 500), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ]
    f["task"].update(claimed_by="successor", lease_id="new-lease")
    f["lease"].update(holder="successor", lease_id="new-lease")
    f["entry"].update(claimant="successor", session="session-successor", lease_id="new-lease")
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=current, prior_lease="old-lease", pickup_lease="new-lease")
    f["comments"][:] = _prepare_and_pin(f, record, receipt_at=now - 850, ack_at=now - 100)
    with pytest.raises(cycle.CycleError, match="not continuously live"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_native_authority_proven_worktree_move_and_conflicting_history(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    repo, old_path = f["source"], f["worktree"]
    old = cycle.agent_worktree.register_worktree(repo, worktree=old_path, owner="session-original", now=now - 1000, ttl_seconds=3600)
    cycle.agent_worktree.release_worktree(repo, worktree=old_path, owner="session-original", now=now - 400)
    new_path = old_path.parent / "moved-worktree"
    cycle.subprocess.run(["git", "-C", str(repo), "worktree", "move", str(old_path), str(new_path)], check=True)
    new = cycle.agent_worktree.register_worktree(repo, worktree=new_path, owner="session-successor", now=now - 300, ttl_seconds=3600)
    f["worktree"] = new_path
    f["entry"].update(owner_worktree=str(new_path), claimant="successor", session="session-successor", lease_id="new-lease")
    f["events"][:] = [
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 900), "payload": {"session": "session-original", "ttl_minutes": 90}},
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 600), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 500), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ]
    f["task"].update(claimed_by="successor", lease_id="new-lease")
    f["lease"].update(holder="successor", lease_id="new-lease")
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=new, prior_lease="old-lease", pickup_lease="new-lease")
    record["successor_acknowledgment"]["prior_worktree_release"].update(path=str(old_path), generation=old["generation"])
    f["comments"][:] = _prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["worktree_owner"]["path"] == str(new_path)
    registry = cycle.agent_worktree._default_registry_path(repo)
    data = json.loads(registry.read_text())
    older_path = str(old_path.parent / "older-retired")
    data["worktrees"][older_path] = {"path": older_path, "branch": "codex/example", "generation": "a" * 32,
                                     "owner": "old-session", "status": "removed", "registered_at": now - 3000,
                                     "heartbeat_at": now - 3000, "expires_at": now - 2900, "removed_at": now - 2800}
    registry.write_text(json.dumps(data))
    assert authority()["worktree_owner"]["path"] == str(new_path)
    data["worktrees"][str(old_path)]["generation"] = "0" * 32
    registry.write_text(json.dumps(data))
    with pytest.raises(cycle.CycleError, match="lifecycle authority"):
        authority()


def test_native_authority_refuses_unproven_worktree_move(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 300)
    # A different historical path in the original pickup is not a move receipt.
    body = f["pr"]["body"].replace(str(f["worktree"]), str(f["worktree"].parent / "missing-old"))
    f["pr"]["body"] = f["live"]["body"] = body
    with pytest.raises(cycle.CycleError, match="move lacks released registration mapping"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("hold", ["hold", "do-not-merge", "do not merge", "wip", "agent:blocked", "agent:needs-human", "agent:needs-review"])
def test_multiissue_merge_refuses_closing_child_hold_and_final_label_drift(tmp_path, monkeypatch, hold):
    layout, config, _ = setup(tmp_path, monkeypatch)
    entry = config[0]
    target = layout.checkout("reviewer") / "tests" / "example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_example(): pass\n")
    issue_body = "## Acceptance Criteria\n- [ ] Child outcome\n  Verify: tests/example.py::test_example\n"
    criteria = cycle.closure._acceptance_criteria(issue_body, repo_root=layout.checkout("reviewer"))
    child = {"state": "open", "title": "child", "body": issue_body, "labels": [{"name": hold}]}
    def multi_fetch(path, timeout):
        if "/issues/6617" in path:
            return 200, json.dumps({"number": 6617, "state": "open", "body": "parent contract"}).encode()
        status, data = fetch(path, timeout)
        return status, data.replace(b"Governing-Issue: #6618", b"Governing-Issue: #6617\\nFixes #6618")
    monkeypatch.setattr(cycle, "github_fetch", multi_fetch)
    pr = cycle.observation._observe(cycle.observation._Reader(multi_fetch, cycle.time.monotonic), 10)
    assert pr is not None
    pr.update(route="native", check_config={"verify_targets": entry["verify_targets"], "test_venv": entry["test_venv"]})
    pr["review_context"], _ = cycle._review_context(pr)
    identity = cycle.completion.work_identity(pr)
    owner_doc = {"outcome": "no_change", "inspected_paths": ["docs/owner.md"], "rationale": "unchanged"}
    review = {"verdict": "pass", "findings": [], "covered_sources": ["app/example.py"], "owner_doc": owner_doc,
              "scope_assessment": {"acceptance": "covered", "verify_coverage": "covered", "limitations": []},
              "closing_assessments": {"6618": {"acceptance": "covered", "verify_coverage": "covered", "limitations": [],
                 "criteria": {criteria[0]["criterion_sha256"]: {"assessment": "covered", "rationale": "path reviewed"}}}}}
    saved = {"kind": "pr_cycle", "number": 10, "identity": identity, "review_operation": "op", "review": review,
             "conversation_provenance": {"reviewer": "cid"},
             "execution_proof": {"operation_id": "op", "engine": "codex", "model": "gpt-6.1-terra", "auth": "chatgpt",
                 "source": "native-session-metadata", "native_session_id": "native", "effort": "high", "timestamp": "now", "conversation_id": "cid"},
             "verification": {"passed": True, "head_sha": HEAD, "targets": entry["verify_targets"]}}
    authority = {"number": 10, "head_sha": HEAD, "body": pr["body"], "title": "", "closing_issues": [6618],
                 "governing_issue": 6617, "governing_issue_hashes": ISSUE_HASHES, "owner": {}}
    monkeypatch.setattr(cycle, "native_authority", lambda *args: dict(authority))
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: dict(child))
    monkeypatch.setattr(cycle, "_api_pages", lambda executor, cwd, endpoint:
                        [{"filename": "app/example.py"}] if endpoint.endswith("/files") else [{"commit": {"message": "Implement child"}}])
    drift = [False]
    def ci(*args):
        if drift[0]:
            child["labels"] = [{"name": hold}]
        return {"exit_code": 0}
    monkeypatch.setattr(cycle, "ci_once", ci)
    effects = []
    def merge(argv, *, timeout):
        assert cycle._find(layout, 10, identity)["merge_intent"]["closing_issues"] == [6618]
        effects.append("merge")
        return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "_command", merge)
    monkeypatch.setattr(cycle, "reconcile_native", lambda *args: {"action": "merged"})
    with pytest.raises(cycle.CycleError, match="held"):
        cycle.merge_once(layout, pr, entry, saved)
    assert effects == []
    child["labels"] = []
    drift[0] = True
    with pytest.raises(cycle.CycleError, match="held"):
        cycle.merge_once(layout, pr, entry, saved)
    assert effects == []
    child["labels"] = []
    drift[0] = False
    assert cycle.merge_once(layout, pr, entry, saved)["action"] == "merged"
    assert effects == ["merge"]


def test_reconcile_distinct_nonclosing_parent_preserves_its_lease_and_labels(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    parent = {"state": "open", "title": "parent", "body": "parent contract", "labels": [{"name": "agent:in-progress"}]}
    child = {"state": "closed", "title": "child", "body": "child contract", "labels": [{"name": "agent:in-progress"}]}
    files = [{"filename": "app/example.py"}]
    receipt = "post-merge owner-doc check: PR #10; no owner-doc change implied."
    intent = {"number": 10, "head_sha": HEAD, "body": "body", "title": "title", "closing_issues": [6618],
              "governing_issue": 6617, "governing_issue_hashes": cycle.closure._issue_hashes(parent),
              "coordination_mode": "dispatcher-backed", "owner": {"task_id": "parent-task", "lease_id": "parent-lease", "lease_holder": "parent-owner"},
              "closing_issue_hashes": {"6618": cycle.closure._issue_hashes(child)},
              "files_digest": cycle.hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
              "owner_doc_receipt": receipt}
    saved = {"kind": "pr_cycle", "number": 10, "identity": "parent-test", "merge_intent": intent}
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"state": "closed", "merged_at": "now", "head": {"sha": HEAD},
                        "merge_commit_sha": "b" * 40, "body": "body", "title": "title"})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6618])
    monkeypatch.setattr(cycle.closure, "_issue", lambda executor, cwd, repo, number: parent if number == 6617 else child)
    monkeypatch.setattr(cycle.closure, "_issue_events", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_closure_evidence", lambda *args: {})
    monkeypatch.setattr(cycle.closure, "_validate_closure_attribution", lambda *args: None)
    monkeypatch.setattr(cycle, "_dispatcher_after_merge", lambda *args: pytest.fail("nonclosing parent lease must remain active"))
    comments = {6617: [], 6618: []}
    def pages(executor, cwd, endpoint):
        if endpoint.endswith("/files"):
            return files
        number = int(endpoint.split("/")[2])
        return [{"body": body, "user": {"login": "RasmusTho"}} for body in comments[number]]
    monkeypatch.setattr(cycle, "_api_pages", pages)
    class Executor:
        def __init__(self, **kwargs):
            pass
        def run(self, argv, *, cwd, input_text=None):
            if "POST" in argv:
                endpoint = next(arg for arg in argv if arg.startswith("repos/"))
                number = int(endpoint.split("/")[-2])
                comments[number].append(next(arg[5:] for arg in argv if arg.startswith("body=")))
            elif "--remove-label" in argv:
                assert argv[3] == "6618"
                child["labels"] = []
            return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    assert cycle.reconcile_native(layout, saved)["action"] == "merged"
    assert cycle.reconcile_native(layout, saved)["action"] == "merged"
    assert comments == {6617: [receipt], 6618: [receipt]}
    assert parent["state"] == "open" and parent["labels"] == [{"name": "agent:in-progress"}]
    assert child["labels"] == [] and saved["reconciled"] is True
