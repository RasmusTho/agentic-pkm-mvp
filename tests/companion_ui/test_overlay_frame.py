"""One overlay modal-frame contract across every overlay (CUIDR-02, #2445).

Implements the `Verify:` targets of
`docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/OVERLAY_MODAL_FRAME_SPEC.md`:

- `test_all_overlays_use_declared_frame` — every overlay (palette, capture,
  receipts, settings, memory, system map) renders through the one frame: a
  declared `data-overlay-frame-position`, a single
  `<header data-region="overlay-header">` carrying the furniture slots in the
  fixed order (title -> status-pill? -> info? -> close), the single host scrim
  wired to `overlayHost.dismiss()`, and the focus-trap hook while open.
- `test_overlay_frame_component_is_sole_frame_source` — the
  `overlay_frame` render path is the single code site that emits the header
  furniture markup and the close dismiss binding; no overlay module emits a
  bespoke `<header data-region="overlay-header">`, a duplicate scrim, or a
  standalone `overlayHost.dismiss()` binding outside the frame.

The frame is presentation only (capability-wide invariant): it carries no
entry-state, authority, posture, staleness, or receipt classification.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from companion_ui.workspace.overlay_frame import (
    FRAME_POSITIONS,
    HEADER_FURNITURE_ORDER,
    overlay_frame_header,
    overlay_frame_root_attrs,
)
from companion_ui.workspace.serve_dev_page import render_index_html

# ---------------------------------------------------------------------------
# Fixtures (mirror the proven workspace fixture in test_overlay_host)
# ---------------------------------------------------------------------------


def _proposal(proposal_id: str) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "artifact_id": "art-2445",
        "description": f"Move {proposal_id}",
        "evidence": {"action_class": "lifecycle.move", "cognition_route": "rule"},
        "status": "staged",
        "affordances": {"confirm": True, "correct": True, "reject": True},
    }


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-2445",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "proposals-staged",
        "panel_proposal_count": 1,
        "panel_proposals": [_proposal("prop-1")],
        "panel_message": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
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


def _render(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


# The six overlays in scope, with the frame position each adopts (spec
# §Concretely table) and the overlay-root testid that marks each surface.
_OVERLAYS: tuple[tuple[str, str, str], ...] = (
    ("cmd", "center", "panel-palette"),
    ("capture", "center", "capture-modal"),
    ("receipts", "center", "receipts-history-modal"),
    ("settings", "right-drawer", "settings-drawer"),
    ("memory", "right-drawer", "memory-review-drawer"),
    ("map", "center", "system-map-overlay"),
)


def _overlay_root_tag(html: str, testid: str) -> str:
    m = re.search(rf'<[a-z]+[^>]*data-testid="{re.escape(testid)}"[^>]*>', html)
    assert m, f"overlay root for {testid!r} must render"
    return m.group(0)


def _overlay_header(html: str, overlay_id: str) -> str:
    """The frame header for one overlay id, extracted from the rendered page."""
    headers = re.findall(
        r'<header[^>]*data-region="overlay-header"[^>]*>.*?</header>', html, re.S
    )
    for header in headers:
        if f'data-overlay-id="{overlay_id}"' in header:
            return header
    raise AssertionError(f"frame header for overlay {overlay_id!r} must render")


def _furniture_positions(header: str) -> dict[str, int]:
    """Index of each furniture slot region inside one frame header."""
    return {
        "title": header.find('data-region="overlay-title"'),
        "status": header.find('data-region="overlay-status-pill"'),
        "info": header.find('data-region="overlay-info"'),
        "close": header.find('data-region="overlay-close"'),
    }


# ---------------------------------------------------------------------------
# AC-B4: every overlay uses one declared frame, identical header furniture
# order and scrim; one dismiss grammar; focus trap while open.
# ---------------------------------------------------------------------------


def test_all_overlays_use_declared_frame() -> None:
    # The capture modal only ships on the orientation substrate when cold; the
    # workspace shell carries the other five plus capture. Render the shell.
    html = _render()

    assert HEADER_FURNITURE_ORDER == ("title", "status", "info", "close")
    assert set(FRAME_POSITIONS) == {"center", "right-drawer"}

    for overlay_id, expected_position, root_testid in _OVERLAYS:
        root = _overlay_root_tag(html, root_testid)

        # Declared frame position — exactly one, from the declared set.
        m = re.search(r'data-overlay-frame-position="([^"]+)"', root)
        assert m, f"{root_testid} must carry data-overlay-frame-position"
        assert m.group(1) in FRAME_POSITIONS
        assert m.group(1) == expected_position, (
            f"{root_testid} must adopt the spec's {expected_position!r} position"
        )

        # Focus-trap hook present on the overlay root (live motion in UAT).
        assert 'data-overlay-focus-trap="true"' in root, (
            f"{root_testid} must declare the focus-trap hook"
        )

        # One frame header with the furniture slots in the fixed order.
        header = _overlay_header(html, overlay_id)
        pos = _furniture_positions(header)
        assert pos["title"] != -1, f"{overlay_id}: title slot is mandatory"
        assert pos["close"] != -1, f"{overlay_id}: close slot is mandatory"
        present = [
            (name, idx) for name, idx in pos.items() if idx != -1
        ]
        order = [name for name, _ in sorted(present, key=lambda kv: kv[1])]
        canonical = [n for n in HEADER_FURNITURE_ORDER if pos[n] != -1]
        assert order == canonical, (
            f"{overlay_id}: header furniture out of order: {order} != {canonical}"
        )

        # The close affordance routes through the one dismiss grammar.
        close = re.search(
            r'<button[^>]*data-region="overlay-close"[^>]*>', header
        )
        assert close, f"{overlay_id}: frame must render a close affordance"
        assert "overlayHost.dismiss()" in close.group(0)
        assert 'data-intent="overlay.dismiss"' in close.group(0)

    # Exactly one scrim on the page, wired to the one dismiss grammar.
    scrims = re.findall(r'data-testid="workspace-overlay-scrim"', html)
    assert len(scrims) == 1, "exactly one overlay scrim must render"
    scrim_tag = re.search(
        r'<div[^>]*data-testid="workspace-overlay-scrim"[^>]*>', html
    )
    assert scrim_tag and "overlayHost.dismiss()" in scrim_tag.group(0)

    # The host controller carries the focus trap: it reads the focus-trap hook
    # and keeps Tab within the open overlay (Esc dismiss + trap motion: UAT).
    assert "data-overlay-focus-trap" in html
    assert "Escape" in html  # one Esc owner (host) — asserted in test_overlay_host

    # The capture modal carries the frame on the cold_start substrate too.
    cold = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_cold_start_orientation(),
    )
    capture_root = _overlay_root_tag(cold, "capture-modal")
    assert 'data-overlay-frame-position="center"' in capture_root
    assert 'data-overlay-focus-trap="true"' in capture_root


# ---------------------------------------------------------------------------
# AC-Frame: the overlay-frame render path is the sole source of frame markup.
# ---------------------------------------------------------------------------

# Overlay modules: each renders content through the shared frame and must not
# emit a bespoke header/scrim/dismiss of its own.
_OVERLAY_MODULES = (
    "panel_palette",
    "capture_modal",
    "receipts_history",
    "settings_drawer",
    "memory_review_drawer",
    "system_map_overlay",
)


def _module_source(name: str) -> str:
    import importlib

    mod = importlib.import_module(f"companion_ui.workspace.{name}")
    import inspect

    return inspect.getsource(mod)


def test_overlay_frame_component_is_sole_frame_source() -> None:
    # The frame header markup is emitted only by overlay_frame: no overlay
    # module contains a literal `data-region="overlay-header"` of its own.
    for name in _OVERLAY_MODULES:
        src = _module_source(name)
        assert 'data-region="overlay-header"' not in src, (
            f"{name} must not emit a bespoke overlay header; use overlay_frame"
        )
        # No overlay module renders its own scrim — the host owns the one scrim.
        assert "workspace-overlay-scrim" not in src, (
            f"{name} must not emit a duplicate scrim; the host owns the scrim"
        )

    # The frame header markup is emitted by the overlay_frame module.
    frame_src = _module_source_frame()
    assert 'data-region="overlay-header"' in frame_src
    assert "overlayHost.dismiss()" in frame_src

    # The single scrim + its dismiss binding live once, in the overlay host.
    host_src = _module_source("overlay_host")
    assert host_src.count('data-testid="workspace-overlay-scrim"') == 1

    # Rendered page: exactly one overlay header per shipped overlay, no more.
    html = _render()
    headers = re.findall(
        r'<header[^>]*data-region="overlay-header"[^>]*data-overlay-id="([^"]+)"',
        html,
    )
    # One header per shell overlay (capture also ships on the shell).
    assert sorted(headers) == sorted(
        ["cmd", "capture", "receipts", "settings", "memory", "map"]
    ), f"each overlay renders exactly one frame header, got {sorted(headers)}"

    # No overlay root emits a duplicate scrim element (the single scrim is in
    # the overlay-host; duplicate = a second data-testid="workspace-overlay-scrim").
    assert html.count('data-testid="workspace-overlay-scrim"') == 1, (
        "exactly one workspace-overlay-scrim must render on the page"
    )

    # Frame close buttons are the only overlay-dismiss inline bindings in
    # overlay markup. Check rendered HTML for onclick bindings outside
    # data-region="overlay-close" elements (the scrim and frame close are
    # the only legitimate inline dismiss sites on the page).
    # Assert there are no overlay root headers that carry the bespoke
    # old-style close testids (pre-CUIDR-02) — these would indicate an
    # overlay bypassed the frame.
    bespoke_close_ids = (
        "capture-close",
        "receipts-history-close",
        "memory-review-close",
        "system-map-close",
        "settings-close",
        "palette-close",
    )
    for testid in bespoke_close_ids:
        assert f'data-testid="{testid}"' not in html, (
            f"overlay must not emit bespoke close {testid!r}; use overlay-frame-close"
        )


def _module_source_frame() -> str:
    import inspect

    from companion_ui.workspace import overlay_frame

    return inspect.getsource(overlay_frame)


# ---------------------------------------------------------------------------
# Frame contract unit tests (pure)
# ---------------------------------------------------------------------------


def test_frame_header_renders_furniture_in_fixed_order() -> None:
    header = overlay_frame_header(
        overlay_id="settings",
        title="Settings",
        status_pill="read-only",
        guidance_surface="settings",
    )
    pos = {
        "title": header.find('data-region="overlay-title"'),
        "status": header.find('data-region="overlay-status-pill"'),
        "info": header.find('data-region="overlay-info"'),
        "close": header.find('data-region="overlay-close"'),
    }
    assert -1 not in pos.values()
    assert pos["title"] < pos["status"] < pos["info"] < pos["close"]
    assert "read-only" in header
    assert "overlayHost.dismiss()" in header


def test_frame_header_omits_absent_slots() -> None:
    # Palette: title + close only (no status-pill, no ⓘ).
    header = overlay_frame_header(overlay_id="cmd", title="Panel")
    assert 'data-region="overlay-status-pill"' not in header
    assert 'data-region="overlay-info"' not in header
    assert 'data-region="overlay-title"' in header
    assert 'data-region="overlay-close"' in header


def test_frame_root_attrs_rejects_undeclared_position() -> None:
    assert "center" in overlay_frame_root_attrs(overlay_id="cmd", position="center")
    with pytest.raises(ValueError):
        overlay_frame_root_attrs(overlay_id="cmd", position="bottom-sheet")


def _cold_start_orientation() -> dict:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-20T10:00:00Z",
            "trace_id": "trace-cold",
            "freshness": "fresh",
            "stale_after": "2026-06-20T10:05:00Z",
            "degraded_reasons": [],
        },
        "leave_point": {"status": "absent"},
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "healthy",
            "degraded": False,
            "reasons": [],
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "mutation_intents": [],
    }
