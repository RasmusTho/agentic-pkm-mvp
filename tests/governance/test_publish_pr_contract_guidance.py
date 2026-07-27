"""Contract tests for issue-closing authority in publish-pr guidance (#4018)."""

from __future__ import annotations

from pathlib import Path


PUBLISH_PR_SKILL = (
    Path(__file__).resolve().parents[2] / ".codex" / "skills" / "publish-pr" / "SKILL.md"
)


def _publish_pr_guidance() -> str:
    return PUBLISH_PR_SKILL.read_text(encoding="utf-8")


def test_commit_message_closing_keywords_are_forbidden() -> None:
    guidance = _publish_pr_guidance()

    assert "Never include `Fixes`, `Closes`, or `Resolves` issue-closing keywords" in guidance
    assert "Use evidence-only `Refs #<id>`" in guidance


def test_pr_body_closing_keywords_remain_required_for_issue_backed_prs() -> None:
    guidance = _publish_pr_guidance()

    assert "Governing-Issue: #<ISSUE_NUMBER>" in guidance
    assert "Fixes #<ISSUE_NUMBER>" in guidance
    assert "closing keywords only for fully delivered" in guidance
