from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import app.builderops.config as builderops_config
from app.builderops.models import BuilderOpsLeaseError
from app.builderops.store import SqliteBuilderOpsStore
from app.builderops.cutover_evidence import build_receipt, write_receipt


def test_noncreating_modes_refuse_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "builderops.sqlite3"

    with pytest.raises(sqlite3.OperationalError):
        SqliteBuilderOpsStore(path, read_only=True).list_records()
    assert not path.exists()
    assert not path.parent.exists()

    with pytest.raises(sqlite3.OperationalError):
        SqliteBuilderOpsStore(
            path,
            create_if_missing=False,
        ).list_records()
    assert not path.exists()
    assert not path.parent.exists()


def test_default_store_leases_coordinate_across_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_dir = tmp_path / "host-state" / "builderops"
    monkeypatch.setattr(
        builderops_config,
        "default_state_dir",
        lambda: state_dir,
    )
    first_cwd = tmp_path / "worktree-a"
    second_cwd = tmp_path / "worktree-b"
    first_cwd.mkdir()
    second_cwd.mkdir()
    state_dir.mkdir(parents=True)
    seeded = SqliteBuilderOpsStore(state_dir / "builderops.sqlite3")
    seeded.initialize()
    seeded.create_agent_worklog(
        id="awl_seed", summary="seed", body="seed", task_context={},
        source_refs=[{"ref_type": "github_issue", "ref": "#3686"}],
        created_by={"actor_type": "agent", "id": "seed"},
    )
    receipt = build_receipt(
        state_dir=state_dir,
        participants=[{"repository": "repo-a", "root": str(first_cwd)}, {"repository": "repo-b", "root": str(second_cwd)}],
        reconciliation=[], actor="operator-test",
    )
    write_receipt(state_dir, receipt)

    monkeypatch.chdir(first_cwd)
    first_store = SqliteBuilderOpsStore(builderops_config.load_paths({}).db_path)
    first_store.initialize()
    first_store.create_agent_worklog(
        id="awl_cross_cwd_lease",
        summary="Cross-CWD lease coordination",
        body="Both worktrees must use one same-host lease table.",
        task_context={"issue": "#3686"},
        source_refs=[{"ref_type": "github_issue", "ref": "#3686"}],
        created_by={"actor_type": "agent", "id": "codex-a"},
    )
    first_store.acquire_lease(
        "awl_cross_cwd_lease",
        actor={"actor_type": "agent", "id": "codex-a"},
    )

    monkeypatch.chdir(second_cwd)
    second_store = SqliteBuilderOpsStore(builderops_config.load_paths({}).db_path)

    assert second_store.db_path == first_store.db_path
    with pytest.raises(BuilderOpsLeaseError, match="active lease already exists"):
        second_store.acquire_lease(
            "awl_cross_cwd_lease",
            actor={"actor_type": "agent", "id": "codex-b"},
        )
