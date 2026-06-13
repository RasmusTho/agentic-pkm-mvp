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
