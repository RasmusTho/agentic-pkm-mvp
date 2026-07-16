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


def test_workflow_uses_trusted_receipt_during_neutralized_body_window() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "resolve_post_merge_issue_authority" in text
    assert "comments?per_page=100" in text
    assert "--paginate" in text
    assert "--comments-json post-merge-docs-classifier/comments.json" in text
    assert ' --repository "${REPOSITORY}"' in text
    assert 'print(issue_numberor"")' in text.replace(" ", "")
    assert "re.search" not in text
