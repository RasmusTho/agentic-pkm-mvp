from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
# The unit-test lane moved from the retired ci.yml into ci-smoke.yaml (#3892).
CI = ROOT / ".github/workflows/ci-smoke.yaml"


def test_not_pg_job_includes_companion_app_on_pythonpath() -> None:
    workflow = CI.read_text(encoding="utf-8")
    unit_job = workflow.split("name: Unit tests (not pg)", 1)[1].split(
        "  contract-validation:", 1
    )[0]

    assert (
        "PYTHONPATH: ${{ github.workspace }}:"
        "${{ github.workspace }}/companion-ui/companion-app"
    ) in unit_job
