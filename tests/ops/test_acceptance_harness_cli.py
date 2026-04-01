from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.not_pg
def test_ops_quality_acceptance_harness_runs(tmp_path: Path) -> None:
    vault_path = Path("docs/examples/vault_test_seed").resolve()
    assert vault_path.exists(), "golden vault seed must exist"

    env = {**os.environ, "PYTHONPATH": str(Path.cwd())}
    result = subprocess.run(
        [sys.executable, "-m", "ops.quality.acceptance_test", "--vault", str(vault_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(Path.cwd()),
        check=True,
    )

    stderr = result.stderr
    assert "CI SUMMARY GATES ok=True" in stderr, "expect acceptance harness to report success"
