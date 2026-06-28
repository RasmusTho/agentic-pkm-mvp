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

    # Posture pill — C1 (#2484): the local posture-emphasis pill (which
    # rendered ``DEFAULT_POSTURE_EMPHASIS`` = ``recovery`` as a ``RECOVERY``
    # indicator) is removed from the shell topbar. Recovery/posture is
    # reachable only via the System Map / operator layer; it must not sit on
    # this anti-dashboard front edge.
    assert (
        'data-testid="workspace-posture-pill"' not in topbar
    ), "the posture pill must not render on the shell topbar (#2484)"
    # Rendering only: no posture.open affordance until the switch overlay ships.
    assert 'data-intent="posture.open"' not in html
    # Presentation only: the emphasis is still declared on the shell root
    # ``<body>`` data attribute (server-authoritative posture preserved); only
    # the visible front-edge pill is gone.
    assert DEFAULT_POSTURE_EMPHASIS in POSTURE_EMPHASES
    body_tag = re.search(r"<body[^>]*>", html)
    assert body_tag and "data-posture-emphasis=" in body_tag.group(0)

    # Surface icons — CUIDR-04 (#2447): the top edge keeps IDENTITY + ONE
    # primary action (Capture). Every other launcher is displaced off the
    # topbar into the never-clipping System Map overflow surface, so the bar
    # stops clipping its own icons off-screen at ≤1440 px.
    icons = re.search(
        r'<nav[^>]*data-region="surface-icons".*?</nav>', topbar, re.S
    )
    assert icons, "topbar must render the surface-icons group"
    rendered_surfaces = set(re.findall(r'data-surface="([^"]+)"', icons.group(0)))
    assert rendered_surfaces == set(SHIPPED_TOPBAR_SURFACES) == {"capture"}
    # Every non-capture launcher leaves the topbar entirely (no icon anywhere
    # on the front edge — reachable via the System Map / bottom bar instead).
    for surface in set(TOPBAR_SURFACES) - set(SHIPPED_TOPBAR_SURFACES):
        assert f'data-surface="{surface}"' not in topbar, (
            f"displaced surface {surface!r} must not render a topbar icon"
        )

    # Vault-status dot present in the topbar.
    assert 'data-testid="workspace-vault-status-dot"' in topbar

    # Shipped identity contracts are preserved on the topbar (testids
    # unchanged). The runtime-status pill, freshness string, and quick-open hint
    # are operator/diagnostic telemetry — CUIDR-04 moves them off the front edge
    # into the operator-telemetry region; they are no longer in the header.
    # CUIDR-04 (#2447): the vault identity chip stays on the header (identity);
    # the standalone "Browse vault" launcher left the front edge (vault routes
    # via the System Map / the chip now).
    assert 'data-testid="workspace-vault-chip"' in topbar
    assert 'data-testid="workspace-browse-vault"' not in topbar
    for relocated in (
        "workspace-runtime-pill",
        "workspace-runtime-status-popover",
        "workspace-freshness",
    ):
        assert f'data-testid="{relocated}"' not in topbar, (
            f"{relocated} is operator telemetry — it must not sit on the topbar"
        )
    # quick-open is removed outright (not relocated).
    assert 'data-testid="workspace-quick-open"' not in html
    # The relocated telemetry lives in the operator layer, off the front edge.
    op_region = re.search(
        r'<section class="workspace-operator-telemetry"[^>]*>.*?</section>',
        html,
        re.S,
    )
    assert op_region, "operator-telemetry region must render off the front edge"
    assert 'data-testid="workspace-runtime-pill"' in op_region.group(0)
    assert 'data-testid="workspace-freshness"' in op_region.group(0)


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
    # navigates the page away or submits a form. NAV-3a (#2639) adds browser-
    # history participation (history.pushState on mount, history.back to unwind
    # on dismiss, a popstate handler) — that is the modal-Back mechanism, NOT a
    # route reset: it never changes the URL path/query and never replaces the
    # document. So pushState/popstate/history.back are explicitly allowed while
    # genuine navigation calls stay forbidden.
    script = _host_script(html)
    for forbidden in ("location.href", "location.assign", "location.reload",
                      "form.submit", "window.open"):
        assert forbidden not in script, f"host dismiss must not call {forbidden}"


# ---------------------------------------------------------------------------
# NAV-3a (#2639): overlays participate in browser history — the CORE mechanism.
# mount pushes a depth-stamped history marker; a popstate handler reconciles the
# overlay stack to the landed entry's depth, so browser Back closes the topmost
# overlay (single AND stacked) and Forward restores the marked one. The optional
# ?overlay= deep-link is #2641 (NAV-3c) and the System Map route sync is #2640
# (NAV-3b) — neither is asserted here.
# ---------------------------------------------------------------------------


