from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/pr-ci-failure-context.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_does_not_push_rerun_label_merge_or_close() -> None:
    text = _workflow_text()
    lowered = text.lower()

    assert "git push" not in lowered
    assert "workflow_dispatch" not in lowered
    assert "rerun" not in lowered
    assert "gh run rerun" not in lowered
    assert "gh issue edit" not in lowered
    assert "add-label" not in lowered
    assert "remove-label" not in lowered
    assert "project" not in lowered
    assert "gh pr merge" not in lowered
    assert "enable-auto" not in lowered
    assert "issues: write" not in lowered
    assert "pull-requests: write" not in lowered


def test_no_agent_invocation_or_patch_operation_exists() -> None:
    text = _workflow_text().lower()

    assert "codex" not in text
    assert "claude" not in text
    assert "agent repair" not in text
    assert "apply_patch" not in text
    assert "git apply" not in text
    assert "python3 scripts/collect_ci_failure_context.py" in text


def test_workflow_permissions_are_least_privilege() -> None:
    text = _workflow_text()
    permissions = text.split("permissions:", 1)[1].split("\njobs:", 1)[0]

    assert "contents: read" in permissions
    assert "actions: read" in permissions
    assert "pull-requests: read" in permissions
    assert "write" not in permissions
    assert "read-all" not in permissions


def test_workflow_is_artifact_only() -> None:
    text = _workflow_text()

    assert "actions/upload-artifact@v4" in text
    assert "ci-failure-context/context.json" in text
    assert "ci-failure-context/context.md" in text
    assert "github.rest.issues.createComment" not in text
    assert "gh pr comment" not in text
