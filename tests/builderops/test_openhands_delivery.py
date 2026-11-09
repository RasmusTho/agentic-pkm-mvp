import json
import hashlib
import hmac
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.builderops import openhands_delivery as delivery

ROOT = Path(__file__).resolve().parents[2]
BODY = (ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md").read_text()
HEAD = "a" * 40
FULL_CLAIM_READBACK = delivery._full_claim_readback


def test_status_does_not_wait_for_delivery_lock_and_detects_state_drift(tmp_path, monkeypatch):
    directory = tmp_path / "delivery"
    directory.mkdir(mode=0o700)
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "phase": "active"}
    delivery.service._write(directory, state)
    monkeypatch.setattr(delivery, "_conversation", lambda *args: {
        "execution_status": "finished", "sub_conversation_ids": [],
    })
    results = []
    done = threading.Event()

    def read_status():
        try:
            results.append(delivery.status(directory))
        finally:
            done.set()

    with delivery.service._locked(directory):
        thread = threading.Thread(target=read_status, daemon=True)
        thread.start()
        assert done.wait(1), "status waited for the delivery lock"
    thread.join(timeout=1)
    assert results[0]["state"] == state and results[0]["conversation_status"] == "finished"

    def changed_during_read(*args):
        delivery.service._write(directory, {**state, "phase": "interrupted"})
        return {"execution_status": "finished"}

    monkeypatch.setattr(delivery, "_conversation", changed_during_read)
    snapshot = delivery.status(directory)
    assert snapshot["state"]["phase"] == "interrupted" and "snapshot_notice" in snapshot
    assert "conversation_status" not in snapshot


def test_recovery_status_survives_service_inspection_failure(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    (directory / "server").mkdir(mode=0o700)
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "phase": "interrupted"}
    delivery.service._write(directory, state)
    def unavailable(*args, **kwargs):
        raise delivery.service.ServiceError("Cannot inspect recorded process")
    monkeypatch.setattr(delivery.service, "_status", unavailable)
    monkeypatch.setattr(delivery, "_recovery_conversation", unavailable)
    result = delivery.status(directory)
    assert result["state"] == state
    assert result["recovery"]["continuation"] == "blocked"
    assert result["recovery"]["execution"]["status"] == "unknown"
    assert "conversation_readback_error" in result and "service_status_error" in result


def test_cancel_returns_when_conversation_creation_holds_delivery_lock(tmp_path):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    delivery.service._write(directory, {"version": 1, "kind": "openhands_delivery_run.v1", "phase": "creating_conversation"})
    outcome = []
    def cancel():
        try:
            delivery.cancel(directory)
        except delivery.service.ServiceError as exc:
            outcome.append(str(exc))
    with delivery.service._locked(directory):
        worker = threading.Thread(target=cancel)
        worker.start()
        worker.join(timeout=7)
        assert not worker.is_alive() and outcome == ["Delivery input is still being processed"]
        assert delivery.service._read(directory)["phase"] == "creating_conversation"


@pytest.fixture
def readbacks(monkeypatch):
    issue = {
        "number": 123, "title": "Implement feature", "body": BODY, "state": "OPEN",
        "labels": [{"name": "agent:ready"}],
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
        "updatedAt": "2026-11-08T00:00:00Z",
    }
    data = {"issue": issue, "prs": [], "branch_exists": False, "calls": []}

    def run(command, **kwargs):
        data["calls"].append(command)
        if command[0] == "gh":
            payload = data["issue"] if command[1:3] == ["issue", "view"] else data["prs"]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[-2:] == ["rev-parse", "--show-toplevel"]:
            output = str(ROOT)
        elif command[-3:] == ["remote", "get-url", "origin"]:
            output = f"https://github.com/{delivery.REPOSITORY}.git"
        elif command[-3:] == ["rev-parse", "--verify", "refs/remotes/origin/main^{commit}"]:
            output = HEAD
        elif "show-ref" in command:
            return subprocess.CompletedProcess(command, 0 if data["branch_exists"] else 1, "", "")
        elif "check-ref-format" in command:
            output = ""
        elif "show" in command:
            output = (ROOT / command[-1].split(":", 1)[1]).read_text()
        else:
            pytest.fail(f"Unexpected command: {command}")
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(delivery.subprocess, "run", run)
    return data


def test_preview_reads_real_contract_and_repo_instructions(readbacks, tmp_path):
    result = delivery.preview(ROOT, 123, "codex/issue-123", tmp_path / "worktree")
    assert result["readiness"] == "ready_candidate"
    assert result["issue"]["body"] == BODY
    assert result["base_commit"] == HEAD
    assert any(cmd[-1] == "refs/remotes/origin/main^{commit}" for cmd in readbacks["calls"])
    assert result["instructions"]["AGENTS.md"]["content"] == (ROOT / "AGENTS.md").read_text()
    assert result["matching_prs"] == []
    assert result["execution"] == "not_started"
    assert result["destination_collisions"] == {
        "local_branch_exists": False, "worktree_exists": False,
    }
    assert all(cmd[0] in {"git", "gh"} for cmd in readbacks["calls"])
    assert all("--repo" in cmd for cmd in readbacks["calls"] if cmd[0] == "gh")


def test_preview_surfaces_existing_pr_and_destination_collisions(readbacks, tmp_path):
    readbacks["branch_exists"] = True
    worktree = tmp_path / "existing"
    worktree.mkdir()
    readbacks["prs"] = [{
        "number": 77, "state": "OPEN", "isDraft": True,
        "headRefName": "codex/issue-123", "headRefOid": HEAD,
        "url": f"https://github.com/{delivery.REPOSITORY}/pull/77",
    }]
    result = delivery.preview(ROOT, 123, "codex/issue-123", worktree)
    assert result["matching_prs"][0]["number"] == 77
    assert all(result["destination_collisions"].values())


def test_preview_refuses_unready_issue_and_ambiguous_pr_readback(readbacks, tmp_path):
    readbacks["issue"]["labels"] = [{"name": "agent:in-progress"}]
    with pytest.raises(delivery.DeliveryError, match="agent:ready"):
        delivery.preview(ROOT, 123, "codex/issue-123", tmp_path / "worktree")
    readbacks["issue"]["labels"] = [{"name": "agent:ready"}]
    readbacks["prs"] = [{"number": 77}]
    with pytest.raises(delivery.DeliveryError, match="ambiguous"):
        delivery.preview(ROOT, 123, "codex/issue-123", tmp_path / "worktree")


def test_preview_uses_readiness_contract_not_just_labels(readbacks, tmp_path):
    readbacks["issue"]["body"] = BODY.replace("## Constraints", "## Unrelated")
    with pytest.raises(delivery.DeliveryError, match="missing_required_sections"):
        delivery.preview(ROOT, 123, "codex/issue-123", tmp_path / "worktree")
    assert not any(cmd[:3] == ["gh", "pr", "list"] for cmd in readbacks["calls"])


