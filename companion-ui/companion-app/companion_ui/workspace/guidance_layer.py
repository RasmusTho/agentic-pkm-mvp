"""Guidance layer — opt-in explanatory callouts (#1788, SEP-06).

Implements ``docs/SYSTEM_ENTRY_POINT/GUIDANCE_LAYER.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Data-attribute vocabulary — ``data-guidance="on"`` on the shell root,
absent = off, the established-user default; §Intent vocabulary —
``guidance.toggle``, UI-local, never routed through the pipeline) and the
design package's "Earned guidance, not embedded help" rule
(``companion-ui/design_handoff/2026-06-09-system-entry-point/design-notes.md``).

Split "help" into its two kinds:

- **Evidence stays, always.** Provenance lines, authority tags, receipt
  pills, and tooltips are what the expert needs to trust state. They are
  terse, persistent, and entirely unaffected by this layer.
- **Explanation is opt-in and decays to nothing.** The "what is this
  surface / how does re-entry work" prose lives in guidance callouts,
  revealed only while the shell root carries ``data-guidance="on"``.

Mechanism — a cross-cutting layer, not a host occupant:

- Callouts are server-rendered in place (``.callout.guidance``) and hidden
  by the stylesheet unless the shell root carries ``data-guidance="on"``.
  The server render is identical in both states; only CSS visibility
  changes, so evidence elements render identically with guidance on/off
  by construction.
- The ``ⓘ`` affordance (``guidance.toggle``) flips the root attribute and
  nothing else: nothing is persisted (not even session storage), no
  save/projection endpoint is reached, and content semantics never change.
  Reload → guidance off again.
- The stored guidance-layer **default** belongs to the Settings drawer
  (#1789, Behaviour section): its controller applies the stored default to
  the root attribute at load. This toggle is the session-local override on
  top of that default — it never writes the stored preference.
- Integrates with — never replaces — the shipped ``/help`` guide (#1755):
  callouts may deep-link into the long-form guide; this layer is the
  in-place layer.

Like ``overlay_host.py``, the pure vocabulary in this module is the
contract the in-page controller (:func:`guidance_layer_script`) mirrors;
tests assert both. Nothing here performs I/O.
"""

from __future__ import annotations

import html as _html

# Spec §Data-attribute vocabulary: `data-guidance="on"` (absent = off) on
# the shell root. Off is the established-user default in every entry state.
GUIDANCE_ATTRIBUTE = "data-guidance"
GUIDANCE_ON = "on"

# Spec §Intent vocabulary: guidance.toggle — UI-local, default off, never
# routed through the governed pipeline.
GUIDANCE_TOGGLE_INTENT = "guidance.toggle"

# The shipped long-form help guide (#1755). Callouts deep-link into it; the
# guidance layer never restates or replaces it.
HELP_GUIDE_ROUTE = "/help"

# Explanatory copy per surface. Guidance adds explanation only — these
# describe what a surface *is* and how it returns to the anchor; they never
# restate or re-classify runtime state (no counts, no statuses, no
# outcomes). `help_anchor` deep-links into the shipped /help guide.
#
# Extension point: a surface that ships later registers its copy here and
# renders `guidance_callout_markup(<id>)` + `guidance_toggle_markup(<id>)`
# from its own head (the system map, #1787, did exactly that). Adding a new
# surface id is a guidance-copy change, not a mechanism change.
GUIDANCE_CALLOUTS: dict[str, dict[str, str]] = {
    "shell": {
        "title": "The shell",
        "body": (
            "The document is the front door: one anchored note, the vault "
            "pane on the left, the agent rail on the right. Every overlay "
            "opens over this anchor and dismisses back to it — nothing "
            "replaces the document."
        ),
        "help_anchor": "layout",
    },
    "reentry": {
        "title": "Re-entry",
        "body": (
            "After time away, these four fixed questions restore your prior "
            "trajectory. Resume returns to where momentum stopped; Start "
            "fresh keeps unresolved tension without re-opening it. Nothing "
            "here mutates the vault."
        ),
        "help_anchor": "reorient",
    },
    "vault": {
        "title": "Vault browser",
        "body": (
            "Browse and search the vault; browsing never writes. Opening a "
            "note re-anchors the shell around it; queue-for-review is the "
            "one governed handoff this surface can make."
        ),
        "help_anchor": "layout",
    },
    "cmd": {
        "title": "Panel command palette",
        "body": (
            "A faster presentation of the same governed Panel proposals as "
            "the rail — propose, confirm, execute, receipt. It is not chat: "
            "no free text, no generation, identical authority to the rail."
        ),
        "help_anchor": "panel",
    },
    "capture": {
        "title": "Capture",
        "body": (
            "A friction-free note to your future self, appended to the "
            "vault inbox through the governed write path. No dates, no "
            "task states — it resurfaces later by relevance like any vault "
            "material."
        ),
        "help_anchor": "layout",
    },
    "memory": {
        "title": "Memory review",
        "body": (
            "Unreviewed memory is not semantic authority. Candidates wait "
            "here until you accept, reject, revise, or defer them; accept "
            "promotes through the governed path and produces a receipt."
        ),
        "help_anchor": "boundaries",
    },
    "receipts": {
        "title": "Receipts",
        "body": (
            "A history of governed outcomes, exactly as the runtime "
            "recorded them — reads only. The UI never invents, edits, or "
            "re-derives a receipt; a guard-held row means a boundary held "
            "and nothing was mutated."
        ),
        "help_anchor": "signals",
    },
    "settings": {
        "title": "Settings",
        "body": (
            "Local UI preferences only: they re-render identical content "
            "and never touch the vault or a save endpoint. The Behaviour "
            "section stores the guidance-layer default; this ⓘ toggle is "
            "the session-local override on top of it."
        ),
        "help_anchor": "layout",
    },
    "map": {
        "title": "System map",
        "body": (
            "An index that makes the existing surfaces one system: each "
            "node states how it is reached from the document anchor and how "
            "it returns. Pull-based — sought from the topbar, never shown "
            "unbidden."
        ),
        "help_anchor": "layout",
    },
}

