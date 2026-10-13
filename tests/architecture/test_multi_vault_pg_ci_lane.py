from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.ops.pg_acceptance import NIGHTLY_SELECTORS, SELECTORS, pytest_arguments

REPO_ROOT = Path(__file__).resolve().parents[2]
PG_TARGETS = (
    "tests/migrations/test_multi_vault_outbox_upgrade.py",
    "tests/services/test_multi_vault_outbox_dual_key_dedup.py",
    "tests/migrations/test_mvr05a_residual_binding_keys.py",
    "tests/migrations/test_multi_vault_ingest_projection_keys.py",
    "tests/migrations/test_multi_vault_replay_projection_backfill.py",
    "tests/integration/test_multi_vault_projection_isolation.py",
    "tests/stores/test_multi_vault_store_reset_scope.py",
    "tests/instance/test_file_state_binding_key.py",
    "tests/services/test_vault_sync_binding_scope.py",
)


def _runner_step(workflow: str, step_name: str) -> str:
    marker = workflow.index(step_name)
    start = workflow.index("python -m app.ops.pg_acceptance", marker)
    end = workflow.index("\n\n", start)
    return workflow[start:end]


def test_mvr05_pg_targets_run_on_provisioned_postgres_and_cannot_skip() -> None:
    """MVR-05A proofs use the same result guard in provisioned PG lanes."""
    nightly = (REPO_ROOT / ".github/workflows/integration-nightly.yaml").read_text()
    invocation = _runner_step(nightly, "Bounded PG verification lane")
    assert "python -m app.ops.pg_acceptance --ci --nightly" in invocation
    assert "--rootdir=." in pytest_arguments(nightly=True)
    assert "-c" in pytest_arguments(nightly=True)
    assert len(NIGHTLY_SELECTORS) == len(set(NIGHTLY_SELECTORS))
    assert all((REPO_ROOT / selector.split("::")[0]).is_file() for selector in NIGHTLY_SELECTORS)

    for target in PG_TARGETS:
        assert target in NIGHTLY_SELECTORS
        assert target in SELECTORS


@pytest.mark.parametrize("case", ("pass", "imported-skip", "uncollected"))
def test_required_pg_lane_rejects_imported_fixture_skip(tmp_path, case: str) -> None:
    """The exact nightly runner rejects a skip from the real imported PG fixture."""
    source = "import pytest\n"
    if case == "imported-skip":
        source += (
            "from tests.migrations.test_multi_vault_ingest_projection_keys "
            "import scratch_db_factory\n"
            "@pytest.mark.pg\ndef test_required(scratch_db_factory):\n"
            "    assert scratch_db_factory()\n"
        )
    else:
        marker = "@pytest.mark.pg\n" if case == "pass" else ""
        source += marker + "def test_required():\n    assert True\n"
    (tmp_path / "test_required.py").write_text(source)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for key in ("DATABASE_URL", "DB_DSN", "PYTEST_ADDOPTS"):
        env.pop(key, None)
    command = (
        "from app.ops import pg_acceptance as p; "
        "p.NIGHTLY_SELECTORS=('test_required.py',); "
        "raise SystemExit(p.main(['--ci', '--nightly']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == (0 if case == "pass" else 78), result.stdout + result.stderr
    if case == "pass":
        summary = json.loads(result.stdout.split("YGGDRASIL_PG_ACCEPTANCE=")[-1])
        assert summary["selected"] == summary["passed"] == 1
        assert summary["required_selectors"] == ["test_required.py"]
        assert summary["passed_nodeids"] == ["test_required.py::test_required"]
    else:
        assert "YGGDRASIL_PG_ACCEPTANCE=refused" in result.stdout
    if case == "imported-skip":
        assert "1 skipped" in result.stdout
        # The optional developer invocation retains its explicit skip; only the
        # required lane turns that incomplete result into a delivery refusal.
        optional = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "test_required.py"],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert optional.returncode == 0, optional.stdout + optional.stderr
        assert "1 skipped" in optional.stdout
