from __future__ import annotations

from pathlib import Path
import re


SKILLS_ROOT = Path(".codex/skills")
README = SKILLS_ROOT / "README.md"
HEADING = "## Builder execution-routing skill integration inventory"
PRODUCT_PREFIX = "mimer-"
ALLOWED_DISPOSITIONS = {
    "direct-consumer",
    "principle-only",
    "unaffected",
}


def _inventory_rows() -> dict[str, str]:
    section = README.read_text(encoding="utf-8").split(HEADING, 1)[1]
    section = section.split("\n## ", 1)[0]
    rows: dict[str, str] = {}
    for line in section.splitlines():
        match = re.match(r"^\| `([^`]+)` \| ([a-z-]+) \|", line)
        if match:
            rows[match.group(1)] = match.group(2)
    return rows


def test_every_builder_skill_has_an_execution_routing_disposition() -> None:
    builder_skills = {
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
        if not path.parent.name.startswith(PRODUCT_PREFIX)
    }
    product_skills = {
        path.parent.name
        for path in SKILLS_ROOT.glob("*/SKILL.md")
        if path.parent.name.startswith(PRODUCT_PREFIX)
    }
    rows = _inventory_rows()

    assert set(rows) == builder_skills
    assert not product_skills.intersection(rows)
    assert set(rows.values()) <= ALLOWED_DISPOSITIONS

    for path in SKILLS_ROOT.glob("*/SKILL.md"):
        if path.parent.name.startswith(PRODUCT_PREFIX):
            continue
        text = path.read_text(encoding="utf-8").casefold()
        assert "gpt-5." not in text
        assert "spark_bonus_available" not in text
        assert "spark bonus available" not in text
