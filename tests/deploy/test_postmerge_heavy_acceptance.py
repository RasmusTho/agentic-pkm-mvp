from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ops import heavy_acceptance as heavy
from app.ops import heavy_acceptance_runner as runner_module
from app.ops import postgres_deploy_linux as linux
from app.ops.heavy_acceptance_runner import HeavyAcceptanceRunner

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
OPERATION = str(uuid4())
ROOT = Path(__file__).resolve().parents[2]
SELECTOR_NAME = "select_pr_tests" + ".py"
SELECTOR_MARKER = (
    "not pg and not alpha_llm and not alpha_llm_live and not panel_llm_e2e "
    "and not eval and not browser_runtime and not human_uat and not uat_integrated_runtime"
)


def _summary(**overrides):
    summary = {
        **heavy.identity(SHA, DIGEST, "test", OPERATION),
        "targets": ["tests/deploy"],
        "exit_status": 0,
        "failures": [],
        "report_hash": "0" * 64,
        "selected": 500,
        "passed": 490,
        "failed": 0,
        "skipped": 10,
        "docker_skipped": 0,
    }
    return {**summary, **overrides}


def _expected():
    return heavy.identity(SHA, DIGEST, "test", OPERATION)


def _partition_tree(tmp_path, file_count=6):
    work = tmp_path / "partition-work"
    (work / "scripts").mkdir(parents=True)
    (work / "tests" / "deploy").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "__init__.py", work / "scripts" / "__init__.py")
    (work / "scripts" / SELECTOR_NAME).write_text(
        "HEAVY_PR_DEFERRED_TARGETS = {'tests/deploy': ()}\n"
        f"PR_MARKER_EXPRESSION = {SELECTOR_MARKER!r}\n"
    )
    for helper in ("plan_full_suite_node_shards.py", "run_scoped_test_partitions.py"):
        shutil.copy2(ROOT / "scripts" / helper, work / "scripts" / helper)
    (work / "tox.ini").write_text("[pytest]\nmarkers =\n    pg: pg\n")
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").write_text(
        "def test_rollback_dry_run_without_sha_parses_flag_and_skips_writes(): pass\n"
        "def test_rollback_with_explicit_sha_still_allows_flags(): pass\n"
    )
    for index in range(file_count - 1):
        (work / "tests" / "deploy" / f"test_extra_{index}.py").write_text(
            f"def test_extra_{index}(): pass\n"
        )
    return work


def _leaky_test_source(pid_file: Path, *, during_collection: bool = False) -> str:
    """The descendant reports its own PID; the parent must observe liveness."""

    child = (
        "from pathlib import Path; import os, time; "
        f"Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(30)"
    )
    imports = "import subprocess\nimport sys\nimport time\nfrom pathlib import Path\n"
    launch = (
        f"subprocess.Popen([sys.executable, '-c', {child!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "deadline = time.monotonic() + 5\n"
        f"while not Path({str(pid_file)!r}).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        f"assert Path({str(pid_file)!r}).exists()\n"
    )
    if during_collection:
        return imports + launch + "def test_leaky_worker(): pass\n"
    return imports + "def test_leaky_worker():\n" + "".join(
        "    " + line + "\n" for line in launch.splitlines()
    )


def test_heavy_profile_uses_exact_candidate_selector_without_baked_ci_imports():
    """The production loader must register its real dataclass module first."""
    import importlib

    importlib.import_module("scripts.select_pr_tests")
    module = heavy._load_selector(ROOT)

    assert module.Selection.__module__ == module.__name__
    assert sys.modules[module.__name__] is module
    selection = module.Selection(False, (), ("tests/deploy",), "regression")
    assert selection.targets == ("tests/deploy",)


def test_heavy_profile_binds_candidate_partition_helpers(tmp_path, monkeypatch):
    import types

    work = _partition_tree(tmp_path, file_count=1)
    foreign_package = types.ModuleType("scripts")
    foreign_package.__path__ = [str(tmp_path / "foreign-scripts")]
    foreign_planner = types.ModuleType("scripts.plan_full_suite_node_shards")
    monkeypatch.setitem(sys.modules, "scripts", foreign_package)
    monkeypatch.setitem(sys.modules, "scripts.plan_full_suite_node_shards", foreign_planner)
    tools = heavy._load_partition_tools(work)
    assert (
        Path(tools.__file__).resolve() == (work / "scripts/run_scoped_test_partitions.py").resolve()
    )
    assert (
        Path(tools.plan_node_units.__code__.co_filename).resolve()
        == (work / "scripts/plan_full_suite_node_shards.py").resolve()
    )


def test_heavy_profile_partitions_deploy_nodes_exactly_once_with_shared_groups(tmp_path):
    work = _partition_tree(tmp_path)
    deadline = time.monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    partitions = heavy._partition_targets(work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline)
    expected_files = {node.split("::", 1)[0] for node in nodes}
    actual_files = {target.split("::", 1)[0] for partition in partitions for target in partition}
    assert len(partitions) <= heavy.MAX_WORKERS
    assert actual_files == expected_files
    assert (
        sum(
            any(
                target.split("::", 1)[0] == "tests/deploy/test_deploy_channel_script.py"
                for target in partition
            )
            for partition in partitions
        )
        == 1
    )


