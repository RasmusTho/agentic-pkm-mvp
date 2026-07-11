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
    assert 'git fetch --no-tags --depth=1 origin "${{ github.base_ref }}"' in workflow


def test_panel_llm_e2e_is_path_scoped_and_does_not_install_when_unconfigured() -> None:
    workflow = CI_SMOKE_WORKFLOW.read_text(encoding="utf-8")

    assert "panel_llm_e2e:" in workflow
    assert "needs.smoke.outputs.panel_llm_e2e == 'true'" in workflow
    assert "'app/agents/panel_agent/**'" in workflow
    assert "id: live-llm" in workflow
    assert "steps.live-llm.outputs.enabled == 'true'" in workflow
    assert "Guard: skip when LLM E2E not configured" not in workflow


def test_dedicated_subsystem_workflows_have_pr_path_filters() -> None:
    browser = BROWSER_WORKFLOW.read_text(encoding="utf-8")
    image = IMAGE_WORKFLOW.read_text(encoding="utf-8")
    import_linter = IMPORT_LINTER_WORKFLOW.read_text(encoding="utf-8")

    assert "paths:" in browser
    assert "'companion-ui/**'" in browser
    assert "paths:" in image
    assert "'Dockerfile'" in image
    assert "paths:" in import_linter
    assert "'app/**'" in import_linter
