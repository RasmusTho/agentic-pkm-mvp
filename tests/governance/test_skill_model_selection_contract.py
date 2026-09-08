"""Skills must declare provider-neutral execution intent, not model branches."""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_INTENTS = {
    ".codex/skills/issue-to-code/SKILL.md": "general_delivery",
    ".codex/skills/deliver-issue-set/SKILL.md": "coordination",
    ".codex/skills/issue-maintenance-change-control/SKILL.md": "general_delivery",
    ".codex/skills/verification-and-closure/SKILL.md": "verification",
}
MODEL_ID = re.compile(r"\b(?:gpt-[0-9]|claude-[a-z])", re.IGNORECASE)


def test_builder_skills_declare_provider_neutral_selection_intent() -> None:
    for relative_path, intent in SKILL_INTENTS.items():
        text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
        assert f"execution_selection_intent: {intent}" in text, relative_path
        assert "Codex" in text and "Claude" in text
        assert not MODEL_ID.search(text), relative_path
