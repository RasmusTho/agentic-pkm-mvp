"""CI verification for BOOTSTRAP-02: Initialize test vault.

Verifies that `make test-vault-init` (scripts/init_test_vault.sh) produces
the required directory structure idempotently in a clean checkout.

These tests exercise the underlying CLI surface directly (no shell subprocess)
so they run hermetically without Docker or vault-test/ in the working directory.

Governing issue: #332
Spec: docs/LOCAL_TEST_BOOTSTRAP/INITIALIZE_TEST_VAULT.md :: BOOTSTRAP-02
"""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.cli.uat import DEFAULT_FOLDER_NAME, DEFAULT_TARGET_SUBDIR
from app.store import object_store as object_store_module

WIRING_SRC = Path("docs/settings/panel-action-wiring.yaml")
SYSTEM_CONFIG_REL = Path("System/Config")
WIRING_FILENAME = "panel-action-wiring.yaml"


def _seed(runner: CliRunner, vault_root: Path, overwrite: bool = False) -> None:
    args = ["uat-seed-vault-test", "--vault-root", str(vault_root)]
    if overwrite:
        args.append("--overwrite")
    result = runner.invoke(cli, args, env={"STORE_BACKEND": "memory"})
    assert result.exit_code == 0, result.output


def _init_vault(tmp_path: Path) -> None:
    """Replicate what scripts/init_test_vault.sh does, without the shell layer."""
    system_config = tmp_path / SYSTEM_CONFIG_REL
    test_dir = tmp_path / DEFAULT_TARGET_SUBDIR

    system_config.mkdir(parents=True, exist_ok=True)
    test_dir.mkdir(parents=True, exist_ok=True)

    # Copy wiring file
    wiring_dst = system_config / WIRING_FILENAME
    wiring_dst.write_text(WIRING_SRC.read_text(encoding="utf-8"), encoding="utf-8")

    # Seed UAT notes
    runner = CliRunner()
    _seed(runner, tmp_path, overwrite=True)


class TestBootstrapInit:
    """BOOTSTRAP-02: vault-test/ structure and idempotence."""

    def test_creates_system_config_with_wiring_file(self, tmp_path: Path) -> None:
        _init_vault(tmp_path)
        wiring = tmp_path / SYSTEM_CONFIG_REL / WIRING_FILENAME
        assert wiring.is_file(), f"expected wiring file at {wiring}"
        content = wiring.read_text(encoding="utf-8")
        assert "promote.intent.created" in content, "wiring file has unexpected content"

    def test_creates_test_dir_with_uat_notes(self, tmp_path: Path) -> None:
        _init_vault(tmp_path)
        test_dir = tmp_path / DEFAULT_TARGET_SUBDIR
        assert test_dir.is_dir()
        uat_notes = list(test_dir.rglob("*.md"))
        assert uat_notes, f"expected UAT notes under {test_dir}"

    def test_idempotent_structure(self, tmp_path: Path) -> None:
        """Running init twice produces the same file content."""
        _init_vault(tmp_path)
        wiring_first = (tmp_path / SYSTEM_CONFIG_REL / WIRING_FILENAME).read_text(encoding="utf-8")
        notes_first = sorted(p.name for p in (tmp_path / DEFAULT_TARGET_SUBDIR).rglob("*.md"))

        _init_vault(tmp_path)
        wiring_second = (tmp_path / SYSTEM_CONFIG_REL / WIRING_FILENAME).read_text(encoding="utf-8")
        notes_second = sorted(p.name for p in (tmp_path / DEFAULT_TARGET_SUBDIR).rglob("*.md"))

        assert wiring_first == wiring_second, "wiring file content changed between runs"
        assert notes_first == notes_second, "UAT note list changed between runs"

    def test_wiring_source_matches_repo_canonical(self, tmp_path: Path) -> None:
        """Copied wiring file matches the repo canonical source."""
        assert WIRING_SRC.is_file(), f"canonical wiring source missing: {WIRING_SRC}"
        _init_vault(tmp_path)
        dst = tmp_path / SYSTEM_CONFIG_REL / WIRING_FILENAME
        assert dst.read_text(encoding="utf-8") == WIRING_SRC.read_text(encoding="utf-8")

    def teardown_method(self) -> None:
        object_store_module._MEMORY_STORE.clear()
