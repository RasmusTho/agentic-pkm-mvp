from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/verification-dispatch-request.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_triggers_from_completed_ci_workflow_run() -> None:
    text = _workflow_text()

    assert "workflow_run:" in text
    assert "workflows: [CI]" in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.event == 'pull_request'" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert 'repos/${REPOSITORY}/pulls/${PR_NUMBER}' in text
    assert 'repos/${REPOSITORY}/commits/${RUN_HEAD_SHA}/pulls' in text
    assert "resolve_pr_number" in text
    assert "scripts/build_verification_dispatch_request.py" in text


def test_successful_current_head_emits_dispatch_artifact() -> None:
    text = _workflow_text()

    assert "verification-dispatch/request.json" in text
    assert "verification-dispatch/request.md" in text
    assert "if: steps.build.outputs.emitted == 'true'" in text
    assert "actions/upload-artifact@v4" in text
    assert "github.event.workflow_run.head_sha" in text


def test_resolve_step_creates_candidate_directory_before_fallback_write() -> None:
    text = _workflow_text()
    resolve_step = text.split("- name: Resolve triggering PR", 1)[1].split(
        "- name: Fetch current PR and linked issue", 1
    )[0]

    mkdir_offset = resolve_step.index("mkdir -p verification-dispatch")
    fallback_offset = resolve_step.index(
        "test -f verification-dispatch/pr-candidates.json"
    )

    assert mkdir_offset < fallback_offset


def test_workflow_is_artifact_only_and_least_privilege() -> None:
    text = _workflow_text()
    lowered = text.lower()
    permissions = text.split("permissions:", 1)[1].split("\njobs:", 1)[0]

    assert "contents: read" in permissions
    assert "pull-requests: read" in permissions
    assert "issues: read" in permissions
    assert "write" not in permissions
    assert "secrets." not in lowered
    for forbidden in (
        "codex",
        "claude",
        "verification_closer",
        "ssh",
        "git push",
        "gh pr merge",
        "gh issue close",
        "gh issue edit",
        "gh pr comment",
        "workflow_dispatch",
        "repository_dispatch",
        "add-label",
        "remove-label",
        "project",
        "dispatcher",
    ):
        assert forbidden not in lowered

    upload_block = text.split("actions/upload-artifact@v4", 1)[1]
    assert "verification-dispatch/" not in upload_block.replace(
        "verification-dispatch/request.json", ""
    ).replace("verification-dispatch/request.md", "")


def test_workflow_permissions_match_used_read_apis() -> None:
    text = _workflow_text()
    permissions = text.split("permissions:", 1)[1].split("\njobs:", 1)[0]

    assert "contents: read" in permissions
    assert "pull-requests: read" in permissions
    assert "issues: read" in permissions
    assert "actions: read" not in permissions
    assert 'repos/${REPOSITORY}/commits/${RUN_HEAD_SHA}/pulls' in text
    assert 'repos/${REPOSITORY}/pulls/${PR_NUMBER}' in text
    assert 'repos/${REPOSITORY}/issues/${ISSUE_NUMBER}' in text