@pytest.fixture
def orchestration(monkeypatch, tmp_path):
    events = []
    worktree = tmp_path / "worktree"
    state_dir = tmp_path / "run"
    plan = {
        "repository": delivery.REPOSITORY, "base_commit": HEAD, "planned_branch": "issue-123",
        "planned_worktree": str(worktree), "matching_prs": [],
        "destination_collisions": {"local_branch_exists": False, "worktree_exists": False},
        "issue": {"number": 123, "title": "Implement feature", "body": BODY,
                  "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
                  "body_sha256": delivery._sha(BODY)},
        "instructions": {"AGENTS.md": {"content": "Repository rules"}},
    }
    monkeypatch.setattr(delivery, "_validate_executables", lambda *args: {"fixed": "settings"})
    monkeypatch.setattr(delivery, "_include_git_metadata", lambda settings, root: settings)
    monkeypatch.setattr(delivery, "preview", lambda *args: plan)

    def effect(command, **kwargs):
        events.append(command)
        if "worktree" in command and "add" in command:
            worktree.mkdir()
        if command[0].endswith("issue_pickup_claim.sh"):
            return (f"pickup-claim-complete issue=123 branch=issue-123 worktree={worktree} "
                    "coordination_mode=dispatcher-backed evidence=verified-dispatcher-lease\n")
        return ""

    monkeypatch.setattr(delivery, "_effect", effect)
    monkeypatch.setattr(delivery, "_json_result", lambda cmd: {
        "number": 123, "state": "OPEN", "title": "Implement feature", "body": BODY,
        "url": plan["issue"]["url"],
    })
    monkeypatch.setattr(delivery.service, "start", lambda *args: events.append(("service", args)))
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "private-test-key")
    http = {"status": "running", "fail_create": False, "interrupt_stays_running": False}

    def request(port, key, method, path, payload=None, **kwargs):
        events.append((method, path, payload, kwargs))
        if path == "/conversations":
            if http["fail_create"]:
                raise delivery.DeliveryError("uncertain")
            return 201, {"id": payload["conversation_id"], "workspace": payload["workspace"],
                         "execution_status": "running"}
        if method == "GET" and not (state_dir / "service.json").exists():
            pytest.fail("state not written")
        if method == "GET":
            state = delivery.service._read(state_dir)
            if state["phase"] == "starting_service":
                return 404, None
            return 200, {"id": state["conversation_id"], "workspace": {"working_dir": str(worktree)},
                         "execution_status": http["status"], "sub_conversation_ids": []}
        if path.endswith("/interrupt") and not http["interrupt_stays_running"]:
            http["status"] = "paused"
        return 200, {"success": True}

    monkeypatch.setattr(delivery, "_http", request)
    kwargs = dict(directory=state_dir, root=ROOT, issue=123, authorized_issue=123,
                  branch="issue-123", worktree=worktree, python=Path("/python"), port=8123,
                  settings_file=Path("/settings"), node=Path("/node"), acp=Path("/acp"))
    return kwargs, events, http


def test_linked_worktree_git_metadata_is_readable_without_write_access(tmp_path, monkeypatch):
    git_dir = tmp_path / "shared-git"
    git_dir.mkdir()
    monkeypatch.setattr(delivery, "_run", lambda cmd: subprocess.CompletedProcess(cmd, 0, str(git_dir)))
    settings = {"sandbox_read_roots": [str(tmp_path)], "codex_config_args": [
        "-c", 'permissions.builder_factory.filesystem={":minimal"="read"}',
    ]}
    updated = delivery._include_git_metadata(settings, tmp_path)
    assert str(git_dir) in updated["sandbox_read_roots"]
    assert f'"{git_dir}"="read"' in updated["codex_config_args"][1]
    assert str(git_dir) not in settings["sandbox_read_roots"]


def test_start_claims_then_starts_workspace_bound_conversation_and_prevents_replay(orchestration):
    kwargs, events, http = orchestration
    result = delivery.start(**kwargs)
    state = result["state"]
    assert state["phase"] == "active"
    assert "pickup-claim-complete" in state["pickup_receipt"]
    claim = next(x for x in events if isinstance(x, list) and x[0].endswith("issue_pickup_claim.sh"))
    assert claim[claim.index("--target-worktree") + 1] == str(kwargs["worktree"])
    server = next(x for x in events if x[0] == "service")
    assert server[1][2] == kwargs["worktree"]
    creation = next(x for x in events if x[0] == "POST" and x[1] == "/conversations")
    assert creation[3]["timeout"] == 120
    created = creation[2]
    assert created["workspace"]["working_dir"] == str(kwargs["worktree"])
    assert created["agent_settings"]["acp_model"] == "gpt-6.1-terra"
    assert created["agent_settings"]["acp_command"] == [
        "/python", "-c", delivery._ACP_BOOTSTRAP, "/node", "/acp"
    ]
    assert created["autotitle"] is False
    assert BODY in created["initial_message"]["content"][0]["text"]
    assert "Repository rules" in created["initial_message"]["content"][0]["text"]
    before = len(events)
    with pytest.raises(delivery.DeliveryError, match="already recorded"):
        delivery.start(**kwargs)
    assert len(events) == before
    assert delivery.status(kwargs["directory"])["conversation_status"] == "running"
    assert delivery.cancel(kwargs["directory"])["state"]["phase"] == "interrupted"
    before = len(events)
    with pytest.raises(delivery.DeliveryError, match="previous execution and delegated work"):
        delivery.resume(kwargs["directory"])
    assert delivery.service._read(kwargs["directory"])["phase"] == "interrupted"
    assert not any(event[0] == "POST" and event[1].endswith("/run") for event in events[before:])


