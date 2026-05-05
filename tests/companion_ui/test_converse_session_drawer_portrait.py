"""Tests for issue #743: session drawer (C.4) and portrait bottom-sheet (C.5) states."""
from pathlib import Path
import importlib.util


def _load_state_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "companion-ui" / "src" / "converse_layout_state.py"
    spec = importlib.util.spec_from_file_location("converse_layout_state", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _html() -> str:
    html_path = Path(__file__).resolve().parents[2] / "companion-ui" / "src" / "converse_layout.html"
    return html_path.read_text(encoding="utf-8")


def _css() -> str:
    css_path = Path(__file__).resolve().parents[2] / "companion-ui" / "src" / "converse_layout.css"
    return css_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1 — Session drawer opens/closes from session pill with scrim-dismiss
# ---------------------------------------------------------------------------


def test_session_pill_present_with_open_intent() -> None:
    html = _html()
    assert 'data-testid="session-pill"' in html
    assert 'data-intent="session-drawer.open"' in html


def test_session_drawer_markup_present_and_closed_by_default() -> None:
    html = _html()
    assert 'data-testid="session-drawer"' in html
    assert 'data-drawer-state="closed"' in html


def test_session_drawer_scrim_has_dismiss_intent() -> None:
    html = _html()
    assert 'data-testid="session-drawer-scrim"' in html
    assert 'data-intent="session-drawer.dismiss"' in html


def test_session_drawer_close_button_has_close_intent() -> None:
    html = _html()
    assert 'data-testid="session-drawer-close"' in html
    assert 'data-intent="session-drawer.close"' in html


def test_session_drawer_contains_header_search_and_list() -> None:
    html = _html()
    assert 'data-testid="session-drawer-search"' in html
    assert 'data-testid="session-list"' in html
    assert 'data-testid="session-list-item-active"' in html
    assert 'data-testid="session-drawer-footer"' in html


def test_session_drawer_css_hidden_when_closed_and_visible_when_open() -> None:
    css = _css()
    assert 'data-drawer-state="closed"' in css
    assert 'data-drawer-state="open"' in css


def test_session_drawer_scrim_css_blur_overlay() -> None:
    css = _css()
    assert "backdrop-filter" in css
    assert ".session-drawer-scrim" in css


def test_session_drawer_state_model_resolves_open_and_closed() -> None:
    state = _load_state_module()
    closed = state.resolve_session_drawer_state(drawer_open=False)
    assert closed.drawer_open is False
    assert closed.drawer_state == "closed"   # must match CSS [data-drawer-state="closed"]
    assert closed.drawer_class == "session-drawer-overlay"

    open_ = state.resolve_session_drawer_state(drawer_open=True)
    assert open_.drawer_open is True
    assert open_.drawer_state == "open"      # must match CSS [data-drawer-state="open"]
    assert open_.drawer_class == closed.drawer_class  # same base class; state carried by drawer_state


# ---------------------------------------------------------------------------
# AC2 — Portrait mode uses bottom-sheet rail instead of side panel
# ---------------------------------------------------------------------------


def test_portrait_bottom_sheet_element_present() -> None:
    html = _html()
    assert 'data-testid="bottom-sheet"' in html
    assert 'data-sheet-snap=' in html


def test_portrait_css_switches_to_full_width_document() -> None:
    css = _css()
    assert "@media" in css
    assert "portrait" in css or "max-width" in css


def test_portrait_css_hides_margin_rail_and_shows_bottom_sheet() -> None:
    css = _css()
    assert ".bottom-sheet" in css


def test_portrait_layout_state_resolves_snap_points() -> None:
    state = _load_state_module()
    peek = state.resolve_portrait_layout_state(sheet_snap="peek")
    assert peek.sheet_snap == "peek"         # value for data-sheet-snap attribute
    assert peek.sheet_height_px == 240
    assert peek.sheet_class == "bottom-sheet"  # base class only; snap state via sheet_snap

    collapsed = state.resolve_portrait_layout_state(sheet_snap="collapsed")
    assert collapsed.sheet_snap == "collapsed"
    assert collapsed.sheet_height_px == 32
    assert collapsed.sheet_class == "bottom-sheet"


# ---------------------------------------------------------------------------
# AC3 — Bottom sheet supports collapsed/expanded states, composer in peek
# ---------------------------------------------------------------------------


def test_bottom_sheet_drag_handle_present() -> None:
    html = _html()
    assert 'data-testid="bottom-sheet-handle"' in html


def test_bottom_sheet_snap_data_attribute_reflects_snap_state() -> None:
    html = _html()
    assert 'data-sheet-snap="peek"' in html


def test_bottom_sheet_contains_composer_for_peek_visibility() -> None:
    html = _html()
    assert 'data-testid="bottom-sheet-composer-send"' in html


def test_portrait_layout_state_full_snap_covers_most_of_viewport() -> None:
    state = _load_state_module()
    full = state.resolve_portrait_layout_state(sheet_snap="full")
    assert full.sheet_snap == "full"
    assert full.sheet_height_vh == 80


def test_portrait_layout_state_rejects_unknown_snap() -> None:
    import pytest
    state = _load_state_module()
    with pytest.raises(ValueError):
        state.resolve_portrait_layout_state(sheet_snap="unknown")
