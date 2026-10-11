"""Test suite for bootstrap reset functionality."""
import os
import pathlib
import shutil
import subprocess


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
RESET_SCRIPT = REPO_ROOT / "scripts" / "reset_to_zero.sh"
MAKEFILE = REPO_ROOT / "Makefile"


def _prepare_reset_sandbox(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    shutil.copy2(MAKEFILE, sandbox / "Makefile")

    scripts_dir = sandbox / "scripts"
    scripts_dir.mkdir()
    sandbox_reset_script = scripts_dir / "reset_to_zero.sh"
    shutil.copy2(RESET_SCRIPT, sandbox_reset_script)
    assert sandbox_reset_script.read_bytes() == RESET_SCRIPT.read_bytes()

    compose_file = sandbox / "compose.sandbox.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    bin_dir = sandbox / "bin"
    bin_dir.mkdir()
    docker_record = sandbox / "docker-record.txt"
    docker_executable = bin_dir / "docker"
    docker_executable.write_text(
        """#!/bin/sh
set -eu
printf 'args=%s\\n' "$*" >> "$DOCKER_RECORD"
printf 'pwd=%s\\n' "$PWD" >> "$DOCKER_RECORD"
printf 'compose_file=%s\\n' "${COMPOSE_FILE-}" >> "$DOCKER_RECORD"
printf 'compose_project_name=%s\\n' "${COMPOSE_PROJECT_NAME-}" >> "$DOCKER_RECORD"
exit "${DOCKER_EXIT_CODE:-0}"
""",
        encoding="utf-8",
    )
    docker_executable.chmod(0o755)
    return sandbox, compose_file, docker_record


def _run_reset(
    sandbox: pathlib.Path,
    compose_file: pathlib.Path,
    docker_record: pathlib.Path,
    *,
    docker_exit_code: int = 0,
    inherited_compose_file: pathlib.Path | None = None,
    inherited_project_name: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PATH"] = f"{sandbox / 'bin'}{os.pathsep}{environment.get('PATH', '')}"
    environment["DOCKER_RECORD"] = str(docker_record)
    environment["DOCKER_EXIT_CODE"] = str(docker_exit_code)

    if inherited_compose_file is not None:
        environment["COMPOSE_FILE"] = str(inherited_compose_file)
    if inherited_project_name is not None:
        environment["COMPOSE_PROJECT_NAME"] = inherited_project_name

    # Select the disposable Compose target at the subprocess boundary so inherited
    # caller selectors cannot redirect the copied reset script.
    environment["COMPOSE_FILE"] = str(compose_file)
    environment["COMPOSE_PROJECT_NAME"] = "reset-test-sandbox"
    return subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=sandbox,
        env=environment,
    )


def _create_reset_artifacts(root: pathlib.Path) -> dict[str, bytes]:
    vault_test_dir = root / "vault-test"
    vault_test_dir.mkdir()
    (vault_test_dir / "test_file.md").write_bytes(b"test vault content\n")

    pause_file = root / ".watcher_pause"
    pause_file.write_bytes(b"paused\n")

    runtime_dir = root / "tmp"
    runtime_dir.mkdir()
    runtime_files = {
        "index-outbox.jsonl": b"sandbox outbox\n",
        "runtime.env": b"SANDBOX_RUNTIME=1\n",
    }
    for filename, contents in runtime_files.items():
        (runtime_dir / filename).write_bytes(contents)

    return {
        "vault-test/test_file.md": (vault_test_dir / "test_file.md").read_bytes(),
        ".watcher_pause": pause_file.read_bytes(),
        "tmp/index-outbox.jsonl": (runtime_dir / "index-outbox.jsonl").read_bytes(),
        "tmp/runtime.env": (runtime_dir / "runtime.env").read_bytes(),
    }


def _assert_reset_artifacts_removed(root: pathlib.Path) -> None:
    assert not (root / "vault-test").exists()
    assert not (root / ".watcher_pause").exists()
    assert not (root / "tmp" / "index-outbox.jsonl").exists()
    assert not (root / "tmp" / "runtime.env").exists()


def _assert_artifacts_unchanged(root: pathlib.Path, snapshot: dict[str, bytes]) -> None:
    for relative_path, contents in snapshot.items():
        artifact = root / relative_path
        assert artifact.read_bytes() == contents


def test_reset_zero_force_exits_zero(tmp_path: pathlib.Path):
    """Test that make reset-zero-force exits with code 0."""
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    result = _run_reset(sandbox, compose_file, docker_record)

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}: {result.stderr}"