def test_heavy_profile_aggregates_two_node_outcomes_and_report_hash(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    aggregate = heavy._run_partitions(
        {**_expected()},
        work,
        SELECTOR_MARKER,
        ("tests/deploy",),
        nodes,
        deadline,
    )
    expected_hash = hashlib.sha256(
        json.dumps([sorted(nodes), []], separators=(",", ":")).encode()
    ).hexdigest()
    assert aggregate["selected"] == len(nodes) == 2
    assert aggregate["passed"] == 2
    assert aggregate["failed"] == aggregate["skipped"] == 0
    assert aggregate["report_hash"] == expected_hash


def test_heavy_profile_rejects_incomplete_duplicate_and_foreign_worker_results(
    tmp_path, monkeypatch
):
    work = _partition_tree(tmp_path, file_count=1)
    test_file = work / "tests" / "deploy" / "test_strict_worker_results.py"
    test_file.write_text(
        "import pytest\n"
        "def test_pass(): pass\n"
        "@pytest.mark.xfail(reason='ordinary call failure')\n"
        "def test_expected_failure(): assert False\n"
    )
    result = tmp_path / "worker.json"
    tools = heavy._load_partition_tools(work)
    with pytest.raises(heavy.HeavyAcceptanceError) as missing:
        heavy._read_worker_result(result, _expected(), (), partition_tools=tools)
    assert missing.value.reason == "heavy_worker_result_missing"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/test_strict_worker_results.py"],
        result,
    )
    payload = json.loads(result.read_text())
    nodes = tuple(payload["nodes"])
    parsed, _ = heavy._read_worker_result(
        result, _expected(), nodes, partition_tools=tools
    )
    assert parsed["selected"] == 2 and parsed["passed"] == 1
    with pytest.raises(heavy.HeavyAcceptanceError):
        heavy._read_worker_result(
            result, _expected(), ("tests/deploy/foreign.py::test_foreign",),
            partition_tools=tools,
        )
    phases = payload["phase_results"]
    terminal = payload["terminal_results"]
    corruptions = (
        {**payload, "nodes": [nodes[0], nodes[0]]},
        {**payload, "phase_results": phases[:-1]},
        {**payload, "phase_results": [*phases, phases[0]]},
        {**payload, "phase_results": [
            {**phases[0], "nodeid": "tests/deploy/foreign.py::test_foreign"}, *phases[1:]
        ]},
        {**payload, "phase_results": [{**phases[0], "docker_skipped": True}, *phases[1:]]},
        {**payload, "terminal_results": terminal[:-1]},
        {**payload, "terminal_results": [terminal[0], terminal[0]]},
        {**payload, "terminal_results": [
            f"{nodes[0]} UNKNOWN", *terminal[1:]
        ]},
        {**payload, "terminal_results": [
            "tests/deploy/foreign.py::test_foreign PASSED", *terminal[1:]
        ]},
        {**payload, "summary": {**payload["summary"], "report_hash": "1" * 64}},
        {**payload, "summary": {**payload["summary"], "source_sha": "c" * 40}},
        {**payload, "summary": {**payload["summary"], "targets": ["tests/ops"]}},
        {**payload, "passed_nodes": [nodes[0], nodes[0]]},
        {key: value for key, value in payload.items() if key != "phase_results"},
    )
    for corrupt in corruptions:
        result.write_text(json.dumps(corrupt))
        with pytest.raises(heavy.HeavyAcceptanceError):
            heavy._read_worker_result(
                result, _expected(), nodes, partition_tools=tools
            )

    # Actual ordinary call-XFAIL reports cannot authenticate a forged passed1.
    xfailed = next(node for node in nodes if node.endswith("::test_expected_failure"))
    xfail_phases = [phase for phase in phases if phase["nodeid"] == xfailed]
    assert [(phase["when"], phase["outcome"], phase["xfail"])
            for phase in xfail_phases] == [
        ("setup", "passed", False), ("call", "skipped", True),
        ("teardown", "passed", False),
    ]
    forged = {
        **payload,
        "nodes": [xfailed],
        "passed_nodes": [xfailed],
        "failed_nodes": [],
        "skipped_nodes": [],
        "phase_results": xfail_phases,
        "terminal_results": [f"{xfailed} XFAIL"],
        "summary": {
            **payload["summary"], "selected": 1, "passed": 1,
            "report_hash": hashlib.sha256(
                json.dumps([[xfailed], []], separators=(",", ":")).encode()
            ).hexdigest(),
        },
    }
    assert heavy.classify(forged["summary"], _expected())["result"] == "passed"
    result.write_text(json.dumps(forged))
    with pytest.raises(heavy.HeavyAcceptanceError):
        heavy._read_worker_result(
            result, _expected(), (xfailed,), partition_tools=tools
        )


