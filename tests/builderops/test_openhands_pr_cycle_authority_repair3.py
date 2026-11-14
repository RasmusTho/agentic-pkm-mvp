"""Verify eligibility across real cycle advancements; external effect ports are synthetic."""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from app.builderops import epic_workspace as workspace
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops import test_openhands_pr_cycle as base
from tests.builderops import test_openhands_pr_cycle_disposition as support
from tests.builderops import test_openhands_pr_cycle_p3_gate as prior


HEAD = "93b580838fdff4139b82fa200e2654bb9360bdef"
TARGET = ("tests/builderops/test_epic_workspace_coordination.py::"
          "test_no_progress_and_false_blocker_trigger_bounded_action")


def _file_cycle(tmp_path, monkeypatch, capsys, *, venv=None):
    """Real main/config, advance, locks, report gate and state; synthetic network/effects."""
    monkeypatch.setattr(base, "HEAD", HEAD)
    monkeypatch.setattr(prior, "HEAD", HEAD)
    monkeypatch.setattr(prior, "ACTUAL", {**copy.deepcopy(prior.ACTUAL), "verify_targets": [TARGET]})
    if venv is not None:
        setup = base.setup

        def setup_with_venv(root, mp):
            layout, entries, server = setup(root, mp)
            entries[0]["test_venv"] = str(venv)
            return layout, entries, server

        monkeypatch.setattr(support, "setup", setup_with_venv)
    layout, entries, server, identity, cid, calls = support.case(tmp_path / "workspace", monkeypatch)
    report_data = prior.reconciled()
    report_data["verify_targets"] = [TARGET]
    report = prior._finish(server, cid, identity, report_data)
    entries[0]["review_disposition"] = support.owner_disposition(report)
    config = tmp_path / "admission.json"

    def write_config(rows):
        with cycle._single_advancement(layout):
            config.write_text(json.dumps({"admissions": rows}), encoding="utf-8")
            config.chmod(0o600)

    write_config(entries)
    effects = prior._merge_ports(layout, monkeypatch, identity)
    real_advance = cycle.advance
    monkeypatch.setattr(cycle, "advance", lambda item, source: real_advance(item, source, fetch=base.fetch, http=server))
    argv = ["--once", "--root", str(layout.root), "--epic", "6615", "--config", str(config)]

    def tick():
        assert cycle.main(argv) == 0
        return json.loads(capsys.readouterr().out)["results"][1]

    return layout, entries, server, identity, report, calls, effects, write_config, tick


