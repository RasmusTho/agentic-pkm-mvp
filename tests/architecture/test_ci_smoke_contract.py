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


def _vaultwide_panel_step() -> str:
    workflow = _workflow_text()
    return workflow.split('      - name: "CI gate: vaultwide panel verifier"', maxsplit=1)[
        1
    ].split("      - name: Skip docker smoke for docs-only PR", maxsplit=1)[0]


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


def test_vaultwide_smoke_activates_registered_fixture_through_production_cutover() -> None:
    step = _vaultwide_panel_step()

    deployment = 'prepare_instance_state_deployment run_ci_compose "${PKM_ENVIRONMENT:-dev}"'
    registration = "python -m app.instance.runtime preflight"
    cutover_binding = "export MVR01C_ROLLBACK_VAULT_BINDING_ID"
    cutover_root = 'export MVR01C_ROLLBACK_VAULT_ROOT="$VAULT_ROOT"'
    principal_cutover = "export MVR03_PRINCIPAL_CUTOVER=1"
    services = "docker compose $compose_files up -d --build db api watcher worker"

    assert step.count(deployment) == 2
    first_deployment = step.index(deployment)
    registration_index = step.index(registration)
    second_deployment = step.index(deployment, first_deployment + len(deployment))
    assert first_deployment < registration_index < second_deployment < step.index(services)
    assert registration_index < step.index(cutover_binding) < second_deployment
    assert registration_index < step.index(cutover_root) < second_deployment
    assert registration_index < step.index(principal_cutover) < second_deployment


def test_vaultwide_smoke_cleanup_removes_cutover_receipts_and_state() -> None:
    step = _vaultwide_panel_step()

    assert 'rm -f "$VAULT_BINDING_RECEIPT_PATH" "$VAULT_BINDING_ID_PATH"' in step
    assert "docker compose $compose_files down -v || true" in step
    assert step.index("trap cleanup EXIT") < step.index("run_ci_compose up -d --wait db")
