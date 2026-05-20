"""Tests for Companion UI production launch profile (#1144)."""

from __future__ import annotations


def test_production_port(monkeypatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    from companion_ui.workspace.serve_production_page import load_config

    assert load_config()["port"] == 8113


def test_no_dev_marker_in_production() -> None:
    from companion_ui.workspace.serve_production_page import render_production_index_html

    html = render_production_index_html(api_base_url="http://127.0.0.1:18000")

    assert "DEV / not production" not in html
    assert "dev/staging" not in html.lower()
    assert "not production" not in html.lower()


def test_runtime_target_configurable(monkeypatch) -> None:
    monkeypatch.setenv("COMPANION_API_BASE_URL", "http://127.0.0.1:18042")
    from companion_ui.workspace.serve_production_page import load_config

    assert load_config()["api_base_url"] == "http://127.0.0.1:18042"


def test_production_output_links_static_asset() -> None:
    from companion_ui.workspace.serve_production_page import render_production_index_html

    html = render_production_index_html(api_base_url="http://127.0.0.1:18000")

    assert 'href="/static/companion-workspace.css"' in html
