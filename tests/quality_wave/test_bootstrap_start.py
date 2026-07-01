"""CI verification for BOOTSTRAP-03: Start full system against test vault.

Verifies the startup script contract for `scripts/start_full_system.sh`:
- An *unset* VAULT_ROOT now boots into a no-vault idle posture (NOT exit 2) —
  the #2005 flip of the #1991 fail-exit precondition to idle-until-opened.
- A *set-but-missing* VAULT_ROOT still exits non-zero with a clear error
  (the open-vault-on-missing-vault regression guard stays loud).
- The `make start-test-system` target is wired correctly in the Makefile.

These tests exercise the early contract only (no Docker required for the
hermetic legs).

Governing issue: #333 (original), #2005 (no-vault idle flip)
Spec: docs/LOCAL_TEST_BOOTSTRAP/START_FULL_SYSTEM.md :: BOOTSTRAP-03
      docs/VAULT_OPTIONAL_RUNTIME/BOOT_RUNTIME_WITHOUT_VAULT.md
"""
from __future__ import annotations

import os
import re
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


def _extract_shell_function(script: str, name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{\n.*?^}}\n", script, re.MULTILINE | re.DOTALL)
    assert match is not None, f"{name} function not found"
    return match.group(0)


def _watcher_wait_functions() -> str:
    script = Path("scripts/start_full_system.sh").read_text(encoding="utf-8")
    return "\n\n".join(
        [
            _extract_shell_function(script, "watcher_heartbeat_ready"),
            _extract_shell_function(script, "wait_for_watcher_heartbeat"),
        ]
    )


