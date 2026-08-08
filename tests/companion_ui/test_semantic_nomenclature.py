"""Regression coverage for current Companion UI terminology."""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from tests.companion_ui._visible_text import visible_text


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ACTIVE_MARKUP = (
    _REPO_ROOT / "companion-ui/companion-app/canvas_suggestion_flow.html",
    _REPO_ROOT / "companion-ui/companion-app/converse_layout.html",
)
_ACTIVE_TEXT_SURFACES = (
    _REPO_ROOT / "companion-ui/companion-app/companion_ui/canvas_suggestion_flow/portrait_sheet.py",
    _REPO_ROOT / "companion-ui/docs/CANVAS_SUGGESTION_FLOW.md",
    _REPO_ROOT / "companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md",
    _REPO_ROOT / "companion-ui/docs/TEMPORAL_OVERLAYS.md",
)


class _AccessibleLabels(HTMLParser):
    """Collect user-facing markup attributes without inspecting CSS selectors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name in {"aria-label", "placeholder", "title"} and value:
                self.values.append(value)


def test_active_companion_ui_has_no_hugin_agent_label() -> None:
    """Current copy is normalized; dated design handoffs remain historical evidence."""
    for path in _ACTIVE_MARKUP:
        markup = path.read_text(encoding="utf-8")
        labels = _AccessibleLabels()
        labels.feed(markup)
        assert "hugin" not in visible_text(markup), path
        assert "hugin" not in " ".join(labels.values).casefold(), path

    for path in _ACTIVE_TEXT_SURFACES:
        assert "hugin" not in path.read_text(encoding="utf-8").casefold(), path

    term_map = (_REPO_ROOT / "companion-ui/docs/CORE_TERM_MAPPING.md").read_text(encoding="utf-8")
    assert "| **Hugin** | Historical design label;" in term_map
    assert "Reserved and inactive." in term_map
    assert "| **Munin** | Historical design label;" in term_map
    assert "Dated handoff history may retain it with historical status." in term_map


def test_canvas_copy_uses_chat_surface_terms() -> None:
    canvas_markup = (_REPO_ROOT / "companion-ui/companion-app/canvas_suggestion_flow.html").read_text(encoding="utf-8")
    converse_markup = (_REPO_ROOT / "companion-ui/companion-app/converse_layout.html").read_text(encoding="utf-8")

    assert "chat conversation rail" in canvas_markup.casefold()
    assert "message chat" in canvas_markup.casefold()
    assert "agent · proposed addition" in visible_text(canvas_markup)
    assert "chat rail" in converse_markup.casefold()
    assert "message chat" in converse_markup.casefold()
    assert "agent · proposed addition" in visible_text(converse_markup)

    # Stable structural selectors remain the test and state-machine contract.
    for markup in (canvas_markup, converse_markup):
        assert 'data-testid="margin-rail"' in markup
        assert 'data-testid="conversation-thread"' in markup
