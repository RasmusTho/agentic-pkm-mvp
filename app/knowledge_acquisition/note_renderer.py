"""Pure renderer for review-required YouTube source-note candidates.

The renderer owns the visible authority boundary. It always emits exactly
three bands, in this order:

1. an owner-authored band that generated content never enters;
2. one explicit non-authoritative proposal wrapper;
3. deterministic evidence and lineage.

Callers provide already-registered proposal modules as ``ProposalSection``
values. Empty modules are omitted. Generated prose is linted before any
Markdown is assembled so language that falsely claims owner authorship,
belief, decision, or approval fails closed.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import regex
import yaml
from markdown_it import MarkdownIt
from markdown_it.token import Token

PROPOSALS_HEADING = "## Proposals (non-authoritative)"
OWNER_NOTES_HEADING = "## Owner notes"
EVIDENCE_HEADING = "## Evidence and lineage"

_SWEDISH_NOTE_OWNER_SUBJECTS = (
    "notägaren",
    "notens ägare",
    "anteckningsägaren",
    "anteckningens ägare",
)
_SWEDISH_AUTHORITY_PREDICATES = (
    "godkänner",
    "godkände",
    "har godkänt",
    "tror",
    "trodde",
    "har trott",
    "bestämmer",
    "bestämde",
    "har bestämt",
)

# These phrases are narrowly authority-bearing: they claim that the current
# note owner already authored, believed, decided, or approved generated
# material. Broader stylistic or epistemic language belongs to later
# evidence/claims slices and is intentionally not invented here.
BANNED_GENERATED_PHRASES: tuple[str, ...] = (
    "you approve",
    "you approved",
    "you have approved",
    "approved by you",
    "you believe",
    "you believed",
    "you have believed",
    "you decide",
    "you decided",
    "you have decided",
    "your takeaway is",
    "your takeaways are",
    "the note owner approves",
    "the note owner approved",
    "the note owner has approved",
    "the note owner believes",
    "the note owner believed",
    "the note owner has believed",
    "the note owner decides",
    "the note owner decided",
    "the note owner has decided",
    "du godkänner",
    "du godkände",
    "du har godkänt",
    "godkänt av dig",
    "du tror",
    "du trodde",
    "du har trott",
    "du bestämmer",
    "du bestämde",
    "du har bestämt",
    "din slutsats är",
    "dina slutsatser är",
) + tuple(
    f"{subject} {predicate}"
    for subject in _SWEDISH_NOTE_OWNER_SUBJECTS
    for predicate in _SWEDISH_AUTHORITY_PREDICATES
)
_RESERVED_SECTION_HEADINGS = (
    OWNER_NOTES_HEADING,
    PROPOSALS_HEADING,
    EVIDENCE_HEADING,
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")
_WIKILINK_RE = re.compile(r"!?\[\[([^\]\n|]*)(?:\|([^\]\n]*))?\]\]")
_IGNORED_INLINE_MARKERS = frozenset(r"[]*_`~\\")
_APOSTROPHE_CHARACTERS = frozenset({"'", "’", "‘", "ʼ"})
_CONTRACTION_EXPANSIONS: Mapping[str, tuple[str, ...]] = {
    "you've": ("you", "have"),
    "owner's": ("owner", "has"),
}
_DEFAULT_IGNORABLE_RE = regex.compile(r"\p{Default_Ignorable_Code_Point}+")
_BIDI_CONTROL_RE = regex.compile(r"\p{Bidi_Control}")
_MARKDOWN = MarkdownIt("commonmark")

NormalizedTokens = tuple[str, ...]


class NoteRenderError(ValueError):
    """Raised when a candidate note cannot be rendered safely."""


class BannedGeneratedPhrasingError(NoteRenderError):
    """Raised when generated prose falsely claims owner authority."""


@dataclass(frozen=True)
class ProposalSection:
    """One registered, review-required generated module output."""

    module_id: str
    title: str
    content: str


def render_review_required_note(
    *,
    frontmatter: Mapping[str, Any],
    proposal_sections: Sequence[ProposalSection],
    evidence: Sequence[tuple[str, str]],
) -> str:
    """Render one authority-banded candidate note.

    The proposal wrapper is structural and therefore always present. Optional
    module headings appear only when their content is non-blank. Every line of
    generated module content is blockquoted, so multiline Markdown cannot
    escape the proposal band or create an owner-authored sibling section.
    """

    _assert_no_bidi_controls_in_value(frontmatter, surface="frontmatter")
    rendered_sections: list[str] = []
    seen_module_ids: set[str] = set()
    for section in proposal_sections:
        if not isinstance(section.content, str):
            raise NoteRenderError(
                f"proposal content must be text for module {section.module_id!r}"
            )
        _assert_no_bidi_controls(section.content, surface="proposal content")
        content = section.content.strip()
        if not content:
            continue
        module_id = section.module_id.strip()
        if not module_id:
            raise NoteRenderError("proposal module_id must be non-blank")
        if module_id in seen_module_ids:
            raise NoteRenderError(
                f"duplicate proposal module_id is not allowed: {module_id!r}"
            )
        _assert_no_bidi_controls(section.title, surface="proposal title")
        title = section.title.strip()
        if not title:
            raise NoteRenderError(
                f"proposal title must be non-blank for module {section.module_id!r}"
            )
        if len(title.splitlines()) != 1:
            raise NoteRenderError(
                f"proposal title must be one plain line for module {section.module_id!r}"
            )
        _assert_proposal_title_allowed(title)
        _assert_generated_prose_allowed(content)
        seen_module_ids.add(module_id)
        rendered_sections.append(
            f"### {_escape_inline_markdown_text(title)}\n\n{_quote_markdown(content)}"
        )

    proposals_body = (
        "\n\n".join(rendered_sections)
        if rendered_sections
        else "> _No proposal modules were produced._"
    )
    rendered_evidence: list[str] = []
    for label, value in evidence:
        _assert_no_bidi_controls(label, surface="evidence label")
        _assert_no_bidi_controls(str(value), surface="evidence value")
        rendered_evidence.append(
            f"- **{_plain_label(label)}:** {_plain_value(value)}"
        )
    evidence_body = "\n".join(rendered_evidence)
    if not evidence_body:
        raise NoteRenderError("at least one deterministic evidence field is required")

    yaml_block = yaml.safe_dump(
        dict(frontmatter),
        sort_keys=False,
        allow_unicode=True,
    ).strip()
    body = f"""
{OWNER_NOTES_HEADING}

