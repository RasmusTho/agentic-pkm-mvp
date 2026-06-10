"""Shared overlay host + unified-topbar vocabulary for the Companion UI shell.

Implements SEP-03 (#1785) from
``docs/SYSTEM_ENTRY_POINT/UNIFIED_TOPBAR_AND_OVERLAY_HOST.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Overlay-grammar rule, §Keyboard map, §Data-attribute vocabulary) and
``companion-ui/docs/OVERLAY_GRAMMAR.md``.

One place to mount, one rule to obey:

- Every overlay opens **over** the document anchor and dismisses **back to
  it** — no route reset, no data loss, no erased cognitive tension (staged
  suggestions and open-loop counts survive open/dismiss cycles).
- Only declared overlays can mount. The declared registry is exactly the
  spec's ``shell_active ⇄ overlay(…)`` set; adding an id is a spec change.
- Declared-but-unshipped overlays are **inert**: mounting them is a graceful
  no-op (never an invented surface, never a dead affordance), until the task
  that ships the surface registers a real occupant.
- Keyboard map (spec §Keyboard map): ``⌘K`` → ``cmd.open``, ``⌘N`` →
  ``capture.open``, ``Esc`` → ``overlay.dismiss``. A fuller keyboard model is
  deferred (package Q14).

The pure model in this module is the contract the in-page controller
(:func:`overlay_host_script`) mirrors; tests assert both. Like
``entry_state.py`` (#1783), nothing here performs I/O.
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field, replace

# The spec's declared overlay set, verbatim from the `shell_active ⇄
# overlay(cmd|vault|memory|peek|posture|map|settings|capture|receipts|tts|help)`
# transition (SYSTEM_ENTRY_POINT_SPEC.md §Allowed transitions). Adding or
# removing an id is a change to that spec.
DECLARED_OVERLAYS: tuple[str, ...] = (
    "cmd",
    "vault",
    "memory",
    "peek",
    "posture",
    "map",
    "settings",
    "capture",
    "receipts",
    "tts",
    "help",
)

# Overlays with a shipped occupant that actually mounts on the host today.
# #1785 scope: the narrow-mode vault-browser modal is treated as an
# overlay-host occupant for the dismiss rule. The ⌘N capture modal (#1791,
# ``capture_modal.py``) is the second shipped occupant. Later SEP tasks
# (palette #1786, map #1787, settings #1789, memory drawer #1793, receipts
# #1794) extend this tuple when their surfaces land.
SHIPPED_OVERLAY_OCCUPANTS: tuple[str, ...] = ("vault", "capture")

# Keyboard map (spec §Keyboard map) — exactly ⌘K / ⌘N / Esc; fuller model
# deferred to package Q14.
KEYBOARD_MAP: dict[str, str] = {
    "meta+k": "cmd.open",
    "meta+n": "capture.open",
    "escape": "overlay.dismiss",
}

# Which overlay each opening intent targets on the host. `overlay.dismiss`
# is a host action, not a mount target.
INTENT_OVERLAY_TARGETS: dict[str, str] = {
    "cmd.open": "cmd",
    "capture.open": "capture",
}

# The five canonical postures (POSTURE_TRANSITIONS.md). The posture pill is
# Local UI **rendering only** in this slice: the switch overlay (`posture`)
# has not shipped, so the server-declared default is the package prototype's
# initial emphasis and no `posture.open` affordance is rendered.
POSTURE_EMPHASES: tuple[str, ...] = (
    "orientation",
    "exploration",
    "synthesis",
    "review",
    "recovery",
)
DEFAULT_POSTURE_EMPHASIS: str = "recovery"

# Topbar surface-icon vocabulary (issue #1785 scope) and the subset whose
# surfaces have shipped. No dead affordances: icons for unshipped surfaces
# are absent until their task ships.
TOPBAR_SURFACES: tuple[str, ...] = (
    "vault",
    "command",
    "map",
    "settings",
    "capture",
    "receipts",
    "help",
)
SHIPPED_TOPBAR_SURFACES: tuple[str, ...] = ("vault", "help")

# Coarse derived postures the vault-status dot may render. Detailed health
# stays with /api/status (runtime popover); the dot never exposes slices.
COARSE_VAULT_POSTURES: tuple[str, ...] = ("ok", "degraded", "blocked", "unavailable")


@dataclass(frozen=True)
class OverlayHostState:
    """The anchor context the overlay host must preserve across mounts.

    Everything except ``stack`` is the document-anchor context: the overlay
    grammar requires that mounting and dismissing overlays can never change
    it. :func:`mount` and :func:`dismiss` only ever replace ``stack``, so
    preservation holds by construction.
    """

    anchor_note_path: str = ""
    route: str = ""
    scroll_owner: str = "note-body"
    rail_state: str = "closed"
    staged_suggestion_ids: tuple[str, ...] = field(default=())
    open_loop_count: int = 0
    stack: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for overlay_id in self.stack:
            if overlay_id not in DECLARED_OVERLAYS:
                raise ValueError(
                    f"undeclared overlay {overlay_id!r} cannot mount; "
                    f"declared: {DECLARED_OVERLAYS}"
                )
        if len(set(self.stack)) != len(self.stack):
            raise ValueError(f"overlay stack must not repeat ids: {self.stack}")


def mount(
    state: OverlayHostState,
    overlay_id: str,
    *,
    occupants: tuple[str, ...] = SHIPPED_OVERLAY_OCCUPANTS,
) -> OverlayHostState:
    """Mount a declared overlay on the host; topmost is last.

    Undeclared ids are rejected (``ValueError``). Declared overlays without a
    registered occupant are inert: the call is a graceful no-op so reserved
    shortcuts and routes never invent a surface. ``occupants`` defaults to
    the shipped set; later SEP tasks register their surfaces by extending it.
    """
    if overlay_id not in DECLARED_OVERLAYS:
        raise ValueError(
            f"undeclared overlay {overlay_id!r} cannot mount; "
            f"declared: {DECLARED_OVERLAYS}"
        )
    if overlay_id not in occupants:
        return state
    new_stack = tuple(o for o in state.stack if o != overlay_id) + (overlay_id,)
    return replace(state, stack=new_stack)


def dismiss(state: OverlayHostState) -> OverlayHostState:
    """``overlay.dismiss`` — return to the document anchor.

    Pops only the topmost overlay. The anchor context (URL/route, scroll
    ownership, anchor identity, rail state, staged suggestions, open-loop
    counts) is untouched by construction — no route reset, no data loss.
    Dismissing with nothing mounted is a calm no-op.
    """
    if not state.stack:
        return state
    return replace(state, stack=state.stack[:-1])


def keyboard_intent(key: str) -> str | None:
    """Resolve a normalized key chord to its declared intent, or ``None``."""
    return KEYBOARD_MAP.get(key)


def apply_intent(state: OverlayHostState, intent: str) -> OverlayHostState:
    """Apply a declared keyboard-map intent to the host state.

    ``overlay.dismiss`` pops the topmost overlay; opening intents mount their
    declared target (inert while the target surface is unshipped). Intents
    outside the declared map are rejected.
    """
    if intent == "overlay.dismiss":
        return dismiss(state)
    target = INTENT_OVERLAY_TARGETS.get(intent)
    if target is None:
        raise ValueError(
            f"undeclared keyboard intent {intent!r}; "
            f"declared: {sorted(set(KEYBOARD_MAP.values()))}"
        )
    return mount(state, target)


def coarse_vault_posture(*, vault_state: str, primary_posture: str) -> str:
    """Derive the coarse posture for the topbar vault-status dot.

    The dot renders **only** a value from :data:`COARSE_VAULT_POSTURES`;
    detailed health slices stay with ``/api/status``. Out-of-contract inputs
    degrade coarsely instead of inventing detail.
    """
    if vault_state == "unreachable":
        return "unavailable"
    if vault_state == "unresolved":
        return "degraded"
    if primary_posture in COARSE_VAULT_POSTURES:
        return primary_posture
    return "degraded"


def overlay_host_markup(*, anchor_note_path: str = "") -> str:
    """The shared overlay-host layer markup (scrim + mount slot).

    A single overlay layer in the shell that later surfaces mount on. It sits
    beside the document column — overlays augment the anchor, never replace
    it (OVERLAY_GRAMMAR.md §Structural rules).
    """
    anchor = _html.escape(anchor_note_path, quote=True)
    declared = " ".join(DECLARED_OVERLAYS)
    shipped = " ".join(SHIPPED_OVERLAY_OCCUPANTS)
    return f"""
  <!-- Shared overlay host (#1785, SEP-03) — the single mount/dismiss
       substrate for shell overlays. Esc and the scrim dismiss the topmost
       overlay back to the document anchor; no route reset, no data loss. -->
  <div class="overlay-host" id="workspace-overlay-host"
       data-testid="workspace-overlay-host" data-region="overlay-host"
       data-overlay-open="none" data-overlay-stack=""
       data-anchor-note-path="{anchor}"
       data-declared-overlays="{declared}"
       data-shipped-occupants="{shipped}">
    <div class="overlay-host-scrim" id="workspace-overlay-scrim"
         data-testid="workspace-overlay-scrim" data-active="false"
         onclick="overlayHost.dismiss()" aria-hidden="true"></div>
    <div class="overlay-host-mount" id="workspace-overlay-mount"
         data-testid="workspace-overlay-mount"></div>
  </div>"""


def overlay_host_script() -> str:
    """The in-page overlay-host controller mirroring the pure model above.

    Must be emitted after ``window.vaultBrowser`` is defined: the narrow-mode
    vault-browser modal is the host's first shipped occupant, and its Esc
    handling is owned here (one Esc owner for host occupants).
    """
    return """
  <script>
  /* overlay-host-controller */
  (function() {
    var host = document.getElementById('workspace-overlay-host');
    var scrim = document.getElementById('workspace-overlay-scrim');
    if (!host) { return; }
    var DECLARED = (host.getAttribute('data-declared-overlays') || '').split(' ');
    var occupants = {};
    var stack = [];
    function assertDeclared(id) {
      if (DECLARED.indexOf(id) === -1) {
        throw new Error('undeclared overlay: ' + id);
      }
    }
    function sync() {
      host.setAttribute('data-overlay-open', stack.length ? stack[stack.length - 1] : 'none');
      host.setAttribute('data-overlay-stack', stack.join(' '));
      if (scrim) { scrim.setAttribute('data-active', stack.length ? 'true' : 'false'); }
    }
    window.overlayHost = {
      register: function(id, adapter) {
        assertDeclared(id);
        occupants[id] = adapter || {};
      },
      mount: function(id) {
        assertDeclared(id);
        var occ = occupants[id];
        // Declared but unshipped: inert no-op — never invent a surface.
        if (!occ) { return; }
        var at = stack.indexOf(id);
        if (at !== -1) { stack.splice(at, 1); }
        stack.push(id);
        sync();
        if (occ.open) { occ.open(); }
      },
      dismiss: function() {
        // overlay.dismiss — return to the document anchor. Pops only the
        // topmost overlay and updates host bookkeeping. It never navigates
        // and never touches the document column, so the URL, scroll
        // ownership, anchor identity, staged suggestions, and open-loop
        // counts are preserved by construction.
        if (!stack.length) { return; }
        var id = stack.pop();
        sync();
        var occ = occupants[id];
        if (occ && occ.close) { occ.close(); }
      },
      notifyClosed: function(id) {
        // An occupant closed itself through its own affordance; keep the
        // host stack truthful without re-running the occupant close hook.
        var at = stack.indexOf(id);
        if (at !== -1) { stack.splice(at, 1); sync(); }
      },
      topmost: function() {
        return stack.length ? stack[stack.length - 1] : null;
      }
    };
    // Keyboard map (SYSTEM_ENTRY_POINT_SPEC.md §Keyboard map):
    //   meta+k -> cmd.open, meta+n -> capture.open, escape -> overlay.dismiss.
    // cmd.open stays inert until the palette surface ships (no dead
    // affordances); capture.open mounts the shipped capture occupant (#1791).
    document.addEventListener('keydown', function(e) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey) {
        var k = String(e.key || '').toLowerCase();
        if (k === 'k') { e.preventDefault(); window.overlayHost.mount('cmd'); return; }
        if (k === 'n') { e.preventDefault(); window.overlayHost.mount('capture'); return; }
      }
      if (e.key === 'Escape') { window.overlayHost.dismiss(); }
    });
    // Shipped occupant: the narrow-mode vault-browser modal (#1785 scope).
    // Its open/close routes through the host so the dismiss rule (Esc /
    // scrim -> anchor) is enforced in one place.
    if (window.vaultBrowser) {
      var rawOpen = window.vaultBrowser.open;
      var rawClose = window.vaultBrowser.close;
      window.overlayHost.register('vault', {
        open: function() { rawOpen(); },
        close: function() { rawClose(); }
      });
      window.vaultBrowser.open = function() { window.overlayHost.mount('vault'); };
      window.vaultBrowser.close = function() {
        rawClose();
        window.overlayHost.notifyClosed('vault');
      };
    }
  })();
  /* /overlay-host-controller */
  </script>"""
