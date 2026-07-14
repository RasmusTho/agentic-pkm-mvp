from __future__ import annotations

from pathlib import Path

import pytest

import app.builderops.config as builderops_config


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
    assert first.db_path == builderops_config.DEFAULT_STATE_DIR / "builderops.sqlite3"
    assert first.db_path.is_absolute()


def test_host_stable_default_still_confined_outside_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "shared-vault"
    monkeypatch.setattr(builderops_config, "DEFAULT_STATE_DIR", vault / "builderops")

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
        builderops_config.DEFAULT_STATE_DIR / "builderops.sqlite3"
    )
    assert _builderops_db_path(
        tmp_path,
        {"BUILDEROPS_STATE_DIR": str(relative_state_dir)},
    ) == str(tmp_path / relative_state_dir / "builderops.sqlite3")
    assert _builderops_db_path(
        tmp_path,
        {"BUILDEROPS_DB_PATH": str(explicit_db_path)},
    ) == str(explicit_db_path)