# Where the ⓘ affordance renders (issue #1788 scope): the topbar, the
# re-entry card head, and each shipped overlay-host occupant head
# (including the system map, #1787).
GUIDANCE_TOGGLE_SURFACES: tuple[str, ...] = (
    "topbar",
    "reentry",
    "vault",
    "cmd",
    "capture",
    "memory",
    "receipts",
    "settings",
    "map",
)


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def guidance_enabled(attribute_value: object) -> bool:
    """Pure model: the layer is on only for the exact spec value ``"on"``.

    Absent (``None``) or anything else is off — off is the default in every
    entry state.
    """
    return attribute_value == GUIDANCE_ON


def toggled_guidance(attribute_value: object) -> str | None:
    """Pure model of ``guidance.toggle``: flip the root attribute value.

    ``None`` (absent — the default) toggles to ``"on"``; ``"on"`` toggles
    back to ``None`` (attribute removed). No other state exists: the toggle
    carries no authority and persists nothing.
    """
    return None if guidance_enabled(attribute_value) else GUIDANCE_ON


def guidance_toggle_markup(surface: str) -> str:
    """The ``ⓘ`` affordance for one surface head.

    Emits the declared ``guidance.toggle`` intent and flips the root
    attribute through the shared controller — UI-local by construction
    (no href, no form, no transport).
    """
    if surface not in GUIDANCE_TOGGLE_SURFACES:
        raise ValueError(
            f"undeclared guidance toggle surface {surface!r}; "
            f"declared: {GUIDANCE_TOGGLE_SURFACES}"
        )
    return (
        f'<button type="button" class="guidance-toggle" '
        f'data-testid="guidance-toggle-{_e(surface)}" '
        f'data-intent="{GUIDANCE_TOGGLE_INTENT}" '
        f'data-guidance-surface="{_e(surface)}" '
        f'aria-pressed="false" '
        f'title="Toggle explanatory guidance (session-local)" '
        f'aria-label="Toggle explanatory guidance" '
        f'onclick="guidanceLayer.toggle()">&#9432;</button>'
    )


def guidance_callout_markup(surface: str) -> str:
    """One explanatory guidance callout, hidden unless guidance is on.

    The callout is explanation only: static prose describing the surface,
    plus a deep link into the shipped ``/help`` guide. It carries no runtime
    state, no counts, and no actions other than the read-only help link.
    """
    callout = GUIDANCE_CALLOUTS.get(surface)
    if callout is None:
        raise ValueError(
            f"no guidance copy registered for surface {surface!r}; "
            f"registered: {tuple(GUIDANCE_CALLOUTS)}"
        )
    help_href = f"{HELP_GUIDE_ROUTE}#{callout['help_anchor']}"
    # A <div role="note">, not an <aside>: callouts render inside occupant
    # drawers that are themselves <aside> containers, and nesting asides
    # would truncate the established `<aside …>.*?</aside>` test extractors.
    return (
        f'<div class="callout guidance guidance-callout" '
        f'data-testid="guidance-callout-{_e(surface)}" '
        f'data-guidance-surface="{_e(surface)}" '
        f'data-authority="explanation" role="note">'
        f'<span class="guidance-callout-kicker">guidance</span>'
        f'<strong class="guidance-callout-title">{_e(callout["title"])}</strong>'
        f'<span class="guidance-callout-body">{_e(callout["body"])}</span>'
        f'<a class="guidance-callout-help-link" href="{_e(help_href)}" '
        f'data-testid="guidance-help-link-{_e(surface)}">Full guide</a>'
        f"</div>"
    )


