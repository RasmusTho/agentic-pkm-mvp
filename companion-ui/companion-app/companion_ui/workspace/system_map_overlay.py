"""System map overlay — pull-based surface index (#1787, SEP-05).

Implements ``docs/SYSTEM_ENTRY_POINT/SYSTEM_MAP_OVERLAY.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Resolved Q4 — system map placement, §Surface composition (NORMATIVE table),
§Overlay-grammar rule) and ``docs/COMPANION_UI_PRODUCT_SPEC.md`` (the
Find / Reorient / Resurface / Act mode model).

One place from which the whole companion is legible — and nothing more:

- The map is a **renderer/router index (Projection)**: the entry-point center
  node plus one node per composition-table surface, each showing the
  surface's product mode, how it is reached, how it returns, and its truthful
  shipped/new status. The map re-classifies nothing — node statuses mirror
  the spec table, never local judgment.
- Clicking a shipped surface's node routes to that surface through its
  **existing** affordance (host mount, ``vaultBrowser.focus()``, pane focus).
  The map emits no new intents and never navigates: routing dismisses the map
  back to the anchor first (overlay grammar — no route reset, no data loss).
- Nodes for not-yet-shipped surfaces are present but visibly inert with their
  status — no dead affordances pretending to work. Parked surfaces (context
  lane / place band, spec §Parked Q15–Q16) appear only as a parked note and
  never as nodes; the reserved intents stay unimplemented.
- The map is **pull-based**: it never auto-opens, never badges, never
  surfaces unbidden. It mounts on the shared overlay host (#1785) as the
  declared ``map`` occupant, opened only by an explicit ``map.open``
  affordance (topbar icon; calm affordance in ``cold_start`` / ``no_vault``).

Like ``overlay_host.py``, the pure model in this module is the contract the
in-page controller (:func:`system_map_overlay_script`) mirrors; tests assert
both. Nothing here performs I/O.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field

from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,
)

# The overlay-host id this surface occupies (declared in
# overlay_host.DECLARED_OVERLAYS; shipped via SHIPPED_OVERLAY_OCCUPANTS).
SYSTEM_MAP_OVERLAY_ID = "map"

# The four user-facing product modes (docs/COMPANION_UI_PRODUCT_SPEC.md
# §Mode Model). Local-UI surfaces the mode model does not classify carry no
# mode and render the truthful "local-ui" chip instead of an invented one.
PRODUCT_MODES: tuple[str, ...] = ("find", "reorient", "resurface", "act")
LOCAL_UI_MODE = "local-ui"

# Truthful status vocabulary, mirroring the spec's composition-table Status
# column: fully shipped, partially shipped (a real seam exists but the
# surface's own task has not landed), or entirely new.
NODE_STATUSES: tuple[str, ...] = ("shipped", "partial", "new")

# Parked surfaces (spec §Parked, Q15–Q16): never nodes, never reachable; the
# reserved intents (`context.open`, `location.enable`) are not implementable.
PARKED_SURFACES: tuple[str, ...] = ("context_lane", "place_band")

# The declared intents routable nodes emit — all existing spec vocabulary
# (§Intent vocabulary); the map introduces none. The Panel rail routes by
# focusing the shipped pane and therefore emits no intent. The governance
# index node routes via receipts.open (its counts live on the receipts surface,
# #2246, TELEMETRY_RELOCATION-02).
ROUTE_INTENTS: dict[str, str] = {
    "anchor": "overlay.dismiss",
    "vault": "vault.open",
    "palette": "cmd.open",
    "memory": "memory.open",
    "capture": "capture.open",
    "receipts": "receipts.open",
    "governance": "receipts.open",
    "settings": "settings.open",
    # Operator/diagnostics layer (#2447, CUIDR-04): the operator drawer is no
    # longer a free-floating front-edge pill — it is reached from the System
    # Map as the operator layer. The drawer carries all runtime/diagnostic
    # telemetry (runtime status, freshness, as-of) that left the top edge.
    "operator": "operator.open",
}

# Surfaces the map controller can route to via an existing affordance.
_ROUTABLE_SURFACE_IDS: tuple[str, ...] = (
    "anchor",
    "vault",
    "panel",
    "palette",
    "memory",
    "capture",
    "receipts",
    "governance",
    "settings",
    "operator",
)

# The entry-point center node (issue #1787: "the entry-point center node plus
# one node per composition-table surface").
MAP_CENTER_NAME = "Entry point · the document anchor"
MAP_CENTER_SUB = (
    "cold start → orientation (latency ladder) → unified shell → any surface → back"
)


@dataclass(frozen=True)
class MapNode:
    """One composition-table surface as the map renders it.

    Pure data mirroring the spec's NORMATIVE composition table — the map is a
    Projection and decides nothing: a parked surface can never become a node,
    and only a shipped surface can be routable.
    """

    surface_id: str
    name: str
    modes: tuple[str, ...]
    reached: str
    returns: str
    status: str
    status_note: str
    routable: bool = field(default=False)

    def __post_init__(self) -> None:
        if self.surface_id in PARKED_SURFACES:
            raise ValueError(
                f"parked surface {self.surface_id!r} must not render as a node "
                f"(spec §Parked, Q15–Q16)"
            )
        if not set(self.modes) <= set(PRODUCT_MODES):
            raise ValueError(
                f"{self.surface_id}: undeclared product mode in {self.modes!r}; "
                f"declared: {PRODUCT_MODES}"
            )
        if self.status not in NODE_STATUSES:
            raise ValueError(
                f"{self.surface_id}: undeclared status {self.status!r}; "
                f"declared: {NODE_STATUSES}"
            )
        if self.routable and self.status != "shipped":
            raise ValueError(
                f"{self.surface_id}: only a shipped surface may route — a "
                f"{self.status!r} node must stay inert (no dead affordances)"
            )
        if self.routable and self.surface_id not in _ROUTABLE_SURFACE_IDS:
            raise ValueError(
                f"{self.surface_id}: no existing affordance routes to this "
                f"surface from the map"
            )

    @property
    def mode_attr(self) -> str:
        return " ".join(self.modes) if self.modes else LOCAL_UI_MODE


# One node per composition-table surface (spec §Surface composition,
# NORMATIVE table), parked rows excluded. Statuses and reached/returns text
# mirror the table; modes follow docs/COMPANION_UI_PRODUCT_SPEC.md.
MAP_SURFACES: tuple[MapNode, ...] = (
    MapNode(
        surface_id="orientation",
        name="Orientation re-entry",
        modes=("reorient",),
        reached="the entry substrate (orienting) — reached by returning, never by opening",
        returns="becomes the shell on resume",
        status="shipped",
        status_note="shipped — re-entry surface with its mist treatments",
    ),
    MapNode(
        surface_id="anchor",
        name="Document anchor (active note)",
        modes=("find", "reorient", "resurface", "act"),
        reached="the shell's primary column",
        returns="— (it is the anchor)",
        status="shipped",
        status_note="shipped — the canonical note body every overlay returns to",
        routable=True,
    ),
    MapNode(
        surface_id="vault",
        name="Vault Browser",
        modes=("find",),
        reached="left pane; modal in narrow mode",
        returns="re-anchors the shell",
        status="shipped",
        status_note="shipped — browse/find (Projection); queue_review is the one governed handoff",
        routable=True,
    ),
    MapNode(
        surface_id="panel",
        name="Panel rail",
        modes=("act",),
        reached="right rail (the shipped agent rail)",
        returns="stays on anchor",
        status="shipped",
        status_note="shipped — proposal → confirmation → receipt (governed)",
        routable=True,
    ),
    MapNode(
        surface_id="palette",
        name="⌘K Panel command palette",
        modes=("act",),
        reached="command overlay (⌘K · cmd.open)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — a Panel presentation, not new authority",
        routable=True,
    ),
    MapNode(
        surface_id="chat_rail",
        name="Chat rail slot",
        modes=("find", "act"),
        reached="margin rail slot (bottom sheet when narrow)",
        returns="dismisses to anchor",
        status="partial",
        status_note="slot defined by the spec; occupant owned by the canvas-chat lane",
    ),
    MapNode(
        surface_id="suggestions",
        name="Canvas suggestion blocks",
        modes=("act",),
        reached="staged block inside the document",
        returns="stays on anchor",
        status="shipped",
        status_note="shipped — proposal → body-edit lane (no receipt)",
    ),
    MapNode(
        surface_id="memory",
        name="Memory candidate review drawer",
        modes=("reorient", "act"),
        reached="right drawer overlay (memory.open)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — governed review outcomes over the candidate drawer",
        routable=True,
    ),
    MapNode(
        surface_id="peek",
        name="Source peek",
        modes=("find",),
        reached="anchored popover (source.peek)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — provenance lines are live; no map route exists on no-vault/error renders",
    ),
    MapNode(
        surface_id="posture",
        name="Posture emphasis switch",
        modes=(),
        reached="centered overlay (posture.open)",
        returns="anchor preserved with carry-forward set",
        status="new",
        status_note="new — not yet shipped",
    ),
    MapNode(
        surface_id="map",
        name="System map overlay",
        modes=("reorient",),
        reached="topbar + cold-start affordance (map.open)",
        returns="dismisses to anchor; nodes route to surfaces",
        status="shipped",
        status_note="shipped — you are here",
    ),
    MapNode(
        surface_id="settings",
        name="Settings drawer",
        modes=(),
        reached="right drawer overlay (settings.open)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — Local UI preferences; canonical hash untouched",
        routable=True,
    ),
    MapNode(
        surface_id="tts",
        name="TTS read-back",
        modes=(),
        reached="per-surface Listen control → plan popover",
        returns="stays on anchor",
        status="shipped",
        status_note="shipped — local listening; the plan is inspected before audio",
    ),
    MapNode(
        surface_id="capture",
        name="Capture",
        modes=("act",),
        reached="top modal (⌘N · capture.open)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — governed append to the vault inbox",
        routable=True,
    ),
    MapNode(
        surface_id="receipts",
        name="Receipts / history",
        modes=("act", "reorient"),
        reached="top modal (receipts.open)",
        returns="dismisses to anchor",
        status="shipped",
        status_note="shipped — runtime receipts rendered verbatim, never invented",
        routable=True,
    ),
    MapNode(
        surface_id="governance",
        name="Governance counts",
        modes=("act", "reorient"),
        reached="receipts surface (receipts.open) — counts header row on the receipts modal",
        returns="dismisses to anchor via receipts surface",
        status="shipped",
        status_note="shipped — projection index; routes via receipts.open",
        routable=True,
    ),
    MapNode(
        surface_id="resurface_rail",
        name="Resurface candidates",
        modes=("resurface",),
        reached="shell resurface rail mode (_render_resurface_mode); navigated in shell, not via overlayHost.mount",
        returns="stays in shell",
        status="shipped",
        status_note="shipped — read-only index node; rail is navigated in shell, never via overlay route",
    ),
    MapNode(
        surface_id="guidance",
        name="Guidance layer",
        modes=(),
        reached="ⓘ toggle on topbar, overlay heads, re-entry card",
        returns="cross-cutting; persists nothing",
        status="shipped",
        status_note="shipped — cross-cutting local UI toggle",
    ),
    MapNode(
        surface_id="operator",
        name="Operator diagnostics",
        modes=(),
        reached="System map (operator.open) — the operator layer",
        returns="dims but does not dismiss; returns to anchor",
        status="shipped",
        status_note=(
            "shipped — operator/diagnostic telemetry "
            "(runtime status, freshness, as-of) moved off the front edge to "
            "this operator layer; not a daily-use surface"
        ),
        routable=True,
    ),
)


def routable_surface_ids() -> tuple[str, ...]:
    """The surfaces the map controller can route to via existing affordances."""
    return tuple(node.surface_id for node in MAP_SURFACES if node.routable)


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _node_html(
    node: MapNode,
    *,
    available: bool,
    open_loops_count: int = 0,
) -> str:
    """Render one surface node.

    Routable nodes whose route is live on this page render as buttons that
    route through the controller; everything else renders as a plainly
    non-interactive article carrying its truthful reach and status — present,
    legible, inert.

    ``open_loops_count`` — when non-zero and the node is the memory surface,
    renders a read-only index count annotation (data-testid=
    "map-memory-node-open-loops-count", data-authority="read-only-projection").
    Omitted when zero or absent (no zero-state — open loops belong to a
    trajectory; legitimately none on first contact).
    """
    mode = _e(node.mode_attr)
    reach = (
        f'<p class="map-node-reach" data-testid="system-map-node-reach">'
        f"reached: {_e(node.reached)} · returns: {_e(node.returns)}</p>"
    )
    status = (
        f'<p class="map-node-status" data-testid="system-map-node-status" '
        f'data-status="{node.status}">{_e(node.status_note)}</p>'
    )
    head = (
        f'<span class="map-node-name">{_e(node.name)}</span>'
        f'<span class="map-node-mode">{mode}</span>'
    )
    # Relocated open-loops index count on the memory map node (#2247,
    # TELEMETRY_RELOCATION-03): omit when zero or absent (no zero-state).
    # data-authority="read-only-projection" — projection only, no mutation.
    open_loops_html = (
        f'<p class="map-node-open-loops-count" '
        f'data-testid="map-memory-node-open-loops-count" '
        f'data-authority="read-only-projection">'
        f'{open_loops_count} open loop{"s" if open_loops_count != 1 else ""}</p>'
        if node.surface_id == "memory" and open_loops_count > 0
        else ""
    )
    if node.routable and available:
        intent = ROUTE_INTENTS.get(node.surface_id)
        intent_attr = f' data-intent="{intent}"' if intent else ""
        return (
            f'<button type="button" class="map-node" data-testid="system-map-node" '
            f'data-surface-id="{node.surface_id}" data-mode="{mode}" '
            f'data-status="{node.status}" data-routable="true"{intent_attr} '
            f"onclick=\"systemMap.route('{node.surface_id}')\">"
            f'<span class="map-node-head">{head}</span>{reach}{status}'
            f'{open_loops_html}</button>'
        )
    unavailable = (
        '<p class="map-node-unavailable" data-testid="system-map-node-unavailable">'
        "not openable from this entry state</p>"
        if node.routable and not available
        else ""
    )
    current = ' data-current="true"' if node.surface_id == SYSTEM_MAP_OVERLAY_ID else ""
    return (
        f'<article class="map-node map-node--inert" data-testid="system-map-node" '
        f'data-surface-id="{node.surface_id}" data-mode="{mode}" '
        f'data-status="{node.status}" data-routable="false"{current} '
        f'aria-disabled="true">'
        f'<span class="map-node-head">{head}</span>{reach}{status}'
        f'{unavailable}{open_loops_html}</article>'
    )


def system_map_overlay_markup(
    *,
    available_routes: tuple[str, ...] = (),
    orientation_freshness: str = "",
    orientation_as_of: str = "",
    orientation_trace_id: str = "",
    open_loops_count: int = 0,
) -> str:
    """The system map overlay markup — closed by default, never unbidden.

    ``available_routes`` declares which routable surfaces are actually live on
    the page being rendered (the workspace shell offers them all; the entry
    surfaces offer only the routes that truthfully exist there, e.g. the
    Vault Browser as the declared ``cold_start → shell_active`` path).
    Undeclared ids are rejected — availability is a contract, not a hint.

    ``orientation_freshness``, ``orientation_as_of``, ``orientation_trace_id``
    carry the relocated telemetry from the removed "Re-entry snapshot" meta
    row (#2171/#2245). When present and non-empty they render as a read-only
    projection row in the entry-point center node. When absent nothing renders
    — no placeholder, no zero-state row.

    ``open_loops_count`` — when non-zero, renders a read-only index count
    annotation on the memory map node (#2247, TELEMETRY_RELOCATION-03).
    Omitted when zero or absent (no zero-state).
    """
    declared = routable_surface_ids()
    for surface_id in available_routes:
        if surface_id not in declared:
            raise ValueError(
                f"undeclared route {surface_id!r}; routable surfaces: {declared}"
            )
    available = frozenset(available_routes)
    nodes = "".join(
        _node_html(node, available=node.surface_id in available, open_loops_count=open_loops_count)
        for node in MAP_SURFACES
    )
    parked = " ".join(PARKED_SURFACES)
    # Relocated telemetry: freshness/as_of/trace_id render only when the
    # orientation payload supplies them (zero-state = omit, no placeholder).
    # data-authority="read-only-projection" — no mutation affordance.
    _f = orientation_freshness.strip()
    _a = orientation_as_of.strip()
    _t = orientation_trace_id.strip()
    entry_point_meta_html = (
        f"""
      <div class="map-center-meta" data-testid="map-entry-point-freshness"
        data-authority="read-only-projection"
        data-region="map-entry-point-meta">
        <span data-testid="map-entry-point-meta-freshness"><code>{_html.escape(_f)}</code></span>
        {(f'<span data-testid="map-entry-point-meta-as-of">{_html.escape(_a)}</span>') if _a else ''}
        {(f'<span data-testid="map-entry-point-meta-trace-id"><code>{_html.escape(_t)}</code></span>') if _t else ''}
      </div>"""
        if (_f or _a or _t)
        else ""
    )
    return f"""
  <!-- system-map-overlay start -->
  <!-- System map overlay (#1787, SEP-05) — a renderer/router index
       (Projection) over the spec's composition table. Pull-based: opened
       only by an explicit map.open affordance; never auto-opens, never
       badges. Dismissal routes through the shared overlay host back to the
       document anchor — no route reset, no data loss. -->
  <style>
    .system-map-overlay {{
      background: var(--bg-surface, #0c1220);
      border: 1px solid var(--border-strong, #1e3050);
      border-radius: 8px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.5);
      display: none;
      left: 50%;
      max-height: 88vh;
      overflow-y: auto;
      padding: 18px 20px 24px;
      position: fixed;
      top: 50%;
      transform: translate(-50%, -50%);
      width: min(960px, 94vw);
      z-index: 960;
    }}
    .system-map-overlay[data-open="true"] {{ display: block; }}
    .system-map-head {{
      align-items: flex-start; display: flex; gap: 12px;
      justify-content: space-between;
    }}
    .system-map-kicker {{
      color: var(--fg-3, #3d5570); font-size: 11px; letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .system-map-title {{ color: var(--fg-1, #dce8f0); font-size: 17px; margin: 2px 0 0; }}
    .system-map-close {{
      background: none; border: 1px solid var(--border, #152030);
      border-radius: 4px; color: var(--fg-2, #7a9ab8); cursor: pointer;
      font-size: 16px; line-height: 1; padding: 4px 9px;
    }}
    .system-map-note {{ color: var(--fg-2, #7a9ab8); font-size: 12px; margin: 10px 0 14px; }}
    .map-center {{
      background: rgba(212, 168, 67, 0.07);
      border: 1px dashed var(--accent, #d4a843); border-radius: 6px;
      margin: 0 0 14px; padding: 12px; text-align: center;
    }}
    .map-center-name {{ color: var(--accent, #d4a843); font-size: 15px; }}
    .map-center-sub {{ color: var(--fg-2, #7a9ab8); font-size: 12px; margin-top: 4px; }}
    .map-center-meta {{
      color: var(--fg-3, #3d5570); font-family: var(--font-mono, monospace);
      font-size: 10px; margin-top: 6px; display: flex; gap: 8px;
      justify-content: center; flex-wrap: wrap;
    }}
    .map-center-meta code {{ font-family: inherit; }}
    .system-map-grid {{
      display: grid; gap: 10px; grid-template-columns: repeat(2, 1fr);
    }}
    @media (max-width: 720px) {{ .system-map-grid {{ grid-template-columns: 1fr; }} }}
    .map-node {{
      background: var(--bg-raised, #111a2e);
      border: 1px solid var(--border, #152030); border-radius: 6px;
      color: var(--fg-1, #dce8f0); display: block; font: inherit;
      padding: 10px 12px; text-align: left; width: 100%;
    }}
    button.map-node {{ cursor: pointer; }}
    button.map-node:hover {{ border-color: var(--accent, #d4a843); }}
    .map-node--inert {{ opacity: 0.72; }}
    .map-node-head {{ display: flex; gap: 8px; justify-content: space-between; }}
    .map-node-name {{ color: var(--fg-1, #dce8f0); font-size: 13px; }}
    .map-node-mode {{
      color: var(--fg-3, #3d5570); font-family: var(--font-mono, monospace);
      font-size: 10px; letter-spacing: 0.06em; text-transform: uppercase;
      white-space: nowrap;
    }}
    .map-node-reach {{ color: var(--fg-2, #7a9ab8); font-size: 11px; margin: 6px 0 0; }}
    .map-node-status {{
      color: var(--fg-3, #3d5570); font-family: var(--font-mono, monospace);
      font-size: 10px; margin: 4px 0 0;
    }}
    .map-node-status[data-status="shipped"] {{ color: var(--cyan, #00d4e8); }}
    .map-node-unavailable {{
      color: var(--amber, #f09030); font-size: 10px; margin: 4px 0 0;
    }}
    .map-node-open-loops-count {{
      color: var(--cyan, #00d4e8); font-family: var(--font-mono, monospace);
      font-size: 10px; margin: 4px 0 0;
    }}
    .system-map-parked {{
      border-top: 1px dashed var(--border, #152030);
      color: var(--fg-3, #3d5570); font-size: 11px; margin: 14px 0 0;
      padding-top: 10px;
    }}
  </style>
  <div class="system-map-overlay" id="system-map-overlay"
    data-testid="system-map-overlay" data-region="system-map-overlay"
    data-overlay-id="{SYSTEM_MAP_OVERLAY_ID}" data-open="false"
    data-authority="projection"
    role="dialog" aria-modal="false" aria-hidden="true"
    aria-label="System map">
    <header class="system-map-head">
      <div>
        <span class="system-map-kicker">System map</span>
        <h2 class="system-map-title">Every surface, one index</h2>
      </div>
      {guidance_toggle_markup('map')}
      <button type="button" class="system-map-close"
        data-testid="system-map-close" data-intent="overlay.dismiss"
        aria-label="Close and return to the document"
        onclick="overlayHost.dismiss()">&times;</button>
    </header>
    {guidance_callout_markup('map')}
    <p class="system-map-note" data-testid="system-map-note">An index of the
      companion's surfaces — it renders and routes, nothing more. Everything
      opens over the document anchor and returns to it; nothing here
      re-classifies anything.</p>
    <div class="map-center" data-testid="system-map-center"
      data-region="system-map-center">
      <div class="map-center-name">{_e(MAP_CENTER_NAME)}</div>
      <div class="map-center-sub">{_e(MAP_CENTER_SUB)}</div>
      {entry_point_meta_html}
    </div>
    <div class="system-map-grid" data-testid="system-map-grid">
      {nodes}
    </div>
    <p class="system-map-parked" data-testid="system-map-parked-note"
      data-parked-surfaces="{parked}">Parked (spec §Parked, Q15–Q16): the
      context lane and the place band have no grounded source yet and are not
      reachable from anywhere — including here.</p>
  </div>
  <!-- system-map-overlay end -->"""


def system_map_overlay_script() -> str:
    """The in-page controller mirroring the pure model above.

    Must be emitted after :func:`overlay_host.overlay_host_script`: the map
    registers as the host's ``map`` occupant so mount/dismiss (Esc, scrim,
    close button, every ``map.open`` affordance) is host-owned in one place.
    The controller never mounts the map itself (pull-based — only explicit
    affordances do), never navigates, and routes to shipped surfaces only
    through their existing affordances.
    """
    return """
  <script>
  /* system-map-controller */
  (function() {
    var overlay = document.getElementById('system-map-overlay');
    if (!overlay || !window.overlayHost) { return; }
    function setOpen(open) {
      overlay.setAttribute('data-open', open ? 'true' : 'false');
      overlay.setAttribute('aria-hidden', open ? 'false' : 'true');
    }
    // Host occupant registration only — nothing in this controller ever
    // mounts the map; opening is owned by explicit map.open affordances.
    window.overlayHost.register('map', {
      open: function() { setOpen(true); },
      close: function() { setOpen(false); }
    });
    function focusRegion(selector) {
      var el = document.querySelector(selector);
      if (!el) { return; }
      if (el.scrollIntoView) { el.scrollIntoView({block: 'nearest'}); }
      if (el.focus) { el.focus(); }
    }
    window.systemMap = {
      // Routing composes existing surfaces: dismiss the map back to the
      // document anchor first (overlay grammar — no route reset, no data
      // loss), then open/focus the target via its own shipped affordance.
      route: function(id) {
        window.overlayHost.dismiss();
        // Focus selectors use unquoted CSS attribute values so the script
        // never embeds another surface's quoted test markers.
        if (id === 'anchor') {
          focusRegion('[data-region=document-column], [data-region=note-body]');
          return;
        }
        if (id === 'vault') {
          if (window.vaultBrowser) { window.vaultBrowser.focus(); return; }
          focusRegion('[data-testid=workspace-orientation-vault-entry]');
          return;
        }
        if (id === 'panel') {
          focusRegion('[data-testid=workspace-agent-rail]');
          return;
        }
        if (id === 'palette') { window.overlayHost.mount('cmd'); return; }
        if (id === 'memory') { window.overlayHost.mount('memory'); return; }
        if (id === 'capture') { window.overlayHost.mount('capture'); return; }
        if (id === 'receipts') { window.overlayHost.mount('receipts'); return; }
        if (id === 'governance') { window.overlayHost.mount('receipts'); return; }
        if (id === 'settings') { window.overlayHost.mount('settings'); return; }
        // Operator layer (#2447): the operator drawer is the home for the
        // runtime/diagnostic telemetry that left the front edge.
        if (id === 'operator') {
          if (window.companionOperator) { window.companionOperator.open(); }
          return;
        }
      }
    };
  })();
  /* /system-map-controller */
  </script>"""
