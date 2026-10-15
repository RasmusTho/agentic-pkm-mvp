from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DISPATCH = REPO_ROOT / ".github/workflows/post-merge-closure-dispatch.yml"
RECOVERY = REPO_ROOT / ".github/workflows/post-merge-closure-reconcile.yml"


def test_only_merged_pr_emits_linked_closure_request() -> None:
    text = DISPATCH.read_text(encoding="utf-8")
    assert "types: [closed]" in text
    assert "github.event.pull_request.merged == true" in text
    assert "post_merge_docs_classifier" in text
    assert "build_closure_dispatch_request" in text
    assert "classification.json" in text
    assert "request.json" in text
    assert "if-no-files-found: ignore" in text


def test_workflows_are_artifact_only_and_least_privilege() -> None:
    for path in (DISPATCH, RECOVERY):
        text = path.read_text(encoding="utf-8")
        permissions = text.split("permissions:", 1)[1].split("\njobs:", 1)[0]
        assert "contents: read" in permissions
        assert "pull-requests: read" in permissions
        assert "issues: read" in permissions
        assert "write" not in permissions
        lowered = text.lower()
        assert "gh issue close" not in lowered
        assert "gh issue edit" not in lowered
        assert "gh label" not in lowered
        assert "gh project" not in lowered
        assert "gh pr merge" not in lowered
        assert "ssh " not in lowered
        assert "codex exec" not in lowered
        assert "agent launch" not in lowered
        assert "actions/upload-artifact" in text

