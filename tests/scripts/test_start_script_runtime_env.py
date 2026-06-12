"""
Unit tests for export_runtime_env.sh channel-scoped artifact path generation.

Verifies that:
- make test-start-full (COMPOSE_PROJECT_NAME=pkm-test) generates tmp-test/
  artifact paths in the runtime.env file without manual intervention.
- Default/prod startup continues to use /app/tmp artifact paths.

No Docker required. Tests invoke the bash script directly with subprocess
and parse the generated output file.

Issue #1629.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

_TMP_TEST_ARTIFACT_VARS = [
    "INDEX_OUTBOX_PATH",
    "WATCHER_HEARTBEAT_PATH",
    "WORKER_HEARTBEAT_PATH",
    "WATCHER_STATE_DIR",
    "WATCHER_STOP_FILE",
    "WATCHER_STATE_PATH",
]


def _run_export_script(tmp_path: Path, extra_env: dict[str, str]) -> Path:
    """Run scripts/export_runtime_env.sh and return the path to the written env file."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    runtime_env_path = tmp_path / "runtime.env"

    env = os.environ.copy()
    # Provide required vars
    env.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app")
    env["VAULT_ROOT"] = str(vault_root)
    env["RUNTIME_ENV_PATH"] = str(runtime_env_path)
    # Clear artifact path overrides so we test the auto-generation logic
    for var in _TMP_TEST_ARTIFACT_VARS:
        env.pop(var, None)
    env.update(extra_env)

    subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        check=True,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert runtime_env_path.exists(), "export_runtime_env.sh did not create runtime.env"
    return runtime_env_path


def test_pkm_test_runtime_env_exports_tmp_test_artifact_paths(tmp_path: Path) -> None:
    """When COMPOSE_PROJECT_NAME=pkm-test, runtime.env must contain /app/tmp-test/
    artifact paths for all six artifact variables.

    Verify: Issue #1629 AC2 —
      tests/scripts/test_start_script_runtime_env.py::test_pkm_test_runtime_env_exports_tmp_test_artifact_paths
    """
    runtime_env_path = _run_export_script(
        tmp_path,
        extra_env={"COMPOSE_PROJECT_NAME": "pkm-test"},
    )
    text = runtime_env_path.read_text(encoding="utf-8")

    # All artifact path vars must be present and point to /app/tmp-test/
    assert re.search(r"^INDEX_OUTBOX_PATH=/app/tmp-test/", text, re.M), (
        "INDEX_OUTBOX_PATH must point to /app/tmp-test/ in pkm-test runtime.env"
    )
    assert re.search(r"^WATCHER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_HEARTBEAT_PATH must point to /app/tmp-test/ in pkm-test runtime.env"
    )
    assert re.search(r"^WORKER_HEARTBEAT_PATH=/app/tmp-test/", text, re.M), (
        "WORKER_HEARTBEAT_PATH must point to /app/tmp-test/ in pkm-test runtime.env"
    )
    assert re.search(r"^WATCHER_STATE_PATH=/app/tmp-test/", text, re.M), (
        "WATCHER_STATE_PATH must point to /app/tmp-test/ in pkm-test runtime.env"
    )
    assert re.search(r"^WATCHER_STATE_DIR=tmp-test$", text, re.M), (
        "WATCHER_STATE_DIR must be 'tmp-test' in pkm-test runtime.env"
    )
    assert re.search(r"^WATCHER_STOP_FILE=/app/tmp-test/", text, re.M), (
        "WATCHER_STOP_FILE must point to /app/tmp-test/ in pkm-test runtime.env"
    )


def test_pkm_test_runtime_env_no_tmp_slash_artifact_paths(tmp_path: Path) -> None:
    """When COMPOSE_PROJECT_NAME=pkm-test, none of the six artifact vars
    should refer to /app/tmp/ (bare tmp, not tmp-test).

    Verify: Issue #1629 — no /app/tmp/ artifacts leaked into test channel env.
    """
    runtime_env_path = _run_export_script(
        tmp_path,
        extra_env={"COMPOSE_PROJECT_NAME": "pkm-test"},
    )
    text = runtime_env_path.read_text(encoding="utf-8")

    for var in ("INDEX_OUTBOX_PATH", "WATCHER_HEARTBEAT_PATH", "WORKER_HEARTBEAT_PATH",
                "WATCHER_STATE_PATH", "WATCHER_STOP_FILE"):
        # Match lines like VAR=/app/tmp/ (not /app/tmp-test/)
        assert not re.search(
            rf"^{re.escape(var)}=/app/tmp/",
            text,
            re.M,
        ), (
            f"{var} must not point to /app/tmp/ in pkm-test runtime.env; "
            "found a bare /app/tmp/ path that will mix test and prod artifacts."
        )


