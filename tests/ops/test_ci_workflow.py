from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
CI_SMOKE_WORKFLOW = WORKFLOWS_DIR / "ci-smoke.yaml"
BROWSER_WORKFLOW = WORKFLOWS_DIR / "browser-runtime.yml"
IMAGE_WORKFLOW = WORKFLOWS_DIR / "app-image-build.yml"
IMPORT_LINTER_WORKFLOW = WORKFLOWS_DIR / "import-linter.yaml"
INTEGRATION_NIGHTLY_WORKFLOW = WORKFLOWS_DIR / "integration-nightly.yaml"
RELEASE_UAT_WORKFLOW = WORKFLOWS_DIR / "release-uat.yaml"
ARCHITECTURE_CI_WORKFLOW = WORKFLOWS_DIR / "architecture-ci.yaml"
FAILURE_CONTEXT_WORKFLOW = WORKFLOWS_DIR / "pr-ci-failure-context.yml"
OVERVIEW_JOURNEY_MODULE = "tests/companion_ui/test_devui_overview_journeys.py"
OVERVIEW_REQUIRED_NODEIDS = (
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_real_gateway_overview_focus_return_journey_preserves_subject_context_and_sha",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_focus_api_failure_renders_honest_visual_error_without_url_probing",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_connected_shell_freezes_server_identity_selector_and_aria_contract",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_connected_shell_renders_full_server_state_matrix_without_reclassification",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_gateway_shell_is_safe_accessible_no_egress_and_effect_free",
)
OVERVIEW_PR_REQUIRED_NODEIDS = OVERVIEW_REQUIRED_NODEIDS + (
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_trust_frame_default_view_is_compact",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_now_band_visible_above_fold_on_mobile_viewport",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_trust_frame_expansion_preserves_all_provider_fields",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_trust_frame_surfaces_degraded_provider_at_glance_depth",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_evidence_axes_reflow_in_narrow_rail_column",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_evidence_axes_render_exactly_once_per_entry",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_evidence_axes_no_illegible_wrapping_on_mobile_viewport",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_now_card_renders_owner_language_not_raw_field_names",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_overview_card_hides_raw_technical_fields_until_expanded",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_focus_sections_render_owner_language_not_raw_field_names",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_degraded_evidence_warning_stays_visible_and_null_limitation_stays_absent[stale]",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_degraded_evidence_warning_stays_visible_and_null_limitation_stays_absent[unknown]",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_degraded_evidence_warning_stays_visible_and_null_limitation_stays_absent[partial]",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_neutral_not_applicable_and_countable_states_stay_silent[not_countable]",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_neutral_not_applicable_and_countable_states_stay_silent[measured_empty]",
    f"{OVERVIEW_JOURNEY_MODULE}::"
    "test_explicit_limitation_remains_visible_in_overview_and_focus",
)


def _smoke_text() -> str:
    return CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")


def _browser_text() -> str:
    return BROWSER_WORKFLOW.read_text(encoding="utf-8")


def _workflow_step(workflow: str, name: str, next_name: str | None = None) -> str:
    start = workflow.index(f"- name: {name}")
    if next_name is None:
        return workflow[start:]
    return workflow[start : workflow.index(f"- name: {next_name}", start)]


def _workflow_run(name: str) -> str:
    return _browser_step(name)["run"]


def _browser_job() -> dict:
    workflow = yaml.safe_load(_browser_text())
    return workflow["jobs"]["companion-ui-browser-runtime"]


def _browser_step(name: str) -> dict:
    return next(step for step in _browser_job()["steps"] if step.get("name") == name)


def _python_heredoc(script: str) -> str:
    match = re.search(r"<<'PY'\n(?P<body>.*?)\nPY(?:\n|$)", script, re.DOTALL)
    assert match is not None
    return match.group("body")


@pytest.mark.parametrize("ffmpeg_present,rg_present,install_exit", [
    (True, True, 0), (True, False, 0), (False, True, 0), (False, False, 0), (False, False, 17),
])
def test_smoke_system_tools_reuse_or_install_with_failure_propagation(
    tmp_path: Path, ffmpeg_present: bool, rg_present: bool, install_exit: int,
) -> None:
    job = yaml.safe_load(_smoke_text())["jobs"]["smoke"]
    step = next(s for s in job["steps"] if s.get("name") == "Install system deps (ffmpeg, ripgrep)")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sources = {
        "sudo": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$APT_CALLS"\nexit "$INSTALL_EXIT"\n',
    }
    for name, present in (("ffmpeg", ffmpeg_present), ("rg", rg_present)):
        if present:
            sources[name] = "#!/bin/sh\nexit 0\n"
    for name, source in sources.items():
        tool = bin_dir / name
        tool.write_text(source, encoding="utf-8")
        tool.chmod(0o755)
    calls = tmp_path / "apt-calls"
    result = subprocess.run(
        ["/bin/bash", "-e", "-u", "-o", "pipefail", "-c", step["run"]],
        env={**os.environ, "PATH": str(bin_dir), "APT_CALLS": str(calls), "INSTALL_EXIT": str(install_exit)},
        capture_output=True, text=True, check=False, timeout=5,
    )

    assert result.returncode == install_exit, result.stdout + result.stderr
    if ffmpeg_present and rg_present:
        assert not calls.exists()
        assert "reusing runner tools" in result.stdout
    else:
        expected = ["apt-get update"] if install_exit else ["apt-get update", "apt-get install -y ffmpeg ripgrep"]
        assert calls.read_text().splitlines() == expected


CI_FITNESS_CALLERS = (
    (CI_SMOKE_WORKFLOW, "smoke", "Fitness report (QAS-003/QAS-010)", "Verify CI summary lines"),
    (INTEGRATION_NIGHTLY_WORKFLOW, "full-suite", "Fitness report", "Verify CI gates"),
    (RELEASE_UAT_WORKFLOW, "uat-gate", "Fitness report", "Verify CI gates"),
)
CI_FITNESS_NODE = (
    "tests/fitness/test_ci_fitness.py::"
    "test_ci_report_entrypoint_uses_scoped_product_gateway_fixture"
)


def _run_ci_fitness_workflow(tmp_path: Path, caller: tuple, *, failure: str = ""):
    """Execute the real producer and parser over disposable copies of the seed inputs."""
    workflow_path, job_name, report_name, verify_name = caller
    job = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))["jobs"][job_name]
    report_step = next(step for step in job["steps"] if step.get("name") == report_name)
    verify_step = next(step for step in job["steps"] if step.get("name") == verify_name)
    for relative in (
        "conftest.py", "pytest.ini", "tests/conftest.py", "tests/fitness/test_ci_fitness.py",
        "ops/quality/baselines.yaml",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination)
    shutil.copytree(REPO_ROOT / "data/golden", tmp_path / "data/golden")
    for name in ("app", "llm_contract", "docs", "config", "configs", "companion-ui"):
        source = REPO_ROOT / name
        if source.exists():
            (tmp_path / name).symlink_to(source, target_is_directory=True)
    (tmp_path / "tmp").mkdir()
    environment = {
        "PATH": f"{Path(sys.executable).parent}:{os.defpath}",
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "STORE_BACKEND": "memory",
        "LLM_PROVIDER": "mock",
        "REASONING_PROVIDER": "mock",
        "PLANNER_PROVIDER": "mock",
        "REASONING_ENABLE": "1",
        "INDEX_PERSIST_PATH": str(tmp_path / "tmp/index.jsonl"),
    }
    diarization = tmp_path / "data/golden/diarization_sample.jsonl"
    if failure == "missing_metric":
        diarization.unlink()
    elif failure == "malformed_metric":
        diarization.write_text("{invalid metric input\n", encoding="utf-8")
    elif failure == "failed_gate":
        (tmp_path / "data/golden/relations.json").write_text(
            '{"promoted": []}', encoding="utf-8"
        )
    elif failure == "missing_thresholds":
        environment["THRESHOLDS_PATH"] = str(tmp_path / "missing-thresholds.yaml")
    result = subprocess.run(
        ["bash", "-c", report_step["run"] + "\n" + verify_step["run"]],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=60,
    )
    log = (tmp_path / "tmp/ci_summary.log").read_text(encoding="utf-8")
    return result, log, job, report_step


