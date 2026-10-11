from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SMOKE = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"


def _workflow_text() -> str:
    return CI_SMOKE.read_text(encoding="utf-8")


def test_ci_smoke_installs_media_system_dependencies() -> None:
    workflow = _workflow_text()

    assert "Install system deps (ffmpeg, ripgrep)" in workflow
    assert "sudo apt-get install -y ffmpeg ripgrep" in workflow


def test_declared_ci_image_sources_are_verified_digest_pins() -> None:
    """Check actual service, action inputs and Dockerfile pull entrypoints."""
    from app.ops.pg_acceptance import POSTGRES_IMAGE

    assert POSTGRES_IMAGE == (
        "mirror.gcr.io/pgvector/pgvector:pg16@sha256:"
        "7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a"
    )

    image_workflow = REPO_ROOT / ".github/workflows/app-image-build.yml"
    image_jobs = yaml.safe_load(image_workflow.read_text(encoding="utf-8"))["jobs"]
    for job_id in ("build-app-image", "build-builderops-images"):
        steps = image_jobs[job_id]["steps"]
        buildx = [step for step in steps if step.get("uses") == "docker/setup-buildx-action@v3"]
        qemu = [step for step in steps if step.get("uses") == "docker/setup-qemu-action@v3"]
        assert len(buildx) == len(qemu) == 1
        assert buildx[0]["with"] == {
            "driver-opts": (
                "image=mirror.gcr.io/moby/buildkit@sha256:"
                "cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
            )
        }
        assert qemu[0]["with"] == {
            "image": (
                "mirror.gcr.io/tonistiigi/binfmt@sha256:"
                "400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0"
            ),
            "platforms": "linux/amd64,linux/arm64",
        }

    expected_bases = {
        "Dockerfile.builderops": [
            "FROM scratch AS devui-source-inputs",
            "FROM mirror.gcr.io/library/python:3.12-slim@sha256:"
            "a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1",
        ],
        "Dockerfile.builderops-postgres": [
            "FROM mirror.gcr.io/library/postgres:16-bookworm@sha256:"
            "0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4"
        ],
    }
    for dockerfile, expected in expected_bases.items():
        actual = [
            line.strip()
            for line in (REPO_ROOT / dockerfile).read_text(encoding="utf-8").splitlines()
            if line.startswith("FROM ")
        ]
        assert actual == expected


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