def test_default_runtime_env_keeps_tmp_artifact_paths(tmp_path: Path) -> None:
    """Without COMPOSE_PROJECT_NAME=pkm-test, runtime.env must not inject
    /app/tmp-test/ overrides — the base defaults from config/runtime.defaults.env
    remain in effect.

    Verify: Issue #1629 AC3 —
      tests/scripts/test_start_script_runtime_env.py::test_default_runtime_env_keeps_tmp_artifact_paths
    """
    runtime_env_path = _run_export_script(
        tmp_path,
        extra_env={
            # No COMPOSE_PROJECT_NAME or explicitly set to something other than pkm-test
        },
    )
    text = runtime_env_path.read_text(encoding="utf-8")

    # The script should NOT inject /app/tmp-test/ artifact overrides for a
    # non-test channel.  The base defaults (config/runtime.defaults.env) already
    # carry /app/tmp/ so no explicit line should be written here.
    for var in _TMP_TEST_ARTIFACT_VARS:
        assert "/app/tmp-test" not in text or f"{var}=/app/tmp-test" not in text, (
            f"{var} must not be set to /app/tmp-test/ in default (non-pkm-test) runtime.env; "
            "test-channel overrides should only fire for COMPOSE_PROJECT_NAME=pkm-test."
        )
    # Specifically: none of the artifact vars should appear pointing at tmp-test
    assert not re.search(r"^INDEX_OUTBOX_PATH=/app/tmp-test", text, re.M)
    assert not re.search(r"^WATCHER_HEARTBEAT_PATH=/app/tmp-test", text, re.M)
    assert not re.search(r"^WORKER_HEARTBEAT_PATH=/app/tmp-test", text, re.M)
    assert not re.search(r"^WATCHER_STATE_PATH=/app/tmp-test", text, re.M)
    assert not re.search(r"^WATCHER_STOP_FILE=/app/tmp-test", text, re.M)
    assert not re.search(r"^WATCHER_STATE_DIR=tmp-test", text, re.M)


def test_pkm_test_runtime_env_via_path_detection(tmp_path: Path) -> None:
    """Test-channel detection also triggers when RUNTIME_ENV_PATH is under
    a tmp-test/ directory (even if COMPOSE_PROJECT_NAME is not explicitly set).

    This covers the case where export_runtime_env.sh is invoked directly
    with a tmp-test path but without an explicit project name env var.
    """
    tmp_test_dir = tmp_path / "tmp-test"
    tmp_test_dir.mkdir(parents=True, exist_ok=True)
    vault_root = tmp_path / "vault"
    vault_root.mkdir(parents=True, exist_ok=True)

    runtime_env_path = tmp_test_dir / "runtime.env"

    env = os.environ.copy()
    env.setdefault("DATABASE_URL", "postgresql+psycopg://app:app@db:5432/app")
    env["VAULT_ROOT"] = str(vault_root)
    env["RUNTIME_ENV_PATH"] = str(runtime_env_path)
    for var in _TMP_TEST_ARTIFACT_VARS:
        env.pop(var, None)
    env.pop("COMPOSE_PROJECT_NAME", None)

    subprocess.run(
        ["bash", "scripts/export_runtime_env.sh"],
        check=True,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )

    assert runtime_env_path.exists()
    text = runtime_env_path.read_text(encoding="utf-8")

    assert re.search(r"^WATCHER_STATE_DIR=tmp-test$", text, re.M), (
        "WATCHER_STATE_DIR must be 'tmp-test' when RUNTIME_ENV_PATH is under tmp-test/"
    )
    assert re.search(r"^INDEX_OUTBOX_PATH=/app/tmp-test/", text, re.M), (
        "INDEX_OUTBOX_PATH must point to /app/tmp-test/ when RUNTIME_ENV_PATH is under tmp-test/"
    )