def test_interrupted_recovery_observes_processes_children_worktree_and_pr_without_assuming_stop(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True, check=True)
    git("init", "-b", "codex/issue-123")
    (worktree / "fixture.txt").write_text("before\n")
    git("add", "fixture.txt")
    git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base")
    (worktree / "fixture.txt").write_text("partially changed\n")
    head = git("rev-parse", "HEAD").stdout.strip()
    child = "11111111-1111-4111-8111-111111111111"
    parent_id = "22222222-2222-4222-8222-222222222222"
    state = {"worktree": str(worktree), "root": str(worktree), "branch": "codex/issue-123",
             "repository": delivery.REPOSITORY, "conversation_id": parent_id, "port": 8123}
    server = {"pid": 12345, "started": "Mon Nov 9 20:24:07 2026", "marker": "test-marker",
              "workspace": str(worktree), "port": 8123, "delivery_identity_challenge": True}
    (tmp_path / "server").mkdir()
    monkeypatch.setattr(delivery.service, "_read", lambda *args: server)
    monkeypatch.setattr(delivery.service, "_status", lambda *args: "running")
    monkeypatch.setattr(delivery.service, "_identity", lambda pid: (
        "Mon Nov 9 20:24:07 2026" if pid == 12345 else "Mon Nov 9 20:24:08 2026", "redacted"))
    monkeypatch.setattr(delivery.service, "_session_key", lambda *args, **kwargs: "test-key")
    reads = []
    child_workspace = {"path": str(worktree)}
    def child_read(port, key, child_id, timeout):
        reads.append(("GET", f"/conversations/{child_id}"))
        return 200, {"id": child, "parent_conversation_id": parent_id,
                     "workspace": {"working_dir": child_workspace["path"]}, "execution_status": "running",
                     "sub_conversation_ids": []}
    monkeypatch.setattr(delivery, "_bounded_recovery_child", child_read)
    monkeypatch.setattr(delivery.publication, "_read_pr_history", lambda *args: [
        {"number": 42, "state": "open", "draft": True,
         "head": {"sha": head, "ref": "codex/issue-123", "repo": {"full_name": delivery.REPOSITORY}},
         "base": {"repo": {"full_name": delivery.REPOSITORY}}},
    ])
    real_run = subprocess.run
    def run(command, **kwargs):
        if command[0] == "ps":
            return subprocess.CompletedProcess(command, 0,
                "12345 1 12345 Mon Nov 9 20:24:07 2026 Ss\n"
                "12346 12345 12346 Mon Nov 9 20:24:08 2026 S\n")
        return real_run(command, **kwargs)
    monkeypatch.setattr(delivery.subprocess, "run", run)
    result = delivery._recovery_observation(tmp_path, state, {"sub_conversation_ids": [child]})
    assert result["continuation"] == "blocked"
    assert result["execution"]["status"] == "unknown"
    assert result["execution"]["candidate_descendant_count"] == 1
    assert result["delegated_work"]["status"] == "unknown"
    assert result["delegated_work"]["openhands_conversations"][0]["status"] == "running"
    assert result["worktree"]["dirty"] is True and result["worktree"]["head"] == head
    assert result["publication"]["matching_prs"][0]["number"] == 42
    assert reads == [("GET", f"/conversations/{child}")]
    child_workspace["path"] = str(tmp_path / "isolated-child")
    isolated = delivery._recovery_observation(tmp_path, state, {"sub_conversation_ids": [child]})
    assert isolated["delegated_work"]["openhands_conversations"][0]["workspace"] == "unverified"
    assert isolated["delegated_work"]["status"] == "unknown"
    monkeypatch.setattr(delivery.publication, "_read_pr_history", lambda *args: [
        {"number": 42, "state": "open", "draft": True,
         "head": {"sha": head, "ref": "codex/issue-123", "repo": {"full_name": delivery.REPOSITORY}},
         "base": {"repo": {"full_name": delivery.REPOSITORY}}},
        {"number": 43, "state": "open", "draft": False,
         "head": {"sha": head, "ref": "codex/issue-123", "repo": {"full_name": delivery.REPOSITORY}},
         "base": {"repo": {"full_name": delivery.REPOSITORY}}},
    ])
    ambiguous = delivery._recovery_observation(tmp_path, state, {"sub_conversation_ids": []})
    assert ambiguous["publication"]["status"] == "ambiguous"
    assert ambiguous["continuation"] == "blocked"
    monkeypatch.setattr(delivery.service, "_read", lambda *args: {**server, "workspace": "/unrelated"})
    wrong_server = delivery._recovery_observation(tmp_path, state, {"sub_conversation_ids": []})
    assert "candidate_descendant_count" not in wrong_server["execution"]
    other_repo = tmp_path / "other-repo"
    other_repo.mkdir()
    subprocess.run(["git", "-C", str(other_repo), "init"], capture_output=True, check=True)
    wrong_repo = delivery._recovery_observation(tmp_path, {**state, "root": str(other_repo)},
                                                 {"sub_conversation_ids": []})
    assert wrong_repo["worktree"]["status"] == "unknown"
    marker = tmp_path / "hook-ran"
    hook = tmp_path / "fsmonitor-hook"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    git("config", "--local", "core.fsmonitor", str(hook))
    configured = delivery._recovery_observation(tmp_path, state, {"sub_conversation_ids": []})
    assert configured["worktree"]["status"] == "unknown" and not marker.exists()