@pytest.mark.parametrize("caller", CI_FITNESS_CALLERS, ids=("smoke", "nightly", "release-uat"))
def test_ci_fitness_callers_use_the_scoped_functional_producer(tmp_path: Path, caller: tuple) -> None:
    from app.fitness.report import SUMMARY_LABELS, parse_summary_lines

    discovered = set()
    for workflow_path in WORKFLOWS_DIR.iterdir():
        if workflow_path.suffix not in {".yaml", ".yml"}:
            continue
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        for job_name, job_definition in workflow.get("jobs", {}).items():
            for step in job_definition.get("steps", []):
                command = step.get("run", "")
                if CI_FITNESS_NODE in command or re.search(
                    r"\bpython(?:3)?\s+-m\s+app\.fitness\.report\b", command
                ):
                    discovered.add((workflow_path, job_name, step.get("name")))
    assert discovered == {
        (path, job_name, report_name)
        for path, job_name, report_name, _verify_name in CI_FITNESS_CALLERS
    }
    result, log, job, report_step = _run_ci_fitness_workflow(tmp_path, caller)
    assert report_step.get("shell") == "bash"
    assert "set -euo pipefail" in report_step["run"]
    assert "python -m pytest -q -s" in report_step["run"]
    assert CI_FITNESS_NODE in report_step["run"]
    assert "2>&1 | tee tmp/ci_summary.log" in report_step["run"]
    assert "continue-on-error" not in report_step
    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in log
    assert "CI gates status: true" in result.stdout
    parsed = parse_summary_lines(log.splitlines(), required=SUMMARY_LABELS)
    assert set(parsed) == set(SUMMARY_LABELS)
    assert parsed["GATES"]["ok"] is True
    uploads = [step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4"]
    assert any(
        step.get("if") == "always()" and "tmp/ci_summary.log" in step["with"]["path"]
        for step in uploads
    )


@pytest.mark.parametrize("caller", CI_FITNESS_CALLERS, ids=("smoke", "nightly", "release-uat"))
@pytest.mark.parametrize(
    ("failure", "cause"),
    (
        ("missing_metric", "DIA_P95"),
        ("malformed_metric", "JSONDecodeError"),
        ("failed_gate", "REL_COV,REL_VAL"),
        ("missing_thresholds", "FileNotFoundError"),
    ),
)
def test_ci_fitness_producer_propagates_report_failure(
    tmp_path: Path, caller: tuple, failure: str, cause: str
) -> None:
    result, log, _job, _step = _run_ci_fitness_workflow(tmp_path, caller, failure=failure)
    assert result.returncode != 0, result.stdout + result.stderr
    assert cause in log
    assert "app/fitness/" in log
    assert "1 failed" in log
    assert "CI gates status:" not in result.stdout
    assert "CI SUMMARY GATES ok=true" not in log


def _unit_tests_job_text() -> str:
    workflow = _smoke_text()
    return workflow[
        workflow.index("pr-unit-tests-not-pg:") : workflow.index("contract-validation:")
    ]


def _contract_job_text() -> str:
    workflow = _smoke_text()
    return workflow[workflow.index("contract-validation:") :]


def _vaultwide_panel_verifier_step_text() -> str:
    workflow = _smoke_text()
    start = workflow.index('- name: "CI gate: vaultwide panel verifier"')
    end = workflow.index("- name: Skip docker smoke for docs-only PR", start)
    return workflow[start:end]


def test_pr_ci_selects_subsystem_scoped_pytest_targets() -> None:
    # Moved from the retired ci.yml into ci-smoke.yaml (#3892); the PR unit
    # test lane must keep subsystem-scoped selection, the mandatory mypy
    # gate, and the intent-classification golden gate.
    job = _unit_tests_job_text()

    assert "Select subsystem-scoped pytest targets" in job
    assert "scripts/select_pr_tests.py" in job
    assert "steps.select-tests.outputs.pytest_args }} -vv --tb=short --durations=20" in job
    assert "Run shared not-pg unit tests in process shards" in job
    assert "xargs -r -n 1 -P 4 bash -c" in job
    assert "tests/invariants/test_vault_multiwriter.py" in job
    assert "tests/ops tests/invariants/test_vault_multiwriter.py" in job
    assert "Run scoped not-pg unit tests" in job
    assert "mypy app" in job
    assert "tests/eval/test_classification_golden.py" in job


def _run_full_suite_workflow(
    tmp_path: Path, *, failing_shard: str = "", mode: str = "success", deferred_targets: str = "",
    source_rpc: bool = False, operations: bool = False,
):
    """Execute the checked-in shell with a fake pytest, including nested tests."""
    files = (
        "tests/alpha/test_root.py", "tests/alpha/nested/test_child.py",
        "tests/beta/deep/test_only_child.py", "tests/test_standalone.py",
        "tests/deploy/test_deploy_channel_script.py", "tests/deploy/test_short.py",
        "tests/deploy/nested/test_child.py", "tests/deploy/nested/child_test.py",
        "tests/ops/test_host.py", "tests/ops/nested/test_host_child.py",
        "tests/invariants/test_vault_multiwriter.py", "tests/invariants/test_other.py",
        "tests/e2e/test_deferred.py", "tests/e2e/nested/test_also_deferred.py",
    )
    if source_rpc:
        files += ("tests/deploy/test_bws_source_rpc_assembly.py",)
    if operations:
        files += ("tests/operations/test_first.py", "tests/operations/nested/test_second.py")
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    planner = tmp_path / "scripts/plan_full_suite_node_shards.py"
    planner.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "scripts/plan_full_suite_node_shards.py", planner)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text(
        f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import signal
import sys
import time
args = sys.argv[1:]
if "--collect-only" in args:
    if os.environ.get("MODE") == "collect-failure":
        print("synthetic deploy collection failure", file=sys.stderr, flush=True)
        raise SystemExit(2)
    target = next(arg for arg in args if arg.startswith("tests/deploy/"))
    if target.endswith("test_bws_source_rpc_assembly.py"):
        print("\n".join(target + f"::test_source_{index}" for index in range(8)))
        raise SystemExit(0)
    for node in [
        target + "::test_rollback_dry_run_without_sha_parses_flag_and_skips_writes",
        target + "::test_rollback_with_explicit_sha_still_allows_flags",
        target + "::test_regular_a",
        target + "::test_regular_b[param with space]",
        target + "::test_regular_c",
        target + "::test_regular_d",
    ]:
        print(node)
    raise SystemExit(0)
targets = [arg for arg in args if arg.startswith("tests/")]
ignored = {arg.split("=", 1)[1] for arg in args if arg.startswith("--ignore=")}
assert os.environ["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
assert args[:2] == ["-m", "pytest"]
assert args[args.index("-m", 2) + 1] == (
    "not pg and not alpha_llm and not alpha_llm_live and not panel_llm_e2e and not eval "
    "and not browser_runtime and not human_uat and not uat_integrated_runtime"
)
assert args[2] == ("-vv" if any("::" in target for target in targets) else "-q")
active = Path("active")
active.mkdir(exist_ok=True)
token = active / str(os.getpid())
if targets[0] == "tests/ops":
    assert not list(active.iterdir()), "serial boundary overlapped parallel pytest"
else:
    token.touch()
    time.sleep(0.05)
state_path = Path(os.environ["FAKE_STATE"])
state_path.parent.mkdir(exist_ok=True)
state_path.touch(exist_ok=True)
lock_path = state_path.with_suffix(".lock")
with lock_path.open("a+", encoding="utf-8") as handle:
    import fcntl
    fcntl.flock(handle, fcntl.LOCK_EX)
    state = __import__("json").loads(state_path.read_text(encoding="utf-8") or "{}")
    state["active"] = state.get("active", 0) + (targets[0] != "tests/ops")
    state["max_active"] = max(state.get("max_active", 0), state["active"])
    temporary_state = state_path.with_suffix(".tmp")
    temporary_state.write_text(__import__("json").dumps(state), encoding="utf-8")
    os.replace(temporary_state, state_path)
    if os.environ.get("MODE") == "state-visible-before-unlock":
        assert __import__("json").loads(state_path.read_text()) == state
    fcntl.flock(handle, fcntl.LOCK_UN)
print("ARGV " + __import__("json").dumps(targets))
if os.environ.get("MODE") == "deploy-deselected" and targets[0] == "tests/deploy/nested/child_test.py":
    print("1 deselected")
    token.unlink()
    sys.exit(5)
for target in targets:
    if "::" in target:
        if not ((os.environ.get("MODE") == "incomplete-node-result" and "::test_regular_a" in target)
                or (os.environ.get("MODE") == "incomplete-rpc-result" and "::test_source_0" in target)):
            print(f"EXECUTED_NODE {target}")
            print(f"{target} PASSED [synthetic]")
            if os.environ.get("MODE") == "duplicate-rpc-result" and "::test_source_0" in target:
                print(f"{target} PASSED [synthetic]")
            if os.environ.get("MODE") == "unexpected-rpc-result" and "::test_source_0" in target:
                print(target.split("::")[0] + "::test_unplanned PASSED")
        continue
    path = Path(target)
    if path.is_dir():
        files = sorted(file for file in path.rglob("*.py")
                       if file.name.startswith("test_") or file.name.endswith("_test.py"))
    else:
        files = [path]
    for file in files:
        if str(file) not in ignored:
            print(f"EXECUTED {file}")
if (os.environ.get("MODE") == "incomplete" and targets[0] == "tests/alpha") or (
    os.environ.get("MODE") == "incomplete-node"
    and any("::test_regular_a" in target for target in targets)
):
    print("PARTIAL synthetic regression", flush=True)
    token.unlink()
    os.kill(os.getppid(), signal.SIGKILL)
    sys.exit(1)
if token.exists():
    token.unlink()
if targets[0] == os.environ.get("FAILING_SHARD") or any(
    target == os.environ.get("FAILING_SHARD") for target in targets
):
    print("FAILED synthetic regression")
    sys.exit(1)
print("1 passed")
if targets[0] != "tests/ops":
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        state = __import__("json").loads(state_path.read_text(encoding="utf-8") or "{}")
        state["active"] -= 1
        temporary_state = state_path.with_suffix(".tmp")
        temporary_state.write_text(__import__("json").dumps(state), encoding="utf-8")
        os.replace(temporary_state, state_path)
        if os.environ.get("MODE") == "state-visible-before-unlock":
            assert __import__("json").loads(state_path.read_text()) == state
        fcntl.flock(handle, fcntl.LOCK_UN)
''', encoding="utf-8",
    )
    fake_python.chmod(0o755)
    job = yaml.safe_load(_smoke_text())["jobs"]["pr-unit-tests-not-pg"]
    step = next(s for s in job["steps"] if s.get("name") ==
                "Run shared not-pg unit tests in process shards")
    script = re.sub(r"\$\{\{.*?\}\}", "fixture", step["run"])
    result = subprocess.run(
        ["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             **step["env"], "GITHUB_SHA": "fixture-sha", "MODE": mode,
             "DEFERRED_TARGETS": deferred_targets,
             "FAKE_STATE": str(tmp_path / "state.json"),
             "RUNNER_TEMP": str(tmp_path / "runner"), "FAILING_SHARD": failing_shard},
        timeout=30,
    )
    return result, files, job


@pytest.mark.parametrize("deferred_targets", ["", "tests/deploy"])
def test_full_suite_shards_cover_test_files_once(tmp_path: Path, deferred_targets: str) -> None:
    result, files, _job = _run_full_suite_workflow(tmp_path, deferred_targets=deferred_targets)
    assert result.returncode == 0, result.stdout + result.stderr
    log = (tmp_path / "pytest-not-pg.log").read_text()
    executed = re.findall(r"^EXECUTED (.+)$", log, re.MULTILINE)
    executed_nodes = re.findall(r"^EXECUTED_NODE (.+)$", log, re.MULTILINE)
    node_module = "tests/deploy/test_deploy_channel_script.py"
    expected = [name for name in files if not name.startswith("tests/e2e/")
                and not (deferred_targets and name.startswith(deferred_targets + "/"))]
    assert sorted(executed) == sorted(name for name in expected if name != node_module)
    if node_module in expected:
        assert {node.split("::", 1)[0] for node in executed_nodes} == {node_module}
        assert len(executed_nodes) == len(set(executed_nodes))
    else:
        assert not executed_nodes
    shards = (tmp_path / "runner/pytest-not-pg-shards/shards").read_text().splitlines()
    expected_shards = {name if name.startswith("tests/deploy/") or name.count("/") == 1
                       else "/".join(name.split("/")[:2])
                       for name in expected if not name.startswith("tests/ops/")}
    assert set(shards) == expected_shards and len(shards) == len(expected_shards)
    assert "tests/deploy" not in shards
    if deferred_targets:
        assert not any(shard.startswith("tests/deploy/") for shard in shards)
        assert shards == sorted(shards)
        assert "SHARD DEFERRED to post-merge heavy tests: tests/deploy/" in result.stderr
    else:
        assert shards[0] == "tests/deploy/test_deploy_channel_script.py"
        assert shards[1:] == sorted(set(shards[1:]))
        coverage = json.loads(
            (tmp_path / "runner/pytest-not-pg-shards/deploy-node-units/coverage.json").read_text()
        )
        planned_nodes = [
            node for unit in coverage["work_items"] for node in unit["nodes"]
        ]
        assert sorted(executed_nodes) == sorted(planned_nodes)
        assert len(coverage["work_items"]) <= 4
        assert coverage["max_workers"] == 4
        invocations = [
            json.loads(line.removeprefix("ARGV "))
            for line in log.splitlines()
            if line.startswith("ARGV ")
        ]
        shared_nodes = {
            "tests/deploy/test_deploy_channel_script.py::test_rollback_dry_run_without_sha_parses_flag_and_skips_writes",
            "tests/deploy/test_deploy_channel_script.py::test_rollback_with_explicit_sha_still_allows_flags",
        }
        assert sum(shared_nodes <= set(invocation) for invocation in invocations) == 1
        assert json.loads((tmp_path / "state.json").read_text())["max_active"] <= 4
    assert "SHARD FINISHED (0): tests/alpha in " in result.stdout
    # The host-sensitive tests run after parallel shards and are never duplicated.
    assert executed[-3:] == ["tests/ops/nested/test_host_child.py",
                             "tests/ops/test_host.py",
                             "tests/invariants/test_vault_multiwriter.py"]


@pytest.mark.parametrize("deferred_targets", ["", "tests/deploy"])
def test_full_suite_prioritizes_operations_without_changing_inventory(
    tmp_path: Path, deferred_targets: str,
) -> None:
    result, files, _job = _run_full_suite_workflow(
        tmp_path, source_rpc=True, operations=True, deferred_targets=deferred_targets,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    root = tmp_path / "runner/pytest-not-pg-shards"
    shards = (root / "shards").read_text().splitlines()
    if deferred_targets:
        assert shards[0] == "tests/operations"
        assert shards[1:] == sorted(shards[1:])
    else:
        assert shards[:3] == ["tests/deploy/test_bws_source_rpc_assembly.py",
                             "tests/deploy/test_deploy_channel_script.py", "tests/operations"]
        assert shards[3:] == sorted(shards[3:])
    assert shards.count("tests/operations") == 1
    assert len(shards) == len(set(shards))
    work_items = (root / "work-items").read_text().splitlines()
    operations_index = work_items.index("tests/operations")
    assert all(item.startswith(("source-rpc-node-unit-", "deploy-node-unit-"))
               for item in work_items[:operations_index])
    log = (tmp_path / "pytest-not-pg.log").read_text()
    executed = re.findall(r"^EXECUTED (.+)$", log, re.MULTILINE)
    node_modules = {"tests/deploy/test_bws_source_rpc_assembly.py",
                    "tests/deploy/test_deploy_channel_script.py"}
    expected = [name for name in files if not name.startswith("tests/e2e/")
                and not (deferred_targets and name.startswith(deferred_targets + "/"))
                and name not in node_modules]
    assert sorted(executed) == sorted(expected)
    assert json.loads((tmp_path / "state.json").read_text())["max_active"] <= 4
    assert executed[-3:] == ["tests/ops/nested/test_host_child.py", "tests/ops/test_host.py",
                             "tests/invariants/test_vault_multiwriter.py"]


def test_required_rpc_assembly_shards_preserve_exact_coverage(tmp_path: Path) -> None:
    result, _files, _job = _run_full_suite_workflow(tmp_path, source_rpc=True)
    assert result.returncode == 0, result.stdout + result.stderr
    root = tmp_path / "runner/pytest-not-pg-shards"
    coverage = json.loads((root / "source-rpc-node-units/coverage.json").read_text())
    nodes = [node for item in coverage["work_items"] for node in item["nodes"]]
    assert len(nodes) == len(set(nodes)) == 8
    assert len(coverage["work_items"]) == 2
    assert [node.rsplit("_", 1)[-1] for node in coverage["work_items"][0]["nodes"]] == ["0", "1", "4", "5"]
    log = (tmp_path / "pytest-not-pg.log").read_text()
    assert all(log.count(f"EXECUTED_NODE {node}\n") == 1 for node in nodes)
    assert json.loads((tmp_path / "state.json").read_text())["max_active"] <= 4


@pytest.mark.parametrize("mode", ["incomplete-rpc-result", "duplicate-rpc-result", "unexpected-rpc-result",
                                  "pytest-failure"])
def test_required_rpc_assembly_shards_fail_closed(tmp_path: Path, mode: str) -> None:
    failing = "tests/deploy/test_bws_source_rpc_assembly.py::test_source_0" if mode == "pytest-failure" else ""
    result, _files, _job = _run_full_suite_workflow(tmp_path, source_rpc=True, mode=mode, failing_shard=failing)
    assert result.returncode != 0
    assert any(message in result.stderr for message in (
        "node execution evidence incomplete", "unexpected pytest result", "SHARD FAILED",
    ))
    assert "tests/ops" not in (tmp_path / "pytest-not-pg.log").read_text()


def test_full_suite_node_plan_covers_collected_nodes_once_and_binds_shared_state() -> None:
    from scripts.plan_full_suite_node_shards import (
        SHARED_CHECKOUT_NODES,
        parse_collected_nodes,
        plan_node_units,
    )

    module = "tests/deploy/test_deploy_channel_script.py"
    nodes = (
        SHARED_CHECKOUT_NODES[0],
        module + "::test_regular_a",
        SHARED_CHECKOUT_NODES[1],
        module + "::test_regular_b[param with space]",
        module + "::test_regular_c",
        module + "::test_regular_d",
    )
    parsed = parse_collected_nodes("\n".join(nodes) + "\n6 tests collected", module)
    assert parsed == nodes
    units = plan_node_units(parsed, module, max_workers=4)
    flattened = [node for unit in units for node in unit]
    assert len(units) <= 4
    assert len(flattened) == len(nodes)
    assert sorted(flattened) == sorted(nodes)
    assert all(len(unit) == len(set(unit)) for unit in units)
    assert sum(set(SHARED_CHECKOUT_NODES) <= set(unit) for unit in units) == 1
    with pytest.raises(ValueError, match="duplicates"):
        plan_node_units((*nodes, nodes[0]), module, max_workers=4)
    with pytest.raises(ValueError, match="shared-checkout node inventory is incomplete"):
        plan_node_units(tuple(node for node in nodes if node != SHARED_CHECKOUT_NODES[0]), module)
    with pytest.raises(ValueError, match="worker cap"):
        plan_node_units(nodes, module, max_workers=5)


def test_full_suite_records_fully_deselected_deploy_module(tmp_path: Path) -> None:
    result, _files, _job = _run_full_suite_workflow(tmp_path, mode="deploy-deselected")
    assert result.returncode == 0, result.stdout + result.stderr
    shard_root = tmp_path / "runner/pytest-not-pg-shards"
    assert "0 tests/deploy/nested/child_test.py" in (shard_root / "status").read_text().splitlines()
    log = (shard_root / "logs/tests_deploy_nested_child_test.py.log").read_text()
    assert "1 deselected" in log and "EXECUTED" not in log


def test_full_suite_fake_shard_state_visible_before_unlock(tmp_path: Path) -> None:
    result, _files, _job = _run_full_suite_workflow(tmp_path, mode="state-visible-before-unlock")
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active"] == 0
    assert state["max_active"] <= 4


def test_full_suite_node_collection_failure_is_fail_red_and_retained(tmp_path: Path) -> None:
    result, _files, _job = _run_full_suite_workflow(tmp_path, mode="collect-failure")
    assert result.returncode == 1
    shard_root = tmp_path / "runner/pytest-not-pg-shards"
    receipt = json.loads((shard_root / "phase-margin.json").read_text())
    assert receipt["exit_status"] == 1 and receipt["phase"] != "complete"
    collection = (shard_root / "deploy-node-collection.log").read_text()
    assert "synthetic deploy collection failure" in collection
    assert "Deploy node collection failed (2)" in result.stderr
    assert not (shard_root / "status").read_text().strip()


def test_full_suite_missing_node_result_fails_red_after_complete_process_accounting(
    tmp_path: Path,
) -> None:
    result, _files, _job = _run_full_suite_workflow(tmp_path, mode="incomplete-node-result")
    assert result.returncode == 1
    shard_root = tmp_path / "runner/pytest-not-pg-shards"
    receipt = json.loads((shard_root / "phase-margin.json").read_text())
    assert receipt["exit_status"] == 1 and receipt["phase"] != "complete"
    assert "node execution evidence incomplete" in result.stderr
    assert "\nEXECUTED_NODE tests/deploy/test_deploy_channel_script.py::test_regular_a\n" not in (
        tmp_path / "pytest-not-pg.log"
    ).read_text()
    assert len((shard_root / "status").read_text().splitlines()) == len(
        (shard_root / "work-items").read_text().splitlines()
    )


def test_required_unit_full_suite_phase_budget_preserves_complete_coverage(tmp_path: Path) -> None:
    result, _files, job = _run_full_suite_workflow(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    step = next(s for s in job["steps"] if s.get("name") ==
                "Run shared not-pg unit tests in process shards")
    # Run 39100438771 completed every parallel shard in 51m35s, including the
    # 45m51s deploy shard, then timed out during the serial host boundary.
    assert step["timeout-minutes"] == 120
    assert step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
    assert "xargs -r -n 1 -P 4 bash -c" in step["run"]
    receipt = json.loads((tmp_path / "runner/pytest-not-pg-shards/phase-margin.json").read_text())
    assert receipt["schema"] == "required-unit-phase-margin.v1"
    assert receipt["github_sha"] == "fixture-sha"
    assert receipt["outer_budget_seconds"] == step["timeout-minutes"] * 60
    assert receipt["per_test_timeout_seconds"] == 120
    assert receipt["phase"] == "complete" and receipt["exit_status"] == 0
    assert receipt["total_seconds"] >= receipt["parallel_seconds"] + receipt["serial_seconds"]


@pytest.mark.parametrize(
    "step_name",
    ["Run shared not-pg unit tests in process shards", "Run scoped not-pg unit tests"],
)
def test_not_pg_steps_have_room_for_selected_coverage(step_name: str) -> None:
    unit_job = yaml.safe_load(_smoke_text())["jobs"]["pr-unit-tests-not-pg"]
    step = next(
        step for step in unit_job["steps"]
        if step.get("name") == step_name
    )

    assert step["timeout-minutes"] >= 30
    assert step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"


def test_scoped_unit_budget_preserves_selected_coverage() -> None:
    job = yaml.safe_load(_smoke_text())["jobs"]["pr-unit-tests-not-pg"]
    step = next(s for s in job["steps"] if s.get("name") == "Run scoped not-pg unit tests")
    assert step["timeout-minutes"] == 75
    assert step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
    assert step["if"] == (
        "steps.changes.outputs.code == 'true' && steps.select-tests.outputs.full_suite != 'true'"
    )
    assert step["shell"] == "bash"
    assert "continue-on-error" not in step
    assert step["run"].startswith(
        "set -euo pipefail\n"
        'echo "Selected subsystems: ${{ steps.select-tests.outputs.subsystems }}"\n'
        'echo "Selection reason: ${{ steps.select-tests.outputs.reason }}"\n'
    )
    assert 'if [[ "$SCOPED_PARTITIONS_JSON" == "[]" ]]; then' in step["run"]
    assert (
        "pytest ${{ steps.select-tests.outputs.pytest_args }} -vv --tb=short "
        "--durations=20 | tee pytest-not-pg.log"
    ) in step["run"]



@pytest.mark.parametrize("pytest_exit", [0, 7])
def test_scoped_unit_budget_preserves_selected_command_and_failure(
    tmp_path: Path, pytest_exit: int,
) -> None:
    job = yaml.safe_load(_smoke_text())["jobs"]["pr-unit-tests-not-pg"]
    step = next(s for s in job["steps"] if s.get("name") == "Run scoped not-pg unit tests")
    assert step["timeout-minutes"] == 75
    assert step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
    assert step["env"]["PYTHONUNBUFFERED"] == "1"
    selected = "-q -m 'not pg and not eval' tests/governance tests/scripts/test_publication.py"
    script = step["run"].replace("${{ steps.select-tests.outputs.pytest_args }}", selected)
    script = re.sub(r"\$\{\{.*?\}\}", "fixture", script)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import json
import os
from pathlib import Path
import sys
import time
Path("invocation.json").write_text(json.dumps({
    "args": sys.argv[1:], "watchdog": os.environ["PYTEST_ADDOPTS"],
    "unbuffered": os.environ["PYTHONUNBUFFERED"],
}))
outcome = "FAILED" if int(os.environ["FIXTURE_PYTEST_EXIT"]) else "PASSED"
print(f"tests/fixture.py::test_scoped_result {outcome}")
if outcome == "FAILED":
    print("tests/fixture.py:7: AssertionError: scoped diagnostic")
deadline = time.monotonic() + 5
while not Path("release").exists() and time.monotonic() < deadline:
    time.sleep(0.01)
sys.exit(int(os.environ["FIXTURE_PYTEST_EXIT"]))
''', encoding="utf-8",
    )
    fake_pytest.chmod(0o755)
    process = subprocess.Popen(
        ["bash", "-c", script], cwd=tmp_path, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
        env={**os.environ, **step["env"], "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "FIXTURE_PYTEST_EXIT": str(pytest_exit),
             "SCOPED_PARTITIONS_JSON": "[]", "SCOPED_TARGETS_JSON": "[]"},
    )
    log_path = tmp_path / "pytest-not-pg.log"
    expected_node = "tests/fixture.py::test_scoped_result " + ("FAILED" if pytest_exit else "PASSED")
    try:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            if log_path.exists() and expected_node in log_path.read_text():
                break
            time.sleep(0.01)
        # Node evidence reaches tee before pytest completes, even through a pipe.
        assert process.poll() is None
        assert expected_node in log_path.read_text()
    finally:
        (tmp_path / "release").touch()
        stdout, stderr = process.communicate(timeout=10)
    assert process.returncode == pytest_exit, stdout + stderr
    invocation = json.loads((tmp_path / "invocation.json").read_text())
    assert invocation == {
        "args": ["-q", "-m", "not pg and not eval", "tests/governance",
                 "tests/scripts/test_publication.py", "-vv", "--tb=short", "--durations=20"],
        "watchdog": "--timeout=120 --timeout-method=thread", "unbuffered": "1",
    }
    log = log_path.read_text()
    assert expected_node in log
    if pytest_exit:
        assert "AssertionError: scoped diagnostic" in log
    assert log in stdout


def test_scoped_deploy_coverage_is_bounded_and_fail_loud(tmp_path: Path) -> None:
    job = yaml.safe_load(_smoke_text())["jobs"]["pr-unit-tests-not-pg"]
    step = next(s for s in job["steps"] if s.get("name") == "Run scoped not-pg unit tests")
    assert step["timeout-minutes"] == 75
    assert step["env"]["PYTEST_ADDOPTS"] == "--timeout=120 --timeout-method=thread"
    assert step["env"]["SCOPED_TARGETS_JSON"] == (
        "${{ steps.select-tests.outputs.pytest_targets_json }}"
    )
    assert step["env"]["SCOPED_PARTITIONS_JSON"] == (
        "${{ steps.select-tests.outputs.scoped_partitions_json }}"
    )
    assert step["env"]["SCOPED_EXECUTION_UNITS_JSON"] == (
        "${{ steps.select-tests.outputs.scoped_execution_units_json }}"
    )
    assert "scripts/run_scoped_test_partitions.py" in step["run"]
    assert "--jobs 4" in step["run"]
    assert "--serial-boundary-json" in step["run"]
    assert "--execution-units-json" in step["run"]
    assert "--shard-timeout-seconds 3300" in step["run"]
    assert "set -euo pipefail" in step["run"]
    upload = next(s for s in job["steps"] if s.get("name") == "Upload scoped partition logs")
    assert upload["if"].startswith("always()")
    assert upload["with"]["path"] == "${{ runner.temp }}/pytest-scoped-shards/"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import subprocess
import sys
import time
if "--collect-only" in sys.argv:
    raise SystemExit(0)
target_text = " ".join(sys.argv[1:])
print(target_text, flush=True)
if serial_marker := os.environ.get("FAKE_SERIAL_MARKER"):
    if "tests/ops/test_instance_state_writer_inventory.py" in sys.argv[1:]:
        Path(serial_marker).touch()
if active_dir_value := os.environ.get("FAKE_ACTIVE_DIR"):
    active_dir = Path(active_dir_value)
    active_dir.mkdir(exist_ok=True)
    token = active_dir / str(os.getpid())
    token.touch()
    if "tests/deploy" in target_text:
        time.sleep(0.3)
    if any(arg.endswith("test_instance_state_writer_inventory.py") and not arg.startswith("--ignore=")
           for arg in sys.argv[1:]) and len(list(active_dir.iterdir())) != 1:
        print("host-sensitive ops partition overlapped another process", file=sys.stderr)
        raise SystemExit(9)
    token.unlink()
if child_pid_path := os.environ.get("FAKE_CHILD_PID_PATH"):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    Path(child_pid_path).write_text(str(child.pid))
if (timeout_target := os.environ.get("FAKE_TIMEOUT_TARGET")) and timeout_target in target_text:
    time.sleep(5)
if (fail_target := os.environ.get("FAKE_FAIL_TARGET")) and fail_target in target_text:
    print("synthetic scoped failure", file=sys.stderr, flush=True)
    raise SystemExit(7)
''', encoding="utf-8")
    fake_pytest.chmod(0o755)
    expected = ["tests/deploy", "tests/ops", "tests/scripts", "tests/ci"]
    partitions = [["tests/deploy"], ["tests/scripts"], ["tests/ci"], ["tests/ops"]]

    def run(*, expected_targets=expected, env: dict[str, str] | None = None, timeout: int = 10):
        return subprocess.run(
            [
                sys.executable, str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
                "--partitions-json", json.dumps(partitions),
                "--expected-targets-json", json.dumps(expected_targets),
                "--log-dir", str(tmp_path / "logs"),
                "--aggregate-log", str(tmp_path / "aggregate.log"),
                "--jobs", "4", "--serial-boundary-json",
                json.dumps(["tests/ops/test_instance_state_writer_inventory.py"]),
                "--shard-timeout-seconds", str(timeout),
            ],
            cwd=REPO_ROOT, capture_output=True, text=True,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
                 "PYTEST_ADDOPTS": "--timeout=120 --timeout-method=thread", **(env or {})},
            check=False,
        )

    success = run()
    assert success.returncode == 0, success.stdout + success.stderr
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert all(target in aggregate for target in expected)
    boundary = run(env={"FAKE_ACTIVE_DIR": str(tmp_path / "active")})
    assert boundary.returncode == 0, boundary.stdout + boundary.stderr
    exact_boundary = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
            "--partitions-json",
            json.dumps(
                [["tests/deploy"], ["tests/ops/test_instance_state_writer_inventory.py"]]
            ),
            "--expected-targets-json",
            json.dumps(
                ["tests/deploy", "tests/ops/test_instance_state_writer_inventory.py"]
            ),
            "--log-dir",
            str(tmp_path / "exact-logs"),
            "--aggregate-log",
            str(tmp_path / "exact-aggregate.log"),
            "--jobs",
            "4",
            "--serial-boundary-json",
            json.dumps(["tests/ops/test_instance_state_writer_inventory.py"]),
            "--shard-timeout-seconds",
            "10",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "PYTEST_ADDOPTS": "--timeout=120 --timeout-method=thread",
            "FAKE_ACTIVE_DIR": str(tmp_path / "exact-active"),
        },
        check=False,
    )
    assert exact_boundary.returncode == 0, exact_boundary.stdout + exact_boundary.stderr
    serial_marker = tmp_path / "serial-invoked"
    failure = run(env={"FAKE_FAIL_TARGET": "tests/ops", "FAKE_SERIAL_MARKER": str(serial_marker)})
    assert failure.returncode == 1
    assert "PARTITION FAILED (7)" in failure.stderr
    assert "synthetic scoped failure" in failure.stderr
    assert "SERIAL BOUNDARY NOT RUN:" in failure.stdout
    assert "SERIAL BOUNDARY FINISHED" not in failure.stdout
    assert not serial_marker.exists()
    aggregate = (tmp_path / "aggregate.log").read_text()
    serial_log = aggregate.split("===== scoped serial boundary =====\n")[1]
    assert serial_log.endswith("NOT RUN: tests/ops/test_instance_state_writer_inventory.py\n")
    assert "SERIAL BOUNDARY NOT RUN: index=4 " in serial_log
    assert len(serial_log.splitlines()) == 2
    assert (tmp_path / "logs/partition-4.log").read_text() == serial_log
    assert "synthetic scoped failure" in aggregate
    assert aggregate.count("===== scoped partition ") == 4
    absent = run(expected_targets=[*expected, "tests/missing"])
    assert absent.returncode != 0
    assert "does not match expected targets exactly once" in absent.stderr
    timed_out = run(env={"FAKE_TIMEOUT_TARGET": "tests/deploy",
        "FAKE_SERIAL_MARKER": str(serial_marker)}, timeout=1)
    assert timed_out.returncode == 1
    assert "PARTITION TIMED OUT after 1s" in timed_out.stderr
    assert "SERIAL BOUNDARY NOT RUN:" in timed_out.stdout
    assert "SERIAL BOUNDARY FINISHED" not in timed_out.stdout
    assert not serial_marker.exists()
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert "PARTITION TIMED OUT after 1s" in aggregate
    assert "NOT RUN: tests/ops/test_instance_state_writer_inventory.py\n" in aggregate
    child_pid_path = tmp_path / "child.pid"
    child_cleanup = run(env={"FAKE_CHILD_PID_PATH": str(child_pid_path)})
    assert child_cleanup.returncode == 0, child_cleanup.stdout + child_cleanup.stderr
    child_pid = int(child_pid_path.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"partition descendant {child_pid} survived process-group cleanup")


def test_scoped_execution_plan_rejects_partial_option_and_overlapping_coverage() -> None:
    from scripts.run_scoped_test_partitions import validate_execution_units

    with pytest.raises(ValueError, match="preserve non-deploy targets exactly once"):
        validate_execution_units(
            [["tests/scripts"]],
            ["tests/scripts", "tests/ci"],
        )
    with pytest.raises(ValueError, match="must not contain pytest options"):
        validate_execution_units(
            [["--ignore=tests/scripts/test_publication.py"]],
            ["tests/scripts"],
        )
    with pytest.raises(ValueError, match="preserve non-deploy targets exactly once"):
        validate_execution_units(
            [["tests/scripts", "tests/scripts/test_publication.py"]],
            ["tests/scripts"],
        )


def test_scoped_execution_plan_requires_complete_current_head_deploy_files() -> None:
    from scripts.run_scoped_test_partitions import validate_execution_units

    deploy_files = sorted(
        str(path)
        for path in (REPO_ROOT / "tests/deploy").rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    )
    relative_files = [str(Path(path).relative_to(REPO_ROOT)) for path in deploy_files]
    assert len(relative_files) > 1
    with pytest.raises(ValueError, match="current-head files exactly once"):
        validate_execution_units([relative_files[:-1]], ["tests/deploy"])
    with pytest.raises(ValueError, match="stable file targets"):
        validate_execution_units(
            [["tests/deploy", *relative_files]],
            ["tests/deploy"],
        )


@pytest.mark.parametrize(
    "nested_target",
    [
        "tests/scripts/test_publication.py",
        "tests/scripts/test_publication.py::test_publish_pr_rejects_missing_governing_issue",
    ],
)
def test_scoped_runner_normalizes_authenticated_directory_overlap_exactly_once(
    tmp_path: Path,
    nested_target: str,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import sys

args = sys.argv[1:]
node = "tests/scripts/test_publication.py::test_publish_pr_rejects_missing_governing_issue"
if "--collect-only" in args:
    print(node)
    raise SystemExit(0)
executions = 0
if "tests/scripts" in args:
    executions += 1
if "tests/scripts/test_publication.py" in args or node in args:
    executions += 1
with Path(os.environ["FAKE_EXECUTIONS"]).open("a", encoding="utf-8") as handle:
    handle.write("covered\n" * executions)
print(" ".join(args))
''',
        encoding="utf-8",
    )
    fake_pytest.chmod(0o755)
    expected = ["tests/scripts", nested_target]
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
            "--partitions-json",
            json.dumps([["tests/scripts"], [nested_target]]),
            "--expected-targets-json",
            json.dumps(expected),
            "--execution-units-json",
            json.dumps([["tests/scripts"], [nested_target]]),
            "--log-dir",
            str(tmp_path / "logs"),
            "--aggregate-log",
            str(tmp_path / "aggregate.log"),
            "--jobs",
            "4",
            "--shard-timeout-seconds",
            "10",
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_EXECUTIONS": str(tmp_path / "executions"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "executions").read_text().splitlines() == ["covered"]
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert "tests/scripts" in aggregate
    assert nested_target not in aggregate


