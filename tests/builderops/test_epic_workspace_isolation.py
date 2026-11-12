"""Isolation and resource boundaries of the epic workspace launch path (#6616)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from app.builderops import epic_workspace as ew


class FakeEngine:
    """Records docker calls; delegates git to the real binary."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.calls: list[list[str]] = []
        self.containers: dict[str, str] = {}

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        if argv[0] == "git":
            return subprocess.run(argv, **kwargs)
        self.calls.append(argv)
        if not self.available:
            return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon")
        if argv[1] == "version":
            return subprocess.CompletedProcess(argv, 0, "29.1.3\n", "")
        if argv[1] == "ps":
            prefix = f"label={ew.LABEL_WORKER}="
            worker = next(a[len(prefix):] for a in argv if a.startswith(prefix))
            state = self.containers.get(worker)
            return subprocess.CompletedProcess(argv, 0, f"{state}\n" if state else "", "")
        if argv[1] == "run":
            worker = argv[argv.index("--label", argv.index("--label") + 1) + 1].split("=", 1)[1]
            self.containers[worker] = "running"
            return subprocess.CompletedProcess(argv, 0, "c0ffee" * 10 + "\n", "")
        if argv[1] == "rm":
            name = argv[-1]
            for worker in list(self.containers):
                if name.endswith(f"-{worker}"):
                    del self.containers[worker]
            return subprocess.CompletedProcess(argv, 0, name + "\n", "")
        raise AssertionError(f"unexpected docker call {argv}")

    def runs(self) -> list[list[str]]:
        return [c for c in self.calls if c[1] == "run"]


def _seed_repo(tmp_path: Path) -> str:
    origin = tmp_path / "origin"
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
    subprocess.run(["git", "init", "--quiet", "--initial-branch=main", str(origin)], check=True)
    (origin / "README.md").write_text("fixture\n")
    subprocess.run(["git", "-C", str(origin), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(origin), "commit", "--quiet", "-m", "seed"], check=True, env=env)
    return str(origin)


def _cli(root: Path, epic: int, engine: FakeEngine, *args: str) -> int:
    return ew.main(["--root", str(root), "--epic", str(epic), *args], runner=engine)


def test_production_launch_enforces_workspace_and_resource_boundaries(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "implement") == 0
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-b", "--issue", "6618", "--branch", "b/b", "--next-action", "implement") == 0
    # A second, disposable fixture epic under the same root.
    assert _cli(root, 9001, engine, "init", "--repo-url", repo) == 0
    assert _cli(root, 9001, engine, "worker-create", "--worker", "w-a", "--issue", "1", "--branch", "b/x", "--next-action", "fixture") == 0

    secret = tmp_path / "secrets" / "claude.env"
    secret.parent.mkdir()
    secret.write_text("CLAUDE_CODE_OAUTH_TOKEN=placeholder\n")
    secret.chmod(0o600)
    capsys.readouterr()

    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--cpus", "0.75", "--memory", "768m", "--pids", "128", "--env-file", str(secret), "--model", "claude-sonnet-5-5", "--", "sleep", "60") == 0
    [run] = engine.runs()
    layout = ew.Layout(root.resolve(), 6615)
    mounts = [run[i + 1] for i, a in enumerate(run) if a == "--mount"]
    assert mounts == [
        f"type=bind,source={layout.checkout('w-a')},target=/workspace",
        f"type=bind,source={layout.home('w-a')},target=/home/worker",
    ]
    for flag, value in [("--cpus", "0.75"), ("--memory", "768m"), ("--memory-swap", "768m"), ("--pids-limit", "128"), ("--cap-drop", "ALL"), ("--security-opt", "no-new-privileges"), ("--user", "1000:1000"), ("--network", "bridge")]:
        assert run[run.index(flag) + 1] == value
    assert "--read-only" in run and "--privileged" not in run
    assert not any("docker.sock" in a for a in run)
    assert run[run.index("--env-file") + 1] == str(secret)
    assert "placeholder" not in json.dumps(run)

    # Refusals happen before any engine effect.
    refused = [
        ["--mount", "/var/run/docker.sock:/var/run/docker.sock"],
        ["--mount", f"{Path.home()}:/host-home"],
        ["--mount", f"{layout.checkout('w-a')}:/other"],
        ["--mount", f"{layout.source}:/source"],
        ["--mount", f"{ew.Layout(root.resolve(), 9001).checkout('w-a')}:/fixture"],
        ["--memory", "unbounded"],
        ["--pids", "0"],
    ]
    for extra in refused:
        before = len(engine.calls)
        assert _cli(root, 6615, engine, "worker-start", "--worker", "w-b", *extra, "--", "true") == 2
        assert engine.calls[before:] == [], extra
    world_readable = tmp_path / "secrets" / "open.env"
    world_readable.write_text("X=1\n")
    world_readable.chmod(0o644)
    before = len(engine.calls)
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-b", "--env-file", str(world_readable), "--", "true") == 2
    assert engine.calls[before:] == []

    # A successor cannot start beside a live container for the same worker.
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "true") == 2
    assert len(engine.runs()) == 1

    # Engine loss is a refusal, never a host fallback.
    down = FakeEngine(available=False)
    assert _cli(root, 6615, down, "worker-start", "--worker", "w-b", "--", "touch", "/tmp/host-effect") == 2
    assert [c[1] for c in down.calls] == ["version"]
    err = capsys.readouterr().err
    assert "EngineUnavailable" in err

    # Workers have separate clones: an edit in one is invisible to the other.
    (layout.checkout("w-a") / "only-a.txt").write_text("a\n")
    assert not (layout.checkout("w-b") / "only-a.txt").exists()
    assert ew.inspect_checkout(layout.checkout("w-b"))["unique_work"] is False