def test_overlay_host_pushes_history_marker_and_handles_popstate() -> None:
    """AC1 Verify target: the rendered overlay-host script pushes a depth-stamped
    history state marker on a net-new ``mount`` and registers a ``popstate``
    handler that reconciles the overlay stack to the depth carried in the history
    entry (browser Back closes the modal; Forward restores it). The programmatic
    dismiss path unwinds its own entry via ``history.back()`` behind a re-entrancy
    guard, and the Esc/scrim/anchor-return grammar is preserved.
    """
    script = _host_script(_render())

    # mount pushes a marked history entry carrying the overlay id AND the stack
    # depth it represents (so popstate can reconcile to it, not blind-pop).
    assert "history.pushState" in script, (
        "mount must push a history state marker so browser Back can pop it"
    )
    assert "overlayHostMarker" in script, "the pushed state must carry the host marker"
    assert "st.depth = stack.length" in script, (
        "the pushed state must carry the stack depth for reconciliation"
    )
    # A re-mount (move-to-top of an already-stacked id) must NOT push a second
    # entry (double-push desyncs depth from history position).
    assert "isNetNew" in script, (
        "only a net-new mount may push a history entry (no double-push on re-mount)"
    )

    # A popstate handler is registered and it RECONCILES to the landed entry's
    # depth (event.state.depth) rather than unconditionally popping. Back closes
    # above target; Forward (depth up by one) restores the marked overlay.
    assert "addEventListener('popstate'" in script, (
        "a popstate handler must be registered so browser Back closes the overlay"
    )
    assert "event.state" in script or "st = event" in script, (
        "the popstate handler must read event.state to reconcile by depth"
    )
    assert "targetDepth" in script, (
        "the popstate handler must reconcile to the entry's target depth"
    )
    assert "stack.length > targetDepth" in script, (
        "Back must pop overlays down to the target depth (close-above-target)"
    )
    assert "stack.length < targetDepth" in script, (
        "Forward must restore the marked overlay when depth increased (recovery)"
    )
    # The programmatic dismiss path unwinds its own entry with history.back(),
    # guarded against re-entrant double-dismiss.
    assert "history.back" in script, (
        "a programmatic dismiss must unwind its matching history entry"
    )
    assert "popping" in script, "a re-entrancy guard must coordinate back/popstate"

    # Esc and the scrim still dismiss to the anchor (grammar preserved).
    assert "Escape" in script and "overlay.dismiss" in script
    assert "overlayHost.dismiss()" in _render()  # scrim onclick


# ---------------------------------------------------------------------------
# NAV-3b (#2640): the System Map route is an ATOMIC overlay->overlay swap.
# overlayHost.replace(id) closes the current topmost occupant and opens the
# destination at the SAME history depth via history.replaceState — never the
# dismiss()->mount() shape, whose pending history.back() (popping=true) raced
# the next push and left browser history desynced from the overlay stack so the
# next Back/Forward acted on the wrong overlay. systemMap.route() is rewired to
# use replace for every map->overlay branch.
# ---------------------------------------------------------------------------


