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
# ``capture_modal.py``), the ⌘K Panel command palette (#1786, SEP-04,
# ``panel_palette.py``), the memory candidate review drawer (#1793,
# SEP-09b, ``memory_review_drawer.py``), the read-only receipts history
# modal (#1794, SEP-10, ``receipts_history.py``), the Settings drawer
# (#1789, SEP-07, ``settings_drawer.py``), and the system map overlay
# (#1787, SEP-05, ``system_map_overlay.py``) are shipped occupants.
SHIPPED_OVERLAY_OCCUPANTS: tuple[str, ...] = (
    "vault",
    "capture",
    "cmd",
    "memory",
    "receipts",
    "settings",
    "map",
)

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
    "map.open": "map",
    "memory.open": "memory",
    "receipts.open": "receipts",
    "settings.open": "settings",
    "vault.open": "vault",
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

# Topbar surface-icon vocabulary (issue #1785 scope; `memory` added by #1793
# — the review drawer is reached from the topbar and from the re-entry
# card's unresolved-inspect affordance; `receipts` added by #1794 — the
# read-only history modal is reached from the topbar; `settings` added by
# #1789 — the Settings drawer is reached from the topbar, `settings.open`;
# `map` added by #1787 — the pull-based system map overlay is reached from
# the topbar in every entry state, `map.open`) and the subset whose surfaces
# have shipped. No dead affordances: icons for unshipped surfaces are absent
# until their task ships.
TOPBAR_SURFACES: tuple[str, ...] = (
    "vault",
    "command",
    "map",
    "settings",
    "capture",
    "memory",
    "receipts",
    "help",
)
# CUIDR-04 (#2447): the top edge keeps IDENTITY + ONE primary action
# (Capture, ⌘N). Every other surface launcher is displaced off the topbar into
# the System Map overflow surface (never-clipping), so the bar stops clipping
# its own icons off-screen at ≤1440 px. ``SHIPPED_TOPBAR_SURFACES`` is now the
# truthful set of launchers that actually sit on the topbar — exactly Capture.
SHIPPED_TOPBAR_SURFACES: tuple[str, ...] = ("capture",)
# The launchers that left the topbar; each is reachable via the System Map
# overlay (`map` node routes), never behind the rail or off the viewport edge.
OVERFLOW_TOPBAR_SURFACES: tuple[str, ...] = (
    "vault",
    "map",
    "memory",
    "receipts",
    "settings",
    "help",
)

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


def resolve_deep_link_overlay(
    overlay_id: str | None,
    *,
    occupants: tuple[str, ...] = SHIPPED_OVERLAY_OCCUPANTS,
) -> str | None:
    """Resolve a ``?overlay=<id>`` deep-link request to an auto-mountable id.

    NAV-3 (#2611): a surface may be opened directly by URL. Only a **declared
    and shipped** overlay is honoured — an undeclared id, an empty value, or a
    declared-but-unshipped id (no registered occupant) resolves to ``None`` so
    the page never auto-mounts a dead surface (the #2610 lesson: don't invent a
    mount for an occupant that only registers on a particular shell). The
    returned id, when present, is safe to hand to ``overlayHost.mount`` on load.
    """
    if not overlay_id:
        return None
    candidate = overlay_id.strip()
    if candidate not in DECLARED_OVERLAYS:
        return None
    if candidate not in occupants:
        return None
    return candidate


