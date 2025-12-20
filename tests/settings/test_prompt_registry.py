from __future__ import annotations

import pytest

from app.components.settings.prompts_loader import load_prompt_registry, load_prompts

pytestmark = pytest.mark.not_pg


def test_prompt_registry_loads() -> None:
    reg = load_prompt_registry()
    assert reg.version >= 1
    assert reg.prompts
    ids = {p.id for p in reg.prompts}
    assert "classifier.v1" in ids
    assert "ask.answer.v1" in ids


def test_prompts_load_and_match_frontmatter() -> None:
    prompts = load_prompts()
    assert "classifier.v1" in prompts
    assert "ask.answer.v1" in prompts
    assert prompts["classifier.v1"].prompt_id == "classifier.v1"
    assert prompts["ask.answer.v1"].prompt_id == "ask.answer.v1"
