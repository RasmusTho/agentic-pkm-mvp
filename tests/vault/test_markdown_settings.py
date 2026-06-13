from __future__ import annotations

import pytest

from app.vault.markdown_settings import MarkdownSettingsError, split_markdown_settings


def test_setext_divider_body_not_treated_as_conflict() -> None:
    frontmatter, body = split_markdown_settings(
        "---\n"
        "schema: design-handoff.vault.v1\n"
        "scope: vault-shared\n"
        "---\n"
        "Setext heading\n"
        "=======\n"
        "Body text\n"
    )

    assert frontmatter["schema"] == "design-handoff.vault.v1"
    assert "=======\n" in body

    with pytest.raises(MarkdownSettingsError, match="conflict markers"):
        split_markdown_settings(
            "---\n"
            "<<<<<<< HEAD\n"
            "schema: design-handoff.vault.v1\n"
            "=======\n"
            "schema: other\n"
            ">>>>>>> branch\n"
            "---\n"
        )