def overlay_deep_link_boot_script(overlay_id: str | None) -> str:
    """Boot script that auto-mounts a deep-linked overlay on load (NAV-3).

    Returns an empty string unless ``overlay_id`` is an already-resolved,
    declared+shipped id (see :func:`resolve_deep_link_overlay`); callers MUST
    resolve first, so this only ever embeds a known-safe literal. The script
    MUST be emitted **after every occupant-registration script** on the shell
    so ``overlayHost`` and the target occupant both exist by the time it runs
    (#2611, Codex findings on closed PR #2637: a boot emitted before
    ``settings_drawer_script()`` mounted ``?overlay=settings`` before its
    occupant registered, a silent no-op). ``mount`` stays a calm no-op if the
    occupant did not register on this particular shell (declared-but-inert), so
    a deep link to an absent surface degrades calmly instead of erroring.

    Special case ``vault`` (#2645 Codex P2): ``vault`` is a shipped occupant,
    but on desktop the canonical browse surface is the inline LEFT PANE, not
    the modal overlay — raw-mounting ``vault`` opens the narrow fallback modal
    unconditionally and produces a duplicate browse surface, violating the
    single-surface invariant (``test_desktop_browse_does_not_open_duplicate_
    modal``). ``vaultBrowser.focus()`` already encapsulates the wide/narrow
    split established in NAV-3b (#2640): inline pane on desktop, modal fallback
    on narrow. So the vault deep-link routes through ``focus()`` and only falls
    back to a raw ``mount('vault')`` if ``vaultBrowser`` is somehow absent.
    """
    if not overlay_id or overlay_id not in DECLARED_OVERLAYS:
        return ""
    if overlay_id == "vault":
        # Honor the canonical browse affordance (inline pane on desktop, modal
        # on narrow) instead of always opening the modal. focus() is defined on
        # the note shell earlier than this last-emitted boot; the guard keeps
        # it inert if it is absent (e.g. a shell without the vault browser).
        return """
  <script>
  /* overlay-deep-link-boot (NAV-3, #2611) */
  (function() {
    if (window.vaultBrowser) {
      try { window.vaultBrowser.focus(); } catch (err) { /* inert */ }
    } else if (window.overlayHost) {
      try { window.overlayHost.mount('vault'); } catch (err) { /* inert */ }
    }
  })();
  /* /overlay-deep-link-boot */
  </script>"""
    # overlay_id is a fixed member of DECLARED_OVERLAYS — a safe JS literal.
    return f"""
  <script>
  /* overlay-deep-link-boot (NAV-3, #2611) */
  (function() {{
    if (!window.overlayHost) {{ return; }}
    try {{ window.overlayHost.mount('{overlay_id}'); }} catch (err) {{ /* inert */ }}
  }})();
  /* /overlay-deep-link-boot */
  </script>"""


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
  <!-- Shared overlay-frame chrome (CUIDR-02, #2445) — the one header
       furniture (title · status-pill · ⓘ · close) every overlay renders
       through overlay_frame.overlay_frame_header. Dark-theme tokens only;
       the frame introduces no white-on-dark chrome (spec D4 non-regression). -->
  <style>
    .overlay-frame-header {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}
    .overlay-frame-title {{
      color: var(--fg-1, #dce8f0);
      flex: 1 1 auto;
      font-family: var(--font-ui, sans-serif);
      font-size: var(--text-sm, 13px);
      font-weight: 600;
    }}
    .overlay-frame-status-pill {{
      background: var(--bg-raised, #111a2e);
      border: 1px solid var(--border, #152030);
      border-radius: 4px;
      color: var(--fg-2, #7a9ab8);
      font-family: var(--font-mono, monospace);
      font-size: var(--text-xs, 11px);
      padding: 2px 7px;
    }}
    .overlay-frame-info {{ display: inline-flex; }}
    .overlay-frame-close {{
      background: transparent;
      border: none;
      color: var(--fg-2, #7a9ab8);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
      padding: 0 4px;
    }}
    .overlay-frame-close:hover {{ color: var(--fg-1, #dce8f0); }}
  </style>
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
    // NAV-3a (#2639): overlays participate in browser history. Each mounted
    // overlay pushes exactly ONE history entry carrying an overlay-host
    // marker; browser Back fires `popstate` and dismisses the TOPMOST overlay
    // (one entry popped per dismiss) instead of navigating the page away. This
    // is the modal-Back expectation; it is NOT a route reset — the URL path,
    // query, scroll ownership, and anchor identity are untouched. The `popping`
    // re-entrancy guard keeps a programmatic dismiss (Esc / scrim / occupant
    // self-close, which calls history.back()) from double-dismissing when the
    // resulting popstate fires.
    var HISTORY_MARKER = 'overlayHostMarker';
    var popping = false;
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
    function popTopmost() {
      // Shared topmost-pop used by both the programmatic dismiss path and the
      // browser-Back (popstate) path. Updates host bookkeeping and runs the
      // occupant close hook; never navigates and never touches the document
      // column, so staged suggestions and open-loop counts survive.
      if (!stack.length) { return null; }
      var id = stack.pop();
      sync();
      var occ = occupants[id];
      if (occ && occ.close) { occ.close(); }
      return id;
    }
    window.overlayHost = {
      register: function(id, adapter) {
        assertDeclared(id);
        occupants[id] = adapter || {};
      },
      mount: function(id, detail) {
        assertDeclared(id);
        var occ = occupants[id];
        // Declared but unshipped: inert no-op — never invent a surface, and
        // never push a phantom history entry for a surface that won't mount.
        if (!occ) { return; }
        var at = stack.indexOf(id);
        // Re-mounting an already-stacked id is a move-to-top, NOT a net-new
        // overlay: it must NOT push a second history entry (that double-push
        // desyncs the stack depth from the history position). Only a net-new
        // mount pushes.
        var isNetNew = at === -1;
        if (at !== -1) { stack.splice(at, 1); }
        stack.push(id);
        sync();
        // Push one history entry per NET-NEW overlay so browser Back can pop it
        // and browser Forward can restore it. Same-document pushState: it
        // changes neither the URL nor the document, only adds an entry carrying
        // the overlay id and the stack depth it represents (depth = the new
        // stack length, i.e. 1 for the first overlay). The popstate handler
        // reconciles the live stack to that depth.
        if (isNetNew) {
          try {
            var st = {}; st[HISTORY_MARKER] = id; st.depth = stack.length;
            if (window.history && window.history.pushState) {
              window.history.pushState(st, '');
            }
          } catch (err) { /* history unavailable — overlay still mounts */ }
        }
        if (occ.open) { occ.open(detail || {}); }
      },
      replace: function(id, detail) {
        // NAV-3b (#2640): atomic overlay->overlay swap for the System Map route.
        // A route is one history entry SWAPPED, not a back-then-push: it closes
        // the current topmost occupant and opens the destination at the SAME
        // history depth via history.replaceState. This deliberately avoids the
        // dismiss()->mount() shape, whose async history.back() (popping=true) is
        // still pending when the next mount() pushes — the delayed popstate is
        // then swallowed by the guard, leaving browser history pointing at the
        // OLD overlay while data-overlay-stack points at the destination, so the
        // next Back/Forward acts on the wrong overlay.
        assertDeclared(id);
        var occ = occupants[id];
        // Declared but unshipped: inert no-op — never invent a surface, and
        // never swap to a surface that won't mount (same rule as mount).
        if (!occ) { return; }
        // Defensive: with nothing mounted there is no entry to swap, only the
        // base page-load entry — fall back to a normal pushState mount so we
        // never clobber the document anchor's history entry.
        if (!stack.length) { this.mount(id, detail); return; }
        // Close + pop the current topmost occupant WITHOUT history.back() (no
        // pending traversal to race the swap), then push the destination.
        popTopmost();
        // De-dup the destination before pushing (same rule as mount): if the
        // target already sits in the stack BELOW the just-closed overlay (e.g.
        // Memory open -> Map over it -> route to Memory), pushing again would
        // make data-overlay-stack carry two 'id' entries while the DOM has one
        // occupant. The next Back would pop one duplicate, hide the only drawer
        // via its close hook, yet still report the overlay as open -> DOM/host
        // desync. Splicing first moves it to the single top and keeps depth true.
        var at = stack.indexOf(id);
        if (at !== -1) { stack.splice(at, 1); }
        stack.push(id);
        sync();
        // Replace the current history entry (the one that represented the old
        // overlay) with the destination marker at the SAME depth: one entry
        // swapped, history position unchanged, no popstate fired.
        try {
          var st = {}; st[HISTORY_MARKER] = id; st.depth = stack.length;
          if (window.history && window.history.replaceState) {
            window.history.replaceState(st, '');
          }
        } catch (err) { /* history unavailable — overlay still swaps */ }
        if (occ.open) { occ.open(detail || {}); }
      },
      dismiss: function() {
        // overlay.dismiss — return to the document anchor. Pops only the
        // topmost overlay and updates host bookkeeping. It never navigates the
        // page and never touches the document column, so the URL path/query,
        // scroll ownership, anchor identity, staged suggestions, and open-loop
        // counts are preserved by construction. To keep the history stack in
        // lock-step with the overlay stack, the matching history entry is
        // unwound with history.back(); the `popping` guard stops the resulting
        // popstate from popping a second overlay.
        if (!stack.length) { return; }
        popTopmost();
        try {
          if (!popping && window.history && window.history.back) {
            popping = true;
            window.history.back();
          }
        } catch (err) { popping = false; }
      },
      notifyClosed: function(id) {
        // An occupant closed itself through its own affordance; keep the
        // host stack truthful without re-running the occupant close hook, and
        // unwind the matching history entry so Back stays in step.
        var at = stack.indexOf(id);
        if (at !== -1) {
          stack.splice(at, 1); sync();
          try {
            if (!popping && window.history && window.history.back) {
              popping = true;
              window.history.back();
            }
          } catch (err) { popping = false; }
        }
      },
      topmost: function() {
        return stack.length ? stack[stack.length - 1] : null;
      }
    };
    // Browser Back/Forward reconcile the overlay stack to the depth carried in
    // the history entry being landed on (NAV-3a, #2639). When the entry this
    // handler reacts to was unwound by a programmatic dismiss (Esc / scrim /
    // occupant self-close, which calls history.back()), the `popping` guard
    // absorbs the event so we never double-dismiss.
    //
    // Reconcile-to-depth (not a blind pop) so Forward after a Back RESTORES the
    // modal instead of closing another one, and stacked overlays never
    // close/restore the WRONG one:
    //   - Back (landed depth < live stack): pop overlays until the live stack
    //     matches the target depth (close-above-target — the common case);
    //   - Forward (landed depth > live stack, by one): re-open the entry's
    //     marked overlay if its occupant is registered and not already mounted,
    //     WITHOUT pushing a new history entry. Single-step forward-restore is
    //     the recovery path; arbitrary multi-overlay forward chains are not
    //     rebuilt.
    // The base document entry carries no overlay state, so its target depth is
    // 0 and Back from the first overlay closes it back to the anchor.
    window.addEventListener('popstate', function(event) {
      if (popping) { popping = false; return; }
      var st = event && event.state;
      var targetDepth = (st && typeof st.depth === 'number') ? st.depth : 0;
      // Back / down: close overlays above the target depth.
      while (stack.length > targetDepth) { popTopmost(); }
      // Forward / up by one: restore the marked overlay (recovery path).
      if (stack.length < targetDepth && st) {
        var marker = st[HISTORY_MARKER];
        var occ = marker ? occupants[marker] : null;
        if (occ && stack.indexOf(marker) === -1) {
          stack.push(marker);
          sync();
          if (occ.open) { occ.open({}); }
        }
      }
    });
    // Keyboard map (SYSTEM_ENTRY_POINT_SPEC.md §Keyboard map):
    //   meta+k -> cmd.open, meta+n -> capture.open, escape -> overlay.dismiss.
    // cmd.open mounts the shipped Panel command palette (#1786, SEP-04);
    // capture.open mounts the shipped capture occupant (#1791).
    // Focus trap (CUIDR-02, #2445): while an overlay carrying
    // data-overlay-focus-trap="true" is the topmost mount, keyboard focus
    // cycles within it and never leaks to the document behind. The frame
    // (overlay_frame.py) stamps the hook on every overlay root; the host owns
    // the trap motion in one place (live-exercised in UAT).
    function topmostTrapEl() {
      var id = stack.length ? stack[stack.length - 1] : null;
      if (!id) { return null; }
      var el = document.querySelector('[data-overlay-id="' + id + '"][data-overlay-focus-trap="true"]');
      return el || null;
    }
    function focusableWithin(el) {
      var sel = 'a[href], button:not([disabled]), textarea:not([disabled]),' +
        ' input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
      return Array.prototype.filter.call(el.querySelectorAll(sel), function(n) {
        return n.offsetParent !== null || n === document.activeElement;
      });
    }
    document.addEventListener('keydown', function(e) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey) {
        var k = String(e.key || '').toLowerCase();
        if (k === 'k') { e.preventDefault(); window.overlayHost.mount('cmd'); return; }
        if (k === 'n') { e.preventDefault(); window.overlayHost.mount('capture'); return; }
      }
      if (e.key === 'Escape') { window.overlayHost.dismiss(); return; }
      if (e.key === 'Tab') {
        var trap = topmostTrapEl();
        if (!trap) { return; }
        var items = focusableWithin(trap);
        if (!items.length) { e.preventDefault(); trap.focus && trap.focus(); return; }
        var first = items[0];
        var last = items[items.length - 1];
        var active = document.activeElement;
        if (!trap.contains(active)) { e.preventDefault(); first.focus(); return; }
        if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
      }
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
