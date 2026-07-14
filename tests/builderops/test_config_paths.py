from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.builderops.config as builderops_config
from app.builderops.store import SqliteBuilderOpsStore


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_default_db_path_is_host_stable_and_cwd_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_cwd = tmp_path / "worktree-a"
    second_cwd = tmp_path / "worktree-b"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.chdir(first_cwd)
    first = builderops_config.load_paths({})
    monkeypatch.chdir(second_cwd)
    second = builderops_config.load_paths({})

    assert first.db_path == second.db_path
    assert first.db_path == builderops_config.default_state_dir() / "builderops.sqlite3"
    assert first.db_path.is_absolute()


def test_host_stable_default_still_confined_outside_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "shared-vault"
    monkeypatch.setattr(
        builderops_config,
        "default_state_dir",
        lambda: vault / "builderops",
    )
    monkeypatch.setattr(builderops_config, "_legacy_store_paths", lambda: ())

    with pytest.raises(ValueError, match="outside BUILDEROPS_VAULT_ROOT"):
        builderops_config.load_paths({"BUILDEROPS_VAULT_ROOT": str(vault)})


def test_explicit_overrides_unchanged(tmp_path: Path) -> None:
    from app.ops.builderops_startup import _builderops_db_path

    relative_state_dir = Path("explicit-relative-state")
    state_paths = builderops_config.load_paths(
        {"BUILDEROPS_STATE_DIR": str(relative_state_dir)}
    )
    explicit_db_path = Path("explicit-relative.sqlite3")
    db_paths = builderops_config.load_paths(
        {"BUILDEROPS_DB_PATH": str(explicit_db_path)}
    )
    cli_override = Path("cli-relative.sqlite3")
    cli_paths = builderops_config.load_paths({}, db_path_override=cli_override)

    assert state_paths.state_dir == relative_state_dir
    assert state_paths.db_path == relative_state_dir / "builderops.sqlite3"
    assert db_paths.db_path == explicit_db_path
    assert cli_paths.db_path == cli_override
    assert _builderops_db_path(tmp_path, {}) == str(
        builderops_config.default_state_dir() / "builderops.sqlite3"
    )
    assert _builderops_db_path(
        tmp_path,
        {"BUILDEROPS_STATE_DIR": str(relative_state_dir)},
    ) == str(tmp_path / relative_state_dir / "builderops.sqlite3")
    assert _builderops_db_path(
        tmp_path,
        {"BUILDEROPS_DB_PATH": str(explicit_db_path)},
    ) == str(explicit_db_path)


def test_explicit_db_override_does_not_require_resolvable_home(tmp_path: Path) -> None:
    explicit_db = tmp_path / "explicit" / "builderops.sqlite3"
    code = f"""
from pathlib import Path
from unittest.mock import patch

with patch.object(Path, "home", side_effect=RuntimeError("home unavailable")):
    from app.builderops.config import load_paths
    paths = load_paths({{"BUILDEROPS_DB_PATH": {str(explicit_db)!r}}})
    assert paths.db_path == Path({str(explicit_db)!r})
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_implicit_cli_fails_before_initializing_when_legacy_store_exists(
    tmp_path: Path,
) -> None:
    legacy_db = tmp_path / "runtime" / "builderops" / "builderops.sqlite3"
    legacy_store = SqliteBuilderOpsStore(legacy_db)
    legacy_store.initialize()
    legacy_store.create_agent_worklog(
        id="awl_legacy_cutover_guard",
        summary="Legacy state must not be orphaned",
        body="The implicit consolidated store must fail before initialization.",
        task_context={"issue": "#3686"},
        source_refs=[{"ref_type": "github_issue", "ref": "#3686"}],
        created_by={"actor_type": "agent", "id": "cutover-test"},
    )
    home = tmp_path / "home"
    consolidated_db = home / ".local" / "state" / "builderops" / "builderops.sqlite3"
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO_ROOT)
    for key in ("BUILDEROPS_DB_PATH", "BUILDEROPS_STATE_DIR", "BUILDEROPS_VAULT_ROOT"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, "-m", "app.builderops", "builderops", "list", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Refusing implicit host-stable BuilderOps store selection" in (
        result.stderr + result.stdout
    )
    assert "set BUILDEROPS_DB_PATH or BUILDEROPS_STATE_DIR explicitly" in (
        result.stderr + result.stdout
    )
    assert not consolidated_db.exists()
