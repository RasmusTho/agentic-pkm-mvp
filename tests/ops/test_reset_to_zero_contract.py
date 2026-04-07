from __future__ import annotations

import os
import subprocess
from pathlib import Path


def test_reset_to_zero_clears_watcher_stop_state(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    scripts_dir = repo_root / "scripts"
    runtime_tmp = repo_root / "tmp"
    scripts_dir.mkdir(parents=True)
    runtime_tmp.mkdir(parents=True)

    source_script = Path("scripts/reset_to_zero.sh")
    reset_script = scripts_dir / "reset_to_zero.sh"
    reset_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
    reset_script.chmod(0o755)

    stop_file = runtime_tmp / "WATCHER_STOP"
    stop_file.write_text("paused\n", encoding="utf-8")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir(parents=True)
    fake_docker = fake_bin / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)

    env = os.environ.copy()
    env["RESET_FORCE"] = "1"
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    subprocess.run(
        ["bash", "scripts/reset_to_zero.sh"],
        cwd=repo_root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert not stop_file.exists()


def test_reset_to_zero_runbook_documents_stop_file_cleanup() -> None:
    runbook = Path("docs/runbooks/RUNBOOK_RESET_TO_ZERO.md").read_text(encoding="utf-8")
    assert "tmp/WATCHER_STOP" in runbook
    assert "stale paused-watcher state" in runbook