def test_heavy_profile_preserves_bounded_failure_projection_for_planned_long_ids(
    tmp_path, monkeypatch
):
    work = _partition_tree(tmp_path, file_count=1)
    test_file = work / "tests" / "deploy" / "test_long_worker_result.py"
    long_id = "space " + ("x" * 220) + " suffix"
    test_file.write_text(
        "import pytest\n"
        f"@pytest.mark.parametrize('value', [False], ids=[{long_id!r}])\n"
        "def test_long_failure(value): assert value\n"
    )
    result = tmp_path / "long-failure.json"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/test_long_worker_result.py"],
        result,
    )
    payload = json.loads(result.read_text())
    node, = payload["nodes"]
    assert len(node) > heavy.MAX_NODEID and " " in node
    parsed, _ = heavy._read_worker_result(
        result, _expected(), (node,), partition_tools=heavy._load_partition_tools(work)
    )
    assert parsed["failures"] == [node[: heavy.MAX_NODEID]]
    assert parsed["report_hash"] == hashlib.sha256(
        json.dumps([[], [node]], separators=(",", ":")).encode()
    ).hexdigest()
    assert heavy.classify(parsed, _expected())["result"] == "failed"


def test_heavy_profile_aggregates_spaced_and_long_node_ids(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    test_file = work / "tests" / "deploy" / "test_spaced_worker_ids.py"
    ids = ["with spaces", "long " + ("x" * 220)]
    test_file.write_text(
        "import pytest\n"
        f"@pytest.mark.parametrize('value', [True, True], ids={ids!r})\n"
        "def test_parameter(value): assert value\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    assert any(" " in node for node in nodes)
    assert any(len(node) > heavy.MAX_NODEID for node in nodes)
    aggregate = heavy._run_partitions(
        _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
    )
    assert aggregate["selected"] == aggregate["passed"] == len(nodes) == 4
    assert aggregate["report_hash"] == hashlib.sha256(
        json.dumps([sorted(nodes), []], separators=(",", ":")).encode()
    ).hexdigest()
    assert heavy.classify(aggregate, _expected())["result"] == "passed"


@pytest.mark.parametrize("reported_status", [0, -1], ids=["ordinary", "nonzero-metadata"])
def test_heavy_profile_aggregates_pass_and_xfail_only_partitions(
    tmp_path, monkeypatch, reported_status
):
    work = _partition_tree(tmp_path, file_count=1)
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").unlink()
    (work / "tests" / "deploy" / "test_pass_partition.py").write_text(
        "def test_pass(): pass\n"
    )
    (work / "tests" / "deploy" / "test_xfail_partition.py").write_text(
        "import pytest\n@pytest.mark.xfail(reason='expected')\n"
        "def test_expected_failure(): assert False\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    assert len(heavy._partition_targets(
        work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
    )) == 2
    real_reader = heavy._read_worker_result
    read_count = 0

    def reader(path, *args, **kwargs):
        nonlocal read_count
        if reported_status != 0 and read_count == 0:
            payload = json.loads(path.read_text())
            payload["summary"]["exit_status"] = reported_status
            path.write_text(json.dumps(payload))
        read_count += 1
        return real_reader(path, *args, **kwargs)

    monkeypatch.setattr(heavy, "_read_worker_result", reader)
    aggregate = heavy._run_partitions(
        _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
    )
    passed = [node for node in nodes if node.endswith("::test_pass")]
    assert (aggregate["selected"], aggregate["passed"], aggregate["failed"],
            aggregate["skipped"]) == (2, 1, 0, 0)
    assert aggregate["report_hash"] == hashlib.sha256(
        json.dumps([passed, []], separators=(",", ":")).encode()
    ).hexdigest()
    assert read_count == 2
    assert heavy.classify(aggregate, _expected())["result"] == (
        "passed" if reported_status == 0 else "failed"
    )


@pytest.mark.parametrize("entrypoint", ["collection", "worker"])
def test_heavy_profile_enforces_deadline_watchdog_and_owned_child_cleanup(
    tmp_path, monkeypatch, entrypoint
):
    work = _partition_tree(tmp_path, file_count=1)
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").unlink()
    slow = (
        "import time\ntime.sleep(30)\ndef test_slow(): pass\n"
        if entrypoint == "collection"
        else "import time\ndef test_slow(): time.sleep(30)\n"
    )
    (work / "tests" / "deploy" / "test_slow.py").write_text(slow)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    nodes = ()
    if entrypoint == "worker":
        nodes = heavy._collect_nodes(
            work, SELECTOR_MARKER, "tests/deploy", time.monotonic() + 30
        )
    real_popen = subprocess.Popen
    real_cleanup = heavy._cleanup_owned_process
    owned = []

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    try:
        deadline = time.monotonic() + 0.5
        with pytest.raises(heavy.HeavyAcceptanceError) as error:
            if entrypoint == "collection":
                heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
            else:
                heavy._run_partitions(
                    _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
                )
        assert error.value.reason == "heavy_deadline_exceeded"
        assert len(owned) == 1
        for process in owned:
            assert process.poll() is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
    finally:
        for process in owned:
            real_cleanup(process)


def test_heavy_profile_cleans_exited_leader_and_descendant_when_peer_times_out(
    tmp_path, monkeypatch
):
    work = _partition_tree(tmp_path, file_count=1)
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").unlink()
    descendant_pid = tmp_path / "descendant.pid"
    peer_started = tmp_path / "peer.pid"
    (work / "tests" / "deploy" / "test_exited.py").write_text(
        _leaky_test_source(descendant_pid)
    )
    (work / "tests" / "deploy" / "test_slow_peer.py").write_text(
        "import os, time\nfrom pathlib import Path\n"
        "def test_slow_peer():\n"
        f"    Path({str(peer_started)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(30)\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    real_monotonic = time.monotonic
    deadline = real_monotonic() + 10
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    assert heavy._partition_targets(
        work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
    ) == (("tests/deploy/test_exited.py",), ("tests/deploy/test_slow_peer.py",))
    real_popen = subprocess.Popen
    real_cleanup = heavy._cleanup_owned_process
    owned = []
    survivor = real_popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    posture_verified = False
    posture_limit = real_monotonic() + 5

    def clock():
        nonlocal posture_verified
        if posture_verified:
            return deadline + 1
        if (
            len(owned) == 2 and owned[0].poll() is not None
            and descendant_pid.exists() and peer_started.exists()
        ):
            child = int(descendant_pid.read_text())
            os.kill(child, 0)
            assert os.getpgid(child) == owned[0].pid
            assert int(peer_started.read_text()) == owned[1].pid
            assert owned[1].poll() is None
            posture_verified = True
            return deadline + 1
        assert real_monotonic() < posture_limit, "real exited-leader posture not reached"
        return real_monotonic()

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    monkeypatch.setattr(heavy, "time", SimpleNamespace(monotonic=clock, sleep=time.sleep))
    try:
        with pytest.raises(heavy.HeavyAcceptanceError) as error:
            heavy._run_partitions(
                _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
            )
        assert error.value.reason == "heavy_deadline_exceeded"
        assert posture_verified and len(owned) == 2
        for process in owned:
            assert process.poll() is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
        assert survivor.poll() is None
    finally:
        for process in owned:
            real_cleanup(process)
        survivor.terminate()
        survivor.wait(timeout=2)


@pytest.mark.parametrize("during_collection", [False, True], ids=["worker", "collection"])
def test_heavy_profile_cleans_descendant_after_nominal_success(
    tmp_path, monkeypatch, during_collection
):
    work = _partition_tree(tmp_path, file_count=1)
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").unlink()
    descendant_pid = tmp_path / "nominal-descendant.pid"
    test_file = work / "tests" / "deploy" / "test_nominal.py"
    test_file.write_text(
        _leaky_test_source(descendant_pid, during_collection=during_collection)
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 10
    nodes = ()
    if not during_collection:
        nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    real_popen = subprocess.Popen
    real_cleanup = heavy._cleanup_owned_process
    owned = []
    observed = []

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    def cleanup(process):
        try:
            # This is observed before the real cleanup, not a marker claiming exit.
            assert process.poll() is not None
            child = int(descendant_pid.read_text())
            os.kill(child, 0)
            assert os.getpgid(child) == process.pid
            observed.append((process.pid, child))
        finally:
            leaked = real_cleanup(process)
        return leaked

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    monkeypatch.setattr(heavy, "_cleanup_owned_process", cleanup)
    try:
        with pytest.raises(heavy.HeavyAcceptanceError) as error:
            if during_collection:
                heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
            else:
                heavy._run_partitions(
                    _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
                )
        assert error.value.reason == "heavy_cleanup_leaked"
        assert len(observed) == len(owned) == 1
        for process in owned:
            assert process.poll() is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
    finally:
        for process in owned:
            real_cleanup(process)


def test_heavy_profile_cleans_all_owned_groups_after_cleanup_unknown(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    (work / "tests" / "deploy" / "test_deploy_channel_script.py").unlink()
    descendant_pid = tmp_path / "unknown-descendant.pid"
    (work / "tests" / "deploy" / "test_first_owned.py").write_text(
        _leaky_test_source(descendant_pid)
    )
    (work / "tests" / "deploy" / "test_second_owned.py").write_text(
        "def test_peer_pass(): pass\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 30
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    real_popen = subprocess.Popen
    real_cleanup = heavy._cleanup_owned_process
    real_group_exists = heavy._group_exists
    owned = []
    injected = False

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    def uncertain_group(group):
        nonlocal injected
        if owned and group == owned[0].pid and not injected:
            child = int(descendant_pid.read_text())
            os.kill(child, 0)
            assert os.getpgid(child) == group
            injected = True
            raise heavy.HeavyAcceptanceError("heavy_cleanup_refused")
        return real_group_exists(group)

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    monkeypatch.setattr(heavy, "_group_exists", uncertain_group)
    try:
        with pytest.raises(heavy.HeavyAcceptanceError) as error:
            heavy._run_partitions(
                _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
            )
        assert error.value.reason == "heavy_cleanup_refused"
        assert injected and len(owned) == 2
        for process in owned:
            assert process.poll() is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
    finally:
        for process in owned:
            real_cleanup(process)


def test_heavy_profile_registers_worker_before_fallible_log_close(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 30
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    real_popen = subprocess.Popen
    real_cleanup = heavy._cleanup_owned_process
    real_open = Path.open
    owned = []

    def launch(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        owned.append(process)
        return process

    class CloseFailure:
        def __init__(self, stream):
            self.stream = stream

        def fileno(self):
            return self.stream.fileno()

        def close(self):
            self.stream.close()
            raise OSError("injected owned-worker log-close failure")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    def open_log(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if path.name.startswith("partition-") and path.suffix == ".log":
            return CloseFailure(stream)
        return stream

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    monkeypatch.setattr(Path, "open", open_log)
    try:
        with pytest.raises(OSError, match="injected owned-worker log-close failure"):
            heavy._run_partitions(
                _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
            )
        assert len(owned) == 1
        for process in owned:
            assert process.poll() is not None
            with pytest.raises(ProcessLookupError):
                os.killpg(process.pid, 0)
    finally:
        for process in owned:
            real_cleanup(process)


@pytest.mark.parametrize("expires_during", ["aggregation", "cleanup"])
def test_heavy_profile_checks_deadline_after_cleanup(tmp_path, monkeypatch, expires_during):
    work = _partition_tree(tmp_path, file_count=1)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    expired = False
    real_monotonic = time.monotonic
    deadline = real_monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    real_reader = heavy._read_worker_result
    real_cleanup = heavy._cleanup_owned_process

    def clock():
        return deadline + 1 if expired else real_monotonic()

    def reader(*args, **kwargs):
        nonlocal expired
        result = real_reader(*args, **kwargs)
        if expires_during == "aggregation":
            expired = True
        return result

    def cleanup(process):
        nonlocal expired
        leaked = real_cleanup(process)
        if expires_during == "cleanup":
            expired = True
        return leaked

    monkeypatch.setattr(heavy, "time", SimpleNamespace(monotonic=clock, sleep=time.sleep))
    monkeypatch.setattr(heavy, "_read_worker_result", reader)
    monkeypatch.setattr(heavy, "_cleanup_owned_process", cleanup)
    with pytest.raises(heavy.HeavyAcceptanceError) as error:
        heavy._run_partitions(
            _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
        )
    assert expired and error.value.reason == "heavy_deadline_exceeded"


def test_heavy_profile_refuses_expired_collection_before_spawning(tmp_path, monkeypatch):
    started = []

    def launch(*args, **kwargs):
        started.append(args)
        raise AssertionError("expired collection admitted")

    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    with pytest.raises(heavy.HeavyAcceptanceError) as error:
        heavy._collect_nodes(
            tmp_path, SELECTOR_MARKER, "tests/deploy", time.monotonic() - 1
        )
    assert error.value.reason == "heavy_deadline_exceeded"
    assert not started


@pytest.mark.parametrize("preparation", ["targets", "log"])
def test_heavy_profile_refuses_expired_worker_preparation_before_spawning(
    tmp_path, monkeypatch, preparation
):
    work = _partition_tree(tmp_path, file_count=1)
    expired = False
    started = []
    real_monotonic = time.monotonic
    deadline = real_monotonic() + 60
    nodes = heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
    real_write = Path.write_text
    real_open = Path.open

    def clock():
        return deadline + 1 if expired else real_monotonic()

    def write(path, *args, **kwargs):
        nonlocal expired
        result = real_write(path, *args, **kwargs)
        if preparation == "targets" and path.suffix == ".targets":
            expired = True
        return result

    def open_log(path, *args, **kwargs):
        nonlocal expired
        stream = real_open(path, *args, **kwargs)
        if preparation == "log" and path.suffix == ".log":
            expired = True
        return stream

    def launch(*args, **kwargs):
        started.append(args)
        raise AssertionError("expired worker admitted")

    monkeypatch.setattr(heavy, "time", SimpleNamespace(monotonic=clock, sleep=time.sleep))
    monkeypatch.setattr(Path, "write_text", write)
    monkeypatch.setattr(Path, "open", open_log)
    monkeypatch.setattr(heavy.subprocess, "Popen", launch)
    with pytest.raises(heavy.HeavyAcceptanceError) as error:
        heavy._run_partitions(
            _expected(), work, SELECTOR_MARKER, ("tests/deploy",), nodes, deadline
        )
    assert expired and error.value.reason == "heavy_deadline_exceeded"
    assert not started


def test_heavy_profile_refuses_exhausted_planning_before_spawning_workers(tmp_path, monkeypatch):
    started: list[object] = []

    def planning(*args, **kwargs):
        time.sleep(0.05)
        return (("tests/deploy/test_extra_0.py",),)

    monkeypatch.setattr(heavy, "_partition_targets", planning)
    real_popen = heavy.subprocess.Popen

    def unexpected_start(*args, **kwargs):
        started.append(args)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(heavy.subprocess, "Popen", unexpected_start)
    with pytest.raises(heavy.HeavyAcceptanceError) as error:
        heavy._run_partitions(
            {**_expected()},
            tmp_path,
            SELECTOR_MARKER,
            ("tests/deploy",),
            (),
            time.monotonic() + 0.01,
        )
    assert error.value.reason == "heavy_deadline_exceeded"
    assert not started


def test_heavy_profile_refuses_collection_errors_and_missing_watchdog(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=2)
    broken = work / "tests" / "deploy" / "test_broken.py"
    broken.write_text("def test_broken(:\n    pass\n")
    result = tmp_path / "collection-error.json"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/test_broken.py"],
        result,
    )
    payload = json.loads(result.read_text())
    assert payload["summary"]["exit_status"] != 0
    assert heavy.classify(payload["summary"], _expected())["result"] == "failed"
    with pytest.raises(heavy.HeavyAcceptanceError) as watchdog:
        heavy.HeavyResults().summary(0)
    assert watchdog.value.reason == "heavy_watchdog_missing"


def test_heavy_profile_preserves_xfail_xpass_and_setup_phase_projection(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    xfail_file = work / "tests" / "deploy" / "test_xfail.py"
    xfail_file.write_text(
        "import pytest\n"
        "@pytest.mark.xfail(reason='expected')\n"
        "def test_expected_failure(): assert False\n"
        "@pytest.mark.xfail(reason='unexpected')\n"
        "def test_unexpected_pass(): assert True\n"
        "@pytest.fixture\n"
        "def setup_xfail(): pytest.xfail('setup')\n"
        "def test_setup_xfail(setup_xfail): pass\n"
        "@pytest.fixture\n"
        "def teardown_xfail():\n"
        "    yield\n"
        "    pytest.xfail('teardown')\n"
        "def test_pass_then_teardown_xfail(teardown_xfail): pass\n"
    )
    result = tmp_path / "xfail.json"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/test_xfail.py"],
        result,
    )
    payload = json.loads(result.read_text())
    summary = payload["summary"]
    # C3 counts call-pass + teardown-XFAIL as passed, and setup/call XFAIL
    # contributes to neither legacy counter. These are not exclusive buckets.
    assert (summary["selected"], summary["passed"], summary["failed"],
            summary["skipped"], summary["exit_status"]) == (4, 2, 0, 0, 0)
    assert sorted(line.rsplit(" ", 1)[1] for line in payload["terminal_results"]) == [
        "XFAIL", "XFAIL", "XFAIL", "XPASS",
    ]
    parsed, _ = heavy._read_worker_result(
        result, _expected(), tuple(payload["nodes"]),
        partition_tools=heavy._load_partition_tools(work),
    )
    assert heavy.classify(parsed, _expected())["result"] == "passed"
    setup_node = next(node for node in payload["nodes"] if node.endswith("::test_setup_xfail"))
    assert [phase["when"] for phase in payload["phase_results"]
            if phase["nodeid"] == setup_node] == ["setup", "teardown"]


@pytest.mark.parametrize("teardown", ["failure", "skip"])
def test_heavy_profile_preserves_v1_overlap_for_teardown_failure(
    tmp_path, monkeypatch, teardown
):
    work = _partition_tree(tmp_path, file_count=1)
    filename = "test_teardown_" + teardown + ".py"
    test_file = work / "tests" / "deploy" / filename
    action = "assert False" if teardown == "failure" else "pytest.skip('teardown')"
    test_file.write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def finishing():\n"
        "    yield\n"
        f"    {action}\n"
        "def test_call_passes(finishing): pass\n"
    )
    result = tmp_path / "teardown-result.json"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/" + filename],
        result,
    )
    payload = json.loads(result.read_text())
    summary = payload["summary"]
    assert summary["passed"] == 1
    assert summary["failed"] == int(teardown == "failure")
    assert summary["skipped"] == int(teardown == "skip")
    parsed, _ = heavy._read_worker_result(
        result, _expected(), tuple(payload["nodes"]),
        partition_tools=heavy._load_partition_tools(work),
    )
    assert heavy.classify(parsed, _expected())["result"] == (
        "failed" if teardown == "failure" else "passed"
    )


def test_heavy_profile_refuses_failure_timeout_and_docker_skip(tmp_path):
    assert heavy.classify(_summary(), _expected())["result"] == "passed"
    # A test failure, a pytest-timeout watchdog kill (reported as a failure),
    # a docker-gated skip, a nonzero session or an empty run are never a pass.
    for overrides in (
        {"failed": 1, "failures": ["tests/deploy/test_a.py::test_slow"]},
        {"exit_status": 1},
        {"docker_skipped": 3},
        {"selected": 0, "passed": 0},
    ):
        assert heavy.classify(_summary(**overrides), _expected())["result"] == "failed", overrides
    # Foreign identity, missing fields or unbounded evidence are refused.
    for broken in (
        _summary(source_sha="c" * 40),
        {k: v for k, v in _summary().items() if k != "targets"},
        _summary(targets=[]),
        _summary(failures=["x\ny"]),
        _summary(failures=["t"] * 21),
        _summary(passed=-1),
    ):
        with pytest.raises(heavy.HeavyAcceptanceError):
            heavy.classify(broken, _expected())

    # In-container entrypoint: the exact tree's own selector, PR marker and
    # the 120 s thread watchdog; a docker-gated skip is counted.
    work = tmp_path / "work"
    # Path pieces, not repo-relative literals: the heavy-trigger census reads
    # string literals in tests/deploy as repo files this suite depends on.
    (work / "scripts").mkdir(parents=True)
    (work / "tests" / "deploy").mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "__init__.py", work / "scripts" / "__init__.py")
    (work / "scripts" / SELECTOR_NAME).write_text(
        "HEAVY_PR_DEFERRED_TARGETS = {'tests/deploy': ()}\n"
        "PR_MARKER_EXPRESSION = 'not pg and not alpha_llm and not alpha_llm_live and not panel_llm_e2e and not eval and not browser_runtime and not human_uat and not uat_integrated_runtime'\n"
    )
    for helper in ("plan_full_suite_node_shards.py", "run_scoped_test_partitions.py"):
        shutil.copy2(ROOT / "scripts" / helper, work / "scripts" / helper)
    (work / "tox.ini").write_text("[pytest]\nmarkers =\n    pg: pg\n")
    (work / "tests" / "deploy" / "test_sample.py").write_text(
        "import pytest\n"
        "def test_ok():\n    pass\n"
        "@pytest.mark.pg\ndef test_pg_is_deselected():\n    raise AssertionError()\n"
        '@pytest.mark.skipif(True, reason="docker executable not found on PATH")\n'
        "def test_compose():\n    pass\n"
    )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(_expected()))
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from app.ops.heavy_acceptance import main; "
            f'sys.path.insert(0, {str(work)!r}); raise SystemExit(main(["--manifest", {str(manifest)!r}]))',
        ],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTEST_ADDOPTS": ""},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(row for row in result.stdout.splitlines() if row.startswith(heavy.RESULT_PREFIX))
    summary = json.loads(line[len(heavy.RESULT_PREFIX) :])
    assert summary["targets"] == ["tests/deploy"]
    assert (
        summary["selected"],
        summary["passed"],
        summary["skipped"],
        summary["docker_skipped"],
    ) == (2, 1, 1, 1)
    assert heavy.classify(summary, _expected())["result"] == "failed"


def test_heavy_profile_preserves_v1_identity_and_report_hash():
    summary = _summary()
    verdict = heavy.classify(summary, _expected())
    assert verdict["profile_version"] == heavy.PROFILE_VERSION
    assert verdict["source_sha"] == SHA
    assert verdict["image_digest"] == DIGEST
    assert verdict["channel"] == "test"
    assert verdict["operation_id"] == OPERATION
    assert verdict["report_hash"] == summary["report_hash"]
    assert verdict["selected"] == summary["selected"]
    assert verdict["passed"] == summary["passed"]
    assert verdict["failed"] == summary["failed"]
    assert verdict["skipped"] == summary["skipped"]
    assert verdict["docker_skipped"] == summary["docker_skipped"]


class _FakeDocker:
    """Records the trusted worker's Docker/Git calls for one disposable run."""

    def __init__(self, repository: Path, output: str):
        self.calls: list[list[str]] = []
        self.output = output
        self.container = None
        self.created: list[str] = []
        self.repository = repository
        self.oom = False
        self.limit_mismatch = False
        self.finished = False

    def __call__(self, argv, *, timeout=60):
        self.calls.append(argv)
        if argv[0] == "git":
            command, where = argv[5:], Path(argv[4])
            if command[:1] == ["rev-parse"]:
                return (
                    SHA if command[1] in {SHA + "^{commit}", "HEAD"} else "e" * 40
                ).encode() + b"\n"
            if command[:1] == ["fetch"]:
                assert (
                    command[-2:] == ["file://" + str(self.repository), SHA] and "--depth" in command
                )
                return b""
            if command[:1] == ["checkout"]:
                (where / "scripts").mkdir()
                (where / "scripts" / SELECTOR_NAME).write_text("x = 1\n")
                return b""
            if command[:1] in (["init"], ["status"]):
                return b""
        command = argv[1:]
        if command[:2] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": "sha256:" + "f" * 64,
                        "RepoDigests": [heavy_image_digest()],
                        "Config": {"Labels": {"org.opencontainers.image.revision": SHA}},
                    }
                ]
            ).encode()
        if command[:2] == ["container", "ls"]:
            return (self.container or "").encode()
        if command[:1] == ["create"]:
            self.created = command
            self.container = "c" * 64
            return self.container.encode() + b"\n"
        if command[:1] == ["inspect"]:
            labels = {}
            for index, value in enumerate(self.created):
                if value == "--label":
                    key, _, item = self.created[index + 1].partition("=")
                    labels[key] = item
            mounts = [
                {"Type": "bind", "Source": self.created[i + 1].split(",")[1].removeprefix("src=")}
                for i, value in enumerate(self.created)
                if value == "--mount"
            ]
            memory = (
                int(self.created[self.created.index("--memory") + 1])
                if "--memory" in self.created
                else 0
            )
            swap = (
                int(self.created[self.created.index("--memory-swap") + 1])
                if "--memory-swap" in self.created
                else 0
            )
            return json.dumps(
                [
                    {
                        "Id": self.container,
                        "Name": "/" + self.created[2],
                        "Image": "sha256:" + "f" * 64,
                        "Config": {"Labels": labels},
                        "Mounts": mounts,
                        "State": {
                            "OOMKilled": self.oom,
                            "ExitCode": 0,
                            "Running": not self.finished,
                        },
                        "HostConfig": {
                            "NetworkMode": "none",
                            "ReadonlyRootfs": True,
                            "CapDrop": ["ALL"],
                            "Memory": memory + int(self.limit_mismatch),
                            "MemorySwap": swap,
                        },
                    }
                ]
            ).encode()
        if command[:2] == ["start", "--attach"]:
            self.finished = True
            return self.output.encode()
        if command[:1] == ["rm"]:
            self.container = None
            return b""
        raise AssertionError(argv)


