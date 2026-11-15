"""The OpenHands-specific fence must not imply Codex writer custody."""

from pathlib import Path

import pytest

from app.builderops import legacy_run_fence


def test_codex_issue_6560_refused_before_run_state_access(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected(**_kwargs: object) -> None:
        pytest.fail("unsupported run reached host-state checks")

    monkeypatch.setattr(legacy_run_fence, "check_locked", unexpected)
    with pytest.raises(legacy_run_fence.RunFenceError, match="outside the qualified legacy scope"):
        with legacy_run_fence.hold(state_root=tmp_path, issue=6560, worktree=tmp_path / "worktree"):
            pytest.fail("unsupported run obtained a fence")


def test_pickup_entrypoint_refuses_6560_before_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.builderops import legacy_git_config, legacy_owner_recovery

    monkeypatch.setattr(legacy_owner_recovery.agent_worktree, "_screen_transfer_workspace", lambda *_a: None)
    monkeypatch.setattr(legacy_git_config, "check_host_config", lambda: None)
    monkeypatch.setattr(legacy_git_config, "check", lambda **_kw: None)

    def unexpected(**_kwargs: object) -> dict[str, object]:
        pytest.fail("pickup reached claim without a qualified writer fence")

    monkeypatch.setattr(legacy_owner_recovery, "_execute_operator_pickup", unexpected)
    with pytest.raises(legacy_owner_recovery.RecoveryEvidenceError, match="outside qualified scope"):
        legacy_owner_recovery.execute_operator_pickup(
            run_state_root=tmp_path, cwd=tmp_path, issue=6560, pr=6565,
            worktree=tmp_path / "fixture", agent="successor", session="fixture-session",
            comment_id=1, workspace_root=tmp_path,
        )