class TestBootstrapStartContract:
    """BOOTSTRAP-03: start_full_system.sh interface contract."""

    def test_unset_vault_root_boots_idle_not_exit_2(self) -> None:
        """#2005: an unset VAULT_ROOT no longer exits 2 — it boots no-vault idle.

        Hermetic (no Docker): a fake `docker` that fails loudly proves the
        script reached the no-vault idle posture (no exit 2, idle banner) before
        any real Docker interaction. Mirrors the fake-docker pattern in
        tests/uat/test_negative_safety_integrated_runtime.py.
        """
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            fake_docker = Path(td) / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\necho fake docker should not run >&2\nexit 99\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)
            result = subprocess.run(
                ["bash", "scripts/start_full_system.sh"],
                capture_output=True,
                text=True,
                timeout=30,
                env=_startup_env(PATH=f"{td}:{_SUBPROCESS_PATH}"),
            )

        combined = result.stdout + result.stderr
        # The #1991 fail-exit (exit 2 "VAULT_ROOT is required") is gone.
        assert result.returncode != 2, (
            f"Unset VAULT_ROOT must not exit 2 (no-vault idle flip); got rc={result.returncode}: {combined[:600]}"
        )
        assert "VAULT_ROOT is required" not in combined, (
            f"The exit-2 'VAULT_ROOT is required' gate must be gone: {combined[:600]}"
        )
        assert "no-vault idle posture" in combined, (
            f"Expected the no-vault idle banner; got: {combined[:600]}"
        )

    def test_exits_on_missing_vault_directory(self, tmp_path: Path) -> None:
        """Script exits non-zero with a clear error when VAULT_ROOT dir does not exist."""
        missing_vault = tmp_path / "does-not-exist"
        fake_docker = tmp_path / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "info" ]; then exit 0; fi\n'
            "echo fake docker should not reach compose commands >&2\n"
            "exit 99\n",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        result = subprocess.run(
            ["bash", "scripts/start_full_system.sh"],
            capture_output=True,
            text=True,
            env=_startup_env(
                PATH=f"{tmp_path}:{_SUBPROCESS_PATH}",
                START_FLIGHT_RECORDER="0",
                VAULT_ROOT=str(missing_vault),
            ),
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
        """make start-test-system is declared in the Makefile and defaults to idle.

        No vault is configured here: the start target must NOT force the
        repo-local scratch vault. A fresh checkout should dry-run with an empty
        VAULT_ROOT so the runtime boots the no-vault idle posture (#2005).
        """
        env = {k: v for k, v in os.environ.items() if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT", "VAULT_ROOT_TEST")}
        result = subprocess.run(
            ["make", "--dry-run", "start-test-system"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"make start-test-system must resolve without a vault (idle boot): {result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "start_full_system" in combined, (
            f"Expected start_full_system.sh in dry-run output; got: {combined[:500]}"
        )
        assert 'VAULT_ROOT=""' in combined, (
            f"Expected start-test-system to leave VAULT_ROOT empty by default; got: {combined[:500]}"
        )
        assert "vault-test" not in combined, (
            f"start-test-system must not force the repo-local scratch vault by default; got: {combined[:500]}"
        )

    def test_make_start_test_system_ignores_plain_vault_root(self) -> None:
        """start-test-system and test-up do not select from plain VAULT_ROOT.

        Plain VAULT_ROOT may point at the operator/prod vault. The test-channel
        targets use TEST_VAULT_ROOT / VAULT_ROOT_TEST or the repo-local
        vault-test scratch fallback instead.
        """
        operator_vault = "/tmp/uat-operator-test-vault"
        for target in ("start-test-system", "test-up"):
            result = subprocess.run(
                ["make", "--dry-run", target],
                capture_output=True,
                text=True,
                env={**os.environ, "VAULT_ROOT": operator_vault},
            )
            assert result.returncode == 0, (
                f"make --dry-run {target} failed: {result.stderr}"
            )
            combined = result.stdout + result.stderr
            assert operator_vault not in combined, (
                f"Plain operator VAULT_ROOT must not select test vault for "
                f"make --dry-run {target}; got: {combined[:500]}"
            )
            expected_binding = 'VAULT_ROOT=""' if target == "start-test-system" else 'VAULT_ROOT="vault-test"'
            assert expected_binding in combined, (
                f"Unexpected VAULT_ROOT binding for make --dry-run {target}; "
                f"got: {combined[:500]}"
            )

    def test_make_test_targets_honor_vault_root_test_override(self) -> None:
        """The per-channel VAULT_ROOT_TEST override is honored and threads through."""
        operator_vault = "/tmp/uat-per-channel-test-vault"
        env = {k: v for k, v in os.environ.items() if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT")}
        env["VAULT_ROOT_TEST"] = operator_vault
        result = subprocess.run(
            ["make", "--dry-run", "test-up"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"make --dry-run test-up failed with VAULT_ROOT_TEST set: {result.stderr}"
        )
        assert operator_vault in (result.stdout + result.stderr), (
            "Expected VAULT_ROOT_TEST to be honored as the test vault root"
        )

    def test_start_targets_boot_without_a_vault_selected(self) -> None:
        """The runtime must start without a vault (#2005) on the start-test path."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT", "VAULT_ROOT_TEST")
        }
        result = subprocess.run(
            ["make", "--dry-run", "start-test-system"],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stderr + result.stdout
        assert result.returncode == 0, (
            f"make start-test-system must boot idle without a vault: {combined[:500]}"
        )
        assert 'VAULT_ROOT=""' in combined, (
            f"start-test-system must resolve to an empty VAULT_ROOT by default: {combined[:500]}"
        )
        assert "is required" not in combined, (
            f"start-test-system must not demand a vault to start: {combined[:500]}"
        )

    def test_make_start_test_system_explicit_missing_test_vault_fails_loud(self, tmp_path: Path) -> None:
        """An explicit missing TEST_VAULT_ROOT must still fail loudly."""
        missing_vault = tmp_path / "missing-test-vault"
        fake_docker = tmp_path / "docker"
        fake_docker.write_text(
            "#!/usr/bin/env bash\n"
            'if [ "${1:-}" = "info" ]; then exit 0; fi\n'
            "echo fake docker should not reach compose commands >&2\n"
            "exit 99\n",
            encoding="utf-8",
        )
        fake_docker.chmod(0o755)
        result = subprocess.run(
            ["make", "start-test-system", f"TEST_VAULT_ROOT={missing_vault}"],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "PATH": f"{tmp_path}:{_SUBPROCESS_PATH}",
                "VAULT_ROOT": "",
            },
        )
        combined = result.stdout + result.stderr
        assert result.returncode != 0, (
            f"Explicit missing TEST_VAULT_ROOT must fail loudly; got rc={result.returncode}: {combined[:500]}"
        )
        assert "Vault root is missing" in combined or "missing" in combined.lower(), (
            f"Expected a clear missing-vault error for explicit TEST_VAULT_ROOT; got: {combined[:500]}"
        )

    def test_make_start_test_system_uses_seeded_repo_local_vault(self, tmp_path: Path) -> None:
        """After test-vault-init creates vault-test, start-test-system binds it."""
        (tmp_path / "vault-test").mkdir()
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT", "VAULT_ROOT_TEST")
        }
        result = subprocess.run(
            [
                "make",
                "--dry-run",
                "-f",
                str(Path.cwd() / "Makefile"),
                "-C",
                str(tmp_path),
                "start-test-system",
            ],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stderr + result.stdout
        assert result.returncode == 0, (
            f"make start-test-system must resolve with a seeded vault-test: {combined[:500]}"
        )
        assert 'VAULT_ROOT="vault-test"' in combined, (
            f"Expected seeded repo-local vault-test to bind start-test-system; got: {combined[:500]}"
        )

    def test_start_test_system_vault_root_sees_vault_created_earlier_in_same_invocation(
        self,
    ) -> None:
        """A chained `make test-vault-init start-test-system` must observe the
        vault-test/ that test-vault-init just created, not a parse-time snapshot.

        GNU Make caches `$(wildcard)` directory reads for the whole invocation,
        so `START_TEST_SYSTEM_VAULT_ROOT` must probe with `$(shell test -d ...)`
        (always forks fresh) rather than `$(wildcard ...)` (cached).
        """
        repo_root = Path.cwd()
        vault_dir = repo_root / "vault-test"
        assert not vault_dir.exists(), "test requires a clean vault-test/ state"
        probe_mk = repo_root / "_probe_vault_root.mk"
        probe_mk.write_text(
            'probe-vault-root:\n\t@echo "PROBE_VAULT_ROOT=$(START_TEST_SYSTEM_VAULT_ROOT)"\n',
            encoding="utf-8",
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT", "VAULT_ROOT_TEST")
        }
        try:
            result = subprocess.run(
                [
                    "make",
                    "-f",
                    "Makefile",
                    "-f",
                    probe_mk.name,
                    "test-vault-init",
                    "probe-vault-root",
                ],
                capture_output=True,
                text=True,
                env=env,
                cwd=repo_root,
            )
            combined = result.stdout + result.stderr
            assert result.returncode == 0, combined[:800]
            assert "PROBE_VAULT_ROOT=vault-test" in combined, (
                "START_TEST_SYSTEM_VAULT_ROOT must see the vault-test/ dir created "
                f"earlier in the same make invocation; got: {combined[:800]}"
            )
        finally:
            probe_mk.unlink(missing_ok=True)
            shutil.rmtree(vault_dir, ignore_errors=True)

    def test_seed_flow_uses_repo_local_vault_test_fallback(self) -> None:
        """Provisioning can seed the repo-local test scratch vault by default."""
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in ("VAULT_ROOT", "TEST_VAULT_ROOT", "VAULT_ROOT_TEST")
        }
        result = subprocess.run(
            ["make", "--dry-run", "test-bootstrap"],
            capture_output=True,
            text=True,
            env=env,
        )
        combined = result.stderr + result.stdout
        assert result.returncode == 0, (
            f"test-bootstrap should dry-run with repo-local vault-test fallback: "
            f"{combined[:500]}"
        )
        assert 'VAULT_ROOT="vault-test"' in combined
        assert '--vault-root "vault-test"' in combined

    def test_watcher_readiness_accepts_heartbeat_at_timeout_boundary(self) -> None:
        """A heartbeat observed on the timeout boundary must satisfy startup readiness."""
        functions = _watcher_wait_functions()
        result = subprocess.run(
            [
                "bash",
                "-c",
                functions
                + r'''
SECONDS=0
WATCHER_HEARTBEAT_TIMEOUT=3
WATCHER_HEARTBEAT_POLL_SECONDS=2
container_watcher_heartbeat_path=/app/tmp-test/watcher_heartbeat.json
run_docker_compose() {
  [ "$SECONDS" -ge 3 ]
}
sleep() {
  SECONDS=$((SECONDS + $1))
}
write_startup_status() {
  echo "status:$*"
}
capture_startup_logs() {
  echo "capture"
}
debug_dump() {
  echo "debug"
}
wait_for_watcher_heartbeat
printf "SECONDS=%s EXIT_REASON=%s\n" "$SECONDS" "${EXIT_REASON:-}"
''',
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr + result.stdout
        assert "SECONDS=3 EXIT_REASON=" in result.stdout
        assert "watcher_heartbeat_timeout" not in result.stdout + result.stderr

    def test_watcher_readiness_timeout_reports_diagnostics(self) -> None:
        """A truly missing watcher heartbeat remains a strict failure with diagnostics."""
        functions = _watcher_wait_functions()
        result = subprocess.run(
            [
                "bash",
                "-c",
                functions
                + r'''
SECONDS=0
WATCHER_HEARTBEAT_TIMEOUT=1
WATCHER_HEARTBEAT_POLL_SECONDS=2
container_watcher_heartbeat_path=/app/tmp-test/watcher_heartbeat.json
run_docker_compose() {
  return 1
}
sleep() {
  SECONDS=$((SECONDS + $1))
}
write_startup_status() {
  echo "status:$*"
}
capture_startup_logs() {
  echo "capture"
}
debug_dump() {
  echo "debug"
}
wait_for_watcher_heartbeat
''',
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        combined = result.stdout + result.stderr
        assert result.returncode == 1
        assert "status:0 watcher_heartbeat_timeout" in combined
        assert "capture" in combined
        assert "debug" in combined
        assert "watcher heartbeat not detected at /app/tmp-test/watcher_heartbeat.json" in combined
