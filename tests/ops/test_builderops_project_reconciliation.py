from __future__ import annotations

from pathlib import Path

from app.dispatcher import cli as dispatcher_cli


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_project_reconciliation_is_separate_from_dispatcher_claim_path() -> None:
    hook = REPO_ROOT / "scripts" / "reconcile_builderops_project_status.sh"
    hook_text = hook.read_text(encoding="utf-8")
    dispatcher_text = (REPO_ROOT / "app" / "dispatcher" / "cli.py").read_text(encoding="utf-8")
    sync_text = (REPO_ROOT / "app" / "dispatcher" / "sync_github.py").read_text(encoding="utf-8")

    assert "Low-frequency" in hook_text
    assert "scripts/reconcile_project_status.py" in hook_text
    assert "next/claim/heartbeat/complete" in hook_text
    assert "reconcile_builderops_project_status" not in dispatcher_text
    assert "reconcile_project_status" not in dispatcher_text
    assert "reconcile_project_status" not in sync_text
    for command in ("next", "claim", "heartbeat", "complete"):
        assert command in dispatcher_cli._COMMAND_MAP