def test_recovery_child_readback_has_hard_time_and_size_limits():
    redirected = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/redirect-target"):
                redirected.append(True)
            if self.path.endswith("/redirect"):
                self.send_response(302)
                self.send_header("Location", "/redirect-target")
                self.end_headers()
                return
            assert self.headers.get("X-Session-API-Key") == "test-key"
            if self.path.endswith("/slow"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{")
                self.wfile.flush()
                time.sleep(0.5)
                return
            body = b"x" * 262145 if self.path.endswith("/large") else b'{"id":"child"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert delivery._bounded_recovery_child(port, "test-key", "normal", 2) == (200, {"id": "child"})
        with pytest.raises(delivery.DeliveryError, match="readback unavailable"):
            delivery._bounded_recovery_child(port, "test-key", "large", 2)
        with pytest.raises(delivery.DeliveryError, match="readback unavailable"):
            delivery._bounded_recovery_child(port, "test-key", "redirect", 2)
        assert not redirected
        status, _ = delivery._http(port, "test-key", "GET", "/conversations/redirect", timeout=2)
        assert status == 302 and not redirected
        started = time.monotonic()
        with pytest.raises(delivery.DeliveryError, match="readback unavailable"):
            delivery._bounded_recovery_child(port, "test-key", "slow", 0.2)
        assert time.monotonic() - started < 1.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_recovery_does_not_create_missing_key(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir()
    state = {"worktree": "/worktree", "port": 8123}
    server = {"workspace": "/worktree", "port": 8123, "delivery_identity_challenge": True}
    monkeypatch.setattr(delivery.service, "_read", lambda *_: server)
    monkeypatch.setattr(delivery.service, "_status", lambda *_: "running")
    with pytest.raises(delivery.service.ServiceError):
        delivery._recovery_server_key(tmp_path, state)
    assert not (server_dir / "session-api-key").exists()


def test_model_free_owner_retains_its_existing_control_service_key(tmp_path, monkeypatch):
    server_dir = tmp_path / "server"
    server_dir.mkdir(mode=0o700)
    key = delivery.service._session_key(server_dir)
    state = {"kind": "openhands_owner_service.v1", "worktree": "/owner", "port": 8123}
    server = {"workspace": "/owner", "port": 8123, "control_only": True}
    monkeypatch.setattr(delivery.service, "status", lambda *_, **__: {"status": "running", "state": server})
    assert delivery._server_key(tmp_path, state) == key
    assert not isinstance(delivery._server_key(tmp_path, state), delivery._BoundWorkerKey)
    with pytest.raises(delivery.DeliveryError, match="identity challenge"):
        delivery._server_key(tmp_path, {**state, "kind": "openhands_delivery_run.v1"})


def test_worker_readback_returns_when_service_lifecycle_lock_is_held(tmp_path):
    directory = tmp_path / "run"
    server_dir = directory / "server"
    server_dir.mkdir(mode=0o700, parents=True)
    outcome = []
    def readback():
        try:
            delivery._server_key(directory, {"worktree": "/work", "port": 8123})
        except delivery.DeliveryError as exc:
            outcome.append(str(exc))
    with delivery.service._locked(server_dir):
        worker = threading.Thread(target=readback)
        worker.start()
        worker.join(timeout=7)
        assert not worker.is_alive() and outcome == ["Recorded service readback unavailable"]


def test_worker_key_is_sent_only_to_peer_that_proves_possession():
    received_keys = []
    prove = {"enabled": True}
    key = "private-test-key"
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/api/_builder_identity":
                nonce = parse_qs(parsed.query)["nonce"][0]
                digest = hmac.new(key.encode(), nonce.encode(), hashlib.sha256).hexdigest() if prove["enabled"] else "0" * 64
                body = digest.encode()
            else:
                received_keys.append(self.headers.get("X-Session-API-Key"))
                body = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        bound = delivery._BoundWorkerKey(key)
        assert delivery._http(port, bound, "GET", "/conversations/example", timeout=2) == (200, {"ok": True})
        assert received_keys == [key]
        prove["enabled"] = False
        with pytest.raises(delivery.DeliveryError, match="identity or API readback unavailable"):
            delivery._http(port, bound, "GET", "/conversations/example", timeout=2)
        assert received_keys == [key]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_start_refuses_base_change_after_environment_preflight(orchestration):
    kwargs, events, _ = orchestration
    with pytest.raises(delivery.DeliveryError, match="Default branch changed"):
        delivery.start(**kwargs, expected_base="0" * 40)
    assert events == []
    assert delivery.service._read(kwargs["directory"]) is None


def test_uncertain_create_is_recorded_and_never_relaunched(orchestration):
    kwargs, events, http = orchestration
    http["fail_create"] = True
    with pytest.raises(delivery.DeliveryError, match="uncertain"):
        delivery.start(**kwargs)
    state = delivery.service._read(kwargs["directory"])
    assert state["phase"] == "creating_conversation"
    before = len(events)
    with pytest.raises(delivery.DeliveryError, match="already recorded"):
        delivery.start(**kwargs)
    assert len(events) == before


def test_start_recovers_if_interrupted_before_first_state(orchestration, monkeypatch):
    kwargs, events, _ = orchestration
    original_save = delivery._save

    def interrupt(*args):
        raise RuntimeError("interrupted before state")

    monkeypatch.setattr(delivery, "_save", interrupt)
    with pytest.raises(RuntimeError, match="interrupted before state"):
        delivery.start(**kwargs)
    assert (kwargs["directory"] / "settings.json").is_file()
    assert not events
    monkeypatch.setattr(delivery, "_save", original_save)
    assert delivery.start(**kwargs)["state"]["phase"] == "active"
    assert len([event for event in events if isinstance(event, list) and "add" in event]) == 1


def test_explicit_issue_authorization_and_changed_contract_fence(orchestration, monkeypatch):
    kwargs, events, http = orchestration
    with pytest.raises(delivery.DeliveryError, match="authorization"):
        delivery.start(**{**kwargs, "authorized_issue": 124})
    assert not events
    monkeypatch.setattr(delivery, "_json_result", lambda command: {
        "number": 123, "state": "OPEN", "title": "Implement feature", "body": "changed",
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/123",
    })
    with pytest.raises(delivery.DeliveryError, match="contract changed"):
        delivery.start(**kwargs)
    assert delivery.service._read(kwargs["directory"])["phase"] == "registering_worktree"
    assert not any(item[0] == "service" for item in events)


def test_pinned_acp_package_and_guard_settings(tmp_path, monkeypatch):
    node = Path(__import__("sys").executable)
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(json.dumps({
        "name": "@agentclientprotocol/codex-acp", "version": "2.2.2",
    }))
    acp = package / "main.js"
    acp.write_text("// sample")
    guard = ROOT / "scripts/openhands_guarded_codex"
    settings = {
        "guard_executable": str(guard), "codex_binary": str(node),
        "codex_config_args": [], "sandbox_read_roots": [str(tmp_path)],
        "conversations_path": str(tmp_path / "conversations"),
        "bash_events_dir": str(tmp_path / "events"),
        "conversation_worktree_root": str(tmp_path / "trees"),
    }
    settings_file = tmp_path / "settings.json"
    settings_file.write_text(json.dumps(settings))
    monkeypatch.setattr(delivery, "_run", lambda cmd: subprocess.CompletedProcess(cmd, 0, "1.60.1\n"))
    assert delivery._validate_executables(node, node, acp, settings_file) == settings
    (package / "package.json").write_text(json.dumps({
        "name": "@agentclientprotocol/codex-acp", "version": "0.0.1",
    }))
    with pytest.raises(delivery.DeliveryError, match="2.2.2"):
        delivery._validate_executables(node, node, acp, settings_file)


def test_acp_bootstrap_does_not_pass_server_key_or_provider_secrets():
    import os
    import sys

    env = dict(os.environ)
    env.update({"OH_SESSION_API_KEYS_0": "test-value", "OTHER_API_KEY": "test-value",
                "CODEX_PATH": "/trusted/guard"})
    probe = "import os; print('OH_SESSION_API_KEYS_0' in os.environ, " \
            "'OTHER_API_KEY' in os.environ, os.getenv('CODEX_PATH'))"
    result = subprocess.run(
        [sys.executable, "-c", delivery._ACP_BOOTSTRAP, sys.executable, "-c", probe],
        env=env, capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "False False /trusted/guard"


def test_cancel_reports_pending_if_conversation_is_still_running(orchestration):
    kwargs, events, http = orchestration
    delivery.start(**kwargs)
    http["interrupt_stays_running"] = True
    result = delivery.cancel(kwargs["directory"])
    assert result["cancel_status"] == "requested_unverified"
    assert result["conversation_status"] == "running"
    assert result["state"]["phase"] == "interrupting"


@pytest.fixture
def draft_publication(tmp_path, monkeypatch):
    from copy import deepcopy

    from scripts.pr_body_generator import generate_pr_body_from_mapping
    from tests.scripts.test_publication import (
        BODY_INPUTS,
        BRANCH,
        COMMIT_SHA,
        FakeExecutor,
    )

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "feature.txt").write_text("verified change\n")
    state_dir = tmp_path / "delivery"
    state_dir.mkdir(mode=0o700)
    body = deepcopy(BODY_INPUTS)
    body["lane"] = "implementation"
    receipt = body.pop("pickup_receipt").replace("/tmp/publication-test", str(worktree))
    state = {
        "version": 1, "kind": "openhands_delivery_run.v1", "phase": "active",
        "repository": delivery.REPOSITORY, "issue": 5230, "worktree": str(worktree),
        "branch": BRANCH, "pickup_receipt": receipt,
        "issue_body_sha256": delivery._sha("contract body"),
    }
    delivery.service._write(state_dir, state)
    monkeypatch.setattr(delivery, "_conversation", lambda *args: {
        "execution_status": "finished", "sub_conversation_ids": [],
    })

    class DraftFake(FakeExecutor):
        def __init__(self, path):
            super().__init__(path)
            full_body = dict(body, pickup_receipt=receipt)
            self.pr_body = generate_pr_body_from_mapping(full_body)
            self.checks_available = True

        def _exact_pr(self, **kwargs):
            pr = super()._exact_pr(**kwargs)
            pr["draft"] = True
            return pr

        def run(self, argv, *, cwd, input_text=None):
            args = tuple(argv)
            if args[:2] == ("gh", "api") and any("/check-runs" in x for x in args):
                self.calls.append(args)
                if not self.checks_available:
                    return delivery.publication.CommandResult(args, 1, "", "unavailable")
                payload = {"total_count": 1, "check_runs": [{"head_sha": COMMIT_SHA,
                           "name": "CI", "status": "queued", "conclusion": None}]}
                return delivery.publication.CommandResult(args, 0, json.dumps(payload), "")
            if args[:2] == ("gh", "api") and any(x.endswith("/status") for x in args):
                self.calls.append(args)
                payload = {"sha": COMMIT_SHA, "state": "pending", "total_count": 1,
                           "statuses": [{"context": "analysis", "state": "pending"}]}
                return delivery.publication.CommandResult(args, 0, json.dumps(payload), "")
            return super().run(argv, cwd=cwd, input_text=input_text)

    executor = DraftFake(worktree)
    return state_dir, body, executor


def _draft_plan(state_dir, body, executor):
    return delivery.publication_plan(
        state_dir, ["feature.txt"], "Add deterministic publication adapter",
        "Add deterministic publication adapter\n\nRefs #5230", body,
        tier=2, risk_surfaces=(), risk_assessment_complete=True, review_gate_complete=True,
        executor=executor,
    )


def test_publish_uses_governed_adapter_and_creates_draft_with_check_readback(draft_publication):
    state_dir, body, executor = draft_publication
    plan = _draft_plan(state_dir, body, executor)
    digest = plan["plan_sha256"]
    result = delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    creations = [call for call in executor.calls if call[:3] == ("gh", "pr", "create")]
    assert len(creations) == 1 and "--draft" in creations[0]
    assert result["draft"] is True
    assert result["checks"]["combined_status"] == "pending"
    assert result["checks"]["statuses"][0]["context"] == "analysis"
    assert result["checks"]["check_runs"][0]["status"] == "queued"
    assert plan["pr"]["body_inputs"]["pickup_receipt"] == delivery._state(state_dir)["pickup_receipt"]
    assert sum(any(str(arg).endswith("agent_workspace_preflight.sh") for arg in call)
               for call in executor.calls) >= 2
    # Replaying the same plan reconciles the already-created PR, without another create.
    delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_publish_refuses_non_draft_history_and_mismatched_attestation(draft_publication):
    state_dir, body, executor = draft_publication
    plan = _draft_plan(state_dir, body, executor)
    digest = plan["plan_sha256"]
    with pytest.raises(delivery.DeliveryError, match="attestations"):
        delivery.publish(state_dir, plan, digest, "0" * 64, digest, executor=executor)
    assert not any(call[:2] in (("git", "add"), ("git", "push")) for call in executor.calls)
    existing = executor._exact_pr()
    existing["draft"] = False
    executor.prs = [existing]
    with pytest.raises(delivery.publication.PublicationRefusal, match="non-draft"):
        _draft_plan(state_dir, body, executor)
    assert not any(call[:3] == ("gh", "pr", "create") for call in executor.calls)


def test_ambiguous_create_is_reconciled_as_draft_without_duplicate(draft_publication):
    state_dir, body, executor = draft_publication
    plan = _draft_plan(state_dir, body, executor)
    executor.failures["pr-create"] = 1
    executor.effect_then_fail.add("pr-create")
    digest = plan["plan_sha256"]
    result = delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert result["receipt"]["reconciled"] is True
    assert executor.prs[0]["draft"] is True
    delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_exact_existing_draft_is_reconciled_after_current_check_readback(draft_publication):
    from tests.scripts.test_publication import COMMIT_SHA

    state_dir, body, executor = draft_publication
    executor.phase = "committed"
    executor.remote_head = COMMIT_SHA
    executor.prs = [executor._exact_pr()]
    plan = _draft_plan(state_dir, body, executor)
    assert plan["pr"]["existing"]["number"] == 6000
    digest = plan["plan_sha256"]
    result = delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert result["receipt"]["reconciled"] is True
    assert result["previous_checks"]["commit"] == COMMIT_SHA
    assert not any(call[:3] == ("gh", "pr", "create") for call in executor.calls)


def test_draft_executor_refuses_merge_and_direct_non_draft_api_create(draft_publication):
    state_dir, body, executor = draft_publication
    draft = delivery.DraftOnlyExecutor(executor)
    before = len(executor.calls)
    for command in (
        ["gh", "pr", "merge", "6000"],
        ["git", "merge", "main"],
        ["gh", "api", "--hostname", "github.com", "--method", "POST",
         f"repos/{delivery.REPOSITORY}/pulls"],
    ):
        with pytest.raises(delivery.publication.PublicationRefusal, match="draft publication"):
            draft.run(command, cwd=state_dir)
    assert len(executor.calls) == before


def test_publication_reads_delegated_conversation_state(draft_publication, monkeypatch):
    state_dir, body, executor = draft_publication
    state = delivery._state(state_dir)
    state.update(conversation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", port=8123)
    delivery.service._write(state_dir, state)
    child = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    monkeypatch.setattr(delivery, "_conversation", lambda *args: {
        "execution_status": "finished", "sub_conversation_ids": [child],
    })
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "local-test-key")
    detail = {"id": child, "parent_conversation_id": state["conversation_id"],
              "workspace": {"working_dir": state["worktree"]},
              "execution_status": "finished", "sub_conversation_ids": []}
    monkeypatch.setattr(delivery, "_http", lambda *args: (200, detail))
    assert _draft_plan(state_dir, body, executor)["governing_issue"]["number"] == 5230
    detail["execution_status"] = "running"
    with pytest.raises(delivery.DeliveryError, match="completion is unverified"):
        _draft_plan(state_dir, body, executor)


def test_failed_check_readback_keeps_receipt_and_reconciles_without_new_pr(draft_publication):
    state_dir, body, executor = draft_publication
    plan = _draft_plan(state_dir, body, executor)
    digest = plan["plan_sha256"]
    executor.checks_available = False
    with pytest.raises(delivery.DeliveryError, match="check-run readback is unavailable"):
        delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    evidence = delivery._state(state_dir)["publication"]
    assert evidence["state"] == "readback_pending"
    assert evidence["receipt"]["pr"]["number"] == 6000
    executor.checks_available = True
    result = delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert result["receipt"]["reconciled"] is True
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


@pytest.mark.parametrize("risk", ["auth", "state-machine", "data"])
def test_declared_high_risk_routes_before_any_publication_effect(draft_publication, risk):
    state_dir, body, executor = draft_publication
    with pytest.raises(delivery.DeliveryError, match=rf"{risk}.*FULL_PATH"):
        delivery.publication_plan(
            state_dir, ["feature.txt"], "Title", "message", body, tier=2,
            risk_surfaces=(risk,), risk_assessment_complete=True,
            review_gate_complete=True, executor=executor,
        )
    assert not executor.calls


def test_normal_apply_refuses_plan_with_declared_risk(draft_publication):
    state_dir, body, executor = draft_publication
    plan = _draft_plan(state_dir, body, executor)
    plan["risk_surfaces"] = ["auth"]
    plan["plan_sha256"] = delivery.publication.publication_plan_hash(plan)
    digest = plan["plan_sha256"]
    before = len(executor.calls)
    with pytest.raises(delivery.publication.PublicationRefusal, match="high-risk publication"):
        delivery.publish(state_dir, plan, digest, digest, digest, executor=executor)
    assert len(executor.calls) == before


@pytest.fixture
def high_risk_publication(draft_publication, tmp_path, monkeypatch):
    from scripts.pr_body_generator import generate_pr_body_from_mapping
    from tests.scripts.test_publication import BASE_SHA, COMMIT_SHA

    state_dir, body, executor = draft_publication
    state = delivery._state(state_dir)
    state.update(issue_body_sha256=delivery._sha(BODY), root=str(ROOT),
                 session_id="worker-session", agent_id="worker-agent")
    delivery.service._write(state_dir, state)
    body["issue_number"] = state["issue"]
    body["final_review_rounds"] = 1
    executor.issue = {"number": state["issue"], "state": "open", "title": "feature", "body": BODY,
                      "labels": [{"name": "agent:in-progress"}]}
    executor.pr_body = generate_pr_body_from_mapping(dict(body, pickup_receipt=state["pickup_receipt"]))
    executor.phase = "committed"
    monkeypatch.setattr(delivery, "_full_claim_readback", lambda *args: None)

    def artifact(name, content):
        path = tmp_path / name
        path.write_text(content)
        return {"path": str(path), "sha256": delivery._sha(content)}

    review = artifact("review.txt", f"Independent review of {COMMIT_SHA}: no blocking findings")
    first = "tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications"
    second = "tests/governance/test_issue_pr_governance.py::test_issue_readiness_workflow_is_strict_for_agent_ready_only"
    test_log = artifact("tests.txt", "2 passed in 0.23s")
    evidence = {
        "version": 1, "repository": delivery.REPOSITORY, "issue": state["issue"],
        "base_sha": BASE_SHA, "head_sha": COMMIT_SHA,
        "risk_surfaces": ["auth", "security", "concurrency", "state-machine"],
        "review": {"reviewer": "independent-reviewer", "verdict": "pass", "head_sha": COMMIT_SHA,
                   "blocking_findings": [], "evidence": review},
        "verification": [{"target": target, "head_sha": COMMIT_SHA, "result": "pass",
                          "evidence": test_log}
                         for target in (first, second)],
    }
    evidence_file = tmp_path / "actual-evidence.json"
    evidence_file.write_text(json.dumps(evidence))
    return state_dir, body, executor, evidence_file, evidence


def test_full_path_publishes_reviewed_candidate_as_draft_and_reconciles(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    result = delivery.publish_full(
        state_dir, ["feature.txt"], "Add deterministic publication adapter", body,
        evidence_file, executor=executor,
    )
    assert result["draft"] is True and result["pr_number"] == 6000
    assert result["commit_sha"] == evidence["head_sha"]
    assert result["checks"]["combined_status"] == "pending"
    creates = [call for call in executor.calls if call[:3] == ("gh", "pr", "create")]
    assert len(creates) == 1 and "--draft" in creates[0]
    review_gates = [call for call in executor.calls if any("review_before_ci_gate.py" in x for x in call)]
    assert review_gates and all(risk in review_gates[0] for risk in evidence["risk_surfaces"])
    delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                          body, evidence_file, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


@pytest.mark.parametrize("review_status", ["pass", "unresolved"])
def test_low_risk_finish_uses_independent_evidence_and_existing_publisher(
    high_risk_publication, monkeypatch, review_status,
):
    from app.builderops import openhands_factory as factory

    state_dir, body, executor, _, evidence = high_risk_publication
    state = delivery._state(state_dir)
    worktree = Path(state["worktree"])
    head, base = evidence["head_sha"], evidence["base_sha"]
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: head)
    monkeypatch.setattr(factory, "_verify", lambda *args: {
        "status": "passed", "head_sha": head, "failed": [], "unresolved": [],
        "verification": evidence["verification"],
    })
    reviews = []

    def review(*args):
        reviews.append(args)
        return {"status": review_status, "head_sha": head, "base_sha": base, "review": evidence["review"]}

    monkeypatch.setattr(factory, "_review", review)
    args = (ROOT, state_dir, state["issue"], ROOT, worktree.parent,
            "Add deterministic publication adapter", body, [], None)
    if review_status == "unresolved":
        with pytest.raises(factory.FinishEvidenceError, match="Independent review"):
            factory._finish(*args, executor=executor)
        assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                       or (call[:2] == ("gh", "api") and "POST" in call) for call in executor.calls)
        assert reviews[0][-3] == []
        return
    result = factory._finish(*args, executor=executor)
    assert result["draft"] is True and result["pr_number"] == 6000
    assert reviews[0][-3] == []
    receipt = json.loads(Path(result["evidence_file"]).read_text())
    assert receipt["risk_surfaces"] == [] and receipt["review"]["verdict"] == "pass"
    gate = next(call for call in executor.calls if any("review_before_ci_gate.py" in item for item in call))
    assert "--risk-assessment-complete" in gate and "--review-gate-complete" in gate
    assert "--risk-surface" not in gate
    monkeypatch.setattr(factory, "_verify", lambda *args: pytest.fail("repeated verification"))
    monkeypatch.setattr(factory, "_review", lambda *args: pytest.fail("repeated review"))
    assert factory._finish(*args, executor=executor)["pr_number"] == 6000
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


@pytest.mark.parametrize("risks", [None, ["unknown"], ["auth", "auth"]])
def test_full_path_still_rejects_missing_or_invalid_risk_assessment(high_risk_publication, risks):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence["risk_surfaces"] = risks
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="risk classification"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   or (call[:2] == ("gh", "api") and "POST" in call) for call in executor.calls)


def test_empty_risk_does_not_bypass_stateful_fallback_gate(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence.update(risk_surfaces=[], stateful_fallback=True, stateful_fallback_matrix_complete=True)
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="Stateful fallback requires an applicable risk surface"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   or (call[:2] == ("gh", "api") and "POST" in call) for call in executor.calls)


def test_finish_replays_existing_full_publication_with_original_private_evidence(
    high_risk_publication, monkeypatch,
):
    from app.builderops import openhands_factory as factory

    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence_file.chmod(0o600)
    title = "Add deterministic publication adapter"
    delivery.publish_full(state_dir, ["feature.txt"], title, body, evidence_file, executor=executor)
    state = delivery._state(state_dir)
    worktree = Path(state["worktree"])
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: evidence["head_sha"])
    monkeypatch.setattr(factory, "_verify", lambda *args: pytest.fail("repeated verification"))
    monkeypatch.setattr(factory, "_review", lambda *args: pytest.fail("repeated review"))
    monkeypatch.setattr(delivery.publication, "SubprocessExecutor", lambda: executor)

    def finish(chosen_title=title, chosen_body=body, risks=None):
        return factory._finish(ROOT, state_dir, state["issue"], ROOT, worktree.parent,
                               chosen_title, chosen_body, risks or evidence["risk_surfaces"], None)

    calls_before = len(executor.calls)
    result = finish()
    assert result["pr_number"] == 6000 and result["commit_sha"] == evidence["head_sha"]
    replay_calls = executor.calls[calls_before:]
    assert any("/check-runs" in arg for call in replay_calls for arg in call)
    assert not any(call[:3] == ("gh", "pr", "create") or call[:2] == ("git", "push")
                   or call[:6] == ("gh", "api", "--hostname", "github.com", "--method", "PATCH")
                   for call in replay_calls)
    with pytest.raises(delivery.DeliveryError):
        finish(chosen_title="Different title")
    with pytest.raises(delivery.DeliveryError):
        finish(chosen_body={**body, "summary": ["Different body"]})
    with pytest.raises(delivery.DeliveryError, match="inputs changed"):
        finish(risks=["auth"])
    evidence_file.chmod(0o644)
    with pytest.raises(delivery.DeliveryError, match="safely read"):
        finish()
    evidence_file.chmod(0o600)
    symlink = state_dir / "evidence-link.json"
    symlink.symlink_to(evidence_file)
    state = delivery._state(state_dir)
    state["full_publication"]["evidence_file"] = str(symlink)
    delivery.service._write(state_dir, state)
    with pytest.raises(delivery.DeliveryError, match="safely read"):
        finish()
    worker_file = worktree / "evidence.json"
    worker_file.write_text(evidence_file.read_text())
    worker_file.chmod(0o600)
    state["full_publication"]["evidence_file"] = str(worker_file)
    delivery.service._write(state_dir, state)
    with pytest.raises(delivery.DeliveryError, match="outside the worker worktree"):
        finish()


