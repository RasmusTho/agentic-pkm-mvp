"""Test suite for bootstrap reset functionality."""
import os
import pathlib
import shutil
import subprocess

import pytest


if not shutil.which("docker"):
    pytestmark = pytest.mark.skip(reason="docker is required for reset-zero-force tests")

def test_reset_zero_force_exits_zero():
    """Test that make reset-zero-force exits with code 0."""
    result = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}: {result.stderr}"


def test_reset_zero_force_removes_vault_test():
    """Test that reset-zero-force removes vault-test directory."""
    vault_test_dir = pathlib.Path("vault-test")

    # Create test vault
    vault_test_dir.mkdir(exist_ok=True)
    (vault_test_dir / "test_file.md").touch()
    assert vault_test_dir.exists(), "vault-test dir should exist before reset"

    # Run reset
    result = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    assert result.returncode == 0
    assert not vault_test_dir.exists(), "vault-test dir should be removed after reset"


def test_reset_zero_force_removes_watcher_pause():
    """Test that reset-zero-force removes .watcher_pause file."""
    pause_file = pathlib.Path(".watcher_pause")

    # Create pause file
    pause_file.touch()
    assert pause_file.exists(), ".watcher_pause should exist before reset"

    # Run reset
    result = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    assert result.returncode == 0
    assert not pause_file.exists(), ".watcher_pause should be removed after reset"


def test_reset_zero_force_idempotent():
    """Test that running reset-zero-force twice produces identical state."""
    # Create test artifacts
    vault_dir = pathlib.Path("vault-test")
    vault_dir.mkdir(exist_ok=True)
    pathlib.Path(".watcher_pause").touch()
    pathlib.Path("tmp/index-outbox.jsonl").parent.mkdir(exist_ok=True)
    pathlib.Path("tmp/index-outbox.jsonl").touch()

    # First run
    result1 = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    assert result1.returncode == 0

    # Second run (should show no artifacts to clean)
    result2 = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )
    assert result2.returncode == 0
    assert "No runtime artifacts existed" in result2.stdout or "(none found)" in result2.stdout


def test_reset_zero_force_emits_clear_messages():
    """Test that reset-zero-force emits clear human-readable messages."""
    # Create test artifacts
    vault_dir = pathlib.Path("vault-test")
    vault_dir.mkdir(exist_ok=True)

    result = subprocess.run(
        ["make", "reset-zero-force"],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
    )

    assert result.returncode == 0
    # Check for clear success messages
    assert "RESET_COMPLETE=true" in result.stdout
    assert "✓ Reset complete" in result.stdout or "reset" in result.stdout.lower()
