"""Production-path regressions for the temporal owner-doc guard."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def _guard_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "guard-repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "docs/development").mkdir(parents=True)
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "guard@example.test"], repo)
    _run(["git", "config", "user.name", "Docs Guard Test"], repo)
    for name in ("docs_guard.py", "docs_guard_logic.py"):
        shutil.copy2(REPO_ROOT / "scripts" / name, repo / "scripts" / name)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "base"], repo)
    return repo


def _guard_result(repo: Path) -> subprocess.CompletedProcess[str]:
    environment = {**os.environ, "GITHUB_BASE_REF": "HEAD~1"}
    return subprocess.run(
        [sys.executable, "scripts/docs_guard.py"],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
    )


def test_mixed_runtime_and_governance_change_still_requires_temporal_owner_doc(
    tmp_path: Path,
) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "app").mkdir()
    (repo / "app/runtime.py").write_text("changed = True\n", encoding="utf-8")
    (repo / "scripts/git_hygiene.py").write_text("# governance\n", encoding="utf-8")
    (repo / "docs/development/WORKFLOW.md").write_text("governance writeback\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "mixed"], repo)

    result = _guard_result(repo)

    assert result.returncode == 1
    assert "temporal code/config changed" in result.stdout


def test_governance_enforcement_with_development_writeback_passes(tmp_path: Path) -> None:
    repo = _guard_repo(tmp_path)
    (repo / "scripts/git_hygiene.py").write_text("# governance\n", encoding="utf-8")
    (repo / "docs/development/WORKFLOW.md").write_text("governance writeback\n", encoding="utf-8")
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "governance"], repo)

    result = _guard_result(repo)

    assert result.returncode == 0
    assert "Docs guard: OK" in result.stdout
