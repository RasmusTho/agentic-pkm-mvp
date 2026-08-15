from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PG_TARGETS = (
    "tests/migrations/test_multi_vault_outbox_upgrade.py",
    "tests/services/test_multi_vault_outbox_dual_key_dedup.py",
)


def _pytest_step(workflow: str, step_name: str) -> str:
    marker = workflow.index(step_name)
    start = workflow.index("pytest", marker)
    end = workflow.index("\n\n", start)
    return workflow[start:end]


def test_mvr05_pg_targets_run_on_provisioned_postgres_and_cannot_skip() -> None:
    """MVR-05A7's PostgreSQL proofs run in both real-DB lanes without skip guards."""
    nightly = (REPO_ROOT / ".github/workflows/integration-nightly.yaml").read_text()
    pr_path = (REPO_ROOT / ".github/workflows/ci-smoke.yaml").read_text()

    for target in PG_TARGETS:
        assert target in _pytest_step(nightly, "Bounded PG verification lane")
        assert target in _pytest_step(pr_path, "durable table ownership PG surface")
        assert f"- '{target}'" in pr_path

        source = (REPO_ROOT / target).read_text()
        assert "pytest.skip" not in source
        assert "pytest.importorskip" not in source