@pytest.mark.parametrize(
    "option",
    ["--serial-boundary-json", "--execution-units-json"],
)
@pytest.mark.parametrize("malformed", [{}, None, False, 0, ""])
def test_scoped_runner_optional_json_shapes_fail_before_execution(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
    malformed: object,
) -> None:
    import scripts.run_scoped_test_partitions as runner

    calls: list[object] = []
    monkeypatch.setattr(
        runner,
        "run_partitions",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_scoped_test_partitions.py",
            "--partitions-json",
            '[["tests/scripts"]]',
            "--expected-targets-json",
            '["tests/scripts"]',
            "--log-dir",
            "unused-logs",
            "--aggregate-log",
            "unused-aggregate.log",
            option,
            json.dumps(malformed),
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 2
    assert calls == []


@pytest.mark.parametrize(
    "option",
    ["--serial-boundary-json", "--execution-units-json"],
)
def test_scoped_runner_optional_json_explicit_empty_list_is_valid(
    monkeypatch: pytest.MonkeyPatch,
    option: str,
) -> None:
    import scripts.run_scoped_test_partitions as runner

    calls: list[object] = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return 17

    monkeypatch.setattr(runner, "run_partitions", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_scoped_test_partitions.py",
            "--partitions-json",
            '[["tests/scripts"]]',
            "--expected-targets-json",
            '["tests/scripts"]',
            "--log-dir",
            "unused-logs",
            "--aggregate-log",
            "unused-aggregate.log",
            option,
            "[]",
        ],
    )
    assert runner.main() == 17
    assert len(calls) == 1
    assert calls[0][1]["serial_boundary"] == ()
    assert calls[0][1]["execution_units"] == ()


