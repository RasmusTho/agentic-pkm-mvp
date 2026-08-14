from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SMOKE = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"


def _workflow_text() -> str:
    return CI_SMOKE.read_text(encoding="utf-8")


def test_ci_smoke_installs_media_system_dependencies() -> None:
    workflow = _workflow_text()

    assert "Install system deps (ffmpeg, ripgrep)" in workflow
    assert "sudo apt-get install -y ffmpeg ripgrep" in workflow


def test_ci_smoke_splits_baseline_and_quality_wave_pytest() -> None:
    workflow = _workflow_text()

    assert "Pytest smoke baseline (memory, fail-fast)" in workflow
    assert "Pytest Quality Wave smoke (memory, fail-fast)" in workflow
    baseline_step = workflow.split("Pytest smoke baseline (memory, fail-fast)", maxsplit=1)[1].split(
        "Pytest Quality Wave smoke (memory, fail-fast)", maxsplit=1
    )[0]
    quality_wave_step = workflow.split("Pytest Quality Wave smoke (memory, fail-fast)", maxsplit=1)[1]

    assert "tests/quality_wave" not in baseline_step
    assert "tests/quality_wave/test_uat_harness.py" in quality_wave_step
    assert "-n auto --dist=loadfile" in baseline_step


def test_quality_wave_smoke_runs_sequentially() -> None:
    workflow = _workflow_text()
    quality_wave_step = workflow.split("Pytest Quality Wave smoke (memory, fail-fast)", maxsplit=1)[1]

    assert "tests/quality_wave/test_uat_harness.py" in quality_wave_step
    assert "-p xdist.plugin" not in quality_wave_step
    assert "-n auto" not in quality_wave_step
    assert "--dist=loadfile" not in quality_wave_step


def test_ci_smoke_gates_heavy_pytest_for_docs_only_prs() -> None:
    workflow = _workflow_text()

    assert "dorny/paths-filter@v3" in workflow
    assert "heavy_smoke:" in workflow
    assert "Skip heavy pytest smoke for docs-only PR" in workflow
    assert "github.event_name != 'pull_request' || steps.changes.outputs.heavy_smoke == 'true'" in workflow


def test_full_ci_smoke_excludes_pr_metadata_edits_but_keeps_code_events() -> None:
    """PR contract edits have their own lightweight governance workflow.

    CI Smoke's expensive Unit/smoke/Docker jobs must only begin when the PR's
    code or integration inputs can have changed.  The Issue and PR Governance
    workflow continues to validate `edited` events, so removing the event here
    does not make PR metadata unvalidated.
    """
    workflow = _workflow_text()
    trigger = workflow.split("  pull_request:", maxsplit=1)[1].split(
        "\n\nconcurrency:", maxsplit=1
    )[0]
    governance = (REPO_ROOT / ".github" / "workflows" / "issue-pr-governance.yml").read_text(
        encoding="utf-8"
    )

    trigger_types = next(
        line.strip() for line in trigger.splitlines() if line.strip().startswith("types:")
    )
    assert trigger_types == "types: [opened, synchronize, reopened, edited]"
    assert "types: [opened, edited, reopened, synchronize]" in governance


def test_no_workflow_step_is_green_on_absent_provider_secret() -> None:
    workflow_dir = REPO_ROOT / ".github" / "workflows"
    all_workflows = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(workflow_dir.iterdir())
        if path.is_file()
    )

    assert "PANEL_AGENT_LLM_E2E_CI" not in all_workflows
    assert "Detect live-LLM CI configuration" not in all_workflows
    assert "steps.live-llm.outputs.enabled" not in all_workflows
    assert "Detect Codex secret" not in all_workflows
    assert "CODEX_API_KEY=${{ secrets.CODEX_API_KEY }}" not in all_workflows
    assert "codex run docs-guardian" not in all_workflows
