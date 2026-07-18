from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

import app.builderops.config as builderops_config
from app.builderops.store import SqliteBuilderOpsStore


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_cutover_ack(
    state_dir: Path,
    repos: list[str] | None = None,
    *,
    roots: list[Path] | None = None,
    acknowledged_at: datetime | None = None,
    host_id: str | None = None,
    user_id: str | None = None,
) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = builderops_config.host_cutover_ack_path(state_dir)
    path.write_text(
        json.dumps(
            {
                "schema_version": builderops_config.CUTOVER_ACK_SCHEMA,
                "scope": "same-user-same-host",
                "host_id": host_id or builderops_config.current_host_id(),
                "user_id": user_id or builderops_config.current_user_id(),
                "legacy_stores_reconciled": True,
                "participating_repos": repos
                if repos is not None
                else [f"local/repo-{index}" for index, _root in enumerate(roots or [Path.cwd()])],
                "participating_roots": [
                    str(root.resolve()) for root in (roots or [Path.cwd()])
                ],
                "inventory_epoch": str(uuid4()),
                "actor": "operator-test",
                "acknowledged_at": (
                    acknowledged_at or datetime.now(timezone.utc)
                ).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)


def _run_implicit_cli(*, cwd: Path, home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO_ROOT)
    for key in ("BUILDEROPS_DB_PATH", "BUILDEROPS_STATE_DIR", "BUILDEROPS_VAULT_ROOT"):
        env.pop(key, None)
    return subprocess.run(
        [sys.executable, "-m", "app.builderops", "builderops", "list", "--json"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_db_path_is_host_stable_and_cwd_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "host-state" / "builderops"
    monkeypatch.setattr(builderops_config, "default_state_dir", lambda: state_dir)
    first_cwd = tmp_path / "worktree-a"
    second_cwd = tmp_path / "worktree-b"
    first_cwd.mkdir()
    second_cwd.mkdir()
    _write_cutover_ack(
        state_dir,
        ["repo-a", "repo-b"],
        roots=[first_cwd, second_cwd],
    )

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
    state_dir = vault / "builderops"
    monkeypatch.setattr(
        builderops_config,
        "default_state_dir",
        lambda: state_dir,
    )
    _write_cutover_ack(state_dir, roots=[Path.cwd()])

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


def test_implicit_cli_requires_host_ack_when_legacy_store_is_in_another_repo(
    tmp_path: Path,
) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    (repo_a / ".git").mkdir(parents=True)
    (repo_b / ".git").mkdir(parents=True)
    legacy_db = repo_b / "runtime" / "builderops" / "builderops.sqlite3"
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
    home = tmp_path / "cross-repo-home"
    consolidated_db = home / ".local" / "state" / "builderops" / "builderops.sqlite3"
    result = _run_implicit_cli(cwd=repo_a, home=home)

    assert result.returncode != 0
    assert "Refusing implicit host-stable BuilderOps store selection" in (
        result.stderr + result.stdout
    )
    assert "BUILDEROPS_DB_PATH / BUILDEROPS_STATE_DIR explicitly" in (
        result.stderr + result.stdout
    )
    assert not consolidated_db.exists()


def test_implicit_cli_requires_host_ack_outside_git(tmp_path: Path) -> None:
    outside_git = tmp_path / "outside-git"
    outside_git.mkdir()
    home = tmp_path / "outside-git-home"
    consolidated_db = home / ".local" / "state" / "builderops" / "builderops.sqlite3"

    result = _run_implicit_cli(cwd=outside_git, home=home)

    assert result.returncode != 0
    assert "same-user/same-host cutover acknowledgement is required" in (
        result.stderr + result.stdout
    )
    assert not consolidated_db.exists()


def test_valid_host_ack_allows_implicit_cli_outside_git(tmp_path: Path) -> None:
    outside_git = tmp_path / "outside-git"
    outside_git.mkdir()
    home = tmp_path / "acknowledged-home"
    state_dir = home / ".local" / "state" / "builderops"
    consolidated_db = state_dir / "builderops.sqlite3"
    _write_cutover_ack(
        state_dir,
        ["owner/repo-a"],
        roots=[outside_git],
    )

    result = _run_implicit_cli(cwd=outside_git, home=home)

    assert result.returncode == 0, result.stderr
    assert consolidated_db.exists()


def test_host_ack_is_bound_to_host_user_inventory_and_reconciliation_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_dir = tmp_path / "host-state" / "builderops"
    legacy_db = repo / "runtime" / "builderops" / "builderops.sqlite3"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"SQLite format 3\x00")
    stale = datetime.now(timezone.utc) - timedelta(days=1)
    monkeypatch.chdir(repo)

    _write_cutover_ack(state_dir, roots=[repo], acknowledged_at=stale)
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)

    _write_cutover_ack(state_dir, roots=[repo], host_id="copied-host")
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)

    _write_cutover_ack(state_dir, roots=[repo], user_id="copied-user")
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)

    other_repo = tmp_path / "new-participant"
    other_repo.mkdir()
    _write_cutover_ack(state_dir, roots=[repo])
    monkeypatch.chdir(other_repo)
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)


def test_host_ack_rejects_broad_parent_that_hides_newer_nested_legacy_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    repo = workspace / "repo-a"
    repo.mkdir(parents=True)
    legacy_db = repo / "runtime" / "builderops" / "builderops.sqlite3"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"SQLite format 3\x00")
    acknowledged_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    newer = acknowledged_at + timedelta(seconds=30)
    os.utime(legacy_db, (newer.timestamp(), newer.timestamp()))
    state_dir = tmp_path / "host-state" / "builderops"
    monkeypatch.chdir(repo)

    _write_cutover_ack(
        state_dir,
        ["owner/workspace"],
        roots=[workspace],
        acknowledged_at=acknowledged_at,
    )

    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)


def test_host_ack_rejects_broad_secondary_root_with_newer_nested_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_repo = tmp_path / "repo-a"
    broad_root = tmp_path / "workspace-b"
    nested_repo = broad_root / "repo-b"
    current_repo.mkdir()
    nested_repo.mkdir(parents=True)
    legacy_db = nested_repo / "runtime" / "builderops" / "builderops.sqlite3"
    legacy_db.parent.mkdir(parents=True)
    legacy_db.write_bytes(b"SQLite format 3\x00")
    acknowledged_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    newer = acknowledged_at + timedelta(seconds=30)
    os.utime(legacy_db, (newer.timestamp(), newer.timestamp()))
    state_dir = tmp_path / "host-state" / "builderops"
    monkeypatch.chdir(current_repo)

    _write_cutover_ack(
        state_dir,
        ["owner/repo-a", "owner/workspace-b"],
        roots=[current_repo, broad_root],
        acknowledged_at=acknowledged_at,
    )

    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)


def test_host_ack_rejects_future_timestamp_and_permissive_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    state_dir = tmp_path / "host-state" / "builderops"
    monkeypatch.chdir(repo)
    _write_cutover_ack(
        state_dir,
        roots=[repo],
        acknowledged_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)

    _write_cutover_ack(state_dir, roots=[repo])
    builderops_config.host_cutover_ack_path(state_dir).chmod(0o644)
    with pytest.raises(ValueError, match="fresh inventory epoch"):
        builderops_config._validate_host_cutover_ack(state_dir)
