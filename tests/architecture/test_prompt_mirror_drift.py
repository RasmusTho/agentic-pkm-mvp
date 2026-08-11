from __future__ import annotations

from pathlib import Path

import pytest


def _assert_no_legacy_prompt_mirrors(root: Path) -> None:
    assert not list((root / "docs" / "settings" / "prompts").glob("*.md")), (
        "prompt mirrors must be generated from canonical vault settings or absent"
    )


def test_mirrors_are_generated_or_absent(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    _assert_no_legacy_prompt_mirrors(root)

    manufactured = tmp_path / "docs" / "settings" / "prompts"
    manufactured.mkdir(parents=True)
    (manufactured / "ask.answer.v1.md").write_text("divergent", encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_no_legacy_prompt_mirrors(tmp_path)