def heavy_image_digest():
    from app.ops.pg_acceptance import IMAGE_REPOSITORY

    return IMAGE_REPOSITORY + "@" + DIGEST


def _runner(tmp_path, monkeypatch, output, *, channel="test", memory_limit=None):
    journal = tmp_path / "journal"
    journal.mkdir(mode=0o700)
    fake = _FakeDocker(tmp_path / "repo", output)
    monkeypatch.setattr(runner_module, "_command", fake)
    docker = tmp_path / "docker"
    compose = tmp_path / "docker-compose"
    for path in (docker, compose):
        path.write_text("")
    monkeypatch.setattr(runner_module, "host_docker_cli", lambda: (docker, compose))
    return HeavyAcceptanceRunner(
        tmp_path / "repo",
        journal,
        sha=SHA,
        digest=DIGEST,
        channel=channel,
        operation_id=OPERATION,
        memory_limit=memory_limit,
    ), fake


def test_runner_isolates_candidate_and_cleans_owned_resources(tmp_path, monkeypatch):
    output = "pytest noise\n" + heavy.RESULT_PREFIX + json.dumps(_summary()) + "\n"
    runner, fake = _runner(tmp_path, monkeypatch, output)
    result = runner.verify()
    assert result["result"] == "passed" and result["selected"] == 500
    create = fake.created
    for flag in (
        ["--network", "none"],
        ["--cap-drop", "ALL"],
        ["--security-opt", "no-new-privileges"],
    ):
        index = create.index(flag[0])
        assert create[index : index + 2] == flag
    assert "--read-only" in create
    mounts = [create[i + 1] for i, value in enumerate(create) if value == "--mount"]
    assert any(m.endswith(f"dst={runner_module.CONTAINER_DOCKER},readonly") for m in mounts)
    assert any(m.endswith(f"dst={runner_module.CONTAINER_COMPOSE},readonly") for m in mounts)
    assert not any("docker.sock" in m for m in mounts)
    assert create[-3:] == ["app.ops.heavy_acceptance", "--manifest", "/heavy-manifest.json"]
    # Exact owned container and work tree are gone after the run.
    assert fake.container is None and not runner.directory.exists()


