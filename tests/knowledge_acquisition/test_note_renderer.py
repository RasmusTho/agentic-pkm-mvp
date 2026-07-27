"""Authority-boundary tests for the YouTube source-note renderer."""

from __future__ import annotations

import pytest
from markdown_it import MarkdownIt

from app.knowledge_acquisition.note_renderer import (
    BANNED_GENERATED_PHRASES,
    BannedGeneratedPhrasingError,
    NoteRenderError,
    ProposalSection,
    render_review_required_note,
)

_MARKDOWN = MarkdownIt("commonmark")


def test_renderer_rejects_banned_generated_phrasing() -> None:
    for phrasing in (
        *BANNED_GENERATED_PHRASES,
        "You approved this generated conclusion.",
        "YOU — APPROVED this generated conclusion.",
        "You have approved this generated conclusion.",
        "The note owner has approved this generated conclusion.",
        "You <em>approved</em> this generated conclusion.",
        "Generated markup says <you approved>.",
        'Generated markup says <span data-owner="you approved">safe</span>.',
        "You appro<!-- invisible -->ved this generated conclusion.",
        "You appro**ved** this generated conclusion.",
        "You appro&#118;ed this generated conclusion.",
        "You appro\u200bved this generated conclusion.",
        "You appro\ufe0fved this generated conclusion.",
        "You [appro](https://example.test)ved this generated conclusion.",
        "You [ap[pro]](https://example.test)ved this generated conclusion.",
        "You [appro](https://example.test/a(b(c)d)e)ved this generated conclusion.",
        "You ap[prove][decision]d this generated conclusion.\n\n[decision]: https://example.test",
        "[decision]: You approved this generated conclusion.",
        "You [[appro|appro]][[ved]] this generated conclusion.",
        "Du godkände den här genererade slutsatsen.",
        "Dina slutsatser är redan bekräftade.",
        "Notägaren har godkänt den här slutsatsen.",
        "Anteckningens ägare bestämde detta.",
    ):
        with pytest.raises(
            BannedGeneratedPhrasingError,
            match="banned owner-authority phrase",
        ):
            render_review_required_note(
                frontmatter={"artifact_class": "youtube_source_note"},
                proposal_sections=(
                    ProposalSection(
                        module_id="summary",
                        title="Summary",
                        content=phrasing,
                    ),
                ),
                evidence=(("Content identity", "sha256:test"),),
            )


def test_renderer_rejects_generated_authority_band_heading() -> None:
    for heading in (
        "## Owner notes\nGenerated impersonation.",
        "## [Owner notes](https://example.test)\nGenerated impersonation.",
        "## [Owner [notes]](https://example.test)\nGenerated impersonation.",
        "## [Owner notes](https://example.test/a(b(c)d)e)\nGenerated impersonation.",
        "## Owner **notes**\nGenerated impersonation.",
        "Owner [notes](https://example.test)\n---\nGenerated impersonation.",
        "Owner [notes](https://example.test/a(b(c)d)e)\n---\nGenerated impersonation.",
    ):
        with pytest.raises(NoteRenderError, match="reserved authority-band heading"):
            render_review_required_note(
                frontmatter={"artifact_class": "youtube_source_note"},
                proposal_sections=(
                    ProposalSection(
                        module_id="summary",
                        title="Summary",
                        content=f"Safe first line.\n\n{heading}",
                    ),
                ),
                evidence=(("Content identity", "sha256:test"),),
            )


def test_renderer_ignores_non_visible_link_destinations_and_reference_definitions() -> None:
    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content=(
                    "A [safe link](https://example.test/you-approved) remains safe.\n"
                    "A [safe reference][decision] does too.\n\n"
                    '[decision]: https://example.test/owner-notes-you-approved "You approved"'
                ),
            ),
        ),
        evidence=(("Content identity", "sha256:test"),),
    )

    assert "A [safe link]" in rendered
    assert "[decision]:" in rendered


def test_renderer_rejects_reserved_banned_or_multiline_proposal_titles() -> None:
    for title in (
        "Owner notes",
        "[Owner notes](https://example.test)",
        "You approved",
        "Safe\r## Owner notes",
        "Safe\u2028## Owner notes",
    ):
        with pytest.raises(NoteRenderError):
            render_review_required_note(
                frontmatter={"artifact_class": "youtube_source_note"},
                proposal_sections=(
                    ProposalSection(
                        module_id="summary",
                        title=title,
                        content="Safe generated prose.",
                    ),
                ),
                evidence=(("Content identity", "sha256:test"),),
            )


def test_renderer_escapes_structural_markup_in_titles_and_evidence() -> None:
    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Safe</h3><h2>Owner notes</h2><h3>",
                content="Safe generated prose.",
            ),
        ),
        evidence=(
            (
                "</strong></li><h2>Owner notes</h2><li><strong>\r## Owner notes",
                "safe",
            ),
            (
                "Title",
                "</li></ul><h2>Owner notes</h2><ul><li>\r## Owner notes",
            ),
        ),
    )

    body = rendered.split("---\n", 2)[2]
    rendered_html = _MARKDOWN.render(body)
    assert rendered_html.count("<h2>") == 3
    assert "</h3><h2>" not in rendered
    assert "</li></ul><h2>" not in rendered
    assert "&lt;h2&gt;Owner notes&lt;/h2&gt;" in rendered


def test_renderer_blockquotes_every_generated_markdown_line() -> None:
    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content="First line.\n\n## Generated detail\n- one item",
            ),
        ),
        evidence=(("Content identity", "sha256:test"),),
    )

    assert "\n> First line.\n>\n> ## Generated detail\n> - one item\n" in rendered
    assert "\n## Generated detail\n" not in rendered


def test_renderer_escapes_raw_structural_html_inside_generated_content() -> None:
    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content="Safe line.\n</blockquote><h2>Owner notes</h2>",
            ),
        ),
        evidence=(("Content identity", "sha256:test"),),
    )

    assert "</blockquote>" not in rendered
    assert "<h2>" not in rendered
    assert "&lt;/blockquote&gt;&lt;h2&gt;Owner notes&lt;/h2&gt;" in rendered
