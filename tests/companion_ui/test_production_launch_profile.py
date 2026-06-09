"""Tests for Companion UI production launch profile (#1144)."""

from __future__ import annotations

import inspect
from http.server import ThreadingHTTPServer


def test_production_port(monkeypatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    from companion_ui.workspace.serve_production_page import load_config

    assert load_config()["port"] == 8113


def test_production_default_host_is_server_bind(monkeypatch) -> None:
    monkeypatch.delenv("HOST", raising=False)
    from companion_ui.workspace.serve_production_page import load_config

    assert load_config()["host"] == "0.0.0.0"


def test_production_default_api_points_at_prod_runtime(monkeypatch) -> None:
    monkeypatch.delenv("COMPANION_API_BASE_URL", raising=False)
    from companion_ui.workspace.serve_production_page import load_config

    assert load_config()["api_base_url"] == "http://127.0.0.1:18000"


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


def test_production_safety_warning_is_explicit() -> None:
    from companion_ui.workspace.serve_production_page import _PRODUCTION_SAFETY_WARNING

    warning = _PRODUCTION_SAFETY_WARNING.lower()
    assert "server/lan bind default" in warning
    assert "public internet exposure is not supported" in warning
    assert "auth" in warning
    assert "tls" in warning
    assert "reverse proxy" in warning


def test_companion_ui_dev_server_uses_threaded_http_server() -> None:
    from companion_ui.workspace import serve_dev_page

    assert issubclass(serve_dev_page.CompanionThreadingHTTPServer, ThreadingHTTPServer)
    assert serve_dev_page.CompanionThreadingHTTPServer.daemon_threads is True
    assert "CompanionThreadingHTTPServer" in inspect.getsource(serve_dev_page.main)


def test_companion_ui_production_server_uses_threaded_http_server() -> None:
    from companion_ui.workspace import serve_dev_page
    from companion_ui.workspace import serve_production_page

    assert (
        serve_production_page.CompanionThreadingHTTPServer
        is serve_dev_page.CompanionThreadingHTTPServer
    )
    assert "CompanionThreadingHTTPServer" in inspect.getsource(
        serve_production_page.main
    )


def test_production_shell_shows_runtime_channel_and_guard_state() -> None:
    from companion_ui.workspace.serve_production_page import render_production_index_html

    html = render_production_index_html(
        api_base_url="http://127.0.0.1:18000",
        fields={
            "title": "Prod Note",
            "note_path": "Notes/prod.md",
            "artifact_id": "art-prod",
            "content_hash": "hash-prod",
            "body": "# Prod Note",
            "runtime_environment_label": "prod",
            "runtime_api_base_url_label": "local-prod",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": True,
            "guard_degraded": False,
        },
    )

    assert 'data-testid="workspace-runtime-channel"' in html
    assert "prod" in html
    assert "local-prod" in html
    assert 'data-testid="workspace-writeguard-state"' in html
    assert 'data-testid="workspace-guard-degraded-state"' in html


def test_production_launch_safety_doc_covers_operator_requirements() -> None:
    from pathlib import Path

    doc = Path("companion-ui/docs/MLP_PRODUCTION_LAUNCH_SAFETY.md").read_text(
        encoding="utf-8"
    )

    assert "python -m companion_ui.workspace.serve_production_page" in doc
    assert "Runtime API | 18001 | 18002 | 18000" in doc
    assert "Companion UI | 8111 | 8112 | 8113" in doc
    assert "HOST=0.0.0.0" in doc
    assert "Tailscale" in doc
    assert "Do not expose this profile to the public internet." in doc
    assert "curl -fsS http://127.0.0.1:18000/health" in doc
    assert "Ctrl-C" in doc
    assert "No direct UI vault writes" in doc


def test_production_launch_docs_cover_tailscale_warning() -> None:
    from pathlib import Path

    doc = Path("companion-ui/docs/MLP_PRODUCTION_LAUNCH_SAFETY.md").read_text(
        encoding="utf-8"
    )

    assert "HOST=127.0.0.1" in doc
    assert "Tailscale" in doc
    assert "trusted personal networks or trusted tailnets" in doc
    assert "Do not expose this profile to the public internet." in doc