### Takeaways

<!-- Add owner-authored takeaways here. -->

### Open threads

<!-- Add owner-authored open threads here. -->

{PROPOSALS_HEADING}

{proposals_body}

{EVIDENCE_HEADING}

{evidence_body}

---

_The source URL remains authoritative. Generated proposals are non-authoritative review
material. Promotion into durable knowledge requires human review and creates a distinct
artifact; this source note remains provenance._
"""
    rendered = f"---\n{yaml_block}\n---\n{body}"
    _assert_no_bidi_controls(rendered, surface="rendered output")
    return rendered


def _assert_generated_prose_allowed(content: str) -> None:
    normalized_variants, headings = _analyze_visible_markdown(content)
    reserved_titles = {
        _normalize_plain_text(heading.lstrip("#").strip())
        for heading in _RESERVED_SECTION_HEADINGS
    }
    for heading_text in headings:
        if _normalize_plain_text(heading_text) in reserved_titles:
            raise NoteRenderError(
                "generated prose cannot declare a reserved authority-band heading: "
                f"{heading_text!r}"
            )
    for normalized in normalized_variants:
        _assert_no_banned_authority_phrasing(normalized)


def _assert_proposal_title_allowed(title: str) -> None:
    normalized_variants, headings = _analyze_visible_markdown(title)
    reserved_titles = {
        _normalize_plain_text(heading.lstrip("#").strip())
        for heading in _RESERVED_SECTION_HEADINGS
    }
    if any(normalized in reserved_titles for normalized in normalized_variants) or any(
        _normalize_plain_text(heading) in reserved_titles for heading in headings
    ):
        raise NoteRenderError(
            "proposal title cannot impersonate a reserved authority-band heading"
        )
    for normalized in normalized_variants:
        _assert_no_banned_authority_phrasing(normalized)


def _assert_no_banned_authority_phrasing(normalized: NormalizedTokens) -> None:
    for phrase in BANNED_GENERATED_PHRASES:
        normalized_phrase = _normalize_plain_text(phrase)
        if _contains_phrase(normalized, normalized_phrase):
            raise BannedGeneratedPhrasingError(
                f"generated prose contains banned owner-authority phrase: {phrase!r}"
            )


def _contains_phrase(
    normalized: NormalizedTokens,
    phrase: NormalizedTokens,
) -> bool:
    if not phrase or len(phrase) > len(normalized):
        return False
    width = len(phrase)
    return any(
        normalized[index : index + width] == phrase
        for index in range(len(normalized) - width + 1)
    )


def _analyze_visible_markdown(
    value: str,
) -> tuple[tuple[NormalizedTokens, ...], tuple[str, ...]]:
    """Return parser-derived visible prose and headings.

    CommonMark owns link/reference parsing so invisible destinations and valid
    reference definitions are omitted while arbitrarily balanced link labels
    remain visible. Obsidian wikilinks are reduced to their visible alias (or
    target) before parsing. Raw HTML is checked both as semantic markup and as
    the escaped text the renderer actually materializes.
    """

    semantic_html = html.unescape(value)
    semantic_html = _HTML_COMMENT_RE.sub("", semantic_html)
    semantic_html = _HTML_TAG_RE.sub("", semantic_html)
    escaped_output = html.escape(value, quote=False)
    projections = (semantic_html, escaped_output)

    visible_variants: list[NormalizedTokens] = []
    headings: list[str] = []
    seen_projections: set[str] = set()
    for projection in projections:
        prepared = _prepare_markdown_projection(projection)
        if prepared in seen_projections:
            continue
        seen_projections.add(prepared)
        visible, projection_headings = _parse_visible_markdown(prepared)
        visible_variants.append(_normalize_plain_text(visible))
        headings.extend(projection_headings)
    return tuple(visible_variants), tuple(headings)


def _prepare_markdown_projection(value: str) -> str:
    prepared = _WIKILINK_RE.sub(
        lambda match: match.group(2) if match.group(2) is not None else match.group(1),
        value,
    )
    return _DEFAULT_IGNORABLE_RE.sub("", prepared)


def _parse_visible_markdown(prepared: str) -> tuple[str, tuple[str, ...]]:
    tokens = _MARKDOWN.parse(prepared)
    visible_parts: list[str] = []
    headings: list[str] = []
    for index, token in enumerate(tokens):
        if token.type == "inline":
            visible = _visible_inline_text(token.children or ())
            visible_parts.append(visible)
            if index > 0 and tokens[index - 1].type == "heading_open":
                headings.append(visible)
        elif token.type in {"code_block", "fence", "html_block"}:
            visible_parts.append(token.content)
    return "\n".join(visible_parts), tuple(headings)


def _visible_inline_text(tokens: Sequence[Token]) -> str:
    parts: list[str] = []
    for token in tokens:
        if token.type in {"text", "code_inline", "image", "html_inline"}:
            parts.append(token.content)
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        elif token.children:
            parts.append(_visible_inline_text(token.children))
    return "".join(parts)


def _normalize_plain_text(value: str) -> NormalizedTokens:
    folded = unicodedata.normalize("NFKC", value).casefold()
    token_text = "".join(
        (
            character
            if character.isalnum()
            else "'"
            if character in _APOSTROPHE_CHARACTERS
            else ""
            if character in _IGNORED_INLINE_MARKERS
            else " "
        )
        for character in folded
    )
    expanded: list[str] = []
    for token in token_text.split():
        expanded.extend(_CONTRACTION_EXPANSIONS.get(token, (token,)))
    return tuple(expanded)


def _assert_no_bidi_controls(value: str, *, surface: str) -> None:
    match = _BIDI_CONTROL_RE.search(value)
    if match is None:
        return
    character = match.group(0)
    codepoint = f"U+{ord(character):04X}"
    name = unicodedata.name(character, "UNKNOWN")
    raise NoteRenderError(
        f"bidirectional control {codepoint} {name} is not allowed in {surface}"
    )


def _assert_no_bidi_controls_in_value(value: Any, *, surface: str) -> None:
    if isinstance(value, str):
        _assert_no_bidi_controls(value, surface=surface)
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            _assert_no_bidi_controls_in_value(key, surface=surface)
            _assert_no_bidi_controls_in_value(item, surface=surface)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            _assert_no_bidi_controls_in_value(item, surface=surface)


def _escape_inline_markdown_text(value: str) -> str:
    return html.escape(value, quote=False)


def _quote_markdown(content: str) -> str:
    escaped = html.escape(content, quote=False)
    return "\n".join(f"> {line}" if line else ">" for line in escaped.splitlines())


def _plain_label(value: str) -> str:
    label = " ".join(value.split())
    if not label:
        raise NoteRenderError("evidence labels must be non-blank")
    return _escape_inline_markdown_text(label).replace("*", r"\*")


def _plain_value(value: str) -> str:
    return _escape_inline_markdown_text(" ".join(str(value).split()))


__all__ = [
    "BANNED_GENERATED_PHRASES",
    "EVIDENCE_HEADING",
    "OWNER_NOTES_HEADING",
    "PROPOSALS_HEADING",
    "BannedGeneratedPhrasingError",
    "NoteRenderError",
    "ProposalSection",
    "render_review_required_note",
]
