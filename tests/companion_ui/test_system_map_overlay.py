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
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.system_map_overlay import (
    MAP_CENTER_NAME,
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
        "guidance",
    }, "exactly the composition-table surfaces (parked rows excluded)"
    for node in MAP_SURFACES:
        assert set(node.modes) <= set(PRODUCT_MODES)
        assert node.status in NODE_STATUSES
        assert node.reached and node.returns and node.status_note

    # The map re-classifies nothing: statuses mirror the spec table.
    by_id = {node.surface_id: node for node in MAP_SURFACES}
    for shipped in ("orientation", "anchor", "vault", "panel", "palette",
                    "suggestions", "memory", "tts", "capture", "receipts",
                    "settings", "map"):
        assert by_id[shipped].status == "shipped", shipped
    for partial in ("chat_rail", "peek"):
        assert by_id[partial].status == "partial", partial
    for new in ("posture", "guidance"):
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
# AC2: shipped nodes route via existing intents; unshipped nodes are inert
# and truthfully labeled
# ---------------------------------------------------------------------------


def test_shipped_nodes_route_and_unshipped_nodes_are_inert() -> None:
    # Pure model: only shipped surfaces can be routable, and the intents the
    # nodes emit are existing declared intents — the map invents none.
    assert set(routable_surface_ids()) == {
        "anchor", "vault", "panel", "palette", "memory", "capture", "receipts",
        "settings",
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
        "settings": "settings.open",
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


# ---------------------------------------------------------------------------
# AC3: the map is reachable from cold_start and no_vault as well as
# shell_active
# ---------------------------------------------------------------------------


def test_map_reachable_from_cold_and_no_vault_states() -> None:
    # The map is a shipped overlay-host occupant and a shipped topbar surface.
    assert SYSTEM_MAP_OVERLAY_ID == "map"
    assert "map" in SHIPPED_OVERLAY_OCCUPANTS
    assert "map" in SHIPPED_TOPBAR_SURFACES
    state = OverlayHostState(anchor_note_path="Notes/note.md")
    assert mount(state, "map").stack == ("map",)

    # shell_active: the topbar surface icon carries the map.open affordance.
    shell = _render_workspace()
    assert _entry_state(shell) == "shell_active"
    icon = re.search(
        r'<button[^>]*data-testid="workspace-surface-icon-map"[^>]*>', shell
    )
    assert icon, "topbar must render the map surface icon"
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
