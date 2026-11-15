"""Production readers must not turn a prepared operator recovery into authority."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import openhands_delivery as delivery
from scripts import agent_worktree

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import upgrade_host_probe as probe  # noqa: E402


@pytest.mark.parametrize("proof", [{"state": "prepared"}, None, {"state": "pinned"}])
def test_openhands_refuses_unqualified_operator_before_dispatcher(tmp_path, monkeypatch, proof):
    worktree = tmp_path.resolve()
    state = {"root": str(worktree), "issue": 123, "branch": "issue-123",
             "session_id": "session", "agent_id": "worker"}
    state["pickup_receipt"] = (
        f"pickup-claim-complete issue=123 branch=issue-123 worktree={worktree} "
        "coordination_mode=dispatcher-backed fallback_reason=none task_id=task "
        "lease_id=lease-123 holder=worker evidence=verified-dispatcher-lease"
    )
    record = {"path": str(worktree), "branch": state["branch"], "owner": "session",
              "status": "active", "generation": "g1", "expires_at": time.time() + 60,
              "operator_registration": proof}
    monkeypatch.setattr(agent_worktree, "load_lifecycle_records", lambda *_: {str(worktree): record})
    monkeypatch.setattr(agent_worktree, "_worktree_generation", lambda *a, **kw: "g1")
    class NoDispatch:
        def run(self, *a, **kw):
            pytest.fail("unqualified registration reached dispatcher readback")
    with pytest.raises(delivery.DeliveryError, match="operator registration"):
        delivery._full_claim_readback(state, NoDispatch(), worktree)


@pytest.mark.parametrize("proof", [{"state": "prepared"}, None, {"state": "pinned"}])
def test_probe_refuses_unqualified_operator_before_github(monkeypatch, proof):
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    lease_id = "lease-123"
    payload = {"ok": True, "task": {"task_id": probe.TASK_ID,
        "repo": "RasmusTho/agentic-pkm-mvp", "issue_number": probe.ISSUE,
        "status": "claimed", "claimed_by": probe.HOLDER, "lease_id": lease_id},
        "lease": {"holder": probe.HOLDER, "lease_id": lease_id,
        "resource": f"issue:{probe.ISSUE}", "released_at": None, "expires_at": expiry}}
    calls = []
    def process(*args, **kwargs):
        calls.append(args)
        if len(calls) > 1:
            pytest.fail("unqualified registration reached GitHub readback")
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(payload))
    monkeypatch.setattr(probe, "_git", lambda *a: probe.EXPECTED_BRANCH)
    monkeypatch.setattr(probe, "_bounded_process", process)
    record = {"owner": probe.SESSION, "branch": probe.EXPECTED_BRANCH, "status": "active",
              "expires_at": time.time() + 60, "operator_registration": proof}
    monkeypatch.setattr(agent_worktree, "load_lifecycle_records", lambda *_: {str(probe.REPOSITORY_ROOT): record})
    with pytest.raises(probe.CarrierRefusal, match="operator registration"):
        probe._lease_readback(lease_id)


@pytest.mark.parametrize("action", ["pickup", "resume"])
def test_operator_wrapper_delegates_after_issue_readback_without_normal_pickup(tmp_path, action):
    import importlib.util
    path = Path(__file__).resolve().parents[1] / "scripts/test_issue_pickup_claim.py"
    spec = importlib.util.spec_from_file_location("pickup_harness", path)
    harness = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(harness)
    issue = json.dumps({"number": 3301, "state": "open", "labels": [
        {"name": "type:task"}, {"name": "prio:high"}, {"name": "lane:governance"},
        {"name": "agent:in-progress"}], "body": harness.VALID_READY_BODY})
    worktree, env = harness._make_harness(tmp_path, status_json=json.dumps({
        "ok": True, "db_exists": True, "coordination_mode": "dispatcher-backed",
        "fallback_reason": None}), issue_json=issue)
    fake_python = Path(env["PYTHON"])
    content = fake_python.read_text()
    content = content.replace('case "$*" in\n', f'case "$*" in\n  *"-m app.builderops.legacy_owner_recovery {action} "*) exit 0 ;;\n', 1)
    fake_python.write_text(content)
    resume_flag = ["--operator-resume"] if action == "resume" else []
    result = harness._run(worktree, env, *resume_flag, "--takeover-stale", "--target-worktree", str(worktree),
                          "--operator-comment-id", "12", "--operator-pr", "34",
                          "--operator-workspace-root", str(tmp_path / "model"))
    assert result.returncode == 0, result.stdout + result.stderr
    log = Path(env["COMMAND_LOG"]).read_text()
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" in log
    assert f"-m app.builderops.legacy_owner_recovery {action} --issue 3301 --pr 34" in log
    assert "app.dispatcher claim" not in log
    assert "app.dispatcher show" not in log
    assert "heartbeat" not in log
    assert "pickup-refresh" not in log


def test_operator_resume_requires_complete_operator_arguments(tmp_path):
    import subprocess
    script = Path(__file__).resolve().parents[2] / "scripts/issue_pickup_claim.sh"
    result = subprocess.run(["bash", str(script), "--issue", "3301", "--takeover-stale",
                             "--operator-resume"], capture_output=True, text=True, check=False,
                            cwd=tmp_path)
    assert result.returncode == 2
    assert "operator pickup requires" in result.stderr


def test_wrapper_arguments_drive_real_host_cli_and_resume_existing_ack(tmp_path, monkeypatch, capsys):
    """The shell boundary is captured; real host CLI runs in-process on isolated state."""
    import importlib.util
    import shlex
    import subprocess
    from app.builderops import legacy_owner_recovery as recovery
    from scripts import agent_worktree

    tests_dir = Path(__file__).resolve().parents[1]
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    pickup = load("pickup_synthetic", tests_dir / "scripts/test_issue_pickup_claim.py")
    host = load("recovery_synthetic", tests_dir / "scripts/test_legacy_successor_recovery.py")
    case = host.operator_case.__wrapped__(tmp_path, monkeypatch)
    sandbox = tmp_path / "wrapper"
    sandbox.mkdir()
    issue = json.dumps({"number": 6601, "state": "open", "labels": [
        {"name": "type:task"}, {"name": "prio:high"}, {"name": "lane:governance"},
        {"name": "agent:in-progress"}], "body": pickup.VALID_READY_BODY})
    _, env = pickup._make_harness(sandbox, status_json=json.dumps({
        "ok": True, "db_exists": True, "coordination_mode": "dispatcher-backed",
        "fallback_reason": None}), issue_json=issue, target_branch="codex/example")
    env["FAKE_WORKTREE"] = str(case["worktree"])
    fake_python = Path(env["PYTHON"])
    content = fake_python.read_text().replace(
        'case "$*" in\n',
        'case "$*" in\n  *"-m app.builderops.legacy_owner_recovery "*) exit 0 ;;\n', 1)
    fake_python.write_text(content)
    monkeypatch.chdir(case["cwd"])
    delegate = recovery.subprocess.run
    posts = []

    def lose_ack_response(args, **kwargs):
        if args[0] == "gh" and "POST" in args:
            posts.append(1)
            delegate(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="response lost")
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", lose_ack_response)
    def shell_then_main(*extra):
        Path(env["COMMAND_LOG"]).write_text("")
        result = pickup._run(case["worktree"], env, *extra, "--takeover-stale", "--target-worktree",
                             str(case["worktree"]), "--operator-comment-id", "1", "--operator-pr", "6602",
                             "--operator-workspace-root", str(case["workspace_root"]),
                             issue="6601", agent="new-agent", session="new-session")
        assert result.returncode == 0, result.stdout + result.stderr
        lines = Path(env["COMMAND_LOG"]).read_text().splitlines()
        host_line = next(line for line in lines if line.startswith("dispatcher -m app.builderops.legacy_owner_recovery "))
        assert not any("app.dispatcher claim" in line or "heartbeat" in line for line in lines)
        argv = shlex.split(host_line)[3:]
        monkeypatch.setattr(sys, "argv", ["legacy_owner_recovery", *argv])
        return recovery._main(), capsys.readouterr().out.splitlines()

    rc, _ = shell_then_main()
    assert rc == 1 and len(posts) == 1
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    assert row["operator_registration"]["state"] == "prepared"
    rc, output = shell_then_main("--operator-resume")
    assert rc == 0 and len(posts) == 1
    receipt = [line for line in output if line.startswith("pickup-claim-complete ")]
    assert len(receipt) == 1 and f"issue=6601 branch=codex/example worktree={case['worktree']} " in receipt[0]
    assert "coordination_mode=dispatcher-backed" in receipt[0]


@pytest.mark.parametrize("case", ["relative", "root", "target", "target_symlink", "script", "missing_target"])
def test_operator_workspace_refused_before_git_or_external_reads(tmp_path, case):
    import os
    import subprocess

    script = Path(__file__).resolve().parents[2] / "scripts/issue_pickup_claim.sh"
    target = tmp_path / "workspace" / "checkout"
    target.mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(target.parent, target_is_directory=True)
    roots = {"relative": "relative/model", "root": "/", "target": str(target.parent),
             "target_symlink": str(alias), "script": str(script.parent.parent),
             "missing_target": str(tmp_path / "safe")}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls"
    for name in ("git", "gh"):
        executable = bin_dir / name
        executable.write_text('#!/bin/sh\nprintf "%s\\n" "invoked" >> "$CALL_LOG"\nexit 1\n')
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "CALL_LOG": str(log),
           "JSON_PYTHON": sys.executable}
    args = ["bash", str(script), "--issue", "3301", "--takeover-stale", "--operator-comment-id", "1",
            "--operator-pr", "2", "--operator-workspace-root", roots[case]]
    if case != "missing_target":
        args += ["--target-worktree", str(target)]
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "operator pickup" in result.stderr
    assert not log.exists()
