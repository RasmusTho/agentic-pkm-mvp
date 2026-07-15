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
    assert "python3 -m scripts.build_pr_evidence_pack" in text
    assert "resolve_issue_authority" in text
    assert "{authority.governing_issue, *authority.closing_issues}" in text
    assert "pr-evidence-pack/issues.jsonl" in text
    assert "jq -s '.'" in text
    assert "re.search" not in text


def test_workflow_fails_closed_on_over_limit_authority_before_issue_fanout() -> None:
    text = _workflow_text()

    guard = text.index("over-limit issue authority")
    loop = text.index("while IFS= read -r ISSUE_NUMBER")
    issue_fetch = text.index('repos/${REPOSITORY}/issues/${ISSUE_NUMBER}')
    assert "closing_issue_authority_exceeds_limit" in text
    assert guard < loop < issue_fetch


def test_workflow_paginates_files_and_check_runs() -> None:
    text = _workflow_text()

    files_fetch = text.split('gh api --paginate "repos/${REPOSITORY}/pulls/${PR_NUMBER}/files', 1)[1].split(
        "> pr-evidence-pack/files.json", 1
    )[0]
    checks_fetch = text.split(
        'gh api --paginate "repos/${REPOSITORY}/commits/${HEAD_SHA}/check-runs', 1
    )[1].split(
        "> pr-evidence-pack/checks.json", 1
    )[0]

    assert "jq -s '.'" in files_fetch
    assert "jq -s '{check_runs: .}'" in checks_fetch
