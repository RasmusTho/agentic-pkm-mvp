from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _workflow_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def test_pr_ci_selects_subsystem_scoped_pytest_targets() -> None:
    workflow = _workflow_text()

    assert "Select subsystem-scoped pytest targets" in workflow
    assert "scripts/select_pr_tests.py" in workflow
    assert "steps.select-tests.outputs.pytest_args" in workflow
    assert 'pytest ${{ steps.select-tests.outputs.pytest_args }} | tee pytest-not-pg.log' in workflow


def test_pr_ci_fetches_base_ref_before_diff_selection() -> None:
    workflow = _workflow_text()

    assert "fetch-depth: 0" in workflow
    assert 'git fetch --no-tags --depth=1 origin "${{ github.base_ref }}"' in workflow