@pytest.fixture
def reviewed_draft_update(high_risk_publication, monkeypatch):
    from tests.scripts.test_publication import COMMIT_SHA

    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                          body, evidence_file, executor=executor)
    new_head = "d" * 40
    executor.head_sha = COMMIT_SHA
    evidence["head_sha"] = new_head
    evidence["review"]["head_sha"] = new_head
    review_file = Path(evidence["review"]["evidence"]["path"])
    review_text = f"Independent review of {new_head}: no blocking findings"
    review_file.write_text(review_text)
    evidence["review"]["evidence"]["sha256"] = delivery._sha(review_text)
    for item in evidence["verification"]:
        item["head_sha"] = new_head
    evidence_file.write_text(json.dumps(evidence))
    body["summary"] = ["Repair the reviewed feature"]
    original_run = executor.run

    def run(argv, *, cwd, input_text=None):
        args = tuple(argv)
        if args[:2] == ("git", "rev-parse") and args[2:] == ("HEAD",):
            executor.calls.append(args)
            return delivery.publication.CommandResult(args, 0, new_head + "\n", "")
        if args[:2] == ("gh", "api") and any("/check-runs" in x for x in args):
            executor.calls.append(args)
            payload = {"total_count": 1, "check_runs": [{"head_sha": new_head, "name": "CI",
                       "status": "queued", "conclusion": None}]}
            return delivery.publication.CommandResult(args, 0, json.dumps(payload), "")
        if args[:2] == ("gh", "api") and any(x.endswith("/status") for x in args):
            executor.calls.append(args)
            payload = {"sha": new_head, "state": "pending", "total_count": 0, "statuses": []}
            return delivery.publication.CommandResult(args, 0, json.dumps(payload), "")
        return original_run(argv, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(executor, "run", run)
    return state_dir, body, executor, evidence_file, new_head


def test_full_path_updates_same_reviewed_draft_and_reads_new_checks(reviewed_draft_update):
    state_dir, body, executor, evidence_file, new_head = reviewed_draft_update
    result = delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                                   evidence_file, executor=executor)
    assert result["pr_number"] == 6000 and result["commit_sha"] == new_head
    assert result["checks"]["commit"] == new_head
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1
    assert sum(call[:2] == ("git", "push") for call in executor.calls) == 2
    assert sum(call[:6] == ("gh", "api", "--hostname", "github.com", "--method", "PATCH")
               for call in executor.calls) == 1
    gates = [call for call in executor.calls if any("review_before_ci_gate.py" in x for x in call)]
    assert any("existing" in gate and "--pr-scope-revalidation" in gate for gate in gates)
    delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                          evidence_file, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_reconciles_lost_metadata_response(reviewed_draft_update):
    state_dir, body, executor, evidence_file, _ = reviewed_draft_update
    executor.failures["pr-update"] = 1
    executor.effect_then_fail.add("pr-update")
    result = delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                                   evidence_file, executor=executor)
    assert result["pr_number"] == 6000
    assert delivery._state(state_dir)["full_publication"]["metadata_reconciled"] is True


