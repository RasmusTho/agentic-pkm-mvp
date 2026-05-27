"""Orphan text-node regression tests for Companion UI (#1343).

Implements ACs 1–5 from issue #1343 / design §11.1 closing rule.
"""
from __future__ import annotations

import pytest
from companion_ui.workspace.serve_dev_page import render_index_html

from tests.companion_ui._orphan_text import (
    CONTAINER_TESTIDS,
    assert_no_orphan_text,
)


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _fields(**overrides) -> dict:
    base: dict = {
        "title": "Orphan Check Note",
        "note_path": "Notes/orphan-check.md",
        "artifact_id": "art-orphan-001",
        "content_hash": "sha256-abc",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": False,
        "guard_update_flow_available": True,
        "runtime_vault_provenance": "resolved",
        "runtime_vault_name": "TestVault",
        "runtime_vault_channel": "dev",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_proposals": [],
        "panel_message": "",
        "find_candidates": [],
        "reorient_sections": None,
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _render(**overrides) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=overrides.get("note_path", "Notes/orphan-check.md"),
        fields=_fields(**overrides),
    )


# ---------------------------------------------------------------------------
# AC1 — helper detects an orphan text node
# ---------------------------------------------------------------------------


class TestHelperDetectsOrphan:
    def test_helper_detects_orphan(self) -> None:
        fragment = "<html><body><div>Bare orphan text here</div></body></html>"
        with pytest.raises(AssertionError, match="orphan"):
            assert_no_orphan_text(fragment)

    def test_helper_is_silent_for_safe_containers(self) -> None:
        fragment = (
            '<html><body>'
            '<div data-testid="workspace-note-body"><p>Safe text</p></div>'
            '</body></html>'
        )
        assert_no_orphan_text(fragment)

    def test_helper_ignores_whitespace_only_nodes(self) -> None:
        fragment = "<html><body><div>   \n\t   </div></body></html>"
        assert_no_orphan_text(fragment)

    def test_helper_ignores_style_and_script_content(self) -> None:
        fragment = (
            "<html><head><style>body { margin: 0; }</style></head>"
            "<body><script>var x = 1;</script></body></html>"
        )
        assert_no_orphan_text(fragment)


# ---------------------------------------------------------------------------
# AC2 — whitelist covers current legitimate surfaces
# ---------------------------------------------------------------------------


class TestWhitelistCoverage:
    def test_whitelist_covers_current_surfaces(self) -> None:
        required = {
            # §7.2 header strip
            "workspace-wordmark",
            "workspace-vault-chip",
            "workspace-runtime-pill",
            "workspace-freshness",
            "workspace-dev-ribbon",
            # breadcrumb
            "workspace-breadcrumb",
            # body
            "workspace-note-body",
            # runtime popover
            "workspace-runtime-status-popover",
            # banner
            "workspace-vault-unreachable-banner",
            # outline
            "note-outline-link",
        }
        for token in required:
            assert token in CONTAINER_TESTIDS, (
                f"{token!r} missing from CONTAINER_TESTIDS — add it to _orphan_text.py"
            )


# ---------------------------------------------------------------------------
# AC3 — helper passes on a clean render
# ---------------------------------------------------------------------------


class TestCleanRenderPasses:
    def test_helper_passes_on_clean_render(self) -> None:
        html = _render(body="# Test Note\n\nThis is body content.\n\n- item 1\n- item 2")
        assert_no_orphan_text(html)

    def test_helper_passes_with_heading_content(self) -> None:
        body = "# Heading\n\n## Sub-heading\n\nBody paragraph.\n\n> Callout text"
        html = _render(body=body)
        assert_no_orphan_text(html)

    def test_helper_passes_with_empty_panel(self) -> None:
        html = _render(panel_state="idle", panel_proposal_count=0)
        assert_no_orphan_text(html)


# ---------------------------------------------------------------------------
# AC4 — helper catches the §4.5 runtime-leak regression class
# ---------------------------------------------------------------------------


class TestRuntimeLeakRegression:
    def test_helper_catches_runtime_leak_regression(self) -> None:
        fragment = (
            '<html><body><div class="workspace-main">'
            "Degradedvault/dev8f3c7b55433e4126b1cb3a6ae30b430c"
            "</div></body></html>"
        )
        with pytest.raises(AssertionError):
            assert_no_orphan_text(fragment)

    def test_helper_catches_runtime_string_at_top_level(self) -> None:
        fragment = (
            '<html><body><div>'
            "runtime/trace/8f3c7b55433e4126b1cb3a6ae30b430c"
            "</div></body></html>"
        )
        with pytest.raises(AssertionError):
            assert_no_orphan_text(fragment)
