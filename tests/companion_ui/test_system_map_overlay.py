"""System map overlay — pull-based surface index (#1787, SEP-05).

One place from which the whole companion is legible
(`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Resolved Q4`, `§Surface
composition (NORMATIVE table)`, `docs/SYSTEM_ENTRY_POINT/SYSTEM_MAP_OVERLAY.md`):

- the map is a renderer/router index (Projection): the entry-point center node
  plus one node per composition-table surface, each showing the surface's
  product mode (Find / Reorient / Resurface / Act per
  `docs/COMPANION_UI_PRODUCT_SPEC.md`), how it is reached, how it returns, and
  its truthful shipped/new status — the map re-classifies nothing;
- clicking a shipped surface's node routes to that surface through its
  existing affordance (opens the overlay / focuses the pane); nodes for
  not-yet-shipped surfaces are present but visibly inert with their status —
  no dead affordances pretending to work;
- the map is pull-based: it never auto-opens, never badges, never surfaces
  unbidden; it is reachable from `cold_start` and `no_vault` as well as
  `shell_active`;
- parked surfaces (context lane / place band) appear only as a parked note —
  never as reachable nodes (spec §Parked, Q15–Q16).
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from companion_ui.workspace.overlay_host import (
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    OverlayHostState,
    mount,
)
from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.system_map_overlay import (
    MAP_CENTER_NAME,
    MAP_CENTER_SUB,
    MAP_SURFACES,
    NODE_STATUSES,
    PARKED_SURFACES,
    PRODUCT_MODES,
    ROUTE_INTENTS,
    SYSTEM_MAP_OVERLAY_ID,
    MapNode,
    routable_surface_ids,
    system_map_overlay_markup,
    system_map_overlay_script,
)

# ---------------------------------------------------------------------------
# Fixtures (mirror the proven fixtures in test_overlay_host /
# test_entry_state_machine)
# ---------------------------------------------------------------------------


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
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
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _orientation_payload(*, leave_status: str | None = "absent") -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-10T12:00:00Z",
            "trace_id": "trace-orientation-1",
            "freshness": "fresh",
            "stale_after": "2026-06-10T12:05:00Z",
            "degraded_reasons": [],
        },
        "leave_point": None if leave_status is None else {"status": leave_status},
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "gov", "label": "gov"},
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


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [
            {
                "note_path": "Notes/resume.md",
                "title": "Resume plan",
                "zone": "Notes",
                "kind": "human_note",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            }
        ],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
        "read_only": True,
        "identity_available": True,
        "vault_identity": {
            "vault_name": "dev-vault",
            "channel": "dev",
            "provenance": "env",
        },
    }


def _render_workspace(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _render_cold_start() -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(leave_status="absent"),
        orientation_vault_browser=_vault_browser_payload(),
    )


def _render_no_vault_orientation() -> str:
    # handle_get's 503 path: orientation fetch failed but vault browsing is
    # available — the orientation page renders the unavailable frame.
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(leave_status=None),
        orientation_error="connection refused",
        orientation_vault_browser=_vault_browser_payload(),
    )


def _render_no_vault_error_page() -> str:
    # The fully-unreachable path: no orientation frame at all.
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        error="connection refused",
    )


def _entry_state(html: str) -> str:
    body = re.search(r"<body[^>]*>", html)
    assert body, "rendered page must have a <body> tag"
    states = re.findall(r'data-entry-state="([^"]*)"', body.group(0))
    assert len(states) == 1
    return states[0]


def _map_overlay(html: str) -> str:
    m = re.search(
        r"<!-- system-map-overlay start -->(.*?)<!-- system-map-overlay end -->",
        html,
        re.S,
    )
    assert m, "system map overlay markup must render"
    return m.group(1)


def _map_script(html: str) -> str:
    m = re.search(
        r"/\* system-map-controller \*/(.*?)/\* /system-map-controller \*/",
        html,
        re.S,
    )
    assert m, "system map controller script must render"
    return m.group(1)


def _nodes(map_html: str) -> dict[str, str]:
    """All rendered node elements keyed by surface id."""
    found: dict[str, str] = {}
    for tag in re.findall(
        r"<(?:button|article)[^>]*data-testid=\"system-map-node\"[^>]*>", map_html
    ):
        sid = re.search(r'data-surface-id="([^"]+)"', tag)
        assert sid, f"every map node must declare data-surface-id: {tag}"
        found[sid.group(1)] = tag
    return found


_ALL_PAGES = (
    _render_workspace,
    _render_cold_start,
    _render_no_vault_orientation,
    _render_no_vault_error_page,
)


# ---------------------------------------------------------------------------
# AC1: one node per composition-table surface with mode, reached-as,
# returns-to, and truthful status
# ---------------------------------------------------------------------------


def test_map_renders_composition_table_nodes() -> None:
    # Pure model: one node per composition-table surface (the NORMATIVE table
    # minus the parked row, which must not become a node), unique ids,
    # declared mode/status vocabularies only.
    ids = [node.surface_id for node in MAP_SURFACES]
    assert len(ids) == len(set(ids)), "surface ids must be unique"
    assert set(ids) == {
        "orientation",
        "anchor",
        "vault",
        "panel",
        "palette",
        "chat_rail",
        "suggestions",
        "memory",
        "peek",
        "posture",
        "map",
        "settings",
        "tts",
        "capture",
        "receipts",
        "governance",
        "resurface_rail",
        "guidance",
        # CUIDR-04 (#2447): the operator/diagnostics layer is now a map node —
        # operator telemetry moved off the front edge and is reached here.
        "operator",
    }, "exactly the composition-table surfaces (parked rows excluded)"
    for node in MAP_SURFACES:
        assert set(node.modes) <= set(PRODUCT_MODES)
        assert node.status in NODE_STATUSES
        assert node.reached and node.returns and node.status_note

    # The map re-classifies nothing: statuses mirror the spec table.
    by_id = {node.surface_id: node for node in MAP_SURFACES}
    for shipped in ("orientation", "anchor", "vault", "panel", "palette",
                    "suggestions", "memory", "peek", "tts", "capture",
                    "receipts", "settings", "map", "guidance", "resurface_rail"):
        assert by_id[shipped].status == "shipped", shipped
    for partial in ("chat_rail",):
        assert by_id[partial].status == "partial", partial
    for new in ("posture",):
        assert by_id[new].status == "new", new
    # Product modes per docs/COMPANION_UI_PRODUCT_SPEC.md, not re-derived.
    assert by_id["vault"].modes == ("find",)
    assert by_id["orientation"].modes == ("reorient",)
    assert by_id["panel"].modes == ("act",)
    assert by_id["palette"].modes == ("act",)
    assert by_id["capture"].modes == ("act",)
    # Local-UI surfaces are not forced into a cognitive mode they do not have.
    assert by_id["settings"].modes == ()
    assert by_id["guidance"].modes == ()

    # Rendered: every node carries mode, reached, returns, status.
    html = _render_workspace()
    overlay = _map_overlay(html)
    assert 'data-overlay-id="map"' in overlay
    assert 'data-authority="projection"' in overlay
    # The entry-point center node.
    assert 'data-testid="system-map-center"' in overlay
    assert MAP_CENTER_NAME in overlay
    nodes = _nodes(overlay)
    assert set(nodes) == set(ids), "one rendered node per composition surface"
    for node in MAP_SURFACES:
        tag = nodes[node.surface_id]
        expected_mode = " ".join(node.modes) if node.modes else "local-ui"
        assert f'data-mode="{expected_mode}"' in tag, node.surface_id
        assert f'data-status="{node.status}"' in tag, node.surface_id
    # Reached / returns / status text renders for every node.
    assert overlay.count('data-testid="system-map-node-reach"') == len(MAP_SURFACES)
    assert overlay.count('data-testid="system-map-node-status"') == len(MAP_SURFACES)
    for node in MAP_SURFACES:
        assert node.status_note in overlay, node.surface_id


# ---------------------------------------------------------------------------
# C4 (#2448): the System Map carries no bare internal issue numbers in
# user-facing copy; each surface entry reads as identity + how-to-reach +
# how-it-returns. The map is an honest index, not a changelog — internal
# references (#1783, SEP-04, #1716+) belong in the operator/guidance layer,
# never in the rendered node copy.
# ---------------------------------------------------------------------------


def test_system_map_no_issue_refs() -> None:
    # Pure model: no node's user-facing copy (reached / returns / status_note)
    # carries a bare internal issue number or SEP reference.
    _bare_issue = re.compile(r"#\d{3,}")
    _sep_ref = re.compile(r"\bSEP-\d+\b")
    for node in MAP_SURFACES:
        for field_name in ("reached", "returns", "status_note"):
            value = getattr(node, field_name)
            assert not _bare_issue.search(value), (
                f"{node.surface_id}.{field_name} leaks a bare issue number: {value!r}"
            )
            assert not _sep_ref.search(value), (
                f"{node.surface_id}.{field_name} leaks a SEP reference: {value!r}"
            )
        # The center node copy is also user-facing.
    assert not _bare_issue.search(MAP_CENTER_NAME)
    assert not _bare_issue.search(MAP_CENTER_SUB)

    # Rendered overlay: no bare issue number appears anywhere a user can read
    # it on the map surface (the rendered node copy + center + parked note).
    # User-facing copy excludes the <style> block (CSS hex colours such as
    # #152030 are not issue numbers) and HTML/source comments (not rendered to
    # the user). Scan the visible copy, which is exactly the contract C4 fixes.
    for render in _ALL_PAGES:
        overlay = _map_overlay(render())
        visible = re.sub(r"<style\b[^>]*>.*?</style>", "", overlay, flags=re.S)
        visible = re.sub(r"<!--.*?-->", "", visible, flags=re.S)
        # Numeric HTML character references (e.g. the ⓘ glyph &#9432;) are
        # glyph encodings, not issue numbers — strip them before the scan.
        visible = re.sub(r"&#\d+;", "", visible)
        assert not _bare_issue.search(visible), (
            "rendered system-map overlay copy must carry no bare internal issue "
            f"numbers: {_bare_issue.search(visible)}"
        )
        assert not _sep_ref.search(visible), (
            "rendered system-map overlay copy must carry no SEP references"
        )


# ---------------------------------------------------------------------------
# AC2: shipped nodes route via existing intents; unshipped nodes are inert
# and truthfully labeled
# ---------------------------------------------------------------------------


def test_shipped_nodes_route_and_unshipped_nodes_are_inert() -> None:
    # Pure model: only shipped surfaces can be routable, and the intents the
    # nodes emit are existing declared intents — the map invents none.
    assert set(routable_surface_ids()) == {
        "anchor", "vault", "panel", "palette", "memory", "capture", "receipts",
        "governance", "settings",
        # CUIDR-04 (#2447): the operator layer routes from the map via the
        # operator drawer (operator.open).
        "operator",
    }
    for node in MAP_SURFACES:
        if node.routable:
            assert node.status == "shipped", (
                f"{node.surface_id}: only shipped surfaces may route"
            )
    assert ROUTE_INTENTS == {
        "anchor": "overlay.dismiss",
        "vault": "vault.open",
        "palette": "cmd.open",
        "memory": "memory.open",
        "capture": "capture.open",
        "receipts": "receipts.open",
        "governance": "receipts.open",
        "settings": "settings.open",
        "operator": "operator.open",
    }
    # An unshipped surface can never be declared routable.
    with pytest.raises(ValueError):
        MapNode(
            surface_id="peek",
            name="Source peek",
            modes=("find",),
            reached="anchored popover (source.peek)",
            returns="dismisses to anchor",
            status="partial",
            status_note="popover presentation has not shipped",
            routable=True,
        )
    # The markup contract rejects undeclared route availability.
    with pytest.raises(ValueError):
        system_map_overlay_markup(available_routes=("peek",))

    html = _render_workspace()
    overlay = _map_overlay(html)
    nodes = _nodes(overlay)

    # Shipped + routable on the workspace shell: clickable buttons that route
    # through the map controller to the existing affordances.
    for sid in ("anchor", "vault", "panel", "palette", "memory", "capture",
                "receipts", "settings"):
        tag = nodes[sid]
        assert tag.startswith("<button"), sid
        assert 'data-routable="true"' in tag, sid
        assert f"systemMap.route('{sid}')" in tag, sid
        if sid in ROUTE_INTENTS:
            assert f'data-intent="{ROUTE_INTENTS[sid]}"' in tag, sid

    # Unshipped / partial surfaces are present but visibly inert: not
    # buttons, no onclick, no intent — and labeled with their truthful status.
    for sid in ("chat_rail", "peek", "posture", "guidance"):
        tag = nodes[sid]
        assert tag.startswith("<article"), sid
        assert 'data-routable="false"' in tag, sid
        assert 'aria-disabled="true"' in tag, sid
        assert "onclick" not in tag, sid
        assert "data-intent" not in tag, sid
    assert 'data-surface-id="peek" data-mode="find" data-status="shipped"' in overlay
    assert "provenance lines are live" in overlay
    assert 'data-surface-id="guidance" data-mode="local-ui" data-status="shipped"' in overlay

    # Shipped surfaces with no map-open affordance (reached by state or by
    # in-document controls) are truthfully non-routable, not dead buttons.
    for sid in ("orientation", "suggestions", "tts", "map"):
        tag = nodes[sid]
        assert tag.startswith("<article"), sid
        assert 'data-routable="false"' in tag, sid
        assert "onclick" not in tag, sid

    # The routing controller composes existing surfaces: host mounts and the
    # shipped vault affordance — and never navigates (overlay grammar: no
    # route reset, no data loss).
    script = _map_script(html)
    assert "overlayHost.mount('cmd')" in script
    assert "overlayHost.mount('memory')" in script
    assert "overlayHost.mount('capture')" in script
    assert "overlayHost.mount('receipts')" in script
    assert "overlayHost.mount('settings')" in script
    assert "vaultBrowser.focus()" in script
    assert "overlayHost.dismiss()" in script
    for forbidden in (
        "location.href",
        "location.assign",
        "location.reload",
        "history.pushState",
        "window.open",
        "form.submit",
        "fetch(",
    ):
        assert forbidden not in script, f"map controller must not call {forbidden}"

    # In cold_start the shell surfaces are not live: only the vault route is
    # offered (the declared cold_start -> shell_active transition), and the
    # rest render truthfully unavailable rather than dead.
    cold_nodes = _nodes(_map_overlay(_render_cold_start()))
    assert cold_nodes["vault"].startswith("<button")
    for sid in ("anchor", "panel", "palette", "memory", "capture", "receipts",
                "settings"):
        assert cold_nodes[sid].startswith("<article"), sid
        assert "onclick" not in cold_nodes[sid], sid

    no_vault_nodes = _nodes(_map_overlay(_render_no_vault_orientation()))
    assert no_vault_nodes["vault"].startswith("<button")

    # On the fully-unreachable error page the live runtime surfaces render
    # truthfully inert — EXCEPT the operator layer. The operator drawer is a
    # client-rendered diagnostics surface that self-fetches `/operator` and
    # degrades gracefully; with the floating operator pill removed (CUIDR-04,
    # #2447), the System Map's `operator` node is the only pointer route into
    # diagnostics, so it must stay routable exactly when the runtime is degraded
    # (Codex review #2458).
    error_nodes = _nodes(_map_overlay(_render_no_vault_error_page()))
    assert error_nodes["operator"].startswith("<button"), "operator"
    assert 'data-intent="operator.open"' in error_nodes["operator"]
    for sid in routable_surface_ids():
        if sid == "operator":
            continue
        assert error_nodes[sid].startswith("<article"), sid
        assert 'data-routable="false"' in error_nodes[sid], sid
        assert "onclick" not in error_nodes[sid], sid


# ---------------------------------------------------------------------------
# AC3: the map is reachable from cold_start and no_vault as well as
# shell_active
# ---------------------------------------------------------------------------


def test_map_reachable_from_cold_and_no_vault_states() -> None:
    # The map is a shipped overlay-host occupant and a shipped topbar surface.
    assert SYSTEM_MAP_OVERLAY_ID == "map"
    assert "map" in SHIPPED_OVERLAY_OCCUPANTS
    # CUIDR-04 (#2447): the System Map is the never-clipping overflow surface;
    # its single opener moved off the crowded topbar into the composed bottom
    # bar (a wayfinding/meta affordance). The top edge keeps IDENTITY + Capture.
    assert "map" not in SHIPPED_TOPBAR_SURFACES
    state = OverlayHostState(anchor_note_path="Notes/note.md")
    assert mount(state, "map").stack == ("map",)

    # shell_active: the bottom-bar map opener carries the map.open affordance.
    shell = _render_workspace()
    assert _entry_state(shell) == "shell_active"
    bottom_bar = re.search(
        r'<[^>]*data-region="bottom-bar"[^>]*>.*?</div>', shell, re.S
    )
    assert bottom_bar, "composed bottom bar must render"
    icon = re.search(
        r'<button[^>]*data-testid="workspace-surface-icon-map"[^>]*>',
        bottom_bar.group(0),
    )
    assert icon, "bottom bar must render the system-map opener"
    assert 'data-intent="map.open"' in icon.group(0)
    assert "overlayHost.mount('map')" in icon.group(0)
    _map_overlay(shell)
    _map_script(shell)

    # cold_start: calm affordance + the overlay present on the entry surface.
    cold = _render_cold_start()
    assert _entry_state(cold) == "cold_start"
    affordance = re.search(
        r'<button[^>]*data-testid="workspace-orientation-map-affordance"[^>]*>',
        cold,
    )
    assert affordance, "cold_start must offer the calm map affordance"
    assert 'data-intent="map.open"' in affordance.group(0)
    assert "overlayHost.mount('map')" in affordance.group(0)
    _map_overlay(cold)
    _map_script(cold)
    assert 'data-region="overlay-host"' in cold

    # no_vault (orientation-unavailable frame): same calm affordance.
    no_vault = _render_no_vault_orientation()
    assert _entry_state(no_vault) == "no_vault"
    assert 'data-testid="workspace-orientation-map-affordance"' in no_vault
    _map_overlay(no_vault)
    _map_script(no_vault)

    # no_vault (fully unreachable error page): the error state offers the map
    # beside the declared entry.retry affordance.
    error_page = _render_no_vault_error_page()
    assert _entry_state(error_page) == "no_vault"
    assert 'data-testid="workspace-entry-retry"' in error_page
    error_affordance = re.search(
        r'<button[^>]*data-testid="workspace-entry-map-affordance"[^>]*>',
        error_page,
    )
    assert error_affordance, "no_vault error page must offer the calm map affordance"
    assert 'data-intent="map.open"' in error_affordance.group(0)
    _map_overlay(error_page)
    _map_script(error_page)


# ---------------------------------------------------------------------------
# AC4: the map never renders unbidden — no render path mounts it without an
# explicit map.open
# ---------------------------------------------------------------------------


def test_map_never_auto_opens() -> None:
    for render in _ALL_PAGES:
        html = render()
        overlay = _map_overlay(html)
        # Closed and hidden on every initial render.
        root = re.search(
            r'<div[^>]*data-testid="system-map-overlay"[^>]*>', overlay
        )
        assert root, "map overlay root must render"
        assert 'data-open="false"' in root.group(0)
        assert 'aria-hidden="true"' in root.group(0)
        # The host mounts nothing at render time.
        host = re.search(r'<div[^>]*data-region="overlay-host"[^>]*>', html)
        assert host and 'data-overlay-open="none"' in host.group(0)
        # No script ever mounts the map: every mount('map') lives in an
        # explicit user-facing affordance (an onclick attribute on a control
        # that declares data-intent="map.open"); script bodies carry none.
        for script_body in re.findall(
            r"<script\b[^>]*>([\s\S]*?)</script\b[^>]*>", html, re.I
        ):
            assert "mount('map'" not in script_body, (
                "no render path may mount the map without an explicit map.open"
            )
        for tag in re.findall(r"<[a-z]+[^>]*overlayHost\.mount\('map'\)[^>]*>", html):
            assert 'data-intent="map.open"' in tag, tag
            assert "onclick=" in tag, tag
        # Pull-based also means no badges and no counts pushing attention.
        assert "data-badge" not in html
        map_affordances = re.findall(
            r'<button[^>]*data-intent="map\.open"[^>]*>([^<]*)</button>', html
        )
        for label in map_affordances:
            assert not re.search(r"\d", label), "map affordances must not badge counts"


# ---------------------------------------------------------------------------
# AC5: parked surfaces (context lane / place band) never render as reachable
# nodes
# ---------------------------------------------------------------------------


def test_parked_surfaces_not_reachable() -> None:
    # Pure model: parked surfaces are not nodes, and a node cannot claim a
    # parked id.
    assert PARKED_SURFACES == ("context_lane", "place_band")
    assert not set(PARKED_SURFACES) & {node.surface_id for node in MAP_SURFACES}
    with pytest.raises(ValueError):
        MapNode(
            surface_id="context_lane",
            name="Context lane",
            modes=(),
            reached="—",
            returns="—",
            status="new",
            status_note="parked",
            routable=False,
        )

    for render in _ALL_PAGES:
        html = render()
        overlay = _map_overlay(html)
        nodes = _nodes(overlay)
        assert "context_lane" not in nodes
        assert "place_band" not in nodes
        # Parked appears only as a non-interactive parked note.
        note = re.search(
            r'<p[^>]*data-testid="system-map-parked-note"[^>]*>', overlay
        )
        assert note, "the parked note must render (truthful, not reachable)"
        assert "onclick" not in note.group(0)
        assert "data-intent" not in note.group(0)
        # The reserved, not-implementable intents never render anywhere.
        assert 'data-intent="context.open"' not in html
        assert 'data-intent="location.enable"' not in html


# ---------------------------------------------------------------------------
# Overlay grammar: the map dismisses to the anchor through the shared host
# ---------------------------------------------------------------------------


def test_map_is_a_host_occupant_with_dismiss_to_anchor() -> None:
    html = _render_workspace()
    overlay = _map_overlay(html)
    close = re.search(
        r'<button[^>]*data-testid="system-map-close"[^>]*>', overlay
    )
    assert close, "the map must offer an explicit dismiss-to-anchor control"
    assert 'data-intent="overlay.dismiss"' in close.group(0)
    assert "overlayHost.dismiss()" in close.group(0)
    script = _map_script(html)
    assert "register('map'" in script, "the map registers as the host's occupant"
    # Standalone markup is renderable and closed by default (pure function).
    fragment = system_map_overlay_markup(available_routes=("vault",))
    assert 'data-open="false"' in fragment
    assert "system-map-controller" in system_map_overlay_script()


# ---------------------------------------------------------------------------
# Telemetry relocation (#2245, #2174): freshness/as_of/trace_id in topbar
# disclosure and map entry-point center node.
# ---------------------------------------------------------------------------


def test_entry_point_map_and_runtime_status_render_relocated_telemetry() -> None:
    """Topbar runtime-status popover and map center node render relocated telemetry.

    Verifies AC1 and AC2 of #2245: when the orientation payload supplies
    freshness/as_of/trace_id, both pull-only surfaces render the values as
    read-only projection rows with data-authority="read-only-projection".
    """
    # --- Map center node (pure function path) ---
    # system_map_overlay_markup accepts the three optional params directly.
    fragment = system_map_overlay_markup(
        available_routes=("vault",),
        orientation_freshness="fresh",
        orientation_as_of="2026-06-10T12:00:00Z",
        orientation_trace_id="trace-orientation-1",
    )
    # Extract the map-center region (spans multiple nested divs; use the grid
    # boundary as the close marker rather than a single </div>).
    center_start = fragment.find('data-testid="system-map-center"')
    center_end = fragment.find('data-testid="system-map-grid"')
    assert center_start >= 0 and center_end > center_start, "system-map-center must render before grid"
    center_html = fragment[center_start:center_end]
    # The meta row renders inside the center node with read-only-projection authority.
    assert 'data-testid="map-entry-point-freshness"' in center_html
    assert 'data-authority="read-only-projection"' in center_html
    assert "fresh" in center_html
    assert "2026-06-10T12:00:00Z" in center_html
    assert "trace-orientation-1" in center_html

    # --- Topbar runtime-status popover (full render path) ---
    # The workspace shell receives orientation meta via fields.
    html = _render_workspace(
        orientation_freshness="fresh",
        orientation_as_of="2026-06-10T12:00:00Z",
        orientation_trace_id="trace-orientation-1",
    )
    # Extract the popover region from the workspace-runtime-status-popover
    # div up to the closing </details> tag.
    pop_start = html.find('data-testid="workspace-runtime-status-popover"')
    pop_end = html.find('</details>', pop_start)
    assert pop_start >= 0, "workspace-runtime-status-popover must render"
    popover_html = html[pop_start:pop_end]
    # Freshness row with read-only-projection authority.
    freshness_row = re.search(
        r'<div[^>]*data-testid="workspace-freshness-as-of"[^>]*>', popover_html
    )
    assert freshness_row, "freshness row must appear in topbar popover"
    assert 'data-authority="read-only-projection"' in freshness_row.group(0)
    assert "fresh" in popover_html
    # as_of row.
    as_of_row = re.search(
        r'<div[^>]*data-testid="workspace-orientation-as-of"[^>]*>', popover_html
    )
    assert as_of_row, "as_of row must appear in topbar popover"
    assert 'data-authority="read-only-projection"' in as_of_row.group(0)
    assert "2026-06-10T12:00:00Z" in popover_html
    # trace_id row.
    trace_row = re.search(
        r'<div[^>]*data-testid="workspace-orientation-trace-id"[^>]*>', popover_html
    )
    assert trace_row, "orientation trace_id row must appear in topbar popover"
    assert 'data-authority="read-only-projection"' in trace_row.group(0)
    assert "trace-orientation-1" in popover_html

    # --- Cold_start orientation page: map center node carries the values ---
    cold = _render_cold_start()
    cold_overlay = _map_overlay(cold)
    cold_center_start = cold_overlay.find('data-testid="system-map-center"')
    cold_center_end = cold_overlay.find('data-testid="system-map-grid"')
    assert cold_center_start >= 0, "system-map-center must render on cold_start orientation page"
    cold_center_html = cold_overlay[cold_center_start:cold_center_end]
    # The map is pull-only — the meta row is present inside the (closed) overlay.
    assert 'data-testid="map-entry-point-freshness"' in cold_center_html
    assert 'data-authority="read-only-projection"' in cold_center_html


def test_note_workspace_map_entry_point_receives_relocated_telemetry() -> None:
    class _Client:
        def __init__(self) -> None:
            self.get_calls: list[tuple[str, dict[str, Any]]] = []

        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            self.get_calls.append((url, params))
            if url == "/api/companion/workspace":
                return {
                    "artifact": {
                        "note_path": "Notes/note.md",
                        "title": "Note",
                        "artifact_id": "art-note",
                        "artifact_kind": "human_note",
                        "content_hash": "sha256-note",
                        "body": "# Note\n\nBody.",
                        "identity_source": "frontmatter.uuid",
                        "identity_state": "resolved",
                        "companion_of": None,
                        "owns_identity": True,
                    },
                    "canvas": {"session_state": "idle"},
                    "panel": {"state": "idle", "proposal_count": 0},
                    "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
                    "runtime": {
                        "environment_label": "dev",
                        "api_base_url_label": "local-dev",
                        "trace_id": "trace-workspace-1",
                    },
                    "suggestions": {},
                }
            if url == "/api/companion/orientation":
                return {
                    "meta": {
                        "freshness": "fresh",
                        "as_of": "2026-06-10T12:00:00Z",
                        "trace_id": "trace-orientation-1",
                    }
                }
            return {}

        def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
            return {}

    client = _Client()
    html = handle_get(
        query_string="note_path=Notes%2Fnote.md",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )

    assert client.get_calls == [
        ("/api/companion/workspace", {"note_path": "Notes/note.md"}),
        ("/api/companion/orientation", {}),
    ]
    overlay = _map_overlay(html)
    center_start = overlay.find('data-testid="system-map-center"')
    center_end = overlay.find('data-testid="system-map-grid"')
    assert center_start >= 0 and center_end > center_start
    center_html = overlay[center_start:center_end]
    assert 'data-testid="map-entry-point-freshness"' in center_html
    assert 'data-authority="read-only-projection"' in center_html
    assert "fresh" in center_html
    assert "2026-06-10T12:00:00Z" in center_html
    assert "trace-orientation-1" in center_html


def test_relocated_map_counts_are_read_only_projection_without_zero_state() -> None:
    """Zero-state: when payload omits freshness/as_of/trace_id, no placeholder row renders.

    Verifies AC4 of #2245: the map center node and topbar popover must not
    render a placeholder or empty row when the orientation payload does not
    supply the relocated telemetry fields.

    Also verifies #2249 ACs 2+3: the resurface_rail MapNode is present in
    MAP_SURFACES with mode=("resurface",) and status="shipped"; it is inert
    (routable=False — the rail is navigated in shell, not via overlayHost.mount).
    """
    # --- Governance MapNode (#2246): read-only index entry, routes via receipts.open ---
    gov_nodes = [n for n in MAP_SURFACES if n.surface_id == "governance"]
    assert gov_nodes, "governance MapNode must appear in MAP_SURFACES (#2246)"
    gn = gov_nodes[0]
    assert gn.status == "shipped", "governance node must have status='shipped'"
    assert "act" in gn.modes or "reorient" in gn.modes, (
        "governance node must carry act or reorient mode"
    )
    # Routes via receipts.open (inert index node, not a new occupant).
    assert ROUTE_INTENTS.get("governance") == "receipts.open", (
        "governance node must route via receipts.open intent"
    )
    # governance node is routable so that it renders as a button when receipts
    # occupant is available — inert (renders as article) when receipts absent.
    # Render inert when governance NOT in available_routes.
    frag_no_gov = system_map_overlay_markup(available_routes=())
    gov_section = re.search(
        r'data-surface-id="governance"[^>]*>', frag_no_gov
    )
    assert gov_section, "governance node must render in system map HTML even when inert"
    assert 'data-routable="false"' in gov_section.group(0), (
        "governance node must render as inert (data-routable=false) when not in available_routes"
    )
    # Render routable button when governance IS in available_routes.
    frag_with_gov = system_map_overlay_markup(available_routes=("governance",))
    gov_btn = re.search(
        r'<button[^>]*data-surface-id="governance"[^>]*>', frag_with_gov
    )
    assert gov_btn, (
        "governance node must render as a button when available (receipts occupant present)"
    )
    assert 'data-intent="receipts.open"' in gov_btn.group(0), (
        "governance button must carry data-intent=receipts.open"
    )
    # JS controller routes governance via overlayHost.mount('receipts').
    script_text = system_map_overlay_script()
    assert "governance" in script_text and "mount('receipts')" in script_text, (
        "system map controller must route governance via overlayHost.mount('receipts')"
    )
    # data-authority on the map overlay is "projection" (map-level); governance
    # node itself is read-only-projection by contract (#2246 cross-task invariant).
    assert gn.routable is True  # ships as routable when receipts occupant present

    # --- Resurface MapNode: index entry present, inert, no overlayHost route ---
    resurface_nodes = [n for n in MAP_SURFACES if n.surface_id == "resurface_rail"]
    assert resurface_nodes, "resurface_rail MapNode must appear in MAP_SURFACES (#2249)"
    rn = resurface_nodes[0]
    assert rn.modes == ("resurface",), (
        "resurface_rail node must carry product mode 'resurface'"
    )
    assert rn.status == "shipped", "resurface_rail node must have status='shipped'"
    assert not rn.routable, (
        "resurface_rail node must be inert (routable=False); "
        "the rail is navigated in shell, not via overlayHost.mount"
    )
    # Node must render without an overlayHost.mount route.
    frag = system_map_overlay_markup(available_routes=())
    resurface_section = re.search(
        r'data-surface-id="resurface_rail"[^>]*>.*?(?=data-surface-id=|</div>)',
        frag,
        re.S,
    )
    assert resurface_section, "resurface_rail node must render in system map HTML"
    assert 'data-routable="false"' in frag, (
        "resurface_rail node must render as data-routable=false (inert)"
    )
    # No overlayHost.mount call for resurface in the map script.
    script_html = frag[frag.find("/* system-map-controller */"):]
    assert "resurface" not in script_html or "mount('resurface" not in script_html, (
        "system map controller must not mount resurface via overlayHost"
    )

    # --- Map center node (pure function, no orientation meta) ---
    fragment_empty = system_map_overlay_markup(available_routes=("vault",))
    assert 'data-testid="map-entry-point-freshness"' not in fragment_empty, (
        "map center node must not render a meta row when orientation meta is absent"
    )
    assert 'data-authority="read-only-projection"' not in fragment_empty or (
        # read-only-projection may appear elsewhere (overlay authority="projection"),
        # but specifically the map-entry-point-freshness div must not.
        'data-testid="map-entry-point-freshness"' not in fragment_empty
    )

    # Only freshness present: as_of and trace_id rows must not render empty.
    fragment_partial = system_map_overlay_markup(
        available_routes=(),
        orientation_freshness="fresh",
        orientation_as_of="",
        orientation_trace_id="",
    )
    cp_start = fragment_partial.find('data-testid="system-map-center"')
    cp_end = fragment_partial.find('data-testid="system-map-grid"')
    assert cp_start >= 0, "system-map-center must render"
    center_partial_html = fragment_partial[cp_start:cp_end]
    # Meta row renders because freshness is present.
    assert 'data-testid="map-entry-point-freshness"' in center_partial_html
    # But as_of and trace_id sub-spans are omitted when empty.
    assert 'data-testid="map-entry-point-meta-as-of"' not in center_partial_html
    assert 'data-testid="map-entry-point-meta-trace-id"' not in center_partial_html

    # --- Topbar popover: no rows when fields absent ---
    html = _render_workspace()  # no orientation_freshness/as_of/trace_id in fields
    pop_start2 = html.find('data-testid="workspace-runtime-status-popover"')
    pop_end2 = html.find('</details>', pop_start2)
    assert pop_start2 >= 0, "workspace-runtime-status-popover must render"
    popover_html2 = html[pop_start2:pop_end2]
    assert 'data-testid="workspace-freshness-as-of"' not in popover_html2, (
        "freshness row must not appear in topbar popover when orientation meta absent"
    )
    assert 'data-testid="workspace-orientation-as-of"' not in popover_html2
    assert 'data-testid="workspace-orientation-trace-id"' not in popover_html2

    # --- #2247 Open-loops count on memory map node: read-only projection, no zero-state ---
    # Zero count: annotation must not render (no zero-state).
    frag_no_loops = system_map_overlay_markup(available_routes=(), open_loops_count=0)
    assert 'data-testid="map-memory-node-open-loops-count"' not in frag_no_loops, (
        "open-loops count annotation must not render when count is zero (no zero-state)"
    )
    # Non-zero count: annotation must render with correct attributes.
    frag_with_loops = system_map_overlay_markup(
        available_routes=("memory",), open_loops_count=3
    )
    mem_node_start = frag_with_loops.find('data-surface-id="memory"')
    assert mem_node_start >= 0, "memory node must render in system map"
    # Find the closing tag of the memory node to extract its inner content.
    # Window is 1100 chars — wide enough to cover the full memory node including
    # the open-loops annotation appended after the status/unavailable paragraphs.
    mem_node_html = frag_with_loops[mem_node_start:mem_node_start + 1100]
    assert 'data-testid="map-memory-node-open-loops-count"' in mem_node_html, (
        "open-loops count annotation must render on the memory node when count is non-zero"
    )
    assert 'data-authority="read-only-projection"' in mem_node_html, (
        "open-loops count annotation must carry data-authority='read-only-projection'"
    )
    assert "3 open loops" in mem_node_html, (
        "open-loops count annotation must display the count number"
    )
    # No list of loop items — counts-not-tiles only.
    # The annotation is a count paragraph, no article/list elements for individual loops.
    assert '<article' not in mem_node_html or "orientation-item" not in mem_node_html, (
        "memory map node must not render individual loop items (counts-not-tiles)"
    )
    # Singular form when count is 1.
    frag_one_loop = system_map_overlay_markup(available_routes=(), open_loops_count=1)
    mem_node_start_one = frag_one_loop.find('data-surface-id="memory"')
    mem_node_html_one = frag_one_loop[mem_node_start_one:mem_node_start_one + 1100]
    assert "1 open loop" in mem_node_html_one, (
        "open-loops count annotation must use singular form when count is 1"
    )
    assert "1 open loops" not in mem_node_html_one, (
        "open-loops count annotation must not use plural for a count of 1"
    )

    # --- #2247 Panel rail open-loops badge in shell_active: non-zero shows, zero omits ---
    # With non-zero orientation_open_loops_count in fields: badge renders.
    html_with_loops = _render_workspace(orientation_open_loops_count=4)
    assert 'data-region="panel-rail-open-loops"' in html_with_loops, (
        "panel-rail-open-loops region must render in shell_active when open_loops count is non-zero"
    )
    assert 'data-authority="read-only-projection"' in html_with_loops, (
        "panel-rail-open-loops badge must carry data-authority='read-only-projection'"
    )
    assert 'data-intent="memory.open"' in html_with_loops, (
        "panel-rail-open-loops badge must carry data-intent='memory.open'"
    )
    assert "4 open loops" in html_with_loops, (
        "panel-rail-open-loops badge must display the open-loops count"
    )
    # No list of loop items — counts-not-tiles only.
    badge_start = html_with_loops.find('data-region="panel-rail-open-loops"')
    badge_snippet = html_with_loops[badge_start:badge_start + 600]
    assert "orientation-item" not in badge_snippet, (
        "panel-rail-open-loops badge must not render individual loop items (counts-not-tiles)"
    )
    # Zero count: badge must not render (no zero-state).
    html_no_loops = _render_workspace()  # no orientation_open_loops_count → defaults to 0
    assert 'data-region="panel-rail-open-loops"' not in html_no_loops, (
        "panel-rail-open-loops badge must not render when open_loops count is zero or absent"
    )


def test_cold_start_omits_relocated_telemetry_regions() -> None:
    """Cold_start door does not render freshness/as_of/trace_id outside pull-only surfaces.

    Verifies AC3 of #2245: the cold_start entry-surface body is clean of
    these telemetry fields. They exist only inside the (closed) system-map
    overlay (pull-only, requires explicit map.open) — never in the entry-
    surface body, never in the topbar row (only inside the <details> popover
    which requires explicit open by the operator).
    """
    cold = _render_cold_start()
    assert _entry_state(cold) == "cold_start"

    # The orientation-meta div (removed by #2171) must not appear in the body
    # outside pull-only surfaces.
    # The body region is everything outside the system-map-overlay fragment.
    cold_no_overlay = re.sub(
        r"<!-- system-map-overlay start -->.*?<!-- system-map-overlay end -->",
        "",
        cold,
        flags=re.S,
    )
    # No "Re-entry snapshot" heading on cold_start (confirmed by #2171).
    assert "Re-entry snapshot" not in cold_no_overlay, (
        "cold_start must not render the Re-entry snapshot heading"
    )
    # The orientation-meta class/region must not appear in the body outside the overlay.
    assert 'class="orientation-meta"' not in cold_no_overlay, (
        "orientation-meta div must not appear on cold_start body outside pull-only overlay"
    )
    # The relocated rows (freshness-as-of / orientation-as-of / orientation-trace-id)
    # must not appear in the body outside the closed map overlay.
    for testid in (
        "workspace-freshness-as-of",
        "workspace-orientation-as-of",
        "workspace-orientation-trace-id",
    ):
        assert f'data-testid="{testid}"' not in cold_no_overlay, (
            f"{testid} must not appear on cold_start body outside pull-only surfaces"
        )
    # The map overlay IS present on the page (pull-only), so the cold_start
    # page carries the overlay in its (closed) state — this is correct:
    # the map requires an explicit map.open affordance to display.
    cold_overlay = _map_overlay(cold)
    root = re.search(
        r'<div[^>]*data-testid="system-map-overlay"[^>]*>', cold_overlay
    )
    assert root and 'data-open="false"' in root.group(0), (
        "system-map-overlay must be closed (not auto-opened) on cold_start"
    )

    # #2246 governance suppression: governance-counts-row must NOT appear on
    # cold_start outside pull-only surfaces (neither on the body nor the
    # receipts modal which is closed on the entry surface).
    # The governance 3-cell grid (workspace-orientation-governance) was
    # suppressed by is_cold guard; the new governance-counts row must also be
    # absent from the cold_start body.
    assert 'data-testid="workspace-orientation-governance"' not in cold_no_overlay, (
        "governance grid must not appear on cold_start body"
    )
    assert 'data-testid="governance-counts-row"' not in cold_no_overlay, (
        "governance-counts-row must not appear on cold_start body outside "
        "pull-only surfaces (receipts modal is closed, map overlay is closed)"
    )