def test_full_path_does_not_repeat_unresolved_metadata_update(reviewed_draft_update):
    state_dir, body, executor, evidence_file, _ = reviewed_draft_update
    executor.failures["pr-update"] = 1
    with pytest.raises(delivery.DeliveryError, match="metadata update outcome is uncertain"):
        delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                              evidence_file, executor=executor)
    with pytest.raises(delivery.DeliveryError, match="metadata update remains unresolved"):
        delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                              evidence_file, executor=executor)
    assert sum(call[:6] == ("gh", "api", "--hostname", "github.com", "--method", "PATCH")
               for call in executor.calls) == 1


def test_full_path_does_not_repeat_unresolved_update_push(reviewed_draft_update):
    state_dir, body, executor, evidence_file, _ = reviewed_draft_update
    executor.failures["push"] = 1
    with pytest.raises(delivery.DeliveryError, match="push outcome is uncertain"):
        delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                              evidence_file, executor=executor)
    with pytest.raises(delivery.DeliveryError, match="push remains unresolved"):
        delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                              evidence_file, executor=executor)
    assert sum(call[:2] == ("git", "push") for call in executor.calls) == 2
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_reconciles_lost_update_push_response(reviewed_draft_update, monkeypatch):
    state_dir, body, executor, evidence_file, new_head = reviewed_draft_update
    executor.failures["push"] = 1
    executor.effect_then_fail.add("push")
    original_run = executor.run

    def run(argv, *, cwd, input_text=None):
        result = original_run(argv, cwd=cwd, input_text=input_text)
        if tuple(argv[:2]) == ("git", "push") and executor.remote_head == new_head:
            executor.prs[0]["head"]["sha"] = new_head
        return result

    monkeypatch.setattr(executor, "run", run)
    result = delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                                   evidence_file, executor=executor)
    assert result["commit_sha"] == new_head
    assert delivery._state(state_dir)["full_publication"]["push_reconciled"] is True
    assert sum(call[:2] == ("git", "push") for call in executor.calls) == 2
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_rejects_nonadditive_draft_update(reviewed_draft_update, monkeypatch):
    from tests.scripts.test_publication import COMMIT_SHA

    state_dir, body, executor, evidence_file, new_head = reviewed_draft_update
    original_run = executor.run

    def run(argv, *, cwd, input_text=None):
        if tuple(argv) == ("git", "merge-base", "--is-ancestor", COMMIT_SHA, new_head):
            return delivery.publication.CommandResult(tuple(argv), 1, "", "")
        return original_run(argv, cwd=cwd, input_text=input_text)

    monkeypatch.setattr(executor, "run", run)
    with pytest.raises(delivery.DeliveryError, match="not an additive successor"):
        delivery.publish_full(state_dir, ["feature.txt"], "Repair feature", body,
                              evidence_file, executor=executor)
    assert sum(call[:2] == ("git", "push") for call in executor.calls) == 1
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_uses_declared_risks_for_any_candidate(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence["risk_surfaces"] = ["data"]
    evidence_file.write_text(json.dumps(evidence))
    delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                          body, evidence_file, executor=executor)
    review_gate = next(call for call in executor.calls if any("review_before_ci_gate.py" in x for x in call))
    assert "data" in review_gate and "auth" not in review_gate and "state-machine" not in review_gate


