from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
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


def _leaky_test_source(marker: Path, *, linger_seconds: float = 1.0) -> str:
    child = f"import time; time.sleep({linger_seconds}); Path({str(marker)!r}).write_text('leaked')"
    return (
        "import subprocess\n"
        "import sys\n"
        "import time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
        "def test_leaky_worker():\n"
        "    time.sleep(0.05)\n"
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


def test_heavy_profile_rejects_incomplete_duplicate_and_foreign_worker_results(tmp_path):
    expected = _expected()
    with pytest.raises(heavy.HeavyAcceptanceError) as missing:
        heavy._read_worker_result(tmp_path / "missing.json", expected)
    assert missing.value.reason == "heavy_worker_result_missing"
    summary = {
        **expected,
        "targets": ["tests/deploy"],
        "exit_status": 0,
        "failures": [],
        "report_hash": hashlib.sha256(
            json.dumps([["tests/deploy/test_a.py::test_a"], []], separators=(",", ":")).encode()
        ).hexdigest(),
        "selected": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "docker_skipped": 0,
    }
    result = tmp_path / "worker.json"
    result.write_text(
        json.dumps(
            {
                "summary": summary,
                "nodes": ["tests/deploy/test_a.py::test_a"],
                "passed_nodes": ["tests/deploy/test_a.py::test_a"],
                "failed_nodes": [],
                "skipped_nodes": [],
            }
        )
    )
    parsed, _ = heavy._read_worker_result(result, expected)
    assert parsed["selected"] == 1
    result.write_text(
        json.dumps(
            {
                **json.loads(result.read_text()),
                "summary": {**summary, "report_hash": "1" * 64},
            }
        )
    )
    with pytest.raises(heavy.HeavyAcceptanceError):
        heavy._read_worker_result(result, expected)
    result.write_text(
        json.dumps(
            {
                "summary": summary,
                "nodes": ["tests/deploy/test_a.py::test_a"],
                "passed_nodes": ["tests/deploy/test_a.py::test_a"],
                "failed_nodes": [],
                "skipped_nodes": [],
            }
        )
    )
    two_summary = {**summary, "selected": 2, "passed": 1, "skipped": 1}
    two_payload = {
        "summary": two_summary,
        "nodes": ["tests/deploy/test_a.py::test_a", "tests/deploy/test_b.py::test_b"],
        "passed_nodes": ["tests/deploy/test_a.py::test_a"],
        "failed_nodes": [],
        "skipped_nodes": ["tests/deploy/test_b.py::test_b"],
    }
    result.write_text(json.dumps(two_payload))
    parsed, _ = heavy._read_worker_result(result, expected)
    assert parsed["selected"] == 2
    result.write_text(json.dumps({**two_payload, "summary": {**two_summary, "skipped": 0}}))
    with pytest.raises(heavy.HeavyAcceptanceError):
        heavy._read_worker_result(result, expected)
    result.write_text(
        json.dumps(
            {
                "summary": summary,
                "nodes": ["tests/deploy/test_a.py::test_a"],
                "passed_nodes": ["tests/deploy/test_a.py::test_a"],
                "failed_nodes": [],
                "skipped_nodes": [],
            }
        )
    )
    for payload in (
        {**json.loads(result.read_text()), "nodes": ["tests/deploy/test_a.py::test_a"] * 2},
        {**json.loads(result.read_text()), "summary": {**summary, "source_sha": "c" * 40}},
        {
            **json.loads(result.read_text()),
            "failed_nodes": ["tests/deploy/test_a.py::test_a"],
            "summary": {**summary, "failed": 1, "passed": 1},
        },
        {
            **json.loads(result.read_text()),
            "summary": {**summary, "targets": ["tests/ops"]},
        },
    ):
        result.write_text(json.dumps(payload))
        with pytest.raises(heavy.HeavyAcceptanceError):
            heavy._read_worker_result(result, expected)


def test_heavy_profile_enforces_deadline_watchdog_and_owned_child_cleanup(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=2)
    marker = tmp_path / "child-finished-after-timeout"
    (work / "tests" / "deploy" / "test_extra_0.py").write_text(
        "import time\n"
        f"from pathlib import Path\nMARKER = Path({str(marker)!r})\n"
        "def test_slow():\n"
        "    time.sleep(1)\n"
        "    MARKER.write_text('leaked')\n"
    )
    monkeypatch.setattr(
        heavy, "_partition_targets", lambda *args, **kwargs: (("tests/deploy/test_extra_0.py",),)
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    with pytest.raises(heavy.HeavyAcceptanceError) as error:
        heavy._run_partitions(
            {**_expected()},
            work,
            SELECTOR_MARKER,
            ("tests/deploy",),
            (),
            time.monotonic() + 0.5,
        )
    assert error.value.reason == "heavy_deadline_exceeded"
    time.sleep(1.2)
    assert not marker.exists()


def test_heavy_profile_cleans_exited_leader_and_descendant_when_peer_times_out(
    tmp_path, monkeypatch
):
    work = _partition_tree(tmp_path, file_count=1)
    exited_marker = tmp_path / "exited-descendant-leaked"
    slow_marker = tmp_path / "slow-descendant-leaked"
    exited_file = work / "tests" / "deploy" / "test_exited.py"
    slow_file = work / "tests" / "deploy" / "test_slow_peer.py"
    exited_file.write_text(_leaky_test_source(exited_marker))
    slow_file.write_text("import time\ndef test_slow_peer(): time.sleep(5)\n")
    monkeypatch.setattr(
        heavy,
        "_partition_targets",
        lambda *args, **kwargs: (
            ("tests/deploy/test_exited.py",),
            ("tests/deploy/test_slow_peer.py",),
        ),
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    survivor = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(2)"], start_new_session=True
    )
    try:
        with pytest.raises(heavy.HeavyAcceptanceError) as error:
            heavy._run_partitions(
                {**_expected()},
                work,
                SELECTOR_MARKER,
                ("tests/deploy",),
                (),
                time.monotonic() + 0.5,
            )
        assert error.value.reason == "heavy_deadline_exceeded"
        assert survivor.poll() is None
        time.sleep(1.2)
        assert not exited_marker.exists()
        assert not slow_marker.exists()
    finally:
        survivor.terminate()
        survivor.wait(timeout=2)


def test_heavy_profile_cleans_descendant_after_nominal_success(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    marker = tmp_path / "nominal-descendant-leaked"
    test_file = work / "tests" / "deploy" / "test_nominal.py"
    test_file.write_text(_leaky_test_source(marker))
    monkeypatch.setattr(
        heavy, "_partition_targets", lambda *args, **kwargs: (("tests/deploy/test_nominal.py",),)
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    deadline = time.monotonic() + 10
    nodes = tuple(
        node
        for node in heavy._collect_nodes(work, SELECTOR_MARKER, "tests/deploy", deadline)
        if node.startswith("tests/deploy/test_nominal.py::")
    )
    aggregate = heavy._run_partitions(
        {**_expected()},
        work,
        SELECTOR_MARKER,
        ("tests/deploy",),
        nodes,
        deadline,
    )
    assert heavy.classify(aggregate, _expected())["result"] == "passed"
    time.sleep(1.2)
    assert not marker.exists()


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


def test_heavy_profile_refuses_xfail_and_xpass_terminal_outcomes(tmp_path, monkeypatch):
    work = _partition_tree(tmp_path, file_count=1)
    xfail_file = work / "tests" / "deploy" / "test_xfail.py"
    xfail_file.write_text(
        "import pytest\n"
        "@pytest.mark.xfail(reason='expected')\n"
        "def test_expected_failure():\n"
        "    assert False\n"
        "@pytest.mark.xfail(reason='unexpected')\n"
        "def test_unexpected_pass():\n"
        "    assert True\n"
    )
    result = tmp_path / "xfail.json"
    monkeypatch.chdir(work)
    heavy._worker_summary(
        {**_expected(), "marker": SELECTOR_MARKER},
        ["tests/deploy/test_xfail.py"],
        result,
    )
    summary = json.loads(result.read_text())["summary"]
    assert summary["exit_status"] == 0
    assert summary["failed"] == 2
    assert heavy.classify(summary, _expected())["result"] == "failed"


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
