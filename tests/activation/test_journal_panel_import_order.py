from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_isolated(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_journal_import_preserves_panel_agent_submodule_attribute() -> None:
    result = _run_isolated(
        """
import sys

import app.journaling.draft
import app.agents.panel_agent as panel_package

panel_module = sys.modules["app.agents.panel_agent.agent"]
assert panel_package.agent is panel_module
"""
    )

    assert result.returncode == 0, result.stderr


def test_journal_first_import_supports_panel_monkeypatch_resolution() -> None:
    result = _run_isolated(
        """
from pathlib import Path

import app.journaling.draft
from pytest import MonkeyPatch

patch = MonkeyPatch()
patch.setattr(
    "app.agents.panel_agent.agent.INDEX_OUTBOX_PATH",
    Path("isolated-index-outbox.jsonl"),
    raising=False,
)
patch.undo()
"""
    )

    assert result.returncode == 0, result.stderr
