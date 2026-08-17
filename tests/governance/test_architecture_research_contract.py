from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_validation_window_requires_bounded_evidence() -> None:
    skill = (REPO_ROOT / ".codex/skills/architecture-research/SKILL.md").read_text(
        encoding="utf-8"
    )
    validation_window = skill.split("### Validation window", maxsplit=1)[1]

    for required_field in (
        "**Start point:**",
        "**Run identity:**",
        "**Completion record:**",
        "**Removal trigger:**",
    ):
        assert required_field in validation_window