def guidance_layer_style() -> str:
    """The visibility gate: callouts exist in the DOM, hidden unless on.

    Every rule that keys on ``data-guidance`` selects only
    ``.guidance-``-scoped elements — evidence elements (provenance lines,
    authority tags, receipt pills, tooltips) are untouchable by this layer
    by construction.
    """
    return """
  <style>
    /* guidance-layer (#1788, SEP-06): explanation is opt-in and decays to
       nothing. Off (attribute absent) is the default in every entry state;
       only .guidance-scoped elements may key on data-guidance. */
    .guidance-callout { display: none; }
    body[data-guidance="on"] .guidance-callout {
      display: flex;
      flex-direction: column;
      gap: 4px;
      margin: 8px 0;
      padding: 8px 10px;
      border: 1px solid var(--border, #152030);
      border-left: 3px solid var(--accent-dim, #1b5e6e);
      border-radius: 8px;
      background: var(--bg-raised, #0e1626);
      color: var(--fg-2, #7a9ab8);
      font-family: var(--font-ui, sans-serif);
      font-size: var(--text-sm, 13px);
    }
    .guidance-callout-kicker {
      color: var(--fg-3, #3d5570);
      font-family: var(--font-mono, monospace);
      font-size: var(--text-xs, 11px);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .guidance-callout-title { color: var(--fg-1, #dce8f0); }
    .guidance-callout-help-link {
      align-self: flex-start;
      color: var(--accent, #35c8e8);
      font-size: var(--text-xs, 11px);
    }
    .guidance-toggle {
      background: transparent;
      border: none;
      border-radius: 6px;
      color: var(--fg-3, #3d5570);
      cursor: pointer;
      font-size: 0.95rem;
      line-height: 1;
      padding: 2px 5px;
    }
    .guidance-toggle:hover { color: var(--fg-1, #dce8f0); }
    body[data-guidance="on"] .guidance-toggle {
      color: var(--accent, #35c8e8);
    }
  </style>"""


def guidance_layer_script() -> str:
    """The in-page controller mirroring :func:`toggled_guidance`.

    ``guidance.toggle`` is UI-local (spec §Intent vocabulary): the
    controller flips the shell-root attribute and syncs the affordances'
    pressed state — nothing else. It performs no fetch, opens no transport,
    writes no storage of any kind (the stored *default* is the Settings
    drawer's, #1789), and never touches the document column. Reload →
    guidance off again unless the stored default re-applies it.
    """
    return """
  <script>
  /* guidance-layer-controller */
  (function() {
    if (window.guidanceLayer) { return; }
    function isOn() {
      return document.body.getAttribute('data-guidance') === 'on';
    }
    function sync() {
      var on = isOn();
      var toggles = document.querySelectorAll('[data-intent="guidance.toggle"]');
      for (var i = 0; i < toggles.length; i++) {
        toggles[i].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }
    window.guidanceLayer = {
      isOn: isOn,
      toggle: function() {
        // Mirrors guidance_layer.toggled_guidance: flip the root
        // attribute only. Nothing persisted, no endpoint reached, no
        // content semantics changed. Mark the session override so Settings
        // default re-application cannot erase it until reload or another
        // explicit guidance toggle.
        document.body.setAttribute('data-guidance-session-override', 'true');
        if (isOn()) { document.body.removeAttribute('data-guidance'); }
        else { document.body.setAttribute('data-guidance', 'on'); }
        sync();
      }
    };
    // The Settings drawer (#1789) applies the stored guidance default to
    // the same root attribute at load; observe the attribute so the
    // affordances stay truthful whichever side flipped it.
    if (window.MutationObserver) {
      new MutationObserver(sync).observe(document.body, {
        attributes: true,
        attributeFilter: ['data-guidance']
      });
    }
    sync();
  })();
  /* /guidance-layer-controller */
  </script>"""


__all__ = [
    "GUIDANCE_ATTRIBUTE",
    "GUIDANCE_CALLOUTS",
    "GUIDANCE_ON",
    "GUIDANCE_TOGGLE_INTENT",
    "GUIDANCE_TOGGLE_SURFACES",
    "HELP_GUIDE_ROUTE",
    "guidance_callout_markup",
    "guidance_enabled",
    "guidance_layer_script",
    "guidance_layer_style",
    "guidance_toggle_markup",
    "toggled_guidance",
]
