from __future__ import annotations

from pathlib import Path

import companion_ui
import yaml


ROOT = Path(__file__).resolve().parents[2]
# The unit-test lane moved from the retired ci.yml into ci-smoke.yaml (#3892).
CI = ROOT / ".github/workflows/ci-smoke.yaml"


def test_not_pg_job_includes_companion_app_on_pythonpath() -> None:
    """Root pytest collection supplies the current checkout's Companion package."""
    unit_job = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["pr-unit-tests-not-pg"]
    assert unit_job["name"] == "Unit tests (not pg)"
    # Read only this job: the former text slice borrowed the adjacent PG job's
    # environment and falsely passed without checking the declared consumer.
    assert "${{ github.workspace }}/companion-ui/companion-app" not in str(unit_job)

    expected = (ROOT / "companion-ui" / "companion-app" / "companion_ui").resolve()
    assert expected in {Path(path).resolve() for path in companion_ui.__path__}
