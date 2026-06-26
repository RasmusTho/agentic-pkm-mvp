"""
Static inspection tests for canonical startup targets (Issue #967, #1629).

Verifies that the Makefile startup targets for test and prod channels
bind the correct compose file, compose project name, PKM_ENVIRONMENT,
and vault root — and that both require an explicit VAULT_ROOT.

Also verifies (Issue #1629) that make test-start-full causes the generated
runtime.env to carry test-scoped artifact paths so containers under
pkm-test write to /app/tmp-test/ without manual post-processing.

No Docker required. Tests read the Makefile and invoke export_runtime_env.sh
directly.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def _makefile_target_body(makefile_text: str, target_name: str) -> str | None:
    """Extract the body of a Makefile target.

    Anchors on `^<target>:` to avoid matching .PHONY declarations.
    Body ends at the next non-tab line (next target or variable).
    """
    pattern = re.compile(
        rf"^{re.escape(target_name)}\s*:.*?(?=\n\S|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    match = pattern.search(makefile_text)
    return match.group(0) if match else None


def test_test_start_target_binds_test_environment() -> None:
    """test-start-full must explicitly bind PKM_ENVIRONMENT=test and use
    the test compose overlay and project name.

    Verify: Issue #967 AC1 —
      tests/ops/test_release_channel_startup_targets.py::test_test_start_target_binds_test_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "test-start-full")

    assert body is not None, (
        "Could not find 'test-start-full' target in Makefile. "
        "A canonical test full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?test["\']?', body), (
        "Makefile 'test-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=test. Test startup must bind this to prevent "
        "test services from running with prod environment (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-test["\']?', body), (
        "Makefile 'test-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-test. "
        "Test and prod channels must use distinct project names (Issue #967)."
    )
    assert re.search(r'docker-compose\.test\.yml', body), (
        "Makefile 'test-start-full' target does not reference docker-compose.test.yml. "
        "The test overlay must be included in the test startup (Issue #967)."
    )


