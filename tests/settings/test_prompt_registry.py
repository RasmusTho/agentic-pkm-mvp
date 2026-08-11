"""Compatibility CI entrypoint for the retired repository prompt registry."""

from pathlib import Path

import pytest


pytestmark = pytest.mark.not_pg


def test_legacy_prompt_registry_is_retired() -> None:
    assert not Path("app/components/settings/prompts_loader.py").exists()
    assert not list(Path("docs/settings/prompts").glob("*.md"))
