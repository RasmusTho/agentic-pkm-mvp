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
        "You appro\u034fved this generated conclusion.",
        "You appro\u180bved this generated conclusion.",
        "You appro\u115fved this generated conclusion.",
        "You appro\u17b4ved this generated conclusion.",
        "You appro\u3164ved this generated conclusion.",
        "You appro\U000e007fved this generated conclusion.",
        "You've approved this generated conclusion.",
        "You’ve approved this generated conclusion.",
        "You've believed this generated conclusion.",
        "You’ve decided this generated conclusion.",
        "The note owner's approved this generated conclusion.",
        "The note owner’s approved this generated conclusion.",
        "Ｙｏｕ ａｐｐｒｏｖｅｄ this generated conclusion.",
        "𝒀𝒐𝒖 𝒂𝒑𝒑𝒓𝒐𝒗𝒆𝒅 this generated conclusion.",
        "You [appro](https://example.test)ved this generated conclusion.",
        "You [ap[pro]](https://example.test)ved this generated conclusion.",
        "You [appro](https://example.test/a(b(c)d)e)ved this generated conclusion.",
        "You ap[prove][decision]d this generated conclusion.\n\n[decision]: https://example.test",
        "[decision]: You approved this generated conclusion.",
        "You [[appro|appro]][[ved]] this generated conclusion.",
        "Du godkände den här genererade slutsatsen.",
        "Dina slutsatser är redan bekräftade.",
        "Notägaren har godkänt den här slutsatsen.",
        "Nota\u0308garen har godka\u0308nt den här slutsatsen.",
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
        "## Ow\u034fner notes\nGenerated impersonation.",
        "## Ow\u3164ner notes\nGenerated impersonation.",
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
        "Ow\u034fner notes",
        "Ow\u3164ner notes",
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


def test_renderer_rejects_every_bidi_control_on_each_rendered_surface() -> None:
    bidi_controls = (
        "\u061c",  # Arabic letter mark
        "\u200e",  # Left-to-right mark
        "\u200f",  # Right-to-left mark
        "\u202a",  # Left-to-right embedding
        "\u202b",  # Right-to-left embedding
        "\u202c",  # Pop directional formatting
        "\u202d",  # Left-to-right override
        "\u202e",  # Right-to-left override
        "\u2066",  # Left-to-right isolate
        "\u2067",  # Right-to-left isolate
        "\u2068",  # First-strong isolate
        "\u2069",  # Pop directional isolate
    )

    for control in bidi_controls:
        surface_inputs = (
            (
                "frontmatter",
                {"artifact_class": f"youtube{control}_source_note"},
                ProposalSection("summary", "Summary", "Safe generated prose."),
                (("Content identity", "sha256:test"),),
            ),
            (
                "title",
                {"artifact_class": "youtube_source_note"},
                ProposalSection("summary", f"Safe{control} title", "Safe prose."),
                (("Content identity", "sha256:test"),),
            ),
            (
                "content",
                {"artifact_class": "youtube_source_note"},
                ProposalSection("summary", "Summary", f"Safe{control} prose."),
                (("Content identity", "sha256:test"),),
            ),
            (
                "evidence label",
                {"artifact_class": "youtube_source_note"},
                ProposalSection("summary", "Summary", "Safe prose."),
                ((f"Content{control} identity", "sha256:test"),),
            ),
            (
                "evidence value",
                {"artifact_class": "youtube_source_note"},
                ProposalSection("summary", "Summary", "Safe prose."),
                (("Content identity", f"sha256:{control}test"),),
            ),
        )
        for surface, frontmatter, section, evidence in surface_inputs:
            with pytest.raises(
                NoteRenderError,
                match=f"bidirectional control.*{surface}",
            ):
                render_review_required_note(
                    frontmatter=frontmatter,
                    proposal_sections=(section,),
                    evidence=evidence,
                )


def test_renderer_preserves_safe_rtl_and_benign_emoji_joiner() -> None:
    safe_content = "Safe multilingual prose: مرحبا שלום 👩\u200d💻."

    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content=safe_content,
            ),
        ),
        evidence=(("Content identity", "sha256:test"),),
    )

    assert safe_content in rendered


def test_renderer_does_not_reject_non_authority_substrings() -> None:
    safe_content = (
        "The YouTube reviewer approved the upload. "
        "A disapproved option remains source evidence."
    )

    rendered = render_review_required_note(
        frontmatter={"artifact_class": "youtube_source_note"},
        proposal_sections=(
            ProposalSection(
                module_id="summary",
                title="Summary",
                content=safe_content,
            ),
        ),
        evidence=(("Content identity", "sha256:test"),),
    )

    assert safe_content in rendered
