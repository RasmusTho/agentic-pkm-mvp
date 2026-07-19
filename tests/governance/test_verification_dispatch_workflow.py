from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github/workflows/verification-dispatch-request.yml"


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_triggers_from_completed_ci_smoke_workflow() -> None:
    text = _workflow_text()

    assert "workflow_run:" in text
    assert "workflows: [CI Smoke]" in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.event == 'pull_request'" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert 'repos/${REPOSITORY}/pulls/${PR_NUMBER}' in text
    assert 'repos/${REPOSITORY}/commits/${RUN_HEAD_SHA}/pulls' in text
    assert "resolve_pr_number" in text
    assert "python3 -m scripts.build_verification_dispatch_request" in text
    assert '--artifact-workflow-run-id "${{ github.run_id }}"' in text
    assert '--artifact-repository-id "${{ github.repository_id }}"' in text


def test_request_builder_runs_as_repository_module() -> None:
    text = _workflow_text()
    command = "python3 -m scripts.build_verification_dispatch_request"

    assert command in text
    assert "python3 scripts/build_verification_dispatch_request.py" not in text
    result = subprocess.run(
        [sys.executable, "-m", "scripts.build_verification_dispatch_request", "--help"],
        cwd=REPO_ROOT,
        env={"PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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


def test_workflow_uses_explicit_governing_issue_contract() -> None:
    text = _workflow_text()

    assert "resolve_issue_contract" in text
    assert "governing_issue" in text
    assert "re.search" not in text
    assert "(?:Fixes|Closes|Resolves)" not in text
