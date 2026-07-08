from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/pr-evidence-pack.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_has_no_merge_close_label_or_project_mutation() -> None:
    text = _workflow_text()
    lowered = text.lower()

    assert "git push" not in lowered
    assert "gh pr merge" not in lowered
    assert "gh issue close" not in lowered
    assert "gh issue edit" not in lowered
    assert "add-label" not in lowered
    assert "remove-label" not in lowered
    assert "project" not in lowered
    assert "github.rest.issues.createcomment" not in lowered
    assert "github.rest.pulls.update" not in lowered
    assert "apply_patch" not in lowered
    assert "git apply" not in lowered


def test_workflow_is_artifact_only_and_least_privilege() -> None:
    text = _workflow_text()
    permissions = text.split("permissions:", 1)[1].split("\njobs:", 1)[0]

    assert "contents: read" in permissions
    assert "pull-requests: read" in permissions
    assert "checks: read" in permissions
    assert "issues: read" in permissions
    assert "write" not in permissions
    assert "actions/upload-artifact@v4" in text
    assert "pr-evidence-pack/evidence.json" in text
    assert "pr-evidence-pack/evidence.md" in text
    upload_block = text.split("actions/upload-artifact@v4", 1)[1]
    assert "pr-evidence-pack/" not in upload_block.replace(
        "pr-evidence-pack/evidence.json", ""
    ).replace("pr-evidence-pack/evidence.md", "")


def test_workflow_collects_pr_issue_file_and_check_evidence() -> None:
    text = _workflow_text()

    assert "repos/${REPOSITORY}/pulls/${PR_NUMBER}" in text
    assert "repos/${REPOSITORY}/pulls/${PR_NUMBER}/files" in text
    assert "repos/${REPOSITORY}/commits/${HEAD_SHA}/check-runs" in text
    assert "repos/${REPOSITORY}/issues/${ISSUE_NUMBER}" in text
    assert "scripts/build_pr_evidence_pack.py" in text
