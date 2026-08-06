from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_issue_to_code_preserves_constituent_surface_classification_read() -> None:
    skill = (REPO_ROOT / ".codex/skills/issue-to-code/SKILL.md").read_text(encoding="utf-8")

    assert "For accepted constituent repository work, also read" in skill
    assert (
        "docs/architecture/SBS_OPERATING_MODEL.md :: "
        "Cross-repo constituent-surface scope"
    ) in skill