def test_overlay_host_replace_swaps_history_entry_at_constant_depth() -> None:
    """The rendered host exposes overlayHost.replace(id, detail): it closes the
    current topmost occupant (its close hook runs, via the shared topmost-pop),
    pushes the destination, and REPLACES the current history entry with the
    destination marker at the SAME depth using history.replaceState — with NO
    history.back() in the swap (no pending traversal to race a later push). A
    declared-but-unshipped id is inert, and an empty stack falls back to a
    pushState mount so the base page-load entry is never clobbered.
    """
    script = _host_script(_render())

    # The replace path exists on the host API.
    assert "replace: function(id, detail)" in script, (
        "host must expose overlayHost.replace(id, detail) for the atomic route swap"
    )

    # Isolate the replace method body so depth/replaceState assertions are about
    # the swap path itself, not the unrelated mount/dismiss bodies.
    m = re.search(
        r"replace: function\(id, detail\) \{(.*?)\n      \},", script, re.S
    )
    assert m, "replace method body must be present"
    body = m.group(1)
    # Strip JS line-comments so call-shape assertions are about executable code,
    # not the explanatory comments (which legitimately *name* history.back /
    # dismiss->mount to document the race being removed).
    code = "\n".join(re.sub(r"//.*$", "", ln) for ln in body.splitlines())

    # It declares the destination, and is inert for an unshipped occupant
    # (same no-op rule as mount — never invent a surface).
    assert "assertDeclared(id)" in code, "replace must assert the id is declared"
    assert "if (!occ) { return; }" in code, (
        "replace must be an inert no-op for a declared-but-unshipped occupant"
    )

    # It closes the current topmost occupant via the shared topmost-pop (which
    # runs the occupant close hook and updates host bookkeeping) WITHOUT calling
    # history.back() — the swap leaves no pending history traversal to race a
    # subsequent push (the central NAV-3b fix).
    assert "popTopmost()" in code, (
        "replace must close the current topmost occupant via the shared pop"
    )
    assert "history.back" not in code, (
        "replace must NOT call history.back() — that pending traversal is the "
        "race NAV-3b removes"
    )

    # It swaps the SAME history entry (replaceState) at constant depth — the
    # destination marker carries the host marker and depth = stack.length, and
    # the entry is REPLACED, not pushed.
    assert "history.replaceState" in code, (
        "replace must use history.replaceState to swap the single history entry"
    )
    assert "history.pushState" not in code, (
        "replace must not push a new entry on the non-empty (swap) path"
    )
    assert "st[HISTORY_MARKER] = id" in code and "st.depth = stack.length" in code, (
        "the swapped entry must carry the destination marker and the stack depth"
    )

    # Empty-stack defensive fallback: with nothing mounted there is no entry to
    # swap, so replace falls back to a normal pushState mount (never clobbers the
    # base page-load entry via replaceState).
    assert "if (!stack.length) { this.mount(id, detail); return; }" in code, (
        "replace must fall back to mount (pushState) when the stack is empty"
    )

    # The destination is opened with its detail.
    assert "occ.open(detail || {})" in code, "replace must open the destination occupant"


def test_system_map_route_uses_replace_not_dismiss_then_mount() -> None:
    """systemMap.route() routes map->overlay via the atomic overlayHost.replace
    swap, not the racy dismiss()->mount() pair. This is the cross-surface
    contract for NAV-3b: against the unrewired route() (dismiss + mount) this
    assertion fails. dismiss() survives only on the non-overlay focus targets
    (anchor / vault / panel / operator).
    """
    html = _render()
    m = re.search(
        r"/\* system-map-controller \*/(.*?)/\* /system-map-controller \*/",
        html,
        re.S,
    )
    assert m, "system-map-controller script must render"
    map_script = m.group(1)

    # Every map->overlay branch uses the atomic replace swap.
    for target in ("cmd", "memory", "capture", "receipts", "settings"):
        assert f"overlayHost.replace('{target}')" in map_script, (
            f"map route to {target} must use the atomic overlayHost.replace swap"
        )
        # ...and NOT the racy dismiss()->mount() shape.
        assert f"overlayHost.mount('{target}')" not in map_script, (
            f"map route to {target} must not use the racy dismiss()->mount() pattern"
        )


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

    # ⌘K / ⌘N route to their declared overlay targets; shipped topbar
    # surface intents are declared here too, so markup does not advertise
    # host mounts outside the model.
    assert INTENT_OVERLAY_TARGETS == {
        "cmd.open": "cmd",
        "capture.open": "capture",
        "map.open": "map",
        "memory.open": "memory",
        "receipts.open": "receipts",
        "settings.open": "settings",
        "vault.open": "vault",
    }
    # ...both occupants are shipped: ⌘K mounts the Panel command palette
    # (#1786, SEP-04) and ⌘N mounts the capture modal (#1791, SEP-08b).
    assert "cmd" in SHIPPED_OVERLAY_OCCUPANTS
    assert "capture" in SHIPPED_OVERLAY_OCCUPANTS
    assert apply_intent(_state(), "cmd.open").stack == ("cmd",)
    assert apply_intent(_state(), "capture.open").stack == ("capture",)
    for intent, target in (
        ("map.open", "map"),
        ("memory.open", "memory"),
        ("receipts.open", "receipts"),
        ("settings.open", "settings"),
        ("vault.open", "vault"),
    ):
        assert target in SHIPPED_OVERLAY_OCCUPANTS
        assert apply_intent(_state(), intent).stack == (target,)

    # Undeclared intents are rejected, not silently absorbed.
    with pytest.raises(ValueError):
        apply_intent(_state(), "overlay.maximize")

    # Rendered wiring: one host keyboard listener carries the declared map.
    html = _render()
    script = _host_script(html)
    assert "'cmd'" in script and "cmd.open" in script
    assert "'capture'" in script and "capture.open" in script
    assert "Escape" in script and "overlay.dismiss" in script

    topbar = _topbar(html)
    # CUIDR-04 (#2447): Capture is the single launcher intent kept on the top
    # edge. Every other surface-open intent (vault/map/memory/receipts/settings)
    # is displaced off the topbar into the System Map overflow surface.
    assert 'data-intent="capture.open"' in topbar
    for intent in (
        "vault.open",
        "map.open",
        "memory.open",
        "receipts.open",
        "settings.open",
    ):
        assert f'data-intent="{intent}"' not in topbar, (
            f"{intent} is displaced off the topbar (reachable via the System Map)"
        )
        assert intent in INTENT_OVERLAY_TARGETS
    # The displaced open-intents are reachable via the System Map routing nodes.
    map_overlay = re.search(
        r"<!-- system-map-overlay start -->.*?<!-- system-map-overlay end -->",
        html,
        re.S,
    )
    assert map_overlay, "system map overlay must render in the shell"
    for intent in ("vault.open", "memory.open", "receipts.open", "settings.open"):
        assert f'data-intent="{intent}"' in map_overlay.group(0)

    # No dead affordances: the capture surface opens through the host's ⌘N
    # wiring and the topbar's single Capture launcher. cmd.open is advertised
    # by the System Map's palette routing node and, since NAV-4 (ui-audit), by
    # the composed bottom bar's direct Search / ⌘K launcher — both route to the
    # shipped `cmd` occupant, never dead chrome. No other element may carry it.
    for tag in re.findall(r'<[a-z]+[^>]*data-intent="cmd.open"[^>]*>', html):
        assert (
            'data-testid="system-map-node"' in tag
            or 'data-testid="workspace-surface-icon-cmd"' in tag
        ), (
            "only a live system-map routing node or the NAV-4 bottom-bar Search "
            f"launcher may advertise cmd.open: {tag}"
        )
    for tag in re.findall(r'<[a-z]+[^>]*data-intent="capture.open"[^>]*>', html):
        assert (
            'data-testid="system-map-node"' in tag
            or 'data-testid="workspace-surface-icon-capture"' in tag
            or 'data-intent="capture.open" onclick' in tag
        ), f"capture.open must be a live topbar launcher or map node: {tag}"


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
    # the host never invents a surface for them. (`capture` left this set when
    # the capture modal shipped, #1791; `cmd` when the palette shipped, #1786;
    # `memory` when the review drawer shipped, #1793; `settings` when the
    # settings drawer shipped, #1789; `map` when the system map overlay
    # shipped, #1787.)
    for declared_unshipped in ("peek", "posture"):
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
    # dismiss rule (Esc / scrim → anchor) is enforced by the host. The memory
    # review drawer (#1793) registers the same way.
    script = _host_script(html)
    assert "register('vault'" in script
    assert "vault" in SHIPPED_OVERLAY_OCCUPANTS
    assert "memory" in SHIPPED_OVERLAY_OCCUPANTS

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