def test_reset_zero_force_removes_vault_test(tmp_path: pathlib.Path):
    """Test that reset-zero-force removes vault-test directory."""
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    vault_test_dir = sandbox / "vault-test"

    vault_test_dir.mkdir()
    (vault_test_dir / "test_file.md").touch()
    assert vault_test_dir.exists(), "vault-test dir should exist before reset"

    result = _run_reset(sandbox, compose_file, docker_record)

    assert result.returncode == 0
    assert not vault_test_dir.exists(), "vault-test dir should be removed after reset"


def test_reset_zero_force_removes_watcher_pause(tmp_path: pathlib.Path):
    """Test that reset-zero-force removes .watcher_pause file."""
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    pause_file = sandbox / ".watcher_pause"

    pause_file.touch()
    assert pause_file.exists(), ".watcher_pause should exist before reset"

    result = _run_reset(sandbox, compose_file, docker_record)

    assert result.returncode == 0
    assert not pause_file.exists(), ".watcher_pause should be removed after reset"


def test_reset_zero_force_idempotent(tmp_path: pathlib.Path):
    """Test that running reset-zero-force twice produces identical state."""
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    _create_reset_artifacts(sandbox)

    result1 = _run_reset(sandbox, compose_file, docker_record)
    assert result1.returncode == 0

    result2 = _run_reset(sandbox, compose_file, docker_record)

    assert result2.returncode == 0
    assert "No runtime artifacts existed" in result2.stdout or "(none found)" in result2.stdout


def test_reset_zero_force_emits_clear_messages(tmp_path: pathlib.Path):
    """Test that reset-zero-force emits clear human-readable messages."""
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    (sandbox / "vault-test").mkdir()

    result = _run_reset(sandbox, compose_file, docker_record)

    assert result.returncode == 0
    assert "RESET_COMPLETE=true" in result.stdout
    assert "✓ Reset complete" in result.stdout or "reset" in result.stdout.lower()


def test_reset_zero_force_isolates_external_runtime_state(tmp_path: pathlib.Path):
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    _create_reset_artifacts(sandbox)
    outside_snapshot = _create_reset_artifacts(outside)
    outside_compose_file = outside / "compose.external.yaml"
    outside_compose_file.write_text("services: {}\n", encoding="utf-8")

    result = _run_reset(
        sandbox,
        compose_file,
        docker_record,
        inherited_compose_file=outside_compose_file,
        inherited_project_name="caller-existing-project",
    )

    assert result.returncode == 0
    _assert_reset_artifacts_removed(sandbox)
    _assert_artifacts_unchanged(outside, outside_snapshot)
    record = docker_record.read_text(encoding="utf-8")
    assert "args=compose down -v --remove-orphans" in record
    assert f"compose_file={compose_file}" in record
    assert "compose_project_name=reset-test-sandbox" in record


def test_reset_zero_force_ignores_external_compose_selectors(tmp_path: pathlib.Path):
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_snapshot = _create_reset_artifacts(outside)
    outside_compose_file = outside / "compose.external.yaml"
    outside_compose_file.write_text("services: {}\n", encoding="utf-8")
    _create_reset_artifacts(sandbox)

    result = _run_reset(
        sandbox,
        compose_file,
        docker_record,
        inherited_compose_file=outside_compose_file,
        inherited_project_name="caller-existing-project",
    )

    assert result.returncode == 0
    _assert_reset_artifacts_removed(sandbox)
    _assert_artifacts_unchanged(outside, outside_snapshot)
    record = docker_record.read_text(encoding="utf-8")
    assert f"compose_file={compose_file}" in record
    assert "compose_file=" + str(outside_compose_file) not in record
    assert "compose_project_name=reset-test-sandbox" in record
    assert "caller-existing-project" not in record


def test_reset_zero_force_preserves_artifacts_on_teardown_failure(tmp_path: pathlib.Path):
    sandbox, compose_file, docker_record = _prepare_reset_sandbox(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    sandbox_snapshot = _create_reset_artifacts(sandbox)
    outside_snapshot = _create_reset_artifacts(outside)

    result = _run_reset(sandbox, compose_file, docker_record, docker_exit_code=37)

    assert result.returncode != 0
    assert "Docker compose teardown failed (exit code: 37)" in result.stdout
    assert "Error 37" in result.stderr
    _assert_artifacts_unchanged(sandbox, sandbox_snapshot)
    _assert_artifacts_unchanged(outside, outside_snapshot)
    record = docker_record.read_text(encoding="utf-8")
    assert "args=compose down -v --remove-orphans" in record
    assert f"compose_file={compose_file}" in record