@pytest.mark.parametrize(
    "output",
    [
        "",
        heavy.RESULT_PREFIX + "refused\n",
        heavy.RESULT_PREFIX + json.dumps(_summary(operation_id=str(uuid4()))) + "\n",
    ],
)
def test_runner_refuses_missing_or_foreign_evidence(tmp_path, monkeypatch, output):
    runner, fake = _runner(tmp_path, monkeypatch, output)
    with pytest.raises(heavy.HeavyAcceptanceError):
        runner.verify()
    assert fake.container is None and not runner.directory.exists()


def test_qualify_heavy_is_fixed_dev_test_and_refuses_uncommitted(
    monkeypatch, capsys, admitted_bws_caller
):
    assert linux.main(["qualify-heavy", "prod", OPERATION]) == 78
    assert json.loads(capsys.readouterr().out) == {
        "profile_version": heavy.PROFILE_VERSION,
        "result": "refused",
        "reason": "fixed_dev_test_invocation_required",
    }

    class Journal:
        directory = Path("/nonexistent")

        @staticmethod
        def read():
            return None

    monkeypatch.setattr(
        linux.LinuxConfig,
        "load",
        classmethod(
            lambda cls, channel, **_kw: type(
                "Config", (), {"channel": channel, "journal": Journal}
            )()
        ),
    )
    assert linux.main(["qualify-heavy", "test", OPERATION]) == 78
    assert (
        json.loads(capsys.readouterr().out)["reason"]
        == "expected_committed_native_operation_required"
    )


def test_launcher_admits_qualify_heavy(monkeypatch):
    # The installed launcher is a fixed action/arity allowlist; the controller's
    # exact `qualify-heavy <channel> <operation-id>` call must pass it and reach
    # the root-owned channel configuration read.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "launcher", ROOT / "scripts" / "postgres_deploy_service.py"
    )
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    opened = []

    def refuse(path, *_args, **_kwargs):
        opened.append(str(path))
        raise PermissionError()

    monkeypatch.setattr(launcher.os, "open", refuse)
    for argv, admitted in (
        (["qualify-heavy", "dev", OPERATION], True),
        (["qualify-heavy", "test", OPERATION], True),
        (["qualify-heavy", "dev"], False),
        (["qualify-heavy", "stage", OPERATION], False),
        (["qualify-anything", "dev", OPERATION], False),
    ):
        opened.clear()
        monkeypatch.setattr(launcher.sys, "argv", ["yggdrasil-bws-deploy", *argv])
        assert launcher.run() == 78  # the config read is refused in this sandbox either way
        assert bool(opened) is admitted, argv