# ---------------------------------------------------------------------------
# AC (#2172): capture.open / ⌘N mounts the capture occupant on cold_start
# ---------------------------------------------------------------------------


def _cold_start_orientation() -> dict:
    """Minimal orientation payload that resolves to cold_start (absent leave_point)."""
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


def test_capture_open_mounts_capture_on_entry_surface() -> None:
    """capture.open / ⌘N mounts the capture occupant on the cold_start surface.

    Before #2172 the orientation overlay substrate omitted the capture modal
    markup and script, so overlayHost.mount('capture') was a silent no-op on
    the entry surface.  This test confirms the occupant is now registered.
    """
    # Pure model: capture.open mounts the capture occupant (unchanged
    # contract; this was already true in the pure model; the bug was in the
    # rendered substrate not including the modal/script).
    assert "capture" in SHIPPED_OVERLAY_OCCUPANTS
    assert KEYBOARD_MAP["meta+n"] == "capture.open"
    state = apply_intent(_state(), "capture.open")
    assert state.stack == ("capture",)

    # Rendered cold_start substrate: the capture modal occupant must be present
    # so that overlayHost.mount('capture') is no longer a silent no-op.
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_cold_start_orientation(),
    )
    assert 'data-entry-state="cold_start"' in html

    # The capture modal DOM element ships with the orientation substrate.
    assert 'data-region="capture-modal"' in html
    assert 'data-region="capture-input"' in html

    # The capture controller registers the occupant on the host so ⌘N mounts
    # a real governed surface, not a silent no-op.
    assert "overlayHost.register('capture'" in html

    # The verb-line capture.open link routes through the host mount.
    assert "overlayHost.mount('capture')" in html

    # The host's ⌘N handler is present (unchanged from the workspace shell).
    host_script_m = re.search(
        r"/\* overlay-host-controller \*/(.*?)/\* /overlay-host-controller \*/",
        html,
        re.S,
    )
    assert host_script_m, "overlay-host-controller script must render"
    assert "'capture'" in host_script_m.group(1)
