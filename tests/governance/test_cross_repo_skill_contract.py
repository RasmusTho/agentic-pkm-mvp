"""Regression coverage for the cross-repo skill contract promised by #3174."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / ".codex" / "skills"


def test_issue_skills_declare_repo_target_or_single_repo_precondition() -> None:
    issue_to_code = (SKILLS / "issue-to-code" / "SKILL.md").read_text(encoding="utf-8")
    maintenance = (SKILLS / "issue-maintenance-change-control" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    breakdown = (SKILLS / "feature-breakdown" / "SKILL.md").read_text(encoding="utf-8")

    for skill in (issue_to_code, maintenance, breakdown):
        assert "## Repository target" in skill
        assert 'REPO` to the explicitly intended `owner/repo`' in skill or (
            'REPO` to the intended `owner/repo`' in skill
        )

    for line in (*issue_to_code.splitlines(), *maintenance.splitlines()):
        if line.lstrip().startswith("gh issue "):
            assert '--repo "$REPO"' in line

    assert 'gh issue create --repo "$REPO"' in breakdown


def test_capture_learning_declares_cross_repo_path() -> None:
    capture_learning = (SKILLS / "capture-learning" / "SKILL.md").read_text(encoding="utf-8")
    store_contract = (REPO_ROOT / "docs/builderops/BUILDEROPS_VAULT_STORE.md").read_text(
        encoding="utf-8"
    )

    assert "## Cross-repository capture" in capture_learning
    assert "github_issue:${REPO}#<issue>" in capture_learning
    assert "repo_doc:${REPO}:<upstream-artifact-path>" in capture_learning
    assert "### Repository-qualified learning provenance" in store_contract


def test_delegated_duplicate_check_preserves_selected_repo() -> None:
    docs_to_issue = (SKILLS / "docs-to-issue" / "SKILL.md").read_text(encoding="utf-8")

    assert "delegated callers such as" in docs_to_issue
    assert "REPO=${REPO:-$(git remote get-url origin" in docs_to_issue
    assert "REPO=$(git remote get-url origin" not in docs_to_issue
    assert 'gh api "repos/$REPO/issues?state=open&per_page=100"' in docs_to_issue


def test_issue_to_code_fallback_preserves_selected_repo() -> None:
    issue_to_code = (SKILLS / "issue-to-code" / "SKILL.md").read_text(encoding="utf-8")
    fallback_start = issue_to_code.index("When dispatcher status selects degraded mode")
    fallback_end = issue_to_code.index("Preserve the wrapper's receipt", fallback_start)
    fallback = issue_to_code[fallback_start:fallback_end]

    assert (
        'scripts/issue_pickup_claim.sh \\\n'
        '  --issue <N> \\\n'
        '  --repo "$REPO"'
    ) in fallback
