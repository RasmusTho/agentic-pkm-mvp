from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/post-merge-docs-classifier.yml"


def test_workflow_does_not_create_docs_pr_issue_label_project_or_close() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "pull_request:" in text
    assert "types: [closed]" in text
    assert "github.event.pull_request.merged == true" in text
    assert "actions/upload-artifact" in text
    assert "contents: read" in text
    assert "pull-requests: read" in text
    assert "issues: read" in text
    assert "issues: write" not in text
    assert "pull-requests: write" not in text
    assert "gh pr create" not in lowered
    assert "gh issue create" not in lowered
    assert "gh issue close" not in lowered
    assert "gh label" not in lowered
    assert "gh project" not in lowered
    assert "createcomment" not in lowered
    assert "issues.createcomment" not in lowered
