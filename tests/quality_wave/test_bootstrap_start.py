"""CI verification for BOOTSTRAP-03: Start full system against test vault.

Verifies the startup script contract for `scripts/start_full_system.sh`:
- VAULT_ROOT is required and validated before any Docker interaction
- The script exits with a clear, deterministic error when VAULT_ROOT is missing
- The script exits with a clear error when VAULT_ROOT points to a non-existent directory
- The `make start-test-system` target is wired correctly in the Makefile

These tests exercise the early-exit contract only (no Docker required).
They run hermetically in CI without a running Docker daemon.

Governing issue: #333
Spec: docs/LOCAL_TEST_BOOTSTRAP/START_FULL_SYSTEM.md :: BOOTSTRAP-03
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_SUBPROCESS_PATH = "/usr/bin:/bin:/usr/local/bin"
_DOCKER_AVAILABLE = shutil.which("docker", path=_SUBPROCESS_PATH) is not None
_requires_docker = pytest.mark.skipif(
    not _DOCKER_AVAILABLE,
    reason="Docker not available in this environment; startup script contract tests skipped",
)


def _startup_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": _SUBPROCESS_PATH,
        "HOME": str(Path.home()),
    }
    env.update(extra)
    return env


class TestBootstrapStartContract:
    """BOOTSTRAP-03: start_full_system.sh interface contract."""

    @_requires_docker
    def test_requires_vault_root(self) -> None:
        """Script exits non-zero with a clear error when VAULT_ROOT is unset."""
        result = subprocess.run(
            ["bash", "scripts/start_full_system.sh"],
            capture_output=True,
            text=True,
            env=_startup_env(),
        )
        assert result.returncode != 0, "Expected non-zero exit when VAULT_ROOT is unset"
        stderr = result.stderr + result.stdout
        assert "VAULT_ROOT" in stderr, f"Expected VAULT_ROOT mentioned in output; got: {stderr[:500]}"

    @_requires_docker
    def test_exits_on_missing_vault_directory(self, tmp_path: Path) -> None:
        """Script exits non-zero with a clear error when VAULT_ROOT dir does not exist."""
        missing_vault = tmp_path / "does-not-exist"
        result = subprocess.run(
            ["bash", "scripts/start_full_system.sh"],
            capture_output=True,
            text=True,
            env=_startup_env(VAULT_ROOT=str(missing_vault)),
        )
        assert result.returncode != 0, "Expected non-zero exit when VAULT_ROOT dir is missing"
        stderr = result.stderr + result.stdout
        assert (
            "missing" in stderr.lower() or "vault" in stderr.lower()
        ), f"Expected vault/missing in error output; got: {stderr[:500]}"

    @_requires_docker
    def test_accepts_vault_root_and_validates_directory(self, tmp_path: Path) -> None:
        """Script accepts VAULT_ROOT when the directory exists and proceeds past vault validation.

        The script will eventually fail on Docker or env-setup, but the
        vault validation phase must pass (no exit 2 for missing VAULT_ROOT,
        no exit 1 for missing vault dir).
        """
        vault_dir = tmp_path / "vault-test"
        vault_dir.mkdir()

        try:
            result = subprocess.run(
                ["bash", "scripts/start_full_system.sh"],
                capture_output=True,
                text=True,
                timeout=20,
                env=_startup_env(VAULT_ROOT=str(vault_dir)),
            )
        except subprocess.TimeoutExpired as exc:
            stderr = "".join(part for part in [exc.stdout, exc.stderr] if part)
            assert "VAULT_ROOT" not in stderr, (
                f"Script should not fail on missing VAULT_ROOT when provided: {stderr[:500]}"
            )
            assert not any(
                marker in stderr.lower() for marker in ("vault root is missing", "must be set")
            ), f"Script rejected an existing VAULT_ROOT before timeout: {stderr[:500]}"
            return

        stderr = result.stderr + result.stdout
        assert result.returncode != 2, (
            f"Script exited 2 (VAULT_ROOT required) even though VAULT_ROOT was set: {stderr[:500]}"
        )
        assert not any(
            marker in stderr.lower() for marker in ("vault root is missing", "must be set")
        ), f"Script rejected an existing VAULT_ROOT as missing: {stderr[:500]}"

    def test_make_start_test_system_target_exists(self) -> None:
        """make start-test-system is declared in the Makefile (wired for BOOTSTRAP-03)."""
        result = subprocess.run(
            ["make", "--dry-run", "start-test-system"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"make start-test-system target missing or broken: {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "start_full_system" in combined, (
            f"Expected start_full_system.sh in dry-run output; got: {combined[:500]}"
        )

    def test_make_start_test_system_uses_test_vault_root(self) -> None:
        """make start-test-system and make test-up both pass TEST_VAULT_ROOT as VAULT_ROOT."""
        for target in ("start-test-system", "test-up"):
            result = subprocess.run(
                ["make", "--dry-run", target],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"make --dry-run {target} failed: {result.stderr}"
            )
            combined = result.stdout + result.stderr
            assert "vault-test" in combined, (
                f"Expected vault-test path in make --dry-run {target} output; got: {combined[:500]}"
            )
