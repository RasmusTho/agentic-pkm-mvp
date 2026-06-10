"""Unified topbar + shared overlay host + keyboard map (#1785, SEP-03).

The shell gets one place for every overlay to mount and one rule to obey
(`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Overlay-grammar rule
(NORMATIVE)`, `§Keyboard map`, `companion-ui/docs/OVERLAY_GRAMMAR.md`,
`docs/SYSTEM_ENTRY_POINT/UNIFIED_TOPBAR_AND_OVERLAY_HOST.md`):

- the shipped workspace header (`data-region="workspace-header"`) evolves into
  the spec's topbar: wordmark, anchor pill (`data-region="document-anchor"`),
  posture pill (`data-posture-emphasis`, rendering only), surface icons for
  shipped surfaces only (no dead affordances), and the coarse vault-status dot;
- a single overlay host in the shell is the mount/dismiss substrate: `Esc`
  dismisses the topmost overlay (`overlay.dismiss`); dismissal returns to the
  document anchor with no route reset and no data loss; staged suggestions and
  open-loop counts survive open/dismiss cycles; only declared overlays mount;
- keyboard map: `⌘K` → `cmd.open`, `⌘N` → `capture.open`, `Esc` →
  `overlay.dismiss`; the map is inert for overlays whose tasks have not
  landed (graceful no-op — never an invented surface);
- the narrow-mode vault-browser modal is treated as an overlay-host occupant
  for the dismiss rule; the shipped 3-column workspace (#1395) is composed,
  not replaced.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from companion_ui.workspace.overlay_host import (
    COARSE_VAULT_POSTURES,
    DECLARED_OVERLAYS,
    DEFAULT_POSTURE_EMPHASIS,
    INTENT_OVERLAY_TARGETS,
    KEYBOARD_MAP,
    POSTURE_EMPHASES,
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    TOPBAR_SURFACES,
    OverlayHostState,
    apply_intent,
    coarse_vault_posture,
    dismiss,
    keyboard_intent,
    mount,
)
from companion_ui.workspace.serve_dev_page import render_index_html

# ---------------------------------------------------------------------------
# Fixtures (mirror the proven workspace fixture in test_entry_state_machine)
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


def _render(**overrides: Any) -> str:
    fields = _fields(**overrides)
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path=str(fields["note_path"]),
        fields=fields,
    )


def _topbar(html: str) -> str:
    m = re.search(
        r'<header[^>]*data-region="workspace-header".*?</header>', html, re.S
    )
    assert m, "topbar (data-region=workspace-header) must render"
    return m.group(0)


def _host_element(html: str) -> str:
    m = re.search(r'<div[^>]*data-region="overlay-host"[^>]*>', html)
    assert m, "shared overlay host (data-region=overlay-host) must render"
    return m.group(0)


def _host_script(html: str) -> str:
    m = re.search(
        r"/\* overlay-host-controller \*/(.*?)/\* /overlay-host-controller \*/",
        html,
        re.S,
    )
    assert m, "overlay-host controller script must render"
    return m.group(1)


def _vault_browser_script(html: str) -> str:
    m = re.search(
        r"var overlay = document\.getElementById\('vault-browser-overlay'\);(.*?)</script>",
        html,
        re.S,
    )
    assert m, "vault browser script must render"
    return m.group(1)


def _state(**overrides: Any) -> OverlayHostState:
    base: dict[str, Any] = {
        "anchor_note_path": "Notes/note.md",
        "route": "/?note_path=Notes%2Fnote.md",
        "scroll_owner": "note-body",
        "rail_state": "open",
        "staged_suggestion_ids": ("s-1", "s-2"),
        "open_loop_count": 3,
        "stack": (),
    }
    base.update(overrides)
    return OverlayHostState(**base)


# ---------------------------------------------------------------------------
# AC1: the topbar renders wordmark, anchor pill, posture pill, surface icons
# for shipped surfaces only, and the vault-status dot
# ---------------------------------------------------------------------------


def test_topbar_renders_declared_regions() -> None:
    html = _render()
    topbar = _topbar(html)

    # The shipped header region is evolved, not replaced.
    assert 'data-region="workspace-header"' in topbar
    assert 'data-testid="workspace-wordmark"' in topbar

    # Anchor pill — current note identity (spec §Data-attribute vocabulary).
    anchor = re.search(r'<span[^>]*data-region="document-anchor"[^>]*>([^<]*)</span>', topbar)
    assert anchor, "topbar must render the document-anchor pill"
    assert 'data-anchor-note-path="Notes/note.md"' in anchor.group(0)
    assert anchor.group(1).strip() == "Note Title"

    # Posture pill — local posture emphasis, rendering only (spec §Resolved Q6).
    pill = re.search(r'<span[^>]*data-testid="workspace-posture-pill"[^>]*>', topbar)
    assert pill, "topbar must render the posture pill"
    emphasis = re.search(r'data-posture-emphasis="([^"]+)"', pill.group(0))
    assert emphasis and emphasis.group(1) in POSTURE_EMPHASES
    assert emphasis.group(1) == DEFAULT_POSTURE_EMPHASIS
    assert DEFAULT_POSTURE_EMPHASIS in POSTURE_EMPHASES
    # Rendering only: no posture.open affordance until the switch overlay ships.
    assert 'data-intent="posture.open"' not in html
    # The shell root declares the same emphasis attribute.
    body_tag = re.search(r"<body[^>]*>", html)
    assert body_tag and "data-posture-emphasis=" in body_tag.group(0)

    # Surface icons — shipped surfaces only (no dead affordances).
    icons = re.search(
        r'<nav[^>]*data-region="surface-icons".*?</nav>', topbar, re.S
    )
    assert icons, "topbar must render the surface-icons group"
    rendered_surfaces = set(re.findall(r'data-surface="([^"]+)"', icons.group(0)))
    assert rendered_surfaces == set(SHIPPED_TOPBAR_SURFACES)
    for surface in set(TOPBAR_SURFACES) - set(SHIPPED_TOPBAR_SURFACES):
        assert f'data-surface="{surface}"' not in html, (
            f"unshipped surface {surface!r} must not render an icon"
        )

    # Vault-status dot present in the topbar.
    assert 'data-testid="workspace-vault-status-dot"' in topbar

    # Shipped header contracts are preserved (testids unchanged).
    for testid in (
        "workspace-vault-chip",
        "workspace-runtime-pill",
        "workspace-runtime-status-popover",
        "workspace-freshness",
        "workspace-quick-open",
        "workspace-browse-vault",
    ):
        assert f'data-testid="{testid}"' in topbar


# ---------------------------------------------------------------------------
# AC2: every mounted overlay dismisses to the document anchor with no route
# reset (URL, scroll ownership, anchor identity preserved)
# ---------------------------------------------------------------------------


def test_overlay_dismiss_returns_to_anchor_without_route_reset() -> None:
    # Pure host model: mount + dismiss returns the identical anchor context.
    before = _state()
    mounted = mount(before, "vault")
    assert mounted.stack == ("vault",)
    dismissed = dismiss(mounted)
    assert dismissed.stack == ()
    assert dismissed == before, "dismissal must restore the exact anchor context"
    assert dismissed.anchor_note_path == before.anchor_note_path
    assert dismissed.route == before.route
    assert dismissed.scroll_owner == before.scroll_owner

    # Dismiss with nothing mounted is a calm no-op, never a navigation.
    assert dismiss(before) == before

    # Stacked overlays dismiss topmost-first; the anchor never changes.
    # (Simulates the host once a later SEP task registers a second occupant.)
    stacked = mount(mounted, "help", occupants=("vault", "help"))
    assert stacked.stack == ("vault", "help")
    top_popped = dismiss(stacked)
    assert top_popped.stack == ("vault",)
    assert top_popped.anchor_note_path == before.anchor_note_path

    # Rendered shell: the host is an overlay layer beside the document column,
    # not a wrapper that replaces it.
    html = _render()
    host = _host_element(html)
    assert 'data-overlay-open="none"' in host
    assert 'data-region="note-body"' in html
    assert 'data-testid="workspace-overlay-scrim"' in html
    assert "overlayHost.dismiss()" in html  # scrim dismisses to the anchor

    # The dismiss path performs no route reset: the host controller never
    # navigates, never submits a form, never rewrites history.
    script = _host_script(html)
    for forbidden in ("location.href", "location.assign", "location.reload",
                      "form.submit", "history.pushState", "window.open"):
        assert forbidden not in script, f"host dismiss must not call {forbidden}"


# ---------------------------------------------------------------------------
# AC3: Esc dismisses the topmost overlay; ⌘K and ⌘N route to declared intents
# ---------------------------------------------------------------------------


def test_keyboard_map_routes_declared_intents() -> None:
    # The declared map is exactly ⌘K / ⌘N / Esc (fuller model deferred, Q14).
    assert KEYBOARD_MAP == {
        "meta+k": "cmd.open",
        "meta+n": "capture.open",
        "escape": "overlay.dismiss",
    }
    assert keyboard_intent("meta+k") == "cmd.open"
    assert keyboard_intent("meta+n") == "capture.open"
    assert keyboard_intent("escape") == "overlay.dismiss"
    assert keyboard_intent("meta+p") is None  # unmapped keys stay unmapped

    # Esc routes through the host: topmost overlay only.
    state = mount(_state(), "vault")
    after_esc = apply_intent(state, "overlay.dismiss")
    assert after_esc.stack == ()
    assert after_esc == _state()

    # ⌘K / ⌘N route to their declared overlay targets...
    assert INTENT_OVERLAY_TARGETS == {"cmd.open": "cmd", "capture.open": "capture"}
    # ...and are inert while those surfaces have not shipped (no-op, no error,
    # no invented surface).
    assert "cmd" not in SHIPPED_OVERLAY_OCCUPANTS
    assert "capture" not in SHIPPED_OVERLAY_OCCUPANTS
    assert apply_intent(_state(), "cmd.open") == _state()
    assert apply_intent(_state(), "capture.open") == _state()

    # Undeclared intents are rejected, not silently absorbed.
    with pytest.raises(ValueError):
        apply_intent(_state(), "overlay.maximize")

    # Rendered wiring: one host keyboard listener carries the declared map.
    html = _render()
    script = _host_script(html)
    assert "'cmd'" in script and "cmd.open" in script
    assert "'capture'" in script and "capture.open" in script
    assert "Escape" in script and "overlay.dismiss" in script

    # No dead affordances: no rendered control advertises the unshipped
    # palette/capture surfaces.
    assert 'data-intent="cmd.open"' not in html
    assert 'data-intent="capture.open"' not in html


# ---------------------------------------------------------------------------
# AC4: staged suggestions and open-loop counts survive an open/dismiss cycle
# ---------------------------------------------------------------------------


def test_overlay_cycle_preserves_staged_state() -> None:
    before = _state(
        staged_suggestion_ids=("s-1", "s-2", "s-3"),
        open_loop_count=5,
        rail_state="open",
    )
    cycled = dismiss(mount(before, "vault"))
    # No erased tension: staged suggestions and open-loop counts intact.
    assert cycled.staged_suggestion_ids == ("s-1", "s-2", "s-3")
    assert cycled.open_loop_count == 5
    # The rail open/closed state survives the cycle (issue: [data-rail="open"]).
    assert cycled.rail_state == "open"
    assert cycled == before

    # A full stack cycle (vault then help, dismiss both) is equally lossless.
    occupants = ("vault", "help")
    full = dismiss(
        dismiss(mount(mount(before, "vault", occupants=occupants), "help", occupants=occupants))
    )
    assert full == before

    # Rendered controller: mount/dismiss only touch host bookkeeping — they
    # never reach into the document column, staged suggestion blocks, or rail.
    script = _host_script(_render())
    for forbidden in ("data-suggestion-id", "suggestion-block", "data-rail",
                      "note-body", "innerHTML"):
        assert forbidden not in script, (
            f"host controller must not touch {forbidden} on open/dismiss"
        )


# ---------------------------------------------------------------------------
# AC5: undeclared overlay ids cannot mount on the host
# ---------------------------------------------------------------------------


def test_undeclared_overlays_rejected() -> None:
    # The declared registry is exactly the spec's overlay set.
    assert DECLARED_OVERLAYS == (
        "cmd", "vault", "memory", "peek", "posture", "map",
        "settings", "capture", "receipts", "tts", "help",
    )

    for bogus in ("task-popup", "", "notifications", "VAULT"):
        with pytest.raises(ValueError):
            mount(_state(), bogus)

    # The state type itself cannot carry an undeclared overlay.
    with pytest.raises(ValueError):
        OverlayHostState(stack=("task-popup",))

    # Declared-but-unshipped overlays do not mount (inert), and do not raise:
    # the host never invents a surface for them.
    for declared_unshipped in ("cmd", "memory", "settings", "capture", "map"):
        assert declared_unshipped in DECLARED_OVERLAYS
        assert declared_unshipped not in SHIPPED_OVERLAY_OCCUPANTS
        assert mount(_state(), declared_unshipped) == _state()

    # Rendered host declares its registry and rejects undeclared ids in the
    # controller as well.
    html = _render()
    host = _host_element(html)
    assert f'data-declared-overlays="{" ".join(DECLARED_OVERLAYS)}"' in host
    assert "undeclared overlay" in _host_script(html)


# ---------------------------------------------------------------------------
# AC6: the vault-status dot renders only a coarse derived posture
# ---------------------------------------------------------------------------


def test_vault_status_dot_is_coarse_posture_only() -> None:
    # Pure derivation: coarse posture only, from already-coarse inputs.
    assert coarse_vault_posture(vault_state="ok", primary_posture="ok") == "ok"
    assert coarse_vault_posture(vault_state="unresolved", primary_posture="ok") == "degraded"
    assert (
        coarse_vault_posture(vault_state="unreachable", primary_posture="ok")
        == "unavailable"
    )
    assert (
        coarse_vault_posture(vault_state="ok", primary_posture="blocked") == "blocked"
    )
    # Out-of-contract input degrades coarsely instead of inventing detail.
    assert (
        coarse_vault_posture(vault_state="ok", primary_posture="half-broken")
        == "degraded"
    )

    html = _render()
    dot = re.search(r'<span[^>]*data-testid="workspace-vault-status-dot"[^>]*>', html)
    assert dot, "vault-status dot must render"
    coarse = re.search(r'data-coarse-posture="([^"]+)"', dot.group(0))
    assert coarse and coarse.group(1) in COARSE_VAULT_POSTURES

    # The dot carries the coarse posture and nothing else: no detailed health
    # slices (those stay with /api/status via the runtime popover).
    dot_data_attrs = set(re.findall(r'data-([a-z-]+)=', dot.group(0)))
    assert dot_data_attrs == {"testid", "coarse-posture"}, (
        f"vault-status dot must expose only the coarse posture, got {dot_data_attrs}"
    )
    for detailed in ("writeguard", "canvas", "update", "trace", "telemetry"):
        assert detailed not in dot.group(0)

    # Unreachable vault renders the coarse 'unavailable' posture on the dot.
    down = _render(runtime_vault_provenance="unreachable")
    down_dot = re.search(
        r'<span[^>]*data-testid="workspace-vault-status-dot"[^>]*>', down
    )
    assert down_dot and 'data-coarse-posture="unavailable"' in down_dot.group(0)


# ---------------------------------------------------------------------------
# AC7: narrow mode keeps every critical affordance reachable; the vault
# narrow-mode modal is an overlay-host occupant for the dismiss rule
# ---------------------------------------------------------------------------


def test_narrow_mode_preserves_critical_affordances() -> None:
    html = _render()

    # Shipped narrow-mode affordances stay composed, not replaced (#1395/#1342).
    assert 'class="workspace-sheet-triggers"' in html
    assert 'data-testid="workspace-outline-sheet-trigger"' in html
    assert 'data-testid="workspace-panel-sheet-trigger"' in html
    assert 'data-testid="vault-browser-overlay"' in html
    assert 'data-browser-role="responsive-fallback"' in html

    # The narrow-mode vault modal is registered as a host occupant, so the
    # dismiss rule (Esc / scrim → anchor) is enforced by the host.
    script = _host_script(html)
    assert "register('vault'" in script
    assert tuple(SHIPPED_OVERLAY_OCCUPANTS) == ("vault",)

    # Exactly one Esc owner for host occupants: the vault browser script no
    # longer carries its own Escape listener.
    assert "Escape" not in _vault_browser_script(html)
    assert "Escape" in script

    # The topbar's critical affordances are not display-gated away in narrow
    # CSS: no rule hides the surface-icons group or the anchor pill.
    assert not re.search(
        r"\.workspace-surface-icons[^{]*\{[^}]*display:\s*none", html
    ), "surface icons must stay reachable in narrow mode"
    assert not re.search(
        r"\.workspace-anchor-pill[^{]*\{[^}]*display:\s*none", html
    ), "the document anchor pill must stay reachable in narrow mode"