def test_scoped_runner_balances_parallel_work_and_preserves_serial_quiescence(
    tmp_path: Path,
) -> None:
    """Collected deploy nodes run once, with the host boundary last."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import fcntl
import json
import os
from pathlib import Path
import sys
import time

args = sys.argv[1:]
deploy_files = [arg for arg in args if arg.startswith("tests/deploy/")]
if "--collect-only" in args:
    for target in deploy_files:
        print(f"{target}::test_one")
        print(f"{target}::test_two")
    if "tests/deploy" in args:
        print("tests/deploy/test_slow.py::test_one")
        print("tests/deploy/test_slow.py::test_two")
    raise SystemExit(0)

state_path = Path(os.environ["FAKE_STATE"])
with state_path.open("a+", encoding="utf-8") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    handle.seek(0)
    raw = handle.read()
    state = json.loads(raw) if raw else {
        "active": 0, "max_active": 0, "executed": [], "invocations": []
    }
    state["active"] += 1
    state["max_active"] = max(state["max_active"], state["active"])
    state["invocations"].append(args)
    for arg in args:
        if arg.startswith("tests/deploy/") and arg.endswith(".py"):
            state["executed"].extend([f"{arg}::test_one", f"{arg}::test_two"])
    serial_targets = json.loads(os.environ["FAKE_SERIAL_TARGETS"])
    is_serial = all(target in args for target in serial_targets)
    state["active_at_serial"] = state["active"] if is_serial else state.get("active_at_serial")
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle)
    handle.flush()
    fcntl.flock(handle, fcntl.LOCK_UN)
time.sleep(0.15)
with state_path.open("a+", encoding="utf-8") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    handle.seek(0)
    state = json.load(handle)
    state["active"] -= 1
    if all(target in args for target in json.loads(os.environ["FAKE_SERIAL_TARGETS"])):
        state["serial_started"] = True
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle)
    handle.flush()
    fcntl.flock(handle, fcntl.LOCK_UN)
''',
        encoding="utf-8",
    )
    fake_pytest.chmod(0o755)
    expected = [
        "tests/deploy/test_slow.py",
        "tests/deploy/test_other.py",
        "tests/scripts",
        "tests/ops",
    ]
    partitions = [[target] for target in expected]
    units = [
        ["tests/deploy/test_slow.py"],
        ["tests/deploy/test_other.py", "tests/scripts"],
        ["tests/ops"],
    ]
    serial_boundary = [
        "tests/ops/test_dormant_ownership_initialization.py",
        "tests/ops/test_git_hygiene.py",
        "tests/ops/test_instance_state_deployment_lease.py",
        "tests/ops/test_instance_state_volume_contract.py",
        "tests/ops/test_instance_state_writer_inventory.py",
        "tests/ops/test_mvr05_mixed_version_fence.py",
        "tests/ops/test_native_journaling_acceptance.py",
        "tests/ops/test_start_full_runtime_health.py",
    ]
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps({"active": 0, "max_active": 0, "executed": [], "invocations": []})
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
            "--partitions-json", json.dumps(partitions),
            "--expected-targets-json", json.dumps(expected),
            "--execution-units-json", json.dumps(units),
            "--log-dir", str(tmp_path / "logs"),
            "--aggregate-log", str(tmp_path / "aggregate.log"),
            "--jobs", "4",
            "--serial-boundary-json", json.dumps(serial_boundary),
            "--shard-timeout-seconds", "10",
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_STATE": str(state_path),
            "FAKE_SERIAL_TARGETS": json.dumps(serial_boundary),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    state = json.loads(state_path.read_text())
    assert state["max_active"] <= 4
    assert state["active_at_serial"] == 1
    assert state["serial_started"] is True
    serial_invocations = [
        invocation
        for invocation in state["invocations"]
        if all(target in invocation for target in serial_boundary)
    ]
    assert len(serial_invocations) == 1
    parallel_invocations = [
        invocation for invocation in state["invocations"] if invocation not in serial_invocations
    ]
    assert all(
        target not in invocation
        for invocation in parallel_invocations
        for target in serial_boundary
    )
    ops_invocation = next(
        invocation for invocation in parallel_invocations if "tests/ops" in invocation
    )
    assert all(f"--ignore={target}" in ops_invocation for target in serial_boundary)
    assert sorted(state["executed"]) == sorted([
        "tests/deploy/test_other.py::test_one",
        "tests/deploy/test_other.py::test_two",
        "tests/deploy/test_slow.py::test_one",
        "tests/deploy/test_slow.py::test_two",
    ])


def test_scoped_runner_balanced_work_units_remain_bounded_and_fail_loud(
    tmp_path: Path,
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import sys
import time
args = sys.argv[1:]
if "--collect-only" in args:
    for arg in args:
        if arg.startswith("tests/deploy/"):
            print(f"{arg}::test_one")
    raise SystemExit(0)
target_text = " ".join(args)
print("synthetic scoped failure", flush=True)
if "tests/deploy/test_slow.py" in target_text and "FAIL_SCOPED" in __import__("os").environ:
    raise SystemExit(7)
if "TIMEOUT_SCOPED" in __import__("os").environ:
    time.sleep(5)
''',
        encoding="utf-8",
    )
    fake_pytest.chmod(0o755)
    expected = ["tests/deploy/test_slow.py", "tests/scripts"]
    partitions = [[target] for target in expected]
    units = [["tests/deploy/test_slow.py"], ["tests/scripts"]]

    def run(*, env: dict[str, str] | None = None, timeout: int = 10, units_value=units):
        return subprocess.run(
            [
                sys.executable,
                str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
                "--partitions-json", json.dumps(partitions),
                "--expected-targets-json", json.dumps(expected),
                "--execution-units-json", json.dumps(units_value),
                "--log-dir", str(tmp_path / "logs"),
                "--aggregate-log", str(tmp_path / "aggregate.log"),
                "--jobs", "4",
                "--shard-timeout-seconds", str(timeout),
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", **(env or {})},
            capture_output=True,
            text=True,
            check=False,
        )

    failed = run(env={"FAIL_SCOPED": "1"})
    assert failed.returncode == 1
    assert "synthetic scoped failure" in failed.stderr
    assert "synthetic scoped failure" in (tmp_path / "aggregate.log").read_text()
    timed_out = run(env={"TIMEOUT_SCOPED": "1"}, timeout=1)
    assert timed_out.returncode == 1
    assert "PARTITION TIMED OUT after 1s" in timed_out.stderr
    duplicate = run(units_value=[["tests/deploy/test_slow.py"], ["tests/deploy/test_slow.py"]])
    assert duplicate.returncode != 0
    assert "duplicate work" in duplicate.stderr
    incomplete = run(units_value=[["tests/deploy/test_slow.py"]])
    assert incomplete.returncode != 0
    assert "incomplete" in incomplete.stderr


def _run_scoped_measured_fixture(tmp_path: Path, mode: str = "complete", *, native=False, jobs=4,
                                 source_rpc=False):
    from scripts.plan_full_suite_node_shards import SHARED_CHECKOUT_NODES, SOURCE_RPC_MODULE, TARGET_MODULE
    from scripts.select_pr_tests import SCOPED_DEPLOY_SERIAL_BOUNDARY

    module = ("tests/ops/test_native_source_diagnostic_admission.py" if native else
              SOURCE_RPC_MODULE if source_rpc else TARGET_MODULE)
    nodes = ([f"{module}::test_regular_{index:03}[value with space]" for index in range(394)]
        if native else [*([] if source_rpc else SHARED_CHECKOUT_NODES), *(
            f"{module}::test_regular_{index}[value with space]" for index in range(9)
        )])
    serial_targets = (list(SCOPED_DEPLOY_SERIAL_BOUNDARY[1:]) if native
        else ["tests/ops/test_native_journaling_acceptance.py"])
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(f"#!{sys.executable}\n" + r'''
import fcntl
import json
import os
from pathlib import Path
import sys
import time
args = sys.argv[1:]
nodes = json.loads(os.environ["FAKE_NODES"])
mode = os.environ["FAKE_MODE"]
if "--collect-only" in args:
    if mode == "collect-failure":
        print("synthetic native collection failure")
        raise SystemExit(2)
    if mode == "collect-duplicate":
        nodes.append(nodes[-1])
    print("\n".join(nodes))
    raise SystemExit(0)
state_path = Path(os.environ["FAKE_STATE"])
serial = all(target in args for target in json.loads(os.environ["FAKE_SERIAL_TARGETS"]))
with state_path.open("a+") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    handle.seek(0)
    raw = handle.read()
    state = json.loads(raw) if raw else {"active": 0, "peak": 0, "invocations": []}
    state["active"] += 1
    state["peak"] = max(state["peak"], state["active"])
    state["invocations"].append(args)
    if serial:
        state["serial_active"] = state["active"]
        state["serial_invocation_count"] = len(state["invocations"])
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle)
time.sleep(0.05)
failed = mode == "pytest-failure" and (
    nodes[-1] in (nodes if os.environ["FAKE_MODULE"] in args else args)
)
for node in (nodes if os.environ["FAKE_MODULE"] in args else args):
    if node in nodes:
        if mode == "missing" and node == nodes[-1]:
            continue
        print(node + (" FAILED" if failed and node == nodes[-1] else " PASSED"), flush=True)
        if mode == "duplicate" and node == nodes[-1]:
            print(node + " PASSED", flush=True)
        if mode == "unexpected" and node == nodes[-1]:
            print(node.split("::")[0] + "::test_unplanned PASSED", flush=True)
with state_path.open("r+") as handle:
    fcntl.flock(handle, fcntl.LOCK_EX)
    state = json.load(handle)
    state["active"] -= 1
    handle.seek(0)
    handle.truncate()
    json.dump(state, handle)
raise SystemExit(1 if failed else 0)
''', encoding="utf-8")
    fake_pytest.chmod(0o755)
    expected = ([module, "tests/scripts", "tests/ci", *serial_targets] if native
        else [module, "tests/scripts", "tests/ops"])
    partitions = [expected] if native else [[target] for target in expected]
    state_path = tmp_path / "state.json"
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
         "--partitions-json", json.dumps(partitions),
         "--expected-targets-json", json.dumps(expected),
         "--execution-units-json", json.dumps(partitions),
         "--log-dir", str(tmp_path / "logs"),
         "--aggregate-log", str(tmp_path / "aggregate.log"),
         "--jobs", str(jobs), "--shard-timeout-seconds", "10",
         "--serial-boundary-json", json.dumps(serial_targets)],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "FAKE_NODES": json.dumps(nodes), "FAKE_MODE": mode, "FAKE_STATE": str(state_path),
             "FAKE_SERIAL_TARGETS": json.dumps(serial_targets), "FAKE_MODULE": module},
        capture_output=True, text=True, timeout=30, check=False,
    )
    return result, json.loads(state_path.read_text()) if state_path.exists() else {}, nodes


def _weighted_root_fixture(tmp_path, monkeypatch, *, collection_code=0):
    import scripts.run_scoped_test_partitions as runner
    from scripts.plan_full_suite_node_shards import SHARED_CHECKOUT_NODES, TARGET_MODULE
    from scripts.select_pr_tests import SCOPED_DEPLOY_SERIAL_BOUNDARY

    serial = SCOPED_DEPLOY_SERIAL_BOUNDARY
    deploy_nodes = (*SHARED_CHECKOUT_NODES, *(
        f"{TARGET_MODULE}::test_regular_{index:04}" for index in range(696)
    ))
    nodes = (*deploy_nodes, *(
        f"tests/ops/test_atomic.py::test_case[{index}]" for index in range(2603)
    ), *(
        f"tests/scripts/test_atomic.py::test_case[{index}]" for index in range(1310)
    ))
    collections = []
    executed = []

    class Collection:
        pid = 123456789
        returncode = collection_code

        def communicate(self, timeout):
            assert timeout == runner.COLLECTION_TIMEOUT_SECONDS
            return "\n".join(nodes) if not collection_code else "collection failed", None

    def collect(command, **kwargs):
        assert "--collect-only" in command
        collections.append(command)
        return Collection()

    def execute(index, targets, *, log_dir, timeout_seconds):
        executed.append(tuple(targets))
        log = log_dir / f"partition-{index}.log"
        log.write_text("".join(f"{node} PASSED\n" for node in targets if node in deploy_nodes))
        return index, 0, log, False

    monkeypatch.setattr(runner.subprocess, "Popen", collect)
    monkeypatch.setattr(runner, "_terminate_process_group", lambda _pid: None)
    monkeypatch.setattr(runner, "_run_partition", execute)
    expected = (TARGET_MODULE, "tests/ops", "tests/scripts")

    def run():
        return runner.run_partitions(
            tuple((target,) for target in expected), log_dir=tmp_path / "logs",
            aggregate_log=tmp_path / "aggregate.log", jobs=4, timeout_seconds=10,
            serial_last=False, serial_boundary=serial,
            execution_units=tuple((target,) for target in expected), expected_targets=expected,
        )

    return run, collections, executed, deploy_nodes, serial


def test_scoped_runner_weights_atomic_roots_without_stacking_deploy_nodes(tmp_path, monkeypatch):
    from scripts.select_pr_tests import PR_MARKER_EXPRESSION
    from scripts.plan_full_suite_node_shards import SHARED_CHECKOUT_NODES

    run, collections, executed, nodes, serial = _weighted_root_fixture(tmp_path, monkeypatch)
    assert run() == 0
    assert len(collections) == 1
    collection = collections[0]
    assert collection[collection.index("-m") + 1] == PR_MARKER_EXPRESSION
    assert "tests/ops" in collection and "tests/scripts" in collection
    assert all(f"--ignore={path}" in collection for path in serial)
    assert executed[-1] == serial
    parallel = executed[:-1]
    assert len(parallel) == 4
    ops = next(unit for unit in parallel if "tests/ops" in unit)
    scripts = next(unit for unit in parallel if "tests/scripts" in unit)
    assert ops != scripts
    assert ops == ("tests/ops", *(f"--ignore={path}" for path in serial))
    assert scripts == ("tests/scripts",)
    assert sorted(target for unit in parallel for target in unit if target in nodes) == sorted(nodes)
    assert sum(set(SHARED_CHECKOUT_NODES) <= set(unit) for unit in parallel) == 1
    assert all(path not in unit for unit in parallel for path in serial)


def test_scoped_runner_weight_collection_failure_stops_execution(tmp_path, monkeypatch):
    run, collections, executed, _nodes, _serial = _weighted_root_fixture(
        tmp_path, monkeypatch, collection_code=2,
    )
    with pytest.raises(RuntimeError, match="collection failed"):
        run()
    assert len(collections) == 1
    assert executed == []


def test_scoped_runner_splits_measured_module_with_exact_coverage(tmp_path: Path) -> None:
    from scripts.plan_full_suite_node_shards import SHARED_CHECKOUT_NODES, TARGET_MODULE

    result, state, nodes = _run_scoped_measured_fixture(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = state["invocations"]
    actual = [target for args in invocations for target in args if target.startswith(TARGET_MODULE)]
    assert sorted(actual) == sorted(nodes)
    node_invocations = [args for args in invocations if any(node in args for node in nodes)]
    assert 2 <= len(node_invocations) <= 4
    assert sum(set(SHARED_CHECKOUT_NODES) <= set(args) for args in node_invocations) == 1
    assert state["peak"] <= 4
    assert state["serial_active"] == 1
    assert state["serial_invocation_count"] == len(invocations)
    assert all("--ignore=tests/ops/test_native_journaling_acceptance.py" in args
               for args in invocations if "tests/ops" in args)
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert all(aggregate.count(node + " PASSED") == 1 for node in nodes)


@pytest.mark.parametrize("mode", ["missing", "duplicate", "unexpected"])
def test_scoped_runner_rejects_incomplete_measured_node_evidence(tmp_path: Path, mode: str) -> None:
    result, state, _nodes = _run_scoped_measured_fixture(tmp_path, mode)
    assert result.returncode == 1
    assert "Collected-node verification failed:" in result.stderr
    assert "Collected-node verification failed:" in (tmp_path / "aggregate.log").read_text()
    assert state["active"] == 0
    assert "serial_active" not in state
    assert "SERIAL BOUNDARY NOT RUN:" in result.stdout
    assert "NOT RUN: tests/ops/test_native_journaling_acceptance.py\n" in (
        tmp_path / "aggregate.log").read_text()


@pytest.mark.parametrize("workers", [2, 3, 4])
def test_native_admission_node_plan_is_closed_and_complete(workers, tmp_path):
    from scripts.plan_full_suite_node_shards import (
        parse_collected_nodes, plan_node_units, verify_executed_nodes, write_plan,
    )

    module = "tests/ops/test_native_source_diagnostic_admission.py"
    nodes = tuple(f"{module}::test_case[{index:03}]" for index in range(394))
    assert parse_collected_nodes("\n".join(nodes), module) == nodes
    units = plan_node_units(nodes, module, max_workers=workers)
    assert [len(unit) for unit in units] == [197, 197]
    assert tuple(node for unit in units for node in unit) == nodes
    assert plan_node_units(nodes[:3], module, max_workers=workers) == (nodes[:1], nodes[1:3])
    plan_dir, logs_dir = tmp_path / "plan", tmp_path / "logs"
    items = write_plan(nodes, module, plan_dir, max_workers=workers)
    logs_dir.mkdir()
    for item, unit in zip(items, units, strict=True):
        (logs_dir / f"{item}.log").write_text("".join(f"{node} PASSED\n" for node in unit))
    assert verify_executed_nodes(plan_dir / "coverage.json", logs_dir) == nodes
    with pytest.raises(ValueError, match="duplicates"):
        plan_node_units((*nodes, nodes[-1]), module)
    with pytest.raises(ValueError, match="escaped"):
        plan_node_units((*nodes, "tests/ops/test_other.py::test_case"), module)
    with pytest.raises(ValueError, match="only accepts"):
        plan_node_units(("tests/ops/test_other.py::test_case",), "tests/ops/test_other.py")


@pytest.mark.parametrize("jobs", [1, 4])
def test_scoped_runner_splits_native_admission_without_overlapping_serial_boundary(tmp_path, jobs):
    from scripts.select_pr_tests import SCOPED_DEPLOY_SERIAL_BOUNDARY

    result, state, nodes = _run_scoped_measured_fixture(tmp_path, native=True, jobs=jobs)
    assert result.returncode == 0, result.stdout + result.stderr
    invocations = state["invocations"]
    module = "tests/ops/test_native_source_diagnostic_admission.py"
    node_units = [tuple(arg for arg in args if arg in nodes) for args in invocations]
    node_units = [unit for unit in node_units if unit]
    if jobs == 1:
        assert node_units == []
        assert sum(module in args for args in invocations) == 1
    else:
        assert [len(unit) for unit in node_units] == [197, 197]
        assert sorted(node for unit in node_units for node in unit) == sorted(nodes)
        assert not any(module in args for args in invocations)
    assert state["peak"] <= jobs
    assert state["serial_active"] == 1
    assert state["serial_invocation_count"] == len(invocations)
    assert [arg for arg in invocations[-1] if arg in SCOPED_DEPLOY_SERIAL_BOUNDARY] == list(
        SCOPED_DEPLOY_SERIAL_BOUNDARY[1:])
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert all(aggregate.count(node + " PASSED") == 1 for node in nodes)


def test_native_admission_receipt_rejects_extra_units(tmp_path):
    from scripts.plan_full_suite_node_shards import verify_executed_nodes, write_plan

    module = "tests/ops/test_native_source_diagnostic_admission.py"
    nodes = tuple(f"{module}::test_case[{index}]" for index in range(4))
    plan_dir, logs_dir = tmp_path / "plan", tmp_path / "logs"
    write_plan(nodes, module, plan_dir, max_workers=4)
    coverage_path = plan_dir / "coverage.json"
    coverage = json.loads(coverage_path.read_text())
    moved = coverage["work_items"][0]["nodes"].pop()
    coverage["work_items"].append({"id": "deploy-node-unit-2", "nodes": [moved]})
    coverage_path.write_text(json.dumps(coverage))
    logs_dir.mkdir()
    for item in coverage["work_items"]:
        (logs_dir / f"{item['id']}.log").write_text("".join(f"{node} PASSED\n" for node in item["nodes"]))
    # The same four nodes appear once with a receipt-declared cap of four,
    # but this exact module is admitted to only two work units.
    with pytest.raises(ValueError, match="worker cap"):
        verify_executed_nodes(coverage_path, logs_dir)


def test_scoped_rpc_assembly_shards_preserve_exact_coverage(tmp_path):
    result, state, nodes = _run_scoped_measured_fixture(tmp_path, source_rpc=True)
    assert result.returncode == 0, result.stdout + result.stderr
    units = [[arg for arg in args if arg in nodes] for args in state["invocations"]]
    units = [unit for unit in units if unit]
    assert len(units) == 2
    assert sorted(node for unit in units for node in unit) == sorted(nodes)
    assert state["peak"] <= 4 and state["serial_active"] == 1
    assert all((tmp_path / "aggregate.log").read_text().count(node + " PASSED") == 1 for node in nodes)


@pytest.mark.parametrize("jobs", [2, 4])
def test_scoped_heavy_node_units_stay_in_distinct_processes(tmp_path, monkeypatch, jobs):
    """The real scoped scheduler must not repack both halves into one pytest."""
    import scripts.run_scoped_test_partitions as runner
    from scripts.plan_full_suite_node_shards import (
        NATIVE_ADMISSION_MODULE, SHARED_CHECKOUT_NODES, SOURCE_RPC_MODULE, TARGET_MODULE,
    )

    source = tuple(f"{SOURCE_RPC_MODULE}::test_case[{i}]" for i in range(574))
    native = tuple(f"{NATIVE_ADMISSION_MODULE}::test_case[{i}]" for i in range(394))
    deploy = (*SHARED_CHECKOUT_NODES, *(f"{TARGET_MODULE}::test_case[{i}]" for i in range(698)))
    other = tuple(f"tests/scripts/test_other.py::test_case[{i}]" for i in range(1900))
    collected = (*source, *native, *deploy, *other)
    serial = ("tests/ops/test_native_journaling_acceptance.py",)
    targets = (SOURCE_RPC_MODULE, NATIVE_ADMISSION_MODULE, TARGET_MODULE, "tests/scripts", *serial)
    calls = []
    monkeypatch.setattr(runner, "_collect_parallel_nodes", lambda _targets: collected)

    def execute(index, selected, *, log_dir, timeout_seconds):
        calls.append(tuple(selected))
        log = log_dir / f"partition-{index}.log"
        log.write_text("".join(f"{node} PASSED\n" for node in selected if node in collected))
        return index, 0, log, False

    monkeypatch.setattr(runner, "_run_partition", execute)
    assert runner.run_partitions(
        tuple((target,) for target in targets), log_dir=tmp_path / "logs",
        aggregate_log=tmp_path / "aggregate.log", jobs=jobs, timeout_seconds=10,
        serial_last=False, serial_boundary=serial,
        execution_units=tuple((target,) for target in targets), expected_targets=targets,
    ) == 0
    assert calls[-1] == serial
    parallel = calls[:-1]
    assert len(parallel) == jobs
    for nodes in (source, native):
        owners = [unit for unit in parallel if any(node in unit for node in nodes)]
        assert len(owners) == 2
        assert sorted(node for unit in owners for node in unit if node in nodes) == sorted(nodes)
    assert sorted(node for unit in parallel for node in unit if node in deploy) == sorted(deploy)
    assert sum(set(SHARED_CHECKOUT_NODES) <= set(unit) for unit in parallel) == 1
    if jobs == 4:
        assert not any(any(node in unit for node in source) and any(node in unit for node in native)
                       for unit in parallel)
    assert sum("tests/scripts" in unit for unit in parallel) == 1


@pytest.mark.parametrize("mode", ["pytest-failure", "missing", "duplicate", "unexpected"])
def test_scoped_rpc_assembly_shards_fail_closed(tmp_path, mode):
    result, state, _nodes = _run_scoped_measured_fixture(tmp_path, mode, source_rpc=True)
    assert result.returncode == 1
    assert state["active"] == 0 and state["peak"] <= 4
    assert "serial_active" not in state
    assert "SERIAL BOUNDARY NOT RUN:" in result.stdout


@pytest.mark.parametrize("mode", ["pytest-failure", "missing", "duplicate", "unexpected"])
def test_scoped_native_admission_requires_complete_node_results(tmp_path, mode):
    from scripts.select_pr_tests import SCOPED_DEPLOY_SERIAL_BOUNDARY

    result, state, _nodes = _run_scoped_measured_fixture(tmp_path, mode, native=True)
    assert result.returncode == 1
    aggregate = (tmp_path / "aggregate.log").read_text()
    if mode == "pytest-failure":
        assert "PARTITION FAILED (1)" in result.stderr
        assert " FAILED" in aggregate
        assert "Collected-node verification failed:" not in aggregate
    else:
        assert "Collected-node verification failed:" in result.stderr
        assert "Collected-node verification failed:" in aggregate
    assert state["active"] == 0 and state["peak"] <= 4
    assert "serial_active" not in state and "serial_invocation_count" not in state
    assert len(state["invocations"]) == 4
    assert "SERIAL BOUNDARY NOT RUN:" in result.stdout
    assert "SERIAL BOUNDARY FINISHED" not in result.stdout
    for target in SCOPED_DEPLOY_SERIAL_BOUNDARY[1:]:
        assert all(target not in args for args in state["invocations"])
        assert aggregate.count(f"NOT RUN: {target}\n") == 1


@pytest.mark.parametrize("mode", ["collect-failure", "collect-duplicate"])
def test_scoped_native_admission_collection_failure_stops_execution(tmp_path, mode):
    result, state, _nodes = _run_scoped_measured_fixture(tmp_path, mode, native=True)
    assert result.returncode != 0
    assert "collection failed" in result.stderr or "inventory contains duplicates" in result.stderr
    assert state == {}


def test_scoped_runner_reports_failure_before_other_partitions_finish(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(f"#!{sys.executable}\n" + r'''
import os
from pathlib import Path
import sys
import time
if "tests/fast" in sys.argv:
    print("early-diagnostic", flush=True)
    raise SystemExit(7)
release = Path(os.environ["FAKE_RELEASE"])
while not release.exists():
    time.sleep(0.01)
print("slow-released-after-diagnostic", flush=True)
''', encoding="utf-8")
    fake_pytest.chmod(0o755)
    release = tmp_path / "release"
    process = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
         "--partitions-json", json.dumps([["tests/fast"], ["tests/slow"], ["tests/serial"]]),
         "--expected-targets-json", json.dumps(["tests/fast", "tests/slow", "tests/serial"]),
         "--log-dir", str(tmp_path / "logs"),
         "--aggregate-log", str(tmp_path / "aggregate.log"),
         "--jobs", "2", "--shard-timeout-seconds", "5", "--serial-last"],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_RELEASE": str(release)},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert process.stdout is not None
    output = []
    for line in process.stdout:
        output.append(line)
        if "early-diagnostic" in line:
            release.touch()
    assert process.wait(timeout=15) == 1
    assert "".join(output).count("early-diagnostic") == 1
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert "early-diagnostic" in aggregate
    assert "slow-released-after-diagnostic" in aggregate
    assert "PARTITION TIMED OUT" not in aggregate
    assert "SERIAL PARTITION NOT RUN:" in aggregate
    assert aggregate.count("slow-released-after-diagnostic") == 1

@pytest.mark.parametrize("fail_target", ["tests/ops", "tests/scripts"])
def test_scoped_runner_serial_last_failure_is_aggregated(tmp_path: Path, fail_target: str) -> None:
    """The legacy serial-last path must remain fail-loud and observable."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pytest = bin_dir / "pytest"
    fake_pytest.write_text(
        f"#!{sys.executable}\n" + r'''
import os
import sys

args = sys.argv[1:]
if "tests/ops" in args:
    print("serial invoked", flush=True)
if os.environ["FAKE_FAIL_TARGET"] in args:
    print("synthetic serial failure", flush=True)
    raise SystemExit(7)
''',
        encoding="utf-8",
    )
    fake_pytest.chmod(0o755)
    expected = ["tests/scripts", "tests/ops"]
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/run_scoped_test_partitions.py"),
            "--partitions-json", json.dumps([["tests/scripts"], ["tests/ops"]]),
            "--expected-targets-json", json.dumps(expected),
            "--log-dir", str(tmp_path / "logs"),
            "--aggregate-log", str(tmp_path / "aggregate.log"),
            "--jobs", "4",
            "--serial-last",
            "--shard-timeout-seconds", "10",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_FAIL_TARGET": fail_target},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    aggregate = (tmp_path / "aggregate.log").read_text()
    assert "===== scoped serial partition =====" in aggregate
    assert "synthetic serial failure" in aggregate
    if fail_target == "tests/ops":
        assert "SERIAL PARTITION FAILED (7): 1" in result.stderr
        assert "serial invoked" in aggregate
        assert "NOT RUN" not in aggregate
    else:
        assert "PARTITION FAILED (7): 0" in result.stderr
        assert "SERIAL PARTITION NOT RUN:" in aggregate
        assert "NOT RUN: tests/ops\n" in aggregate
        assert "serial invoked" not in aggregate
        assert "SERIAL PARTITION FINISHED" not in result.stdout