def _private_test_venv(tmp_path):
    """Make an isolated interpreter and copy local pytest packages into its own site-packages."""
    venv = tmp_path / "controller-test-venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, text=True)
    site = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    for name in ("pytest", "_pytest", "pluggy", "iniconfig", "pygments", "packaging", "py"):
        spec = importlib.util.find_spec(name)
        assert spec is not None and spec.origin is not None
        source = Path(spec.origin)
        if source.name == "__init__.py":
            shutil.copytree(source.parent, site / source.parent.name,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(source, site / source.name)
    assert "include-system-site-packages = false" in (venv / "pyvenv.cfg").read_text()
    return venv, site


def test_current_environment_is_verified_after_ci_before_merge(tmp_path, monkeypatch, capsys):
    real_sandbox, real_minor = cycle.sandbox_verify, cycle._venv_python_minor
    venv, site = _private_test_venv(tmp_path)
    dependency = site / "review_dependency.py"
    dependency.write_text('VALUE = "working"\n', encoding="utf-8")
    layout, entries, server, identity, report, calls, effects, _, tick = _file_cycle(
        tmp_path, monkeypatch, capsys, venv=venv)
    workspace._record_worker(layout, 6618, image="synthetic@sha256:" + "c" * 64)
    target = layout.checkout("reviewer") / TARGET.split("::")[0]
    target.write_text("from review_dependency import VALUE\n"
                      "def test_no_progress_and_false_blocker_trigger_bounded_action():\n"
                      "    assert VALUE == 'working'\n", encoding="utf-8")
    # The workspace ancestors are group-writable, so setup stubs only the source ownership
    # preflight; the real verifier, venv version check and its container orchestration run.
    monkeypatch.setattr(cycle, "_venv_python_minor", real_minor)
    monkeypatch.setattr(cycle, "sandbox_verify", real_sandbox)
    monkeypatch.setattr(workspace, "_remove_owned", lambda *args, **kwargs: None)
    statuses = iter([1, 1, 1, 0, 1, 1, 1, 0, 0, 0])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": next(statuses)})
    merge_command = cycle._command
    outcomes = []

    def run_pytest():
        env = {"PATH": os.defpath, "HOME": str(tmp_path), "PYTHONPATH": str(layout.checkout("reviewer")),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
        return subprocess.run([str(venv / "bin/python"), "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--confcutdir", str(target.parent), str(target) + "::" + TARGET.split("::")[1]],
                              cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=30)

    def docker_or_merge(argv, *, timeout):
        if argv[:2] == ["docker", "create"]:
            assert any(f"source={venv},target={cycle.CONTAINER_TEST_VENV},readonly" in arg for arg in argv)
            assert argv[-1] == TARGET
            return subprocess.CompletedProcess(argv, 0, "e" * 64, "")
        if argv[:3] == ["docker", "start", "--attach"]:
            with pytest.raises(cycle.CycleError, match="another advancement"):
                with cycle._single_advancement(layout):
                    pytest.fail("a cooperative environment writer acquired the held lock")
            result = run_pytest()
            outcomes.append(result)
            calls.append("sandbox")
            return subprocess.CompletedProcess(argv, result.returncode, result.stdout, result.stderr)
        return merge_command(argv, timeout=timeout)

    monkeypatch.setattr(cycle, "_command", docker_or_merge)
    for _ in range(3):
        assert tick()["action"] == "wait"
        assert "verification" not in cycle._find(layout, 10, identity)
    assert calls == ["stop", "ci", "ci", "ci"] and outcomes == []

    # Passing Verify followed by pending premerge CI leaves a historical passing receipt.
    assert tick()["action"] == "wait"
    first = cycle._find(layout, 10, identity)
    assert first["verification"]["passed"] is True and outcomes[0].returncode == 0, (
        outcomes[0].stdout, outcomes[0].stderr)
    assert effects == []
    proof = copy.deepcopy(first["execution_proof"])
    for _ in range(2):
        assert tick()["action"] == "wait"
        assert "verification" not in cycle._find(layout, 10, identity)
    assert len(outcomes) == 1 and effects == []
    with cycle._single_advancement(layout):
        dependency.write_text('VALUE = "broken"\n', encoding="utf-8")
    changed = run_pytest()
    assert changed.returncode != 0 and "FAILED" in changed.stdout

    assert tick()["action"] == "wait"
    failed = cycle._find(layout, 10, identity)
    assert outcomes[1].returncode != 0 and "FAILED" in outcomes[1].stdout
    assert failed["verification"]["passed"] is False and "merge_intent" not in failed
    assert effects == [] and failed["review"] == report and failed["execution_proof"] == proof

    with cycle._single_advancement(layout):
        dependency.write_text('VALUE = "working"\n', encoding="utf-8")
    assert tick()["action"] == "merged"
    assert [result.returncode for result in outcomes] == [0, 1, 0]
    assert effects == ["merge", "comment", "comment"]
    assert len(prior._posts(server)) == 1
    assert len([row for row in workspace._load_state(layout)["dispatch_decisions"]
                if row.get("request") == "independent-review"]) == 1
    print(json.dumps({"head": HEAD, "verify_exits": [result.returncode for result in outcomes],
                      "changed_environment_exit": changed.returncode, "pending_ticks": 5,
                      "failed_verify_output": outcomes[1].stdout,
                      "synthetic_effects": effects, "same_report_and_proof": True}, sort_keys=True))


def test_identical_readmission_reuses_review_and_proof_without_inventing_a_timer(tmp_path, monkeypatch, capsys):
    layout, entries, server, identity, report, calls, effects, write_config, tick = _file_cycle(
        tmp_path, monkeypatch, capsys)
    statuses = iter([0, 1, 0, 0])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": next(statuses)})
    assert tick()["action"] == "wait"  # green CI, passing Verify, pending premerge CI
    first = cycle._find(layout, 10, identity)
    assert first["verification"]["passed"] is True
    write_config([])
    assert tick()["reason"] == "not admitted at this head"
    assert effects == []
    write_config(entries)
    assert tick()["action"] == "merged"
    final = cycle._find(layout, 10, identity)
    assert final["review"] == report and final["execution_proof"] == first["execution_proof"]
    assert final["stop_intent"] == first["stop_intent"] and len(prior._posts(server)) == 1
    # Reverification follows from unknown environment contents across ticks, not from a
    # rule that identical reauthorization alone invalidated otherwise valid evidence.
    assert calls == ["stop", "ci", "sandbox", "ci", "ci", "sandbox", "ci"]
    assert effects == ["merge", "comment", "comment"]


def test_interrupted_fresh_verify_cannot_leave_an_old_pass_eligible(tmp_path, monkeypatch, capsys):
    layout, _, _, identity, _, calls, effects, _, tick = _file_cycle(tmp_path, monkeypatch, capsys)
    statuses = iter([0, 1, 0, 0, 0])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": next(statuses)})
    assert tick()["action"] == "wait"
    assert cycle._find(layout, 10, identity)["verification"]["passed"] is True
    verify = cycle.sandbox_verify

    def interrupted(*args):
        calls.append("interrupted-sandbox")
        raise cycle.CycleError("synthetic verifier interruption")

    monkeypatch.setattr(cycle, "sandbox_verify", interrupted)
    assert "synthetic verifier interruption" in tick()["reason"]
    saved = cycle._find(layout, 10, identity)
    assert "verification" not in saved and "merge_intent" not in saved and effects == []
    monkeypatch.setattr(cycle, "sandbox_verify", verify)
    assert tick()["action"] == "merged"
    assert effects == ["merge", "comment", "comment"]
