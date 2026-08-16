from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_SMOKE = REPO_ROOT / ".github" / "workflows" / "ci-smoke.yaml"


def _workflow_text() -> str:
    return CI_SMOKE.read_text(encoding="utf-8")


def _worker_startup_step() -> str:
    workflow = _workflow_text()
    return workflow.split('      - name: "Docker smoke: worker emits startup log"', maxsplit=1)[
        1
    ].split('      - name: "CI gate: vaultwide panel verifier"', maxsplit=1)[0]


def test_worker_smoke_starts_db_before_instance_state_deployment() -> None:
    step = _worker_startup_step()

    db_start = "run_ci_compose up -d --wait db"
    deployment = 'prepare_instance_state_deployment run_ci_compose "${PKM_ENVIRONMENT:-dev}"'

    assert db_start in step
    assert step.index(db_start) < step.index(deployment)


def test_worker_smoke_cleanup_covers_started_dependencies() -> None:
    step = _worker_startup_step()

    trap_registration = "trap cleanup EXIT"
    db_start = "run_ci_compose up -d --wait db"
    cleanup = "docker compose $compose_files down -v || true"

    assert cleanup in step
    assert step.index(trap_registration) < step.index(db_start)
    assert 'if [ "$rc" -ne 0 ]; then' in step
    assert 'exit "$rc"' in step


def test_push_smoke_registers_worker_startup_gate() -> None:
    workflow = _workflow_text()
    trigger = workflow.split("\nconcurrency:", maxsplit=1)[0]
    docker_job = workflow.split("  smoke-docker:", maxsplit=1)[1]

    assert "  push:\n    branches: [main]" in trigger
    assert '      - name: "Docker smoke: worker emits startup log"' in docker_job
    assert "if: github.event_name != 'pull_request' || github.base_ref == 'stable'" in docker_job