@pytest.mark.parametrize(
    ("mode", "failing_shard"),
    [("shard-failure", "tests/alpha"),
     ("deploy-shard-failure", "tests/deploy/test_short.py"),
     ("node-failure", "tests/deploy/test_deploy_channel_script.py::test_regular_a"),
     ("incomplete", "tests/alpha"), ("incomplete-node", "tests/deploy/test_deploy_channel_script.py::test_regular_a"),
     ("serial-failure", "tests/ops")],
)
def test_full_suite_shards_retain_failure_logs(tmp_path: Path, mode: str, failing_shard: str) -> None:
    result, _files, job = _run_full_suite_workflow(tmp_path, failing_shard=failing_shard, mode=mode)
    assert result.returncode == 1
    shard_root = tmp_path / "runner" / "pytest-not-pg-shards"
    receipt = json.loads((shard_root / "phase-margin.json").read_text())
    assert receipt["exit_status"] == 1
    assert receipt["phase"] != "complete"
    if mode in {"incomplete", "incomplete-node"}:
        assert "Process-shard runner incomplete" in result.stderr
        partial_logs = [path for path in (shard_root / "logs").glob("*.log")
                        if "PARTIAL synthetic regression" in path.read_text()]
        assert len(partial_logs) == 1
        expected_missing = "tests/alpha" if mode == "incomplete" else "deploy-node-unit-1"
        assert expected_missing not in (shard_root / "status").read_text()
    elif mode in {"shard-failure", "deploy-shard-failure", "node-failure"}:
        if mode == "node-failure":
            assert "SHARD FAILED (1): deploy-node-unit-1" in result.stderr
            assert "FAILED synthetic regression" in (tmp_path / "pytest-not-pg.log").read_text()
            assert "deploy-node-unit-1" in (shard_root / "status").read_text()
        else:
            assert f"SHARD FAILED (1): {failing_shard}" in result.stderr
            log_name = failing_shard.replace("/", "_") + ".log"
            assert "FAILED synthetic regression" in (shard_root / "logs" / log_name).read_text()
            assert f"1 {failing_shard}" in (shard_root / "status").read_text()
        assert "FAILED synthetic regression" in (tmp_path / "pytest-not-pg.log").read_text()
    else:
        assert receipt["phase"] == "serial"
        assert "FAILED synthetic regression" in (tmp_path / "pytest-not-pg.log").read_text()
    upload = next(s for s in job["steps"] if s.get("name") == "Upload process shard logs")
    assert "always()" in upload["if"]
    assert "${{ runner.temp }}/pytest-not-pg-shards/" in upload["with"]["path"]


def _run_nightly_suite_workflow(tmp_path: Path, *, mode: str = "success"):
    """Run the actual nightly shell against finite, isolated pytest populations."""
    population = {
        "tests/alpha/test_root.py": [],
        "tests/alpha/nested/test_pg.py": ["pg"],
        "tests/beta/deep/test_child.py": [],
        "tests/deploy/test_deploy_channel_script.py": [],
        "tests/deploy/test_short.py": ["e2e"],
        "tests/deploy/nested/test_child.py": [],
        "tests/deploy/nested/child_test.py": ["pg"],
        "tests/deploy/test_optin_only.py": ["eval"],
        "tests/gamma/test_llm.py": ["alpha_llm"],
        "tests/test_standalone.py": ["e2e"],
        "tests/standalone_test.py": ["eval"],
        "tests/ops/test_host.py": [],
        "tests/ops/nested/test_host_child.py": ["human_uat"],
        "tests/invariants/test_vault_multiwriter.py": [],
        "tests/invariants/test_other.py": [],
        "tests/e2e/test_root.py": ["e2e"],
        "tests/e2e/nested/test_child.py": [],
    }
    for marker in (
        "alpha_llm_live", "panel_llm_e2e", "eval", "browser_runtime",
        "human_uat", "uat_integrated_runtime",
    ):
        population[f"tests/optin/test_{marker}.py"] = [marker]
    if mode == "empty-inventory":
        population = {}
    elif mode == "empty-selection":
        population = {name: ["pg"] for name in population}
    for name in population:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    deploy_helpers = tmp_path / "tests/deploy/helpers"
    deploy_helpers.mkdir(parents=True, exist_ok=True)
    (deploy_helpers / "support.py").touch()
    (tmp_path / "population.json").write_text(json.dumps(population), encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    fake_python.write_text(
        f"#!{sys.executable}\n" + r'''
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
import xml.etree.ElementTree as ET
from _pytest.mark.expression import Expression

args = sys.argv[1:]
if Path(sys.argv[0]).name != "pytest" and args[:2] not in (["-m", "pytest"], ["-u", "-m"]):
    os.execv(sys.executable, [sys.executable, *args])
population = json.loads(Path("population.json").read_text())
targets = [arg for arg in args if arg.startswith("tests/")] or ["tests"]
ignored = {arg.split("=", 1)[1] for arg in args if arg.startswith("--ignore=")}
marker = args[args.index("-m", args.index("pytest") + 1 if "pytest" in args else 0) + 1]
expression = Expression.compile(marker)
selected = [name for name, markers in population.items()
            if any(name == target or name.startswith(target + "/") for target in targets)
            and name not in ignored and expression.evaluate(lambda name, **_: name in markers)]
phase = "serial" if "tests/ops" in targets else "parallel"
active = Path("active")
active.mkdir(exist_ok=True)
identity = active / str(os.getpid())
def record(event):
    with Path("fixture.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for child in active.iterdir():
            try:
                os.kill(int(child.name), 0)
            except ProcessLookupError:
                child.unlink()
        if event == "start" and phase == "parallel":
            identity.touch()
        elif event == "finish":
            identity.unlink(missing_ok=True)
        with Path("events.jsonl").open("a") as events:
            events.write(json.dumps({"event": event, "phase": phase, "targets": targets,
                                     "active": len(list(active.iterdir())), "args": args,
                                     "marker": marker,
                                     "addopts": os.getenv("PYTEST_ADDOPTS"),
                                     "unbuffered": os.getenv("PYTHONUNBUFFERED")}) + "\n")
record("start")
print(f"NODE START {targets[0]}::test_synthetic", flush=True)
mode = os.environ["NIGHTLY_FIXTURE_MODE"]
if targets[0] == "tests/alpha":
    if mode == "terminated":
        os.kill(os.getpid(), signal.SIGTERM)
    if mode == "unreported":
        os.kill(os.getppid(), signal.SIGTERM)
    if mode == "incomplete":
        record("finish")
        sys.exit(0)
if targets[0] == "tests/deploy/test_deploy_channel_script.py" and mode == "deploy-file-incomplete":
    record("finish")
    sys.exit(0)
time.sleep(0.1)
failed = (mode == "failure" and targets[0] == "tests/alpha"
          or mode == "deploy-file-failure" and targets[0] == "tests/deploy/test_deploy_channel_script.py"
          or mode == "serial-failure" and targets[0] == "tests/ops")
for name in selected:
    print(f"EXECUTED {name}", flush=True)
    print(f"{name}::test_synthetic {'FAILED' if failed else 'PASSED'}", flush=True)
if failed:
    print("AssertionError: synthetic regression", flush=True)
report = next((arg.split("=", 1)[1] for arg in args if arg.startswith("--junitxml=")), None)
if report:
    count = len(selected) + (mode == "miscount" and targets[0] == "tests/alpha")
    suite = ET.Element("testsuite", tests=str(count), failures=str(len(selected) if failed else 0),
                       errors="0", skipped="0")
    for name in selected:
        case = ET.SubElement(suite, "testcase", classname=name, name="test_synthetic")
        if failed:
            ET.SubElement(case, "failure").text = "synthetic regression"
    ET.ElementTree(suite).write(report)
print(f"{len(selected)} {'failed' if failed else 'passed'}" if selected else "no tests ran", flush=True)
print("slowest durations: 0.01s test_synthetic", flush=True)
record("finish")
sys.exit(1 if failed else 0 if selected else 5)
''', encoding="utf-8",
    )
    fake_python.chmod(0o755)
    (bin_dir / "pytest").symlink_to(fake_python)
    job = yaml.safe_load(INTEGRATION_NIGHTLY_WORKFLOW.read_text())["jobs"]["full-suite"]
    step = next(s for s in job["steps"] if s.get("name") == "Full test suite (memory, not pg)")
    result = subprocess.run(
        ["bash", "-c", step["run"]], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, **step.get("env", {}),
             "PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path / "runner"),
             "NIGHTLY_FIXTURE_MODE": mode}, timeout=30,
    )
    return result, population, job, step


