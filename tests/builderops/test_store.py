from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.builderops.config as builderops_config
from app.builderops.models import BuilderOpsLeaseError
from app.builderops.store import SqliteBuilderOpsStore


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
    state_dir.mkdir(parents=True)
    builderops_config.host_cutover_ack_path(state_dir).write_text(
        json.dumps(
            {
                "schema_version": builderops_config.CUTOVER_ACK_SCHEMA,
                "scope": "same-user-same-host",
                "legacy_stores_reconciled": True,
                "participating_repos": ["repo-a", "repo-b"],
                "actor": "operator-test",
                "acknowledged_at": "2026-07-15T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    first_cwd = tmp_path / "worktree-a"
    second_cwd = tmp_path / "worktree-b"
    first_cwd.mkdir()
    second_cwd.mkdir()

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