def test_full_path_rejects_stale_or_nonindependent_review_before_effect(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence["review"]["reviewer"] = "worker-agent"
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="Independent convergence review"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   or (call[:2] == ("gh", "api") and "POST" in call) for call in executor.calls)


def test_full_path_rechecks_source_evidence_and_issue_targets(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    Path(evidence["review"]["evidence"]["path"]).write_text("modified review")
    with pytest.raises(delivery.DeliveryError, match="evidence is empty or has changed"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   for call in executor.calls)


def test_full_claim_rechecks_exact_dispatcher_lease_and_worktree(high_risk_publication, monkeypatch):
    from datetime import datetime, timedelta, timezone

    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    state = delivery._state(state_dir)
    worktree = Path(state["worktree"])
    issue = state["issue"]
    task = f"github-RasmusTho--agentic-pkm-mvp-issue-{issue}"
    state["pickup_receipt"] = (
        f"pickup-claim-complete issue={issue} branch={state['branch']} worktree={worktree} "
        f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task} "
        "lease_id=lease-123 holder=worker-agent evidence=verified-dispatcher-lease"
    )
    record = {"path": str(worktree), "branch": state["branch"], "owner": state["session_id"],
              "status": "active", "generation": "g1", "expires_at": __import__("time").time() + 60}
    monkeypatch.setattr(delivery.agent_worktree, "load_lifecycle_records", lambda *a: {str(worktree): record})
    monkeypatch.setattr(delivery.agent_worktree, "_worktree_generation", lambda *a, **kw: "g1")
    payload = {"ok": True, "task": {"task_id": task, "repo": delivery.REPOSITORY,
               "issue_number": issue, "claimed_by": "worker-agent", "lease_id": "lease-123",
               "status": "in_progress"}, "lease": {"lease_id": "lease-123", "holder": "worker-agent",
               "resource": f"issue:{issue}", "released_at": None,
               "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()}}

    class DispatcherReadback:
        def run(self, argv, *, cwd, input_text=None):
            assert "--events" in argv
            return delivery.publication.CommandResult(tuple(argv), 0, json.dumps(payload), "")

    FULL_CLAIM_READBACK(state, DispatcherReadback(), worktree)
    mismatched = dict(state, branch="different-branch")
    with pytest.raises(delivery.DeliveryError, match="does not bind"):
        FULL_CLAIM_READBACK(mismatched, DispatcherReadback(), worktree)
    payload["lease"]["holder"] = "different-agent"
    with pytest.raises(delivery.DeliveryError, match="no longer active"):
        FULL_CLAIM_READBACK(state, DispatcherReadback(), worktree)


def test_full_path_reconciles_lost_create_response_without_duplicate(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    executor.failures["pr-create"] = 1
    executor.effect_then_fail.add("pr-create")
    result = delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                                   body, evidence_file, executor=executor)
    assert result["draft"] is True
    assert delivery._state(state_dir)["full_publication"]["creation_reconciled"] is True
    delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                          body, evidence_file, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_does_not_retry_unresolved_pr_creation(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    executor.failures["pr-create"] = 1
    with pytest.raises(delivery.DeliveryError, match="outcome is uncertain"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert delivery._state(state_dir)["full_publication"]["state"] == "creating_pr"
    with pytest.raises(delivery.DeliveryError, match="remains unresolved"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_reconciles_exact_existing_draft_without_new_create(high_risk_publication):
    from tests.scripts.test_publication import COMMIT_SHA

    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    executor.remote_head = COMMIT_SHA
    executor.prs = [executor._exact_pr()]
    result = delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                                   body, evidence_file, executor=executor)
    assert result["draft"] is True and result["pr_number"] == 6000
    assert not any(call[:3] == ("gh", "pr", "create") for call in executor.calls)


def test_full_path_requires_every_issue_verify_target(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence["verification"].pop()
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="Not every governing Issue Verify target"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   for call in executor.calls)


def test_full_path_checks_quiet_test_summary_against_claimed_targets(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    test_log = Path(evidence["verification"][0]["evidence"]["path"])
    test_log.write_text("1 passed in 0.23s")
    for entry in evidence["verification"]:
        entry["evidence"].pop("sha256", None)
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="fewer passes"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   for call in executor.calls)


def test_full_path_check_readback_failure_preserves_draft_for_reconciliation(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    executor.checks_available = False
    with pytest.raises(delivery.DeliveryError, match="check-run readback is unavailable"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert delivery._state(state_dir)["full_publication"]["state"] == "check_readback_pending"
    executor.checks_available = True
    result = delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                                   body, evidence_file, executor=executor)
    assert result["pr_number"] == 6000
    assert sum(call[:3] == ("gh", "pr", "create") for call in executor.calls) == 1


def test_full_path_rejects_review_for_another_commit(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    evidence["review"]["head_sha"] = "0" * 40
    evidence_file.write_text(json.dumps(evidence))
    with pytest.raises(delivery.DeliveryError, match="Independent convergence review"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not any(call[:2] == ("git", "push") or call[:3] == ("gh", "pr", "create")
                   for call in executor.calls)


def test_full_path_declares_required_final_review_depth(high_risk_publication):
    state_dir, body, executor, evidence_file, evidence = high_risk_publication
    body["final_review_rounds"] = 0
    with pytest.raises(delivery.DeliveryError, match="one independent final review"):
        delivery.publish_full(state_dir, ["feature.txt"], "Add deterministic publication adapter",
                              body, evidence_file, executor=executor)
    assert not executor.calls
