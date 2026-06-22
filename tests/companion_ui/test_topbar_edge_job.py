"""Edge job and reachability — CUIDR-04 (#2447).

Static render assertions for ``docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/
EDGE_JOB_AND_REACHABILITY.md`` (B2, B3, C1). All three are server-rendered
captures — no live runtime.

The settled design decision this enforces:

- **Top edge keeps identity + ONE primary action** (Capture, ⌘N). Every other
  surface launcher (vault, map, memory, receipts, settings, help) leaves the
  topbar nav and is reachable via the System Map overlay — a never-clipping
  surface. ``capture`` stays on the topbar at every width.
- **At 430 px** the identity/status string truncates (never runs off-screen)
  and the bottom edge consolidates into a single composed bar; no
  independently positioned ``position: fixed`` sibling remains at the bottom
  edge.
- **Operator/diagnostic telemetry is off the shell and orientation surfaces.**
  The runtime pill, the freshness string, the front-edge quick-open hint, and
  the floating ``operator.open`` affordance do not render on the shell or any
  entry-state orientation surface; the operator layer (System Map node +
  operator drawer) is the only place they are reachable.

Binding constraint (Codex review of the spec PR #2454): the displaced
launchers are **not** routed into the ``cmd`` Panel palette — ``cmd`` is a
presentation of the Panel rail's server-declared proposals, not a general
surface launcher (``tests/companion_ui/test_panel_command_palette.py``). They
route to the System Map overlay, the real surface index. This module asserts
that, and asserts the topbar nav no longer carries them.

Presentation only: the telemetry VALUES still arrive from the runtime payload;
this changes WHERE they render, never the server-authoritative classification.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.overlay_host import (
    OVERFLOW_TOPBAR_SURFACES,
    SHIPPED_TOPBAR_SURFACES,
)
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.system_map_overlay import system_map_overlay_markup

# ---------------------------------------------------------------------------
# Fixtures — workspace shell (fields) + orientation (entry-state) snapshots
# ---------------------------------------------------------------------------

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
_GAP_NO_MIST = timedelta(seconds=30)
_GAP_THREAD_FADE = timedelta(minutes=5)
_GAP_FULL_MIST = timedelta(days=1)
_GAP_LONG_MIST = timedelta(days=7)
_GAP_COLD = timedelta(days=21)


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-edge",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-edge",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-edge",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
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
        "workspace_loaded_at": "2026-06-10T21:08:00Z",
    }
    base.update(overrides)
    return base


def _shell(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact_ref() -> dict[str, str]:
    return {
        "artifact_id": "art-resume",
        "note_path": "Notes/resume.md",
        "title": "Resume plan",
    }


def _orientation_payload(
    *, gap: timedelta | None = _GAP_FULL_MIST, degraded: bool = False
) -> dict[str, Any]:
    reasons = ["resurfacing_source_unavailable"] if degraded else []
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-orientation-1",
            "freshness": "partial" if reasons else "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": reasons,
            "caps": {
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "mutation_intents": 0,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": {
            "status": "present",
            "artifact_ref": _artifact_ref(),
            "label": "Resume the runtime API contract",
            "captured_at": _iso(_AS_OF - gap) if gap is not None else None,
            "last_session_id": "session-123",
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        },
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "logged",
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "g", "label": "g"},
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded" if reasons else "healthy",
            "degraded": bool(reasons),
            "reasons": reasons,
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "mutation_intents": [],
    }


def _orientation(**kwargs: Any) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(**kwargs),
    )


# Entry-state render matrix the C1 scan walks (the spec names these by name;
# the "mist" rungs are gaps within the `orienting` resolution).
_ENTRY_RENDERS: dict[str, str] = {
    "cold_start": _orientation(gap=_GAP_COLD),
    "no_mist": _orientation(gap=_GAP_NO_MIST),
    "thread_fade": _orientation(gap=_GAP_THREAD_FADE),
    "full_mist": _orientation(gap=_GAP_FULL_MIST),
    "long_mist": _orientation(gap=_GAP_LONG_MIST),
    "degraded": _orientation(gap=_GAP_FULL_MIST, degraded=True),
}


def _topbar_nav(html: str) -> str:
    """The surface-icons nav region of the workspace topbar."""
    m = re.search(
        r'<nav[^>]*data-region="surface-icons"[^>]*>(.*?)</nav>', html, re.S
    )
    assert m, "topbar surface-icons nav must render"
    return m.group(0)


# ---------------------------------------------------------------------------
# B2 — reachability at 1280 and 1440 px
# ---------------------------------------------------------------------------


def test_launchers_reachable_at_1280_and_1440() -> None:
    """Every shipped launcher is on the topbar (capture only) or in the System
    Map overlay; no non-capture launcher sits in the topbar nav at any width.

    The render is width-independent server markup, so the 1280/1440 contract is
    proven structurally: a launcher reachable via the never-clipping System Map
    cannot clip off the topbar at any viewport width because it is not on the
    topbar. ``capture`` is the single retained topbar launcher.
    """
    html = _shell()
    nav = _topbar_nav(html)
    # Every composition-table surface renders a node (data-surface-id) whether
    # or not it is routable from a given entry state, so the surface index is
    # complete; reachability is the node's presence on a never-clipping surface.
    map_overlay = system_map_overlay_markup()

    # Capture is the single primary launcher kept on the top edge — and it is
    # the entire shipped topbar set (the constant is truthful).
    assert SHIPPED_TOPBAR_SURFACES == ("capture",)
    assert 'data-surface="capture"' in nav
    assert 'data-intent="capture.open"' in nav

    # Every displaced launcher leaves the topbar nav. None sits behind the rail
    # or off the viewport edge — each is reachable through a never-clipping
    # surface: vault/map/memory/receipts/settings via the System Map overlay;
    # help via the composed bottom bar (the Help control).
    for surface in OVERFLOW_TOPBAR_SURFACES:
        assert (
            f'data-surface="{surface}"' not in nav
        ), f"{surface} launcher must not sit in the topbar nav (it clips ≤1440px)"
    for surface in (s for s in OVERFLOW_TOPBAR_SURFACES if s != "help"):
        assert (
            f'data-surface-id="{surface}"' in map_overlay
        ), f"{surface} must be reachable via the System Map overlay"
    # Help is reachable via the composed bottom bar, never clipped off the edge.
    assert 'data-testid="workspace-help-toggle"' in html

    # The two width contracts render identical server markup for the topbar;
    # the reachability property holds at both because it is structural — a
    # launcher reachable only via the never-clipping System Map cannot clip off
    # the topbar at any viewport width.
    for width in (1280, 1440):
        assert 'data-surface="capture"' in nav, f"capture missing at {width}px"
        for surface in OVERFLOW_TOPBAR_SURFACES:
            assert (
                f'data-surface="{surface}"' not in nav
            ), f"{surface} clips at {width}px"


# ---------------------------------------------------------------------------
# B3 — composed edges at 430 px
# ---------------------------------------------------------------------------


def test_narrow_shell_composed_edges_at_430() -> None:
    """At 430px the identity region truncates and the bottom edge is one
    composed bar with no stray fixed-position siblings."""
    html = _shell()

    # Identity/status string truncates rather than overflowing the viewport.
    header = re.search(
        r'<header[^>]*data-region="workspace-header"[^>]*>.*?</header>',
        html,
        re.S,
    )
    assert header, "workspace header must render"
    header_block = header.group(0)
    # The identity region (the anchor pill) renders on the header; its CSS
    # guarantees truncation so the string never runs off-screen at 430 px.
    assert 'data-testid="workspace-anchor-pill"' in header_block
    anchor_css = re.search(
        r"\.workspace-anchor-pill\s*\{[^}]*\}", html, re.S
    )
    assert anchor_css, "anchor-pill CSS rule must render"
    assert "text-overflow: ellipsis" in anchor_css.group(0), (
        "identity region must carry text-overflow: ellipsis"
    )
    assert "white-space: nowrap" in anchor_css.group(0)
    assert "overflow: hidden" in anchor_css.group(0)

    # A single composed bottom bar exists.
    bottom_bars = re.findall(r'data-region="bottom-bar"', html)
    assert len(bottom_bars) == 1, "exactly one composed bottom-bar container"

    bottom_bar = re.search(
        r'<[^>]*data-region="bottom-bar"[^>]*>(.*?)</(?:div|footer|nav)>',
        html,
        re.S,
    )
    assert bottom_bar, "bottom-bar container must render with content"
    bar = bottom_bar.group(1)
    # Composed controls live inside the bar: sheet triggers, the body-edit
    # hint, and the Help control.
    assert 'data-testid="workspace-help-toggle"' in bar

    # No independently-positioned fixed element with `bottom` remains outside
    # the composed bar — the floating Operator pill is gone from the edge. The
    # rendered toggle element and its fixed-position CSS rule must both be
    # absent (a defensive null-safe querySelector in an unrelated script may
    # still name the testid; that is not a rendered affordance).
    assert (
        'class="operator-toggle"' not in html
    ), "the floating Operator pill element must not render"
    assert not re.search(
        r"<button[^>]*data-testid=\"workspace-operator-toggle\"", html
    ), "no operator-toggle button element on the bottom edge"
    assert not re.search(
        r"\.operator-toggle\s*\{[^}]*position:\s*fixed", html
    ), "no fixed-position operator-toggle CSS at the bottom edge"


# ---------------------------------------------------------------------------
# C1 — no operator/diagnostic telemetry on shell or orientation surfaces
# ---------------------------------------------------------------------------

_FORBIDDEN_TELEMETRY_TESTIDS = (
    'data-testid="workspace-runtime-pill"',
    'data-testid="workspace-freshness"',
    'data-testid="workspace-quick-open"',
)
_FORBIDDEN_OPERATOR_INTENT = 'data-intent="operator.open"'


def _strip_operator_layer(html: str) -> str:
    """Remove the operator layer (System Map overlay + operator drawer) so the
    scan covers only the shell / orientation front surface.

    The AC permits the operator/diagnostic markers *inside* the operator layer
    — that is exactly where they are supposed to live. C1 forbids them only on
    the shell/orientation surface, i.e. everywhere else.
    """
    stripped = re.sub(
        r"<!-- system-map-overlay start -->.*?<!-- system-map-overlay end -->",
        "",
        html,
        flags=re.S,
    )
    # The server-rendered operator-telemetry region (the relocated runtime
    # disclosure) is the operator layer too — strip it from the front-surface
    # scan. It is hidden from the reading surface and surfaced via the operator
    # node.
    stripped = re.sub(
        r'<section class="workspace-operator-telemetry".*?</section>',
        "",
        stripped,
        flags=re.S,
    )
    # The operator drawer host (and its lazy-load controller) is the operator
    # layer too; drop it from the front-surface scan.
    stripped = re.sub(
        r'<div class="operator-drawer-host".*?</div>\s*(?=<|$)',
        "",
        stripped,
        flags=re.S,
    )
    return stripped


def test_operator_telemetry_absent_from_shell() -> None:
    """No operator/diagnostic telemetry on the shell or orientation surfaces;
    the operator layer (System Map node + operator drawer) carries it."""
    shell_front = _strip_operator_layer(_shell())

    # The shell front edge carries none of the forbidden telemetry affordances.
    for marker in _FORBIDDEN_TELEMETRY_TESTIDS:
        assert marker not in shell_front, f"{marker} must not render on the shell"
    assert _FORBIDDEN_OPERATOR_INTENT not in shell_front, (
        "operator.open must not be a free-floating front-edge affordance"
    )
    # Front-edge runtime status text is gone from the orientation surface too.
    for state, raw in _ENTRY_RENDERS.items():
        front = _strip_operator_layer(raw)
        for marker in _FORBIDDEN_TELEMETRY_TESTIDS:
            assert marker not in front, f"{marker} leaked on entry state {state}"
        assert (
            _FORBIDDEN_OPERATOR_INTENT not in front
        ), f"operator.open leaked on entry state {state}"

    # The telemetry is not discarded — it relocates into the server-rendered
    # operator-telemetry region (the operator layer), hidden from the reading
    # surface. Presentation only: the values still come from the runtime
    # payload, only WHERE they render changed.
    full_shell = _shell()
    op_region = re.search(
        r'<section class="workspace-operator-telemetry"[^>]*>(.*?)</section>',
        full_shell,
        re.S,
    )
    assert op_region, "operator-telemetry region must render"
    region_open = re.search(
        r'<section class="workspace-operator-telemetry"[^>]*>', full_shell
    )
    assert "hidden" in region_open.group(0), "region is hidden from the reading surface"
    assert 'data-layer="operator"' in region_open.group(0)
    body = op_region.group(1)
    for marker in _FORBIDDEN_TELEMETRY_TESTIDS:
        if marker == 'data-testid="workspace-quick-open"':
            continue  # quick-open is removed outright, not relocated
        assert marker in body, f"{marker} must relocate into the operator layer"

    # The operator layer IS reachable — via the System Map overlay's operator
    # node (operator.open), which routes to the operator drawer. The node and
    # its intent live inside the System Map overlay region only.
    map_overlay = system_map_overlay_markup(available_routes=("operator",))
    assert _FORBIDDEN_OPERATOR_INTENT in map_overlay, (
        "operator surface must be reachable via the System Map / operator layer"
    )
    assert 'data-surface-id="operator"' in map_overlay

    # The relocated telemetry is not dead markup: opening the operator layer
    # reveals the operator-telemetry region (and closing re-hides it), so the
    # relocated pill/freshness is actually reachable by the user.
    assert "revealTelemetry(true)" in full_shell
    assert "revealTelemetry(false)" in full_shell
    assert 'data-region="operator-telemetry"' in full_shell

    # Operator access must not regress on entry-state pages: the operator node
    # is routable on every orientation render (the operator drawer ships there).
    for state, raw in _ENTRY_RENDERS.items():
        node = re.search(
            r'<button[^>]*data-surface-id="operator"[^>]*data-routable="true"[^>]*>',
            raw,
        )
        assert node, f"operator node must be routable on entry state {state}"
        assert 'data-intent="operator.open"' in node.group(0)
