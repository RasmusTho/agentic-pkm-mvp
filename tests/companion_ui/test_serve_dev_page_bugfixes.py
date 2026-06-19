"""Focused regressions for serve_dev_page render bugs (#2159, #2160, #2161, #2162)."""

from __future__ import annotations

from types import SimpleNamespace

from companion_ui.workspace.serve_dev_page import (
    _e,
    _is_remote_page_origin,
    _render_orientation_resurface,
    _render_portrait_sheet,
    _render_workspace_breadcrumb,
)


def test_portrait_sheet_aria_hidden_lowercase() -> None:
    # #2159 — ARIA defines only lowercase true/false; a Python bool must not be
    # stringified to "True"/"False" (which assistive tech does not honor).
    hidden = _render_portrait_sheet({"is_visible": False})
    assert 'aria-hidden="true"' in hidden
    assert 'aria-hidden="True"' not in hidden
    assert 'aria-hidden="False"' not in hidden

    shown = _render_portrait_sheet({"is_visible": True})
    assert 'aria-hidden="false"' in shown
    assert 'aria-hidden="True"' not in shown
    assert 'aria-hidden="False"' not in shown


def test_breadcrumb_escapes_once() -> None:
    # #2160 — the incoming note_path is already HTML-escaped; the breadcrumb must
    # escape exactly once, not double-escape every non-ampersand metacharacter.
    note_path = _e("Today's plan.md")  # what the caller passes: "Today&#x27;s plan.md"
    html = _render_workspace_breadcrumb(
        note_path=note_path,
        artifact_id="",
        content_hash="",
        identity_state="",
        identity_source="",
        artifact_kind="",
        owns_identity=False,
        companion_html="",
        rendered_props=SimpleNamespace(fields=(), html=""),
    )
    assert "Today&#x27;s plan.md" in html
    # The bug rendered the literal "Today&amp;#x27;s plan.md" (double-escaped),
    # both in the visible breadcrumb and in data-note-path (read by JS as the
    # real path) — neither must double-escape.
    assert "Today&amp;#x27;s" not in html
    assert 'data-note-path="Today&#x27;s plan.md"' in html


def test_resurface_badge_counts_all_candidates() -> None:
    # #2161 — with more candidates than the display budget (3), the count badge
    # must show the full capped count, like the sibling sections, not just the
    # visible subset.
    resurface = {"candidates": [{"label": f"C{i}", "why_now": "x"} for i in range(5)]}
    html = _render_orientation_resurface(resurface)  # no caps -> no server cap

    assert '<span class="orientation-count">5</span>' in html
    assert '<span class="orientation-count">3</span>' not in html
    # The 2 beyond the budget are still offered as overflow.
    assert 'data-resurface-overflow-count="2"' in html


def test_bracketed_ipv6_loopback_with_port_is_local() -> None:
    # #2162 — a bracketed IPv6 loopback carrying a port must be recognized as
    # local, not misclassified as a remote origin.
    assert _is_remote_page_origin("[::1]:8111") is False
    assert _is_remote_page_origin("[::1]") is False
    assert _is_remote_page_origin("127.0.0.1:8111") is False
    assert _is_remote_page_origin("localhost:8111") is False
    assert _is_remote_page_origin("localhost") is False
    # Real remote hosts still classify as remote.
    assert _is_remote_page_origin("example.com") is True
    assert _is_remote_page_origin("example.com:443") is True
    assert _is_remote_page_origin("[2001:db8::1]:443") is True