def test_prod_start_target_binds_prod_environment() -> None:
    """prod-start-full must explicitly bind PKM_ENVIRONMENT=prod and use
    the prod compose overlay and project name.

    Verify: Issue #967 AC2 —
      tests/ops/test_release_channel_startup_targets.py::test_prod_start_target_binds_prod_environment
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    body = _makefile_target_body(makefile_text, "prod-start-full")

    assert body is not None, (
        "Could not find 'prod-start-full' target in Makefile. "
        "A canonical prod full-stack startup target is required (Issue #967)."
    )
    assert re.search(r'PKM_ENVIRONMENT\s*=\s*["\']?prod["\']?', body), (
        "Makefile 'prod-start-full' target does not explicitly set "
        "PKM_ENVIRONMENT=prod. Prod startup must bind this explicitly "
        "to prevent implicit env inheritance (Issue #967)."
    )
    assert re.search(r'COMPOSE_PROJECT_NAME\s*=\s*["\']?pkm-prod["\']?', body), (
        "Makefile 'prod-start-full' target does not set COMPOSE_PROJECT_NAME=pkm-prod. "
        "Prod channel must use an explicit project name (Issue #967)."
    )
    assert re.search(r'docker-compose\.prod\.yml', body), (
        "Makefile 'prod-start-full' target does not reference docker-compose.prod.yml. "
        "The prod overlay must be included in the prod startup (Issue #967)."
    )


def test_full_start_targets_use_channel_specific_vault_binding() -> None:
    """Full start targets must use channel-appropriate vault binding.

    Test startup remains explicitly supplied by the caller, while prod startup
    must not require an inline VAULT_ROOT because the prod channel default is
    loaded from .env.prod.local.

    Verify: Issue #967 AC3 —
      tests/ops/test_release_channel_startup_targets.py::test_full_start_targets_use_channel_specific_vault_binding
    """
    makefile_text = MAKEFILE.read_text(encoding="utf-8")

    test_body = _makefile_target_body(makefile_text, "test-start-full")
    assert test_body is not None, "Could not find 'test-start-full' target in Makefile."
    assert "require-vault-root" in test_body and re.search(r'VAULT_ROOT', test_body), (
        "Makefile 'test-start-full' must still require an explicit test VAULT_ROOT."
    )

    prod_body = _makefile_target_body(makefile_text, "prod-start-full")
    assert prod_body is not None, "Could not find 'prod-start-full' target in Makefile."
    assert "require-vault-root" not in prod_body, (
        "Makefile 'prod-start-full' must use .env.prod.local defaults instead of "
        "requiring an inline VAULT_ROOT."
    )
    assert not re.search(r'\bVAULT_ROOT\s*=', prod_body), (
        "Makefile 'prod-start-full' must not override the prod channel vault default "
        "with an inline VAULT_ROOT assignment."
    )


def test_test_start_full_uses_tmp_test_runtime_artifact_paths(tmp_path: Path) -> None:
    """make test-start-full must generate a runtime.env file under tmp-test/
    that carries /app/tmp-test/ artifact paths for all six artifact variables,
    so pkm-test containers never write runtime artifacts to /app/tmp/.

    This test invokes export_runtime_env.sh with COMPOSE_PROJECT_NAME=pkm-test
    (mirroring what make test-start-full sets) and verifies the output file
    contains the expected test-scoped paths.  No Docker required.

    Verify: Issue #1629 AC1 —
      tests/ops/test_release_channel_startup_targets.py::test_test_start_full_uses_tmp_test_runtime_artifact_paths
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)
    runtime_env_path = tmp_path / "runtime.env"

    env = os.environ.copy()
    env["COMPOSE_PROJECT_NAME"] = "pkm-test"
    env["VAULT_ROOT"] = str(vault_root)
    env["RUNTIME_ENV_PATH"] = str(runtime_env_path)
    env.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app_test")
    # Clear any operator overrides so we test the auto-generation path
    for var in (
        "WATCHER_STATE_DIR",
        "WATCHER_STOP_FILE",
        "INDEX_OUTBOX_PATH",
        "WATCHER_HEARTBEAT_PATH",
        "WORKER_HEARTBEAT_PATH",
        "WATCHER_STATE_PATH",
    ):
        env.pop(var, None)

    subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        check=True,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert runtime_env_path.exists(), (
        "export_runtime_env.sh did not create runtime.env for pkm-test channel"
    )
    text = runtime_env_path.read_text(encoding="utf-8")

    assert re.search(r"^INDEX_OUTBOX_PATH=/app/tmp-test/", text, re.M), (
        "INDEX_OUTBOX_PATH must point to /app/tmp-test/ for the pkm-test channel "
        "(Issue #1629: test containers were inheriting /app/tmp defaults)"
    )
    assert re.search(r"^WATCHER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_HEARTBEAT_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WORKER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WORKER_HEARTBEAT_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STATE_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_STATE_PATH must point to /app/tmp-test/ for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STATE_DIR=tmp-test$", text, re.M), (
        "WATCHER_STATE_DIR must be 'tmp-test' for the pkm-test channel"
    )
    assert re.search(r"^WATCHER_STOP_FILE=/app/tmp-test/", text, re.M), (
        "WATCHER_STOP_FILE must point to /app/tmp-test/ for the pkm-test channel"
    )
    # No bare /app/tmp/ artifact paths should remain for these variables
    for var in ("INDEX_OUTBOX_PATH", "WATCHER_HEARTBEAT_PATH", "WORKER_HEARTBEAT_PATH",
                "WATCHER_STATE_PATH", "WATCHER_STOP_FILE"):
        assert not re.search(rf"^{re.escape(var)}=/app/tmp/", text, re.M), (
            f"{var} must not point to bare /app/tmp/ in pkm-test runtime.env"
        )
