from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CI_SMOKE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"
BROWSER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "browser-runtime.yml"
IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "app-image-build.yml"
IMPORT_LINTER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "import-linter.yaml"


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
    # Full (non-shallow) base fetch: --depth=1 cuts the base tip's parents when
    # the base branch advances mid-run, breaking merge-base for diff selection.
    assert 'git fetch --no-tags origin "${{ github.base_ref }}"' in workflow
    assert "--depth=1" not in workflow


def test_panel_llm_e2e_runs_only_after_merge() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    assert "panel_llm_e2e:" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
    assert "'app/agents/panel_agent/**'" in workflow
    assert "'app/agents/panel/**'" in workflow
    assert "'tests/agents/panel_agent/**'" in workflow
    assert "'tests/agents/test_panel*.py'" in workflow
    assert "id: live-llm" in workflow
    assert "steps.live-llm.outputs.enabled == 'true'" in workflow
    assert "Docker smoke runs after merge, not on pull requests." in workflow


def test_dedicated_subsystem_workflows_have_path_filters_and_browser_runs_post_merge() -> None:
    browser = BROWSER_WORKFLOW.read_text(encoding="utf-8")
    image = IMAGE_WORKFLOW.read_text(encoding="utf-8")
    import_linter = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")

    assert "paths:" in browser
    assert "branches: [main]" in browser
    assert "pull_request:" not in browser
    assert "'companion-ui/**'" in browser
    assert "paths:" in image
    assert "'Dockerfile'" in image
    assert "paths:" in import_linter
    assert "'app/**'" in import_linter


def test_ci_smoke_keeps_legacy_skills_lint_when_consolidating_smoke() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    assert "cache: pip" in workflow
    assert "python3 scripts/lint_skills_consistency.py" in workflow