def test_nightly_suite_shards_preserve_the_full_marker_inventory(tmp_path: Path) -> None:
    result, population, job, step = _run_nightly_suite_workflow(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    executed = re.findall(r"^EXECUTED (.+)$", (tmp_path / "tmp/nightly-pytest.log").read_text(), re.MULTILINE)
    expected = [
        name for name, markers in population.items()
        if not {"pg", "alpha_llm", "eval"}.intersection(markers)
    ]
    assert sorted(executed) == sorted(expected)
    shards = (tmp_path / "runner/pytest-nightly-shards/shards").read_text().splitlines()
    expected_shards = {name if name.startswith("tests/deploy/") or name.count("/") == 1
                       else "/".join(name.split("/")[:2])
                       for name in population if not name.startswith("tests/ops/")}
    assert set(shards) == expected_shards and len(shards) == len(expected_shards)
    assert shards[0] == "tests/deploy/test_deploy_channel_script.py"
    assert shards[1:] == sorted(set(shards[1:]))
    assert "tests/deploy" not in shards
    status = (tmp_path / "runner/pytest-nightly-shards/status").read_text().splitlines()
    for deselected in ("tests/deploy/nested/child_test.py", "tests/deploy/test_optin_only.py"):
        assert f"5 {deselected}" in status
        report = tmp_path / "runner/pytest-nightly-shards/logs" / (deselected.replace("/", "_") + ".xml")
        assert 'tests="0"' in report.read_text()
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    for event in events:
        assert event["marker"] == "not pg and not alpha_llm and not eval"
        assert "-v" in event["args"] and "--tb=short" in event["args"]
        assert "--import-mode=importlib" in event["args"] and "--durations=30" in event["args"]
        assert event["addopts"] == "--timeout=120 --timeout-method=thread"
        assert event["unbuffered"] == "1"
    assert step["timeout-minutes"] == 50 and job["timeout-minutes"] == 60
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in job.get("env", {})


def test_nightly_memory_producer_respects_qualified_eval_lane() -> None:
    job = yaml.safe_load(INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["full-suite"]
    checkout = next(step for step in job["steps"] if step.get("name") == "Checkout")
    install = next(
        step for step in job["steps"] if step.get("name") == "Install standalone sidecar test dependencies"
    )
    suite = next(step for step in job["steps"] if step.get("name") == "Full test suite (memory, not pg)")

    assert job["env"]["PYTHON"] == "python"
    assert checkout["with"] == {"fetch-depth": 0}
    assert install["run"] == (
        "pip install --requirement mimer-mcp-sidecar/requirements.txt\n"
        "pip install --no-deps --editable mimer-mcp-sidecar\n"
    )
    assert "marker='not pg and not alpha_llm and not eval'" in suite["run"]

    def collect(marker: str) -> list[str]:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "pytest_timeout",
                "-p",
                "pytest_asyncio.plugin",
                "-p",
                "anyio.pytest_plugin",
                "--collect-only",
                "-q",
                "tests/evals/test_sv_en_retrieval_eval.py",
                "-m",
                marker,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        prefix = "tests/evals/test_sv_en_retrieval_eval.py::"
        return [line for line in result.stdout.splitlines() if line.startswith(prefix)]

    deterministic = collect("not eval")
    qualified_live = collect("eval")
    assert len(deterministic) == 10
    assert len(qualified_live) == 2
    assert set(deterministic).isdisjoint(qualified_live)


@pytest.mark.parametrize("mode", ["failure", "serial-failure", "terminated", "unreported",
                                  "incomplete", "miscount", "empty-selection", "empty-inventory",
                                  "deploy-file-failure", "deploy-file-incomplete"])
def test_nightly_suite_failed_and_incomplete_shards_fail_closed(tmp_path: Path, mode: str) -> None:
    result, _population, job, _step = _run_nightly_suite_workflow(tmp_path, mode=mode)
    assert result.returncode != 0, result.stdout + result.stderr
    root = tmp_path / "runner/pytest-nightly-shards"
    assert (root / "shards").exists() and (root / "status").exists()
    if mode not in {"empty-inventory", "empty-selection"}:
        assert "NODE START tests/alpha::test_synthetic" in (root / "logs/tests_alpha.log").read_text()
        assert "0 tests/beta" in (root / "status").read_text()
    if mode not in {"empty-inventory", "unreported"}:
        assert "host-sensitive" in (root / "status").read_text()
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        serial = [event for event in events if event["phase"] == "serial" and event["event"] == "start"]
        assert len(serial) == 1 and serial[0]["active"] == 0
    elif mode == "unreported":
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        assert not any(event["phase"] == "serial" for event in events)
    if mode == "failure":
        assert "AssertionError: synthetic regression" in (root / "logs/tests_alpha.log").read_text()
        assert "1 tests/alpha" in (root / "status").read_text()
        assert "AssertionError: synthetic regression" in result.stderr
    elif mode == "deploy-file-failure":
        assert "1 tests/deploy/test_deploy_channel_script.py" in (root / "status").read_text()
        assert "AssertionError: synthetic regression" in (
            root / "logs/tests_deploy_test_deploy_channel_script.py.log"
        ).read_text()
        assert "AssertionError: synthetic regression" in result.stderr
    elif mode == "deploy-file-incomplete":
        assert "0 tests/deploy/test_deploy_channel_script.py" in (root / "status").read_text()
        assert not (root / "logs/tests_deploy_test_deploy_channel_script.py.xml").exists()
        assert "incomplete" in result.stderr
    elif mode == "serial-failure":
        assert "1 host-sensitive" in (root / "status").read_text()
        assert "AssertionError: synthetic regression" in (root / "logs/host-sensitive.log").read_text()
        assert "AssertionError: synthetic regression" in result.stderr
    elif mode == "terminated":
        assert "143 tests/alpha" in (root / "status").read_text()
    elif mode == "unreported":
        assert "tests/alpha" not in (root / "status").read_text()
        assert "incomplete" in result.stderr
    elif mode in {"incomplete", "miscount"}:
        assert "0 tests/alpha" in (root / "status").read_text()
        assert "incomplete" in result.stderr
    upload = next(s for s in job["steps"] if s.get("name") == "Upload test log")
    assert upload["if"] == "always()"
    assert "${{ runner.temp }}/pytest-nightly-shards/" in upload["with"]["path"]


def test_nightly_suite_keeps_host_sensitive_tests_serial(tmp_path: Path) -> None:
    result, _population, job, step = _run_nightly_suite_workflow(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
    starts = [event for event in events if event["event"] == "start"]
    parallel = [event for event in starts if event["phase"] == "parallel"]
    assert 1 < max(event["active"] for event in parallel) <= 4
    serial = [event for event in starts if event["phase"] == "serial"]
    assert len(serial) == 1 and serial[0]["active"] == 0
    assert serial[0]["targets"] == ["tests/ops", "tests/invariants/test_vault_multiwriter.py"]
    first_serial = events.index(serial[0])
    assert all(event["phase"] == "parallel" for event in events[:first_serial])
    assert sum(event["event"] == "finish" for event in events[:first_serial]) == len(parallel)
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["include"] == [
        {"python-version": "3.12", "experimental": False},
        {"python-version": "3.13", "experimental": True},
    ]
    assert job["continue-on-error"] == step["continue-on-error"] == "${{ matrix.experimental }}"
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text()
    assert '- cron: "0 2 * * *"' in workflow and "workflow_dispatch:" in workflow


def test_pg_contracts_have_bounded_diagnostics() -> None:
    from app.ops.pg_acceptance import pytest_arguments

    arguments = pytest_arguments()
    assert '--timeout=120' in arguments and '--timeout-method=thread' in arguments
    assert '-vv' in arguments and '--durations=20' in arguments
    assert arguments[arguments.index('-m') + 1] == 'pg'
    assert "pytest-timeout==" in (REPO_ROOT / "dev-requirements.txt").read_text()


def test_ci_smoke_installs_acl_tools_for_linux_acl_fixture() -> None:
    job = _unit_tests_job_text()

    install_start = job.index("- name: Install Linux ACL tools")
    install_end = job.index("- name: Install dependencies", install_start)
    selected_test_run = job.index("- name: Run shared not-pg unit tests in process shards")
    install_step = job[install_start:install_end]

    assert "runs-on: ubuntu-latest" in job
    assert "steps.changes.outputs.code == 'true'" in install_step
    assert "sudo apt-get update" in install_step
    assert "sudo apt-get install -y acl" in install_step
    assert "continue-on-error" not in install_step
    assert install_start < selected_test_run


def test_pg_acceptance_handoff_preserves_required_coverage() -> None:
    from app.ops.pg_acceptance import NIGHTLY_SELECTORS, SELECTORS, pytest_arguments

    # Accepted PR coverage at the handoff. New selectors may add coverage;
    # neither a permanent test count nor another manual stage gate is added.
    accepted_targets = {
        'tests/index/test_provenance_stamp.py',
        'tests/index/test_identity_migration.py',
        'tests/indexer/test_outbox_roundtrip_pg.py',
        'tests/indexer/test_mixed_identity_detection.py',
        'tests/cli/test_index_doctor_mixed.py',
        'tests/cli/test_index_rebuild_cli.py',
        'tests/cli/test_index_reconcile.py',
        'tests/knowledge_acquisition/test_youtube_api_quota_pg.py',
        'tests/knowledge_acquisition/test_youtube_sync_state_pg.py',
        'tests/heimdal/test_entity_review_operation_journal.py',
        'tests/migrations/test_entity_review_operation_journal_schema_parity.py',
        'tests/migrations/test_file_state_adoption.py',
        'tests/migrations/test_objects_adoption.py',
        'tests/migrations/test_legacy_objects_fk_migration.py',
        'tests/migrations/test_store_schema_parity.py',
        'tests/migrations/test_multi_vault_ingest_projection_keys.py',
        'tests/store/test_membership_store.py',
        'tests/migrations/test_ingest_schema_parity.py',
        'tests/migrations/test_multi_vault_replay_projection_backfill.py',
        'tests/migrations/test_replay_schema_parity.py',
        'tests/migrations/test_mvr05a_residual_binding_keys.py',
        'tests/migrations/test_decisions_fk_set_null.py',
        'tests/integration/test_decisions_rebuild_from_log_only.py',
        'tests/integration/test_multi_vault_projection_isolation.py',
        'tests/episodes/test_episode_projection.py',
        'tests/integration/test_vault_sync_atomicity.py',
        'tests/ingest/test_vault_root_ingest_pg.py',
        'tests/invariants/test_retrieval_spine_invariants.py',
        'tests/jobs/test_decisions_export.py',
        'tests/jobs/test_decisions_projection_rebuild.py',
        'tests/jobs/test_multi_vault_decisions_rebuild_scope.py',
        'tests/jobs/test_calibration_projection_rebuild.py',
        'tests/integration/test_calibration_rebuild_from_log_only.py',
        'tests/stores/test_decisions_fk_semantics.py',
        'tests/stores/test_ensure_tables_assert_only.py',
        'tests/stores/test_multi_vault_store_reset_scope.py',
        'tests/stores/test_pg_truncate_reset.py',
        'tests/stores/test_pg_vector_index.py',
        'tests/stores/test_store_contract_pg.py',
        'tests/stores/test_vector_generation_identity.py',
        'tests/services/test_audit_writer.py',
        'tests/migrations/test_outbox_schema_parity.py',
        'tests/migrations/test_multi_vault_outbox_upgrade.py',
        'tests/services/test_multi_vault_outbox_dual_key_dedup.py',
        'tests/services/test_outbox_bootstrap_assert_only.py',
        'tests/instance/test_file_state_binding_key.py',
        'tests/services/test_vault_sync_binding_scope.py',
        'tests/integration/test_single_vault_compatibility.py',
        'tests/heimdal/test_trigger_ownership_pg.py',
        'tests/migrations/test_heimdal_raw_representation_migration.py',
        'tests/migrations/test_heimdal_raw_liveness_migration.py',
        'tests/builderops/test_owner_fact_producers.py',
        'tests/api/test_devui_owner_facts.py',
        'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_production_admission',
        'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_transaction_recovery',
        'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_concurrent_identical_start_replays_winner',
        'tests/builderops/test_control_plane_issue_delivery.py::test_issue_approval_concurrent_competing_start_preserves_conflict',
        'tests/builderops/test_control_plane_issue_delivery.py::test_host_candidate_versions_preserve_v1_v2_history',
        'tests/builderops/test_control_plane_issue_delivery.py::test_v3_live_start_refuses_unqualified_continuation',
        'tests/builderops/test_devui_runtime.py::test_managed_source_preserves_v3_candidate_binding',
        'tests/builderops/control_plane/test_postgres_transaction_kernel.py::test_initial_issue_import_preserves_transaction_lease_and_outbox_boundaries',
        'tests/builderops/test_issue_delivery_effect_executor.py',
        'tests/builderops/test_issue_delivery_operation.py',
        'tests/builderops/test_issue_delivery_readback.py',
        'tests/builderops/test_standalone_consumer_conformance.py',
    }
    assert accepted_targets.issubset(set(SELECTORS))
    assert all((REPO_ROOT / selector.split('::')[0]).is_file() for selector in SELECTORS)
    jobs = yaml.safe_load(_smoke_text())["jobs"]
    assert "pr-index-pg-contracts" not in jobs
    assert pytest_arguments()[pytest_arguments().index('-m') + 1] == 'pg'
    nightly = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    assert "python -m app.ops.pg_acceptance --ci --nightly" in nightly
    assert "tests/migrations/test_heimdal_raw_representation_migration.py" in NIGHTLY_SELECTORS
    assert "tests/heimdal/test_entity_review_operation_journal.py" in NIGHTLY_SELECTORS
    assert "tests/migrations/test_entity_review_operation_journal_schema_parity.py" in NIGHTLY_SELECTORS


def test_pr_ci_fetches_base_ref_before_diff_selection() -> None:
    job = _unit_tests_job_text()

    assert "fetch-depth: 0" in job
    # Full (non-shallow) base fetch: --depth=1 cuts the base tip's parents when
    # the base branch advances mid-run, breaking merge-base for diff selection.
    assert 'git fetch --no-tags origin "${{ github.base_ref }}"' in job
    assert "--depth=1" not in job


def test_optional_panel_llm_e2e_job_is_absent() -> None:
    workflow = _smoke_text()

    assert "panel_llm_e2e:" not in workflow
    assert "id: live-llm" not in workflow
    assert "steps.live-llm.outputs.enabled" not in workflow


def test_smoke_docker_runs_for_stable_targeting_pull_requests() -> None:
    workflow = _smoke_text()

    stable_or_post_merge = "github.event_name != 'pull_request' || github.base_ref == 'stable'"
    ordinary_pull_request = "github.event_name == 'pull_request' && github.base_ref != 'stable'"

    assert workflow.count(f"if: {stable_or_post_merge}") == 2
    assert f"if: {ordinary_pull_request}" in workflow
    assert "Docker smoke is skipped only for ordinary pull requests." in workflow
    assert "types: [opened, synchronize, reopened, edited]" in workflow


def test_vaultwide_panel_verifier_diagnostic_reads_runner_paths() -> None:
    # #4463: the failure diagnostic read the verifier script's workspace-relative
    # tmp/ defaults while the runner overrode LOG_PATH/REPORT_PATH to absolute
    # /tmp paths namespaced by run id and attempt. The two never matched, so a
    # failing gate printed the literal string "verifier artifacts" and nothing
    # else. Both sides must resolve from one declaration.
    step = _vaultwide_panel_verifier_step_text()

    log_declaration = (
        'VAULTWIDE_PANEL_LOG_PATH='
        '"/tmp/verify_vaultwide_panel.${GITHUB_RUN_ID}.${GITHUB_RUN_ATTEMPT}.log"'
    )
    report_declaration = (
        'VAULTWIDE_PANEL_REPORT_PATH='
        '"/tmp/verify_vaultwide_panel.${GITHUB_RUN_ID}.${GITHUB_RUN_ATTEMPT}.report"'
    )
    assert step.count(log_declaration) == 1, (
        "the verifier log path must be declared exactly once, keeping the "
        "run-id/attempt namespacing"
    )
    assert step.count(report_declaration) == 1, (
        "the verifier report path must be declared exactly once, keeping the "
        "run-id/attempt namespacing"
    )

    # The runner writes through the declared paths...
    assert 'LOG_PATH="$VAULTWIDE_PANEL_LOG_PATH"' in step
    assert 'REPORT_PATH="$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert "bash scripts/verify_vaultwide_panel.sh" in step

    # ...and the failure diagnostic reads the same declared paths back.
    assert 'cat "$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert 'tail -n 400 "$VAULTWIDE_PANEL_LOG_PATH"' in step
    assert 'grep -F "FAIL: " "$VAULTWIDE_PANEL_LOG_PATH"' in step

    # The stale workspace-relative glob must be gone; it never matched what the
    # runner wrote, which is exactly how the failure became unreadable.
    assert "tmp/verify_vaultwide_panel.*" not in step


def test_vaultwide_panel_verifier_diagnostic_fails_loud_on_missing_artifact() -> None:
    # #4463: every `ls` in the old diagnostic was swallowed by
    # `2>/dev/null || true`, so "no artifact found" and "artifact found and
    # empty" were indistinguishable from a healthy silent step.
    step = _vaultwide_panel_verifier_step_text()

    marker = "VAULTWIDE_PANEL_VERIFIER_ARTIFACT_MISSING"
    assert f'echo "{marker} report=$VAULTWIDE_PANEL_REPORT_PATH"' in step
    assert f'echo "{marker} log=$VAULTWIDE_PANEL_LOG_PATH"' in step

    # The artifact listing must not suppress its own stderr: the "No such file"
    # line names the path that was expected and is itself the evidence.
    listing = 'ls -l "$VAULTWIDE_PANEL_REPORT_PATH" "$VAULTWIDE_PANEL_LOG_PATH"'
    assert listing in step
    assert "2>/dev/null" not in step, (
        "the verifier diagnostic must not discard stderr; a swallowed error is "
        "how #4463 produced a red gate with no readable evidence"
    )


def test_vaultwide_panel_verifier_gate_remains_blocking() -> None:
    # #4463 is bounded to legibility: the gate itself keeps failing the job and
    # the verifier's assertions are untouched.
    workflow = _smoke_text()
    step = _vaultwide_panel_verifier_step_text()

    assert '- name: "CI gate: vaultwide panel verifier"' in workflow
    assert "continue-on-error" not in step

    # The verifier runs bare, so its exit status is the step's exit status, and
    # the cleanup trap re-raises the original status instead of masking it.
    assert "bash scripts/verify_vaultwide_panel.sh ||" not in step
    assert 'exit "$rc"' in step

    verifier = (REPO_ROOT / "scripts" / "verify_vaultwide_panel.sh").read_text(
        encoding="utf-8"
    )
    assert 'if [[ "$FAIL" -eq 0 ]]; then' in verifier
    assert verifier.rstrip().endswith('_log "SUMMARY PASS=$PASS FAIL=$FAIL"\nexit 1')


def test_dedicated_subsystem_workflows_have_path_filters_and_browser_runs_post_merge() -> None:
    browser = BROWSER_WORKFLOW.read_text(encoding="utf-8")
    image = IMAGE_WORKFLOW.read_text(encoding="utf-8")
    import_linter = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    browser_triggers = browser[: browser.index("concurrency:")]
    browser_pull_request = browser_triggers[
        browser_triggers.index("  pull_request:") : browser_triggers.index(
            "  workflow_dispatch:"
        )
    ]

    assert "paths:" in browser
    assert "branches: [main]" in browser
    assert "pull_request:" in browser_triggers
    assert "paths:" in browser_pull_request
    assert "'companion-ui/**'" in browser
    assert "'companion-ui/**'" in browser_pull_request
    assert "paths:" in image
    assert "'Dockerfile'" in image
    assert "paths:" in import_linter
    assert "'app/**'" in import_linter


def test_browser_runtime_supports_exact_ref_dispatch_with_pull_request_qualification() -> None:
    browser = _browser_text()
    triggers = browser[: browser.index("concurrency:")]
    checkout = _workflow_step(browser, "Checkout", "Setup Python")

    assert "push:" in triggers
    assert "branches: [main]" in triggers
    assert "workflow_dispatch:" in triggers
    assert "pull_request:" in triggers
    assert "ref: ${{ github.sha }}" in checkout

    job = _browser_job()
    job_without_steps = {key: value for key, value in job.items() if key != "steps"}
    assert "${{ runner." not in json.dumps(job_without_steps), (
        "runner context is unavailable while jobs.<job_id>.env is evaluated"
    )
    journey_env = _browser_step("Run exact-ref Overview browser journeys")["env"]
    manifest_env = _browser_step("Build exact-SHA Overview evidence manifest")["env"]
    expected_runner_temp_env = {
        "DEVUI_OVERVIEW_EVIDENCE_DIR": "${{ runner.temp }}/devui-overview",
        "DEVUI_OVERVIEW_JUNIT": "${{ runner.temp }}/devui-overview/junit.xml",
        "DEVUI_OVERVIEW_RECEIPT": (
            "${{ runner.temp }}/devui-overview/receipts/"
            "devui-overview-browser-accessibility.v1.json"
        ),
        "DEVUI_OVERVIEW_TRACE_DIR": "${{ runner.temp }}/devui-overview/traces",
        "DEVUI_OVERVIEW_SCREENSHOT_DIR": (
            "${{ runner.temp }}/devui-overview/screenshots"
        ),
    }
    assert journey_env == expected_runner_temp_env
    assert manifest_env == expected_runner_temp_env | {
        "DEVUI_OVERVIEW_MANIFEST": "${{ runner.temp }}/devui-overview/manifest.json",
        "DEVUI_OVERVIEW_JOURNEY_OUTCOME": "${{ steps.overview-journeys.outcome }}",
    }
    pr_journey_env = _browser_step("Run PR Overview browser regressions")["env"]
    assert pr_journey_env == {
        "DEVUI_OVERVIEW_PR_JUNIT": "${{ runner.temp }}/devui-overview-pr/junit.xml"
    }
    pr_upload = _browser_step("Upload PR Overview browser regression evidence")
    assert pr_upload["if"] == "${{ always() && github.event_name == 'pull_request' }}"
    assert pr_upload["with"]["path"] == "${{ runner.temp }}/devui-overview-pr/junit.xml"
    assert "${{ runner.temp }}" in _browser_step(
        "Upload exact-SHA Overview browser evidence"
    )["with"]["path"]
    for existing_blocking_module in (
        "tests/companion_ui/test_runtime_unavailable_browser.py",
        "tests/companion_ui/test_overlay_history_browser.py",
        "tests/companion_ui/test_cockpit_journeys.py",
    ):
        assert f"pytest -q {existing_blocking_module}" in browser


def test_browser_runtime_runs_focus_owner_fact_advisory(tmp_path, monkeypatch) -> None:
    trigger = yaml.safe_load(BROWSER_WORKFLOW.read_text(encoding="utf-8"))[True]
    for event in ("push", "pull_request"):
        assert "tests/builderops/focus_owner_facts_fixture.py" in trigger[event]["paths"]
    step = _browser_step("Run deterministic Focus owner-fact browser regressions")
    assert step.get("continue-on-error", False) is False
    assert "if" not in step and "--live-jev" not in step["run"]
    assert "python3 scripts/run_jev_browser_advisory.py" in step["run"]
    assert "--surface focus-owner-facts" in step["run"]
    from scripts import run_jev_browser_advisory as runner
    calls = []
    def observe(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runner.subprocess, "run", observe)
    assert runner._run_browser(tmp_path, "a" * 40, "focus-owner-facts") == 0
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-1] == "tests/companion_ui/test_focus_owner_facts_runtime.py"
    assert kwargs["env"]["COMPANION_UI_BROWSER_TESTS"] == "1"
    assert kwargs["env"]["DEVUI_MANAGED_EVIDENCE_DIR"] == str(tmp_path / "browser")
    assert kwargs["env"]["COMPANION_UI_JEV_OBSERVATIONS_DIR"] == str(tmp_path / "observations")
    assert kwargs["env"]["COMPANION_UI_JEV_SOURCE_SHA"] == "a" * 40
    evidence = _browser_step("Retain Focus owner-fact diagnostics")
    assert evidence["if"] == "always()" and evidence["uses"] == "actions/upload-artifact@v4"
    assert evidence["with"]["path"] == "${{ runner.temp }}/focus-owner-facts"
    assert evidence["with"]["if-no-files-found"] == "error"


def test_browser_runtime_runs_focus_evidence_state_advisory(tmp_path, monkeypatch) -> None:
    trigger = yaml.safe_load(BROWSER_WORKFLOW.read_text(encoding="utf-8"))[True]
    for event in ("push", "pull_request"):
        assert "tests/companion_ui/**" in trigger[event]["paths"]
    step = _browser_step("Run deterministic Focus evidence-state browser regressions")
    assert step.get("continue-on-error", False) is False
    assert "if" not in step and "--live-jev" not in step["run"]
    assert "--surface focus-evidence-state" in step["run"]
    upload = _browser_step("Retain Focus evidence-state diagnostics")
    assert upload["if"] == "always()" and upload["with"]["if-no-files-found"] == "error"
    from scripts import run_jev_browser_advisory as runner
    calls = []
    def observe(args, **kwargs):
        calls.append((args, kwargs)); return subprocess.CompletedProcess(args, 0)
    monkeypatch.setattr(runner.subprocess, "run", observe)
    assert runner._run_browser(tmp_path, "a" * 40, "focus-evidence-state") == 0
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[-1] == "tests/companion_ui/test_focus_evidence_state_runtime.py"
    assert kwargs["env"]["COMPANION_UI_BROWSER_TESTS"] == "1"
    assert kwargs["env"]["DEVUI_MANAGED_EVIDENCE_DIR"] == str(tmp_path / "browser")
    assert kwargs["env"]["COMPANION_UI_JEV_OBSERVATIONS_DIR"] == str(tmp_path / "observations")
    assert kwargs["env"]["COMPANION_UI_JEV_SOURCE_SHA"] == "a" * 40
    evidence = _browser_step("Retain Focus evidence-state diagnostics")
    assert evidence["if"] == "always()" and evidence["uses"] == "actions/upload-artifact@v4"
    assert evidence["with"]["path"] == "${{ runner.temp }}/focus-evidence-state"
    assert evidence["with"]["if-no-files-found"] == "error"


def test_browser_runtime_executes_vault_state_matrix_and_retains_diagnostics(
    tmp_path: Path, monkeypatch,
) -> None:
    step = _browser_step("Run deterministic Companion UI browser-runtime tests")
    assert step.get("continue-on-error", False) is False
    assert "if" not in step
    assert step["env"] == {
        "COMPANION_UI_STATE_EVIDENCE_DIR": "${{ runner.temp }}/vault-browser-state-matrix"
    }
    assert "pytest -q tests/companion_ui/test_runtime_unavailable_browser.py" in step["run"]
    assert "pytest -q tests/companion_ui/test_jev_advisory.py" in step["run"]
    assert "python3 scripts/run_jev_browser_advisory.py" in step["run"]
    assert '--output-dir "$COMPANION_UI_STATE_EVIDENCE_DIR/advisory"' in step["run"]
    assert "--live-jev" not in step["run"]

    # Exercise the runner's real pytest entrypoint rather than depending on the
    # command being inline in YAML. The subprocess is intercepted before launch.
    from scripts import run_jev_browser_advisory as runner

    invocations = []

    def observe(args, **kwargs):
        invocations.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(runner.subprocess, "run", observe)
    assert runner._run_browser(tmp_path, "a" * 40) == 0
    assert len(invocations) == 1
    args, kwargs = invocations[0]
    assert args == [
        runner.sys.executable, "-m", "pytest", "-q",
        f"--junitxml={tmp_path / 'junit.xml'}",
        "tests/companion_ui/test_vault_browser_state_runtime.py",
    ]
    assert kwargs["env"]["COMPANION_UI_BROWSER_TESTS"] == "1"
    assert kwargs["env"]["COMPANION_UI_STATE_EVIDENCE_DIR"] == str(tmp_path / "browser")
    assert kwargs["env"]["COMPANION_UI_JEV_OBSERVATIONS_DIR"] == str(tmp_path / "observations")
    assert kwargs["env"]["COMPANION_UI_JEV_SOURCE_SHA"] == "a" * 40

    evidence = _browser_step("Retain Vault Browser state-matrix diagnostics")
    assert evidence["if"] == "always()"
    assert evidence["uses"] == "actions/upload-artifact@v4"
    assert evidence["with"]["path"] == "${{ runner.temp }}/vault-browser-state-matrix"
    assert evidence["with"]["if-no-files-found"] == "error"


def test_browser_runtime_dispatch_requires_non_skipped_overview_journeys(
    tmp_path: Path,
) -> None:
    step = _workflow_step(
        _browser_text(),
        "Run exact-ref Overview browser journeys",
        "Run deterministic Companion UI browser-runtime tests",
    )

    assert "if: github.event_name == 'workflow_dispatch'" in step
    assert "set -euo pipefail" in step
    assert "test -f tests/companion_ui/test_devui_overview_journeys.py" in step
    assert "--junitxml=\"$DEVUI_OVERVIEW_JUNIT\"" in step
    assert "tests/companion_ui/test_devui_overview_journeys.py" in step
    assert "required Overview journey collection is empty" in step
    assert "required Overview journeys were skipped" in step
    assert "required Overview journey nodeids mismatch" in step
    assert "required Overview journey nodeids are duplicated" in step
    dispatch_command = _workflow_run("Run exact-ref Overview browser journeys").split(
        'python - "$DEVUI_OVERVIEW_JUNIT"', maxsplit=1
    )[0]
    pytest_command = dispatch_command.split("pytest -q", maxsplit=1)[1]
    assert "tests/companion_ui/test_devui_overview_journeys.py\n" not in pytest_command
    for nodeid in OVERVIEW_REQUIRED_NODEIDS:
        module, name = nodeid.split("::", maxsplit=1)
        assert module in step
        assert name in step
        assert nodeid in dispatch_command
    for nodeid in set(OVERVIEW_PR_REQUIRED_NODEIDS) - set(OVERVIEW_REQUIRED_NODEIDS):
        assert nodeid not in dispatch_command
    assert "\n        continue-on-error:" not in step

    junit_guard = _python_heredoc(
        _workflow_run("Run exact-ref Overview browser journeys")
    )
    junit_path = tmp_path / "junit.xml"

    def junit_case(nodeid: str, *, skipped: bool = False) -> str:
        module, name = nodeid.split("::", maxsplit=1)
        classname = module.removesuffix(".py").replace("/", ".")
        child = '<skipped message="not run"/>' if skipped else ""
        return f'<testcase classname="{classname}" name="{name}">{child}</testcase>'

    scenarios = (
        ((), (), False, "collection is empty"),
        (OVERVIEW_REQUIRED_NODEIDS[:-1], (), False, "nodeids mismatch"),
        (
            OVERVIEW_REQUIRED_NODEIDS[:-1]
            + (f"{OVERVIEW_JOURNEY_MODULE}::test_renamed_required_journey",),
            (),
            False,
            "nodeids mismatch",
        ),
        (
            OVERVIEW_REQUIRED_NODEIDS + (OVERVIEW_REQUIRED_NODEIDS[0],),
            (),
            False,
            "nodeids are duplicated",
        ),
        (
            OVERVIEW_REQUIRED_NODEIDS
            + (f"{OVERVIEW_JOURNEY_MODULE}::test_unmapped_extra_journey",),
            (),
            False,
            "nodeids mismatch",
        ),
        (
            OVERVIEW_REQUIRED_NODEIDS,
            (OVERVIEW_REQUIRED_NODEIDS[-1],),
            False,
            "journeys were skipped",
        ),
        (OVERVIEW_REQUIRED_NODEIDS, (), True, ""),
    )
    for nodeids, skipped_nodeids, should_pass, expected_error in scenarios:
        cases = "".join(
            junit_case(nodeid, skipped=nodeid in skipped_nodeids)
            for nodeid in nodeids
        )
        junit_path.write_text(
            "<testsuites><testsuite "
            f'tests="{len(nodeids)}" skipped="{len(skipped_nodeids)}" '
            f'failures="0" errors="0">{cases}</testsuite></testsuites>\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-", str(junit_path)],
            input=junit_guard,
            text=True,
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) is should_pass
        assert expected_error in result.stderr


def test_browser_runtime_pr_requires_non_skipped_overview_regressions(
    tmp_path: Path,
) -> None:
    step = _workflow_step(
        _browser_text(),
        "Run PR Overview browser regressions",
        "Run exact-ref Overview browser journeys",
    )

    assert "if: github.event_name == 'pull_request'" in step
    assert "set -euo pipefail" in step
    assert "test -f tests/companion_ui/test_devui_overview_journeys.py" in step
    assert '--junitxml="$DEVUI_OVERVIEW_PR_JUNIT"' in step
    assert "required PR Overview journey collection is empty" in step
    assert "required PR Overview journeys were skipped" in step
    assert "required PR Overview journey nodeids mismatch" in step
    assert "required PR Overview journey nodeids are duplicated" in step
    for nodeid in OVERVIEW_PR_REQUIRED_NODEIDS:
        module, name = nodeid.split("::", maxsplit=1)
        assert module in step
        assert name in step
    assert "failures or errors" in step
    assert "\n        continue-on-error:" not in step

    junit_guard = _python_heredoc(_workflow_run("Run PR Overview browser regressions"))
    junit_path = tmp_path / "junit.xml"

    def junit_case(nodeid: str, *, skipped: bool = False, failed: bool = False) -> str:
        module, name = nodeid.split("::", maxsplit=1)
        classname = module.removesuffix(".py").replace("/", ".")
        child = ""
        if skipped:
            child = '<skipped message="not run"/>'
        elif failed:
            child = '<failure message="failed"/>'
        return f'<testcase classname="{classname}" name="{name}">{child}</testcase>'

    scenarios = (
        ((), (), (), False, "collection is empty"),
        (OVERVIEW_PR_REQUIRED_NODEIDS[:-1], (), (), False, "nodeids mismatch"),
        (
            OVERVIEW_PR_REQUIRED_NODEIDS + (f"{OVERVIEW_JOURNEY_MODULE}::test_extra",),
            (),
            (),
            False,
            "nodeids mismatch",
        ),
        (
            OVERVIEW_PR_REQUIRED_NODEIDS + (OVERVIEW_PR_REQUIRED_NODEIDS[0],),
            (),
            (),
            False,
            "nodeids are duplicated",
        ),
        (
            OVERVIEW_PR_REQUIRED_NODEIDS,
            (OVERVIEW_PR_REQUIRED_NODEIDS[-1],),
            (),
            False,
            "journeys were skipped",
        ),
        (
            OVERVIEW_PR_REQUIRED_NODEIDS,
            (),
            (OVERVIEW_PR_REQUIRED_NODEIDS[-1],),
            False,
            "failures or errors",
        ),
        (OVERVIEW_PR_REQUIRED_NODEIDS, (), (), True, ""),
    )
    for nodeids, skipped_nodeids, failed_nodeids, should_pass, expected_error in scenarios:
        cases = "".join(
            junit_case(
                nodeid,
                skipped=nodeid in skipped_nodeids,
                failed=nodeid in failed_nodeids,
            )
            for nodeid in nodeids
        )
        failures = len(failed_nodeids)
        junit_path.write_text(
            "<testsuites><testsuite "
            f'tests="{len(nodeids)}" skipped="{len(skipped_nodeids)}" '
            f'failures="{failures}" errors="0">{cases}</testsuite></testsuites>\n',
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-", str(junit_path)],
            input=junit_guard,
            text=True,
            capture_output=True,
            check=False,
        )
        assert (result.returncode == 0) is should_pass
        assert expected_error in result.stderr


def test_browser_runtime_managed_inventory_covers_trust_frame_hostile_cases() -> None:
    step = _workflow_step(
        _browser_text(),
        "Run standalone managed Overview and Focus journeys",
        "Retain standalone managed browser evidence",
    )
    for action in (
        "trust_additional",
        "trust_substituted",
        "trust_moved",
        "trust_duplicated",
        "trust_editable",
        "trust_lookalike",
        "trust_provider_substituted",
        "trust_provider_reversed",
        "trust_provider_dropped",
        "trust_matrix_moved",
    ):
        for surface in (
            "overview-/devui/overview",
            "focus-/devui/focus?subject=github%3Aexample%2Ffixture%23501",
        ):
            assert (
                "test_managed_keyboard_proof_rejects_unexpected_interactive_action["
                f"{action}-{surface}]"
            ) in step


def test_browser_runtime_dispatch_uploads_exact_sha_overview_evidence(
    tmp_path: Path,
) -> None:
    browser = _browser_text()
    manifest = _workflow_step(
        browser,
        "Build exact-SHA Overview evidence manifest",
        "Upload exact-SHA Overview browser evidence",
    )
    upload = _workflow_step(browser, "Upload exact-SHA Overview browser evidence")

    assert '["git", "rev-parse", "HEAD"]' in manifest
    assert "GITHUB_SHA" in manifest
    assert 'missing.append("junit")' in manifest
    assert 'missing.append("receipt")' in manifest
    assert "path.stat().st_size > 0" in manifest
    assert "json.loads(receipt_path.read_text" in manifest
    for required_receipt_field in (
        "contract_version",
        "github_sha",
        "test_module",
        "required_nodeids",
        "journey_assertions",
        "fixture_versions",
        "token_sha256",
        "screenshots",
        "accessibility_results",
        "failures",
        "unresolved_visual_questions",
    ):
        assert f'"{required_receipt_field}"' in manifest
    assert "trace" in manifest
    assert "screenshot" in manifest
    assert "name: devui-overview-browser-exact-${{ github.sha }}" in upload
    assert "${{ runner.temp }}/devui-overview/junit.xml" in upload
    assert "${{ runner.temp }}/devui-overview/manifest.json" in upload
    assert "${{ runner.temp }}/devui-overview/receipts/**" in upload
    assert "${{ runner.temp }}/devui-overview/traces/**" in upload
    assert "${{ runner.temp }}/devui-overview/screenshots/**" in upload
    assert "if-no-files-found: error" in upload

    evidence_dir = tmp_path / "devui-overview"
    receipt_path = evidence_dir / "receipts" / "devui-overview-browser-accessibility.v1.json"
    trace_path = evidence_dir / "traces" / "trace.zip"
    screenshot_path = evidence_dir / "screenshots" / "overview.png"
    junit_path = evidence_dir / "junit.xml"
    for parent in (receipt_path.parent, trace_path.parent, screenshot_path.parent):
        parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_bytes(b"trace")
    screenshot_path.write_bytes(b"screenshot")

    def write_junit(nodeids: tuple[str, ...] = OVERVIEW_REQUIRED_NODEIDS) -> None:
        cases = []
        for nodeid in nodeids:
            module, name = nodeid.split("::", maxsplit=1)
            classname = module.removesuffix(".py").replace("/", ".")
            cases.append(f'<testcase classname="{classname}" name="{name}"/>')
        junit_path.write_text(
            "<testsuites><testsuite "
            f'tests="{len(nodeids)}" failures="0" errors="0" skipped="0">'
            + "".join(cases)
            + "</testsuite></testsuites>\n",
            encoding="utf-8",
        )

    write_junit()
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest_path = evidence_dir / "manifest.json"
    env = os.environ | {
        "DEVUI_OVERVIEW_EVIDENCE_DIR": str(evidence_dir),
        "DEVUI_OVERVIEW_JUNIT": str(junit_path),
        "DEVUI_OVERVIEW_RECEIPT": str(receipt_path),
        "DEVUI_OVERVIEW_TRACE_DIR": str(trace_path.parent),
        "DEVUI_OVERVIEW_SCREENSHOT_DIR": str(screenshot_path.parent),
        "DEVUI_OVERVIEW_MANIFEST": str(manifest_path),
        "DEVUI_OVERVIEW_JOURNEY_OUTCOME": "success",
        "GITHUB_REF": "refs/heads/codex/exact-ref-proof",
        "GITHUB_SHA": head_sha,
    }
    manifest_run = _workflow_run("Build exact-SHA Overview evidence manifest").replace(
        "python - <<'PY'", f'"{sys.executable}" - <<\'PY\'', 1
    )

    valid_receipt = {
        "contract_version": "devui-overview-browser-accessibility.v1",
        "github_sha": head_sha,
        "test_module": OVERVIEW_JOURNEY_MODULE,
        "required_nodeids": list(OVERVIEW_REQUIRED_NODEIDS),
        "journey_assertions": {
            nodeid: {
                "url_assertions": "passed",
                "network_assertions": "passed",
                "status_assertions": "passed",
                "page_errors": [],
            }
            for nodeid in OVERVIEW_REQUIRED_NODEIDS
        },
        "fixture_versions": {
            "connected-overview-focus": "v1",
            "hostile-source-state-matrix": "v1",
        },
        "token_sha256": (
            "7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1"
        ),
        "screenshots": ["screenshots/overview.png"],
        "accessibility_results": {
            "status": "passed",
            "checks": [
                "desktop",
                "narrow",
                "zoom-200",
                "keyboard",
                "screen-reader-name-focus-order",
                "print",
                "javascript-off",
            ],
        },
        "failures": [],
        "unresolved_visual_questions": [],
    }

    def run_manifest(receipt: dict, *, run_env: dict | None = None):
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return subprocess.run(
            ["bash", "-c", manifest_run],
            cwd=REPO_ROOT,
            env=run_env or env,
            text=True,
            capture_output=True,
            check=False,
        )

    result = run_manifest(valid_receipt)
    assert result.returncode == 0, result.stderr
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["artifact_name"] == f"devui-overview-browser-exact-{head_sha}"
    assert payload["checkout_sha"] == head_sha
    assert payload["github_sha"] == head_sha
    assert payload["missing_evidence"] == []
    assert payload["receipt_validation_errors"] == []
    assert payload["receipt"] == valid_receipt
    assert payload["required_nodeids"] == list(OVERVIEW_REQUIRED_NODEIDS)
    assert payload["executed_nodeids"] == list(OVERVIEW_REQUIRED_NODEIDS)
    assert payload["junit_node_results"] == {
        nodeid: {
            "collected": True,
            "executed": True,
            "passed": True,
            "skipped": False,
        }
        for nodeid in OVERVIEW_REQUIRED_NODEIDS
    }
    assert payload["junit_inventory_errors"] == []
    assert {item["path"] for item in payload["files"]} == {
        "junit.xml",
        "receipts/devui-overview-browser-accessibility.v1.json",
        "screenshots/overview.png",
        "traces/trace.zip",
    }

    invalid_receipts = (
        ({}, "missing keys="),
        (
            valid_receipt | {"contract_version": "foreign-receipt.v1"},
            "contract_version mismatch",
        ),
        (
            valid_receipt | {"github_sha": "0" * 40},
            "github_sha mismatch",
        ),
        (
            valid_receipt | {"test_module": "tests/companion_ui/test_other.py"},
            "test_module mismatch",
        ),
        (
            valid_receipt
            | {"required_nodeids": list(OVERVIEW_REQUIRED_NODEIDS[:-1])},
            "required_nodeids mismatch",
        ),
        (
            valid_receipt
            | {
                "required_nodeids": list(OVERVIEW_REQUIRED_NODEIDS)
                + [OVERVIEW_REQUIRED_NODEIDS[0]]
            },
            "required_nodeids mismatch",
        ),
        (
            valid_receipt
            | {
                "journey_assertions": {
                    **valid_receipt["journey_assertions"],
                    f"{OVERVIEW_JOURNEY_MODULE}::test_unmapped_extra_journey": {
                        "url_assertions": "passed",
                        "network_assertions": "passed",
                        "status_assertions": "passed",
                        "page_errors": [],
                    },
                }
            },
            "journey_assertions nodeids mismatch",
        ),
        (
            valid_receipt
            | {
                "journey_assertions": valid_receipt["journey_assertions"]
                | {
                    OVERVIEW_REQUIRED_NODEIDS[0]: {
                        "url_assertions": "passed",
                        "network_assertions": "passed",
                        "status_assertions": "passed",
                    }
                }
            },
            "journey_assertions fields mismatch",
        ),
        (
            valid_receipt
            | {
                "journey_assertions": valid_receipt["journey_assertions"]
                | {
                    OVERVIEW_REQUIRED_NODEIDS[0]: {
                        "url_assertions": "passed",
                        "network_assertions": "failed",
                        "status_assertions": "passed",
                        "page_errors": [],
                    }
                }
            },
            "journey_assertions must pass URL, network, and status",
        ),
        (
            valid_receipt
            | {
                "journey_assertions": valid_receipt["journey_assertions"]
                | {
                    OVERVIEW_REQUIRED_NODEIDS[0]: {
                        "url_assertions": "passed",
                        "network_assertions": "passed",
                        "status_assertions": "passed",
                        "page_errors": ["console error"],
                    }
                }
            },
            "journey_assertions must report no page errors",
        ),
        (
            valid_receipt | {"fixture_versions": {}},
            "fixture_versions must name the exact required fixtures",
        ),
        (
            valid_receipt | {"fixture_versions": {"foreign-fixture": "v1"}},
            "fixture_versions must name the exact required fixtures",
        ),
        (
            valid_receipt | {"token_sha256": "not-a-sha"},
            "token_sha256 must match the binding token source",
        ),
        (
            valid_receipt | {"token_sha256": "a" * 64},
            "token_sha256 must match the binding token source",
        ),
        (
            valid_receipt | {"screenshots": ["screenshots/foreign.png"]},
            "screenshots do not match archived evidence",
        ),
        (
            valid_receipt
            | {
                "accessibility_results": {
                    "status": "failed",
                    "checks": ["keyboard"],
                }
            },
            "accessibility_results must contain passed status",
        ),
        (
            valid_receipt
            | {
                "accessibility_results": {
                    "status": "passed",
                    "checks": ["keyboard"],
                }
            },
            "accessibility_results must contain passed status",
        ),
        (
            valid_receipt | {"failures": ["page error"]},
            "failures must be empty for successful evidence",
        ),
        (
            valid_receipt | {"unresolved_visual_questions": None},
            "unresolved_visual_questions must be a string list",
        ),
    )
    for invalid_receipt, expected_error in invalid_receipts:
        invalid_result = run_manifest(invalid_receipt)
        assert invalid_result.returncode != 0
        assert expected_error in invalid_result.stderr

    mismatch_result = run_manifest(
        valid_receipt,
        run_env=env | {"GITHUB_SHA": "0" * 40},
    )
    assert mismatch_result.returncode != 0
    assert "exact-ref mismatch" in mismatch_result.stderr

    write_junit(OVERVIEW_REQUIRED_NODEIDS[:-1])
    missing_nodeid_result = run_manifest(valid_receipt)
    assert missing_nodeid_result.returncode != 0
    assert "required Overview journey nodeids mismatch" in missing_nodeid_result.stderr
    write_junit()

    screenshot_path.unlink()
    missing_result = run_manifest(valid_receipt)
    assert missing_result.returncode != 0
    assert "screenshots do not match archived evidence" in missing_result.stderr


def test_browser_runtime_exact_ref_contract_is_owner_documented() -> None:
    strategy = (
        REPO_ROOT / "docs" / "development" / "TEST_STRATEGY_HOT_PATH.md"
    ).read_text(encoding="utf-8")
    normalized_strategy = " ".join(strategy.split())

    assert "#4836" in strategy
    assert "workflow_dispatch" in strategy
    assert ".github/workflows/browser-runtime.yml" in strategy
    assert "${{ github.sha }}" in strategy
    assert "ordinary PR unit CI does not provide" in normalized_strategy
    for receipt_contract_term in (
        "devui-overview-browser-accessibility.v1",
        "github_sha",
        "test-module identity",
        "fixture versions",
        "token_sha256",
        "screenshot list",
        "Accessibility results",
        "failures",
        "unresolved visual questions",
        "validated receipt",
    ):
        assert receipt_contract_term in normalized_strategy
    for exact_receipt_identity in (
        "connected-overview-focus",
        "hostile-source-state-matrix",
        "7d8cdd49f59061f895959159a08e82348e7e02eb8b8ba7426020a50c7fa915b1",
        "screen-reader name/focus order",
        "JavaScript-off",
    ):
        assert exact_receipt_identity in normalized_strategy
    for nodeid in OVERVIEW_REQUIRED_NODEIDS:
        assert nodeid in normalized_strategy
    for per_journey_dimension in (
        "required_nodeids",
        "journey_assertions",
        "URL assertions",
        "network assertions",
        "status assertions",
        "page errors",
    ):
        assert per_journey_dimension in normalized_strategy
    assert "Runner-temporary paths are declared only at step scope" in normalized_strategy


def test_legacy_smoke_workflow_is_retired_without_stale_references() -> None:
    retired = WORKFLOWS_DIR / "smoke.yml"

    # ci-smoke.yaml is the single PR-triggered smoke gate (#3891).
    assert not retired.exists(), "legacy smoke.yml must stay deleted"

    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "smoke.yml" not in text, (
            f"{workflow_path.name} references the retired smoke.yml workflow"
        )

    audit_script = (REPO_ROOT / "tools" / "audit_smoke.sh").read_text(encoding="utf-8")
    assert ".github/workflows/smoke.yml" not in audit_script, (
        "tools/audit_smoke.sh must not require the retired smoke.yml workflow"
    )
    assert ".github/workflows/ci-smoke.yaml" in audit_script, (
        "tools/audit_smoke.sh must require the consolidated ci-smoke.yaml gate"
    )


def test_ci_smoke_keeps_legacy_skills_lint_when_consolidating_smoke() -> None:
    workflow = _smoke_text()

    assert "cache: pip" in workflow
    assert "python3 scripts/lint_skills_consistency.py" in workflow
    assert "docs/DIAGRAMS.md must not contain literal" in workflow
    assert "Mermaid fences must not be indented" in workflow
    assert "Forbidden math fence syntax inside table detected" in workflow


def test_dispatch_only_ci_workflows_are_retired_without_stale_references() -> None:
    # ci.yml and ci-lite.yml were dead workflow_dispatch-era workflows whose
    # live gates moved into ci-smoke.yaml / integration-nightly.yaml (#3892).
    assert not (WORKFLOWS_DIR / "ci.yml").exists(), "ci.yml must stay deleted"
    assert not (WORKFLOWS_DIR / "ci-lite.yml").exists(), "ci-lite.yml must stay deleted"

    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "ci-lite" not in text, (
            f"{workflow_path.name} references the retired ci-lite.yml workflow"
        )

    failure_context = FAILURE_CONTEXT_WORKFLOW.read_text(encoding="utf-8")
    assert "\n      - CI\n" not in failure_context, (
        "pr-ci-failure-context.yml must not watch the retired CI workflow"
    )
    assert "- CI Smoke" in failure_context


def test_pr_ci_runs_each_owned_contract_check_once() -> None:
    """PR and non-PR graphs each have one owner for the import check."""
    smoke = yaml.safe_load(_smoke_text())
    import_linter = yaml.safe_load(
        IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    )

    import_workflow = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    assert import_workflow.count("lint-imports --config importlinter.ini") == 1
    smoke_import_steps = [
        step
        for step in smoke["jobs"]["contract-validation"]["steps"]
        if "lint-imports --config importlinter.ini" in step.get("run", "")
    ]
    assert len(smoke_import_steps) == 1
    assert smoke_import_steps[0]["if"] == "github.event_name != 'pull_request'"

    smoke_runs = "\n".join(
        step.get("run", "")
        for job in smoke["jobs"].values()
        for step in job.get("steps", [])
    )
    assert "pytest -c /dev/null tests/architecture/test_pr_hot_path_governance.py" not in smoke_runs

    # PyYAML 1.1 parses the YAML 1.2 `on` key as boolean True.
    trigger = import_linter[True]
    assert "pull_request" in trigger
    assert "workflow_dispatch" in trigger
    assert set(trigger["pull_request"]["paths"]) >= {
        "app/**",
        "importlinter.ini",
        ".github/workflows/import-linter.yaml",
        ".github/workflows/ci-smoke.yaml",
    }


def test_deduplicated_contract_checks_preserve_failure_and_trigger_coverage() -> None:
    smoke = yaml.safe_load(_smoke_text())
    import_workflow = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")
    contract_job = _contract_job_text()
    unit_job = _unit_tests_job_text()

    # The dedicated import-boundary job remains blocking and covers the same
    # PR surfaces that previously reached the duplicate CI Smoke invocation.
    assert "continue-on-error" not in import_workflow
    assert "lint-imports --config importlinter.ini" in import_workflow
    smoke_import_steps = [
        step
        for step in smoke["jobs"]["contract-validation"]["steps"]
        if "lint-imports --config importlinter.ini" in step.get("run", "")
    ]
    assert len(smoke_import_steps) == 1
    assert smoke_import_steps[0]["if"] == "github.event_name != 'pull_request'"
    assert "'app/**'" in import_workflow
    assert "'importlinter.ini'" in import_workflow
    assert "'.github/workflows/ci-smoke.yaml'" in import_workflow

    # CI Smoke keeps its unique contract gates and owns import-linter only for
    # non-PR events, where the dedicated pull_request workflow does not run.
    assert "openapi:" in contract_job
    assert "yaml_json:" in contract_job
    assert "import-linter" in contract_job
    assert "lint-imports --config importlinter.ini" in contract_job

    # The selector-owned governance test remains a real failure-propagating
    # pytest target in the scoped Unit tests lane.
    assert "tests/architecture" in unit_job
    assert "Run scoped not-pg unit tests" in unit_job
    assert "pytest ${{ steps.select-tests.outputs.pytest_args }} -vv --tb=short --durations=20" in unit_job


def test_ci_smoke_validates_openapi_and_contract_surfaces() -> None:
    job = _contract_job_text()

    assert "python -m openapi_spec_validator api/openapi.yaml" in job
    assert "@redocly/cli" in job
    assert "'app/api/**'" in job
    assert "'api/**'" in job
    assert "events/asyncapi.yaml" in job
    assert "yamllint -c .yamllint.yml ." in job
    assert "jsonschema" in job


def test_ci_smoke_new_gates_skip_docs_only_pull_requests() -> None:
    unit_job = _unit_tests_job_text()
    contract_job = _contract_job_text()

    assert "uses: dorny/paths-filter@v3" in unit_job
    assert "steps.changes.outputs.code == 'true'" in unit_job

    assert "uses: dorny/paths-filter@v3" in contract_job
    assert "steps.changes.outputs.openapi == 'true'" in contract_job
    assert "steps.changes.outputs.yaml_json == 'true'" in contract_job


def test_integration_nightly_keeps_k6_and_pg_contract_lanes_nightly_only() -> None:
    nightly = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "k6-search:" in nightly
    assert "k6 run scripts/k6_search.js" in nightly
    assert "pg-contracts:" in nightly
    # Nightly schedule stays unchanged (out of scope for #3892).
    assert '- cron: "0 2 * * *"' in nightly
    # k6 must not leak onto the PR path.
    assert "k6 run" not in _smoke_text()


def test_k6_search_uses_migrated_canonical_fixture() -> None:
    workflow = yaml.safe_load(INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["k6-search"]
    steps = {step.get("name"): step for step in job["steps"] if "name" in step}
    names = list(steps)

    assert job["services"]["db"]["image"] == "pgvector/pgvector:pg16"
    assert job["services"]["db"]["env"]["POSTGRES_DB"] == "k6_search"
    assert job["env"]["STORE_BACKEND"] == "pg"
    assert job["env"]["EMBED_PROFILE"] == "deterministic"
    assert names.index("Prepare pgvector extension") < names.index("Apply migrations")
    assert names.index("Apply migrations") < names.index("Bootstrap database")
    assert names.index("Bootstrap database") < names.index("Seed search fixture")
    assert "scripts.k6_search_fixture prepare-extension" in steps["Prepare pgvector extension"]["run"]
    assert "alembic upgrade head" in steps["Apply migrations"]["run"]
    assert "bootstrap()" in steps["Bootstrap database"]["run"]
    assert "scripts.k6_search_fixture seed" in steps["Seed search fixture"]["run"]
    assert "objects_embeddings" not in str(job)
    assert "STORE_SCHEMA_AUTOCREATE" not in str(job)
    assert job["env"]["K6_FIXTURE_MANIFEST"] == "/tmp/k6-search.json"
    for name in ("Seed search fixture", "Wait for API readiness", "Warm up search endpoint"):
        assert '"$K6_FIXTURE_MANIFEST"' in steps[name]["run"]
    assert "scripts.k6_search_fixture probe" in steps["Wait for API readiness"]["run"]
    assert "--wait-seconds 90" in steps["Wait for API readiness"]["run"]
    assert "scripts.k6_search_fixture probe" in steps["Warm up search endpoint"]["run"]
    assert "k6 run scripts/k6_search.js" in steps["Run k6 smoke"]["run"]
    assert "workflow_dispatch" in INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")


def test_architecture_ci_is_stripped_to_unique_dispatch_only_jobs() -> None:
    text = ARCHITECTURE_CI_WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch" in text
    assert "pull_request" not in text
    assert "qas-010:" in text
    assert "docs-guard:" in text
    # Absorbed gates must not linger here as dead duplicate steps.
    assert "lint-imports" not in text
    assert "openapi_spec_validator" not in text
    assert "@redocly" not in text
    assert "@asyncapi/cli" not in text
    assert "yamllint" not in text
    assert "k6 run" not in text


def test_no_workflow_silently_ignores_alembic_upgrade_failures() -> None:
    for workflow_path in sorted(WORKFLOWS_DIR.iterdir()):
        if not workflow_path.is_file():
            continue
        text = workflow_path.read_text(encoding="utf-8")
        assert "alembic upgrade head || true" not in text, (
            f"{workflow_path.name} masks migration failures with '|| true'"
        )


def test_integration_nightly_installs_required_media_libraries() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "Install media build dependencies" in workflow
    assert "libavformat-dev" in workflow
    assert "libavcodec-dev" in workflow
    assert "pkg-config" in workflow


def test_integration_nightly_uses_collision_safe_test_imports() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    full_suite = workflow[workflow.index("full-suite:") : workflow.index("pg-contracts:")]
    assert "--import-mode=importlib" in full_suite
    assert "-c /dev/null" not in full_suite
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD" not in full_suite
    test_step = full_suite[full_suite.index("Full test suite (memory, not pg)") :]
    assert "continue-on-error: ${{ matrix.experimental }}" in test_step


def test_integration_nightly_prepares_pgvector_before_migrations() -> None:
    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")

    assert "image: pgvector/pgvector:pg16" in workflow
    extension = workflow.index("CREATE EXTENSION IF NOT EXISTS vector")
    migration = workflow.index("alembic upgrade head")
    assert extension < migration


def test_integration_nightly_runs_yss01_pg_contract_targets() -> None:
    from app.ops.pg_acceptance import NIGHTLY_SELECTORS

    workflow = INTEGRATION_NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    pg_contracts = workflow[
        workflow.index("pg-contracts:") : workflow.index("  k6-search:")
    ]

    assert "python -m app.ops.pg_acceptance --ci --nightly" in pg_contracts
    assert "tests/knowledge_acquisition/test_source_registry_pg.py::test_pg_backend_contract" in NIGHTLY_SELECTORS
    assert (
        "tests/migrations/test_yss01_source_registry_schema_parity.py::"
        "test_yss01_migration_bootstrap_parity_and_legacy_repair"
    ) in NIGHTLY_SELECTORS


@pytest.mark.parametrize("change", ["missing", "duplicate", "foreign", "node"])
def test_scoped_ops_execution_rejects_incomplete_or_nonmodule_inventory(change):
    from scripts.run_scoped_test_partitions import validate_execution_units

    files = sorted(str(path.relative_to(REPO_ROOT)) for path in (REPO_ROOT / "tests/ops").rglob("*.py")
                   if path.name.startswith("test_") or path.name.endswith("_test.py"))
    assert validate_execution_units([files], ["tests/ops"]) == (tuple(files),)
    if change == "missing":
        files.pop()
    elif change == "duplicate":
        files.append(files[0])
    elif change == "foreign":
        files.append("tests/scripts/test_select_pr_tests.py")
    else:
        files[0] += "::test_one"
    with pytest.raises(ValueError):
        validate_execution_units([files], ["tests/ops"])
