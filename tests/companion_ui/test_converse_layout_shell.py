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


def test_layout_state_switch_and_geometry_tokens() -> None:
    state = _load_state_module()

    collapsed = state.resolve_layout_state("collapsed")
    assert collapsed.rail_width_px == 32
    assert collapsed.rail_class == "rail rail--collapsed"

    expanded = state.resolve_layout_state("expanded")
    assert expanded.rail_width_px == 288
    assert expanded.rail_class == "rail rail--expanded"


def test_document_column_is_constrained_and_centered() -> None:
    css_path = Path(__file__).resolve().parents[2] / "companion-ui" / "src" / "converse_layout.css"
    css_text = css_path.read_text(encoding="utf-8")

    assert "max-width: 640px;" in css_text
    assert "margin: 0 auto;" in css_text


def test_landscape_shell_contains_top_bar_document_and_rail_container() -> None:
    html_path = Path(__file__).resolve().parents[2] / "companion-ui" / "src" / "converse_layout.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert 'data-testid="top-bar"' in html_text
    assert 'data-testid="document-pane"' in html_text
    assert 'data-testid="margin-rail"' in html_text
    assert 'data-rail-state="collapsed"' in html_text
