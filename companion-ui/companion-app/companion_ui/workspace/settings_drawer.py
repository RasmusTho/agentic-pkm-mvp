"""Settings drawer — Local UI preference drawer (#1789, SEP-07).

Implements ``docs/SYSTEM_ENTRY_POINT/SETTINGS_DRAWER.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Resolved Q18 — quiet hours, §Resolved Q19 — settings storage home,
§Intent vocabulary ``settings.*``) and
``companion-ui/docs/DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md``.

One coherent home for the Local UI preferences — without changing their
authority class:

- Preferences re-render identical content. The canonical Markdown /
  content hash is **byte-unchanged** across any preference change; nothing
  in this module receives, carries, or returns note content.
- No preference write reaches the vault or a save/projection endpoint.
  The storage home is the `WORKSPACE_STATE_CONTRACT.md` local-state home as
  pinned by `DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md` — browser-local
  state (#1675 shipped ``localStorage``; this drawer keeps that mechanism,
  it does not fork it).
- **Display** consolidates the shipped #1675 controls
  (``data-testid="display-pref-*"``) in presentation only: the form moves
  into the drawer, while its storage and apply mechanism
  (``companion.displayPreferences.v1`` in ``serve_dev_page.py``) stays the
  single owner of display state. The drawer drives those controls through
  the DOM and never writes their storage key.
- **Listening** preferences (#1641/#1643 contract lineage): modality and
  speed over the shipped TTS read-back — render-only pacing; the TTS
  provider/endpoint boundary (`LOCAL_FIRST_TTS_CONTRACT.md`) is untouched.
- **Behaviour**: the guidance-layer default as a stored Local UI preference
  (declared via the spec's ``data-guidance="on"`` root attribute; absent =
  off), and **quiet hours**, which dampen ambient salience presentation
  only — they can never become a scheduler: there are nothing to schedule,
  suppress, or batch (spec §Resolved Q18; there are no notifications).
- **Connection** posture is a read-only display of server-declared runtime
  and vault posture; the UI never selects a vault.
- A **`local-only render` badge** appears whenever a preference diverges
  from the canonical render; **reset-to-canonical is always available**.

Like ``overlay_host.py`` and ``memory_review_drawer.py``, the pure model in
this module is the contract the in-page controller
(:func:`settings_drawer_script`) mirrors; tests assert both. Nothing here
performs I/O.
"""

from __future__ import annotations

import html as _html
import re as _re

from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,  # noqa: F401
)
from companion_ui.workspace.overlay_frame import (
    overlay_frame_header,
    overlay_frame_root_attrs,
)
from companion_ui.workspace.vault_settings_panel import (
    vault_settings_section_markup,
)

# The drawer's sections, in render order (SETTINGS_DRAWER.md §What This Task
# Does). #2590 adds the "vault" section: the relocated scoped Markdown-settings
# editor — the only server-write section in the drawer; the others stay
# render-only / read-only Local UI.
SETTINGS_SECTIONS: tuple[str, ...] = (
    "display",
    "listening",
    "behaviour",
    "connection",
    "vault",
)

# The spec's settings intents (§Intent vocabulary): none routes through the
# governed pipeline — preferences are Local UI state.
SETTINGS_INTENTS: dict[str, str] = {
    "open": "settings.open",
    "set": "settings.set",
    "reset": "settings.reset",
}

# The divergence indicator's exact label (spec §Resolved Q19).
LOCAL_ONLY_BADGE_LABEL = "local-only render"

# Canonical defaults of the shipped #1675 display mechanism — mirrored here
# so the drawer can detect divergence and reset, never re-implemented: the
# shipped script in `serve_dev_page._display_preferences_script` stays the
# single owner of display-preference storage and application.
DISPLAY_PREF_CANONICAL: dict[str, object] = {
    "fontSize": "16px",
    "lineHeight": "1.65",
    "readingWidth": "68ch",
    "focusMode": False,
}

# Drawer-owned Local UI preference storage (browser-local; §Resolved Q19).
# Distinct from — never a replacement of — the shipped #1675 display key.
SETTINGS_STORAGE_KEY = "companion.settingsPreferences.v1"

# Listening vocabulary per DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md §What
# may be re-rendered ("read, listen, sequential, bimodal, and speed"); the
# speed steps mirror the shipped read-back rate control (`tts-rate`).
LISTENING_MODALITIES: tuple[str, ...] = ("read", "listen", "sequential", "bimodal")
LISTENING_SPEEDS: tuple[str, ...] = ("0.85", "1", "1.15", "1.3")

SETTINGS_CANONICAL: dict[str, object] = {
    "listeningModality": "read",
    "listeningSpeed": "1",
    "guidanceDefault": False,
    "quietHoursEnabled": False,
    "quietHoursStart": "22:00",
    "quietHoursEnd": "07:00",
}

_TIME_KEYS: tuple[str, ...] = ("quietHoursStart", "quietHoursEnd")
_TOGGLE_KEYS: tuple[str, ...] = ("guidanceDefault", "quietHoursEnabled")
_TIME_RE = _re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# The complete vocabulary of what quiet hours may do (spec §Resolved Q18):
# one presentation directive. No schedule, no suppression, no batching key
# exists or may be added without a spec change.
QUIET_HOURS_PRESENTATION_KEYS: tuple[str, ...] = ("ambient_dampened",)


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def parse_time_to_minutes(value: str) -> int:
    """Parse a ``HH:MM`` wall-clock string to minutes since midnight."""
    match = _TIME_RE.match(str(value or ""))
    if not match:
        raise ValueError(f"not a HH:MM wall-clock time: {value!r}")
    return int(match.group(1)) * 60 + int(match.group(2))


def apply_preference(prefs: dict, key: str, value: object) -> dict:
    """``settings.set`` — pure preference update on the drawer-owned state.

    Only declared preference keys exist; the returned dict can never carry
    document content, so the byte-unchanged guarantee holds by construction
    on this side of the contract. Undeclared keys and out-of-vocabulary
    values are rejected.
    """
    if key not in SETTINGS_CANONICAL:
        raise ValueError(
            f"undeclared preference {key!r}; declared: {sorted(SETTINGS_CANONICAL)}"
        )
    if key == "listeningModality" and value not in LISTENING_MODALITIES:
        raise ValueError(
            f"undeclared listening modality {value!r}; declared: {LISTENING_MODALITIES}"
        )
    if key == "listeningSpeed" and value not in LISTENING_SPEEDS:
        raise ValueError(
            f"undeclared listening speed {value!r}; declared: {LISTENING_SPEEDS}"
        )
    if key in _TIME_KEYS:
        parse_time_to_minutes(str(value))
    if key in _TOGGLE_KEYS:
        value = bool(value)
    updated = {k: prefs.get(k, default) for k, default in SETTINGS_CANONICAL.items()}
    updated[key] = value
    return updated


def reset_to_canonical() -> tuple[dict, dict]:
    """``settings.reset`` — canonical display and drawer preference state."""
    return dict(DISPLAY_PREF_CANONICAL), dict(SETTINGS_CANONICAL)


def preferences_diverge(display_prefs: dict, settings_prefs: dict) -> bool:
    """Whether any preference diverges from the canonical render.

    Drives the ``local-only render`` badge: visible whenever this is true,
    gone after reset-to-canonical (spec §Resolved Q19).
    """
    for key, canonical in DISPLAY_PREF_CANONICAL.items():
        if display_prefs.get(key, canonical) != canonical:
            return True
    for key, canonical in SETTINGS_CANONICAL.items():
        if settings_prefs.get(key, canonical) != canonical:
            return True
    return False


def quiet_hours_active(
    now_minutes: int, *, enabled: bool, start_minutes: int, end_minutes: int
) -> bool:
    """Pure quiet-hours window check, wrap-around aware (e.g. 22:00–07:00).

    A degenerate window (start == end) is never active — quiet hours must be
    an explicit, bounded window, never an always-on mute.
    """
    if not enabled:
        return False
    if start_minutes == end_minutes:
        return False
    if start_minutes < end_minutes:
        return start_minutes <= now_minutes < end_minutes
    return now_minutes >= start_minutes or now_minutes < end_minutes


def quiet_hours_presentation(now_minutes: int, prefs: dict) -> dict:
    """Everything quiet hours are allowed to do (spec §Resolved Q18).

    Returns exactly one presentation directive — dampen ambient salience
    rendering inside the window. There is no notification machinery in this
    product, so there is nothing to schedule, suppress, or batch, and this
    projection has no key that could express any of that.
    """
    enabled = bool(prefs.get("quietHoursEnabled", False))
    start = parse_time_to_minutes(
        str(prefs.get("quietHoursStart", SETTINGS_CANONICAL["quietHoursStart"]))
    )
    end = parse_time_to_minutes(
        str(prefs.get("quietHoursEnd", SETTINGS_CANONICAL["quietHoursEnd"]))
    )
    return {
        "ambient_dampened": quiet_hours_active(
            now_minutes, enabled=enabled, start_minutes=start, end_minutes=end
        )
    }


def connection_posture_rows(fields: dict) -> tuple[tuple[str, str, str], ...]:
    """Read-only connection posture rows from server-declared fields.

    Pure projection of values the server already declared on the page —
    nothing re-derived, nothing selectable. The UI never selects a vault;
    vault binding is runtime-owned.
    """
    data = fields if isinstance(fields, dict) else {}
    return (
        ("settings-connection-runtime", "runtime", str(data.get("runtime_environment_label") or "unknown")),
        ("settings-connection-channel", "channel", str(data.get("runtime_api_base_url_label") or "unknown")),
        ("settings-connection-vault", "vault", str(data.get("runtime_vault_name") or "unknown")),
        ("settings-connection-vault-channel", "vault channel", str(data.get("runtime_vault_channel") or "unknown")),
        ("settings-connection-vault-provenance", "vault provenance", str(data.get("runtime_vault_provenance") or "unknown")),
    )


def _display_section_form() -> str:
    """The shipped #1675 display-preference controls, consolidated here.

    This markup is the delivered #1675 slice moved verbatim into the drawer
    (same testids, names, options, and defaults). Its semantics are owned by
    the shipped mechanism in ``serve_dev_page._display_preferences_script``
    — storage key, persistence, and CSS application are unchanged; only the
    presentation home moved (SETTINGS_DRAWER.md: "move into / are mirrored
    by the drawer").
    """
    return """
          <form class="display-preferences"
            data-testid="display-preferences"
            data-storage-scope="browser-local"
            data-authority="render-only">
            <label class="display-preference-control">
              <span>Font size</span>
              <select data-testid="display-pref-font-size"
                name="font-size"
                aria-label="Font size">
                <option value="15px">15</option>
                <option value="16px">16</option>
                <option value="18px">18</option>
                <option value="20px">20</option>
              </select>
            </label>
            <label class="display-preference-control">
              <span>Line height</span>
              <select data-testid="display-pref-line-height"
                name="line-height"
                aria-label="Line height">
                <option value="1.45">1.45</option>
                <option value="1.65">1.65</option>
                <option value="1.85">1.85</option>
                <option value="2">2.0</option>
              </select>
            </label>
            <label class="display-preference-control">
              <span>Reading width</span>
              <select data-testid="display-pref-reading-width"
                name="reading-width"
                aria-label="Reading width">
                <option value="56ch">56ch</option>
                <option value="68ch">68ch</option>
                <option value="78ch">78ch</option>
              </select>
            </label>
            <label class="display-preference-toggle">
              <input type="checkbox"
                data-testid="display-pref-focus-mode"
                name="focus-mode">
              <span>Focus mode</span>
            </label>
          </form>"""


def _listening_section() -> str:
    modality_options = "".join(
        f'<option value="{m}"{" selected" if m == SETTINGS_CANONICAL["listeningModality"] else ""}>{m}</option>'
        for m in LISTENING_MODALITIES
    )
    speed_options = "".join(
        f'<option value="{s}"{" selected" if s == SETTINGS_CANONICAL["listeningSpeed"] else ""}>{s}&times;</option>'
        for s in LISTENING_SPEEDS
    )
    return f"""
        <section class="settings-section" data-testid="settings-section-listening"
          data-settings-section="listening" data-authority="render-only">
          <h3 class="settings-section-title">Listening</h3>
          <label class="settings-control">
            <span>Modality</span>
            <select data-testid="settings-listening-modality"
              data-intent="settings.set" name="listening-modality"
              aria-label="Listening modality">{modality_options}</select>
          </label>
          <label class="settings-control">
            <span>Speed</span>
            <select data-testid="settings-listening-speed"
              data-intent="settings.set" name="listening-speed"
              aria-label="Listening speed">{speed_options}</select>
          </label>
          <p class="settings-section-note" data-testid="settings-listening-note">
            Render-only pacing over the shipped read-back. The read-back
            boundary itself is unchanged.</p>
        </section>"""


def _behaviour_section() -> str:
    return f"""
        <section class="settings-section" data-testid="settings-section-behaviour"
          data-settings-section="behaviour" data-authority="render-only">
          <h3 class="settings-section-title">Behaviour</h3>
          <label class="settings-toggle">
            <input type="checkbox" data-testid="settings-guidance-default"
              data-intent="settings.set" name="guidance-default">
            <span>Guidance layer on by default</span>
          </label>
          <label class="settings-toggle">
            <input type="checkbox" data-testid="settings-quiet-hours-enabled"
              data-intent="settings.set" name="quiet-hours-enabled">
            <span>Quiet hours</span>
          </label>
          <div class="settings-quiet-hours-window" data-testid="settings-quiet-hours-window">
            <label class="settings-control">
              <span>From</span>
              <input type="time" class="settings-time-input"
                data-testid="settings-quiet-hours-start"
                data-intent="settings.set" name="quiet-hours-start"
                value="{_e(SETTINGS_CANONICAL["quietHoursStart"])}"
                aria-label="Quiet hours start">
            </label>
            <label class="settings-control">
              <span>Until</span>
              <input type="time" class="settings-time-input"
                data-testid="settings-quiet-hours-end"
                data-intent="settings.set" name="quiet-hours-end"
                value="{_e(SETTINGS_CANONICAL["quietHoursEnd"])}"
                aria-label="Quiet hours end">
            </label>
          </div>
          <p class="settings-section-note" data-testid="settings-quiet-hours-note">
            Quiet hours soften ambient cues during the window &mdash;
            presentation only. Nothing is scheduled, suppressed, or batched;
            there are no notifications.</p>
        </section>"""


def _connection_section(fields: dict) -> str:
    rows = "".join(
        f"""
            <div class="settings-connection-row" data-testid="{testid}">
              <span class="settings-connection-key">{_e(label)}</span>
              <code>{_e(value)}</code>
            </div>"""
        for testid, label, value in connection_posture_rows(fields)
    )
    return f"""
        <section class="settings-section" data-testid="settings-section-connection"
          data-settings-section="connection" data-authority="read-only"
          data-vault-selection="never">
          <h3 class="settings-section-title">Connection</h3>
          <div class="settings-connection-rows">{rows}
          </div>
          <p class="settings-section-note" data-testid="settings-connection-note">
            Posture declared by the runtime; display only. The UI never
            selects a vault.</p>
        </section>"""


def _vault_section() -> str:
    """The relocated scoped-settings editor as a drawer section (#2590).

    Settings are a settings surface, so the scoped Markdown-settings editor
    (watcher/writes/shared-local-edit flags + handoff/assets folders + Save)
    moves here from the retired loaded-note vault drawer. This is a
    **server-write** section (it posts ``vault.settings.write`` to the runtime
    with the existing #2518 confirm guard) — distinct from the drawer's
    render-only / read-only Local UI sections, so the drawer's render-only badge
    logic does not mislabel it. The markup, fragment route, and write controller
    are reused unchanged (:func:`vault_settings_panel.vault_settings_section_markup`);
    only the mount point moved. Vault *switching* is not here — that is the
    Choose-a-vault overlay opened from the vault chip.
    """
    return vault_settings_section_markup()


def settings_drawer_markup(fields: dict) -> str:
    """The Settings right-drawer shell plus the local-only render badge.

    Renders closed (``data-open="false"``); the overlay host's ``settings``
    occupant adapter opens and closes it so the dismiss rule (Esc / scrim /
    close → document anchor) is enforced in one place. The badge is a shell
    chip outside the drawer so divergence stays visible while the drawer is
    closed. Styles are scoped here so the drawer is self-contained.

    Header furniture is emitted by :func:`overlay_frame.overlay_frame_header`
    (CUIDR-02, #2445) in the canonical order: title · status-pill · ⓘ · close.
    The root carries ``data-overlay-frame-position="right-drawer"``.
    """
    sections = " ".join(SETTINGS_SECTIONS)
    _frame_root = overlay_frame_root_attrs(
        overlay_id="settings", position="right-drawer"
    )
    _frame_header = overlay_frame_header(
        overlay_id="settings",
        title="Settings",
        # No frame-wide status-pill: Settings is a real (writable) settings
        # surface, not a read-only render. Storing settings in Markdown does not
        # make the menu read-only — the Vault section writes scoped settings to
        # the runtime (vault.settings.write). Authority is therefore declared
        # PER SECTION (render-only preferences vs the server-write Vault section),
        # not by a single misleading frame designation (#2590 — owner reframe;
        # OVERLAY_MODAL_FRAME_SPEC.md updated to match).
        status_pill=None,
        guidance_surface="settings",
    )
    return f"""
  <!-- Settings drawer (#1789, SEP-07) — a real settings surface. The Display/
       Listening/Behaviour preference sections re-render identical content
       (canonical hash byte-unchanged), persist browser-local, and are always
       resettable (spec §Resolved Q18/Q19); Connection is a read-only display of
       server state; the Vault section is a server-write surface (vault.settings.write
       to Markdown). Authority is declared per section, not frame-wide (#2590). -->
  <style>
    .settings-drawer {{
      background: var(--bg-surface, #0c1220);
      border-left: 1px solid var(--border-strong, #1e3050);
      bottom: 0;
      box-shadow: -18px 0 40px rgba(0, 0, 0, 0.45);
      display: flex;
      flex-direction: column;
      gap: 14px;
      max-width: 92vw;
      overflow-y: auto;
      padding: 18px 20px 28px;
      position: fixed;
      right: 0;
      top: 0;
      transform: translateX(100%);
      transition: transform 160ms ease;
      width: 380px;
      z-index: 960;
    }}
    .settings-drawer[data-open="true"] {{ transform: translateX(0); }}
    .settings-head {{
      align-items: flex-start; display: flex; gap: 12px;
      justify-content: space-between;
    }}
    .settings-kicker {{
      color: var(--fg-3, #3d5570); font-size: 11px; letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .settings-title {{ color: var(--fg-1, #dce8f0); font-size: 17px; margin: 2px 0 0; }}
    .settings-close {{
      background: none; border: 1px solid var(--border, #152030);
      border-radius: 4px; color: var(--fg-2, #7a9ab8); cursor: pointer;
      font-size: 16px; line-height: 1; padding: 4px 9px;
    }}
    .settings-authority-note, .settings-section-note {{
      color: var(--fg-3, #3d5570); font-size: 12px; margin: 0;
    }}
    .settings-section {{
      border-top: 1px solid var(--border, #152030);
      display: flex; flex-direction: column; gap: 8px; padding-top: 12px;
    }}
    .settings-section-title {{
      color: var(--fg-2, #7a9ab8); font-size: 11px; letter-spacing: 0.08em;
      margin: 0; text-transform: uppercase;
    }}
    .settings-control {{
      align-items: center; color: var(--fg-2, #7a9ab8); display: flex;
      font-size: 13px; gap: 8px; justify-content: space-between;
    }}
    .settings-control select, .settings-control input {{
      background: var(--bg-raised, #111a2e); border: 1px solid var(--border-strong, #1e3050);
      border-radius: 4px; color: var(--fg-1, #dce8f0); font-size: 12px;
      padding: 4px 8px;
    }}
    /* Quiet-hours time inputs onto the dark palette (#2448, D4): the native
       time field and its picker indicator default to white chrome; pin them to
       the design-system tokens and invert the indicator so no input stands out
       against the dark theme. */
    .settings-time-input {{
      background: var(--bg-raised, #111a2e);
      color: var(--fg-1, #dce8f0);
      color-scheme: dark;
    }}
    .settings-time-input::-webkit-calendar-picker-indicator {{
      filter: invert(0.8);
    }}
    .settings-toggle {{
      align-items: center; color: var(--fg-2, #7a9ab8); display: flex;
      font-size: 13px; gap: 8px;
    }}
    .settings-quiet-hours-window {{ display: flex; gap: 12px; }}
    .settings-connection-rows {{ display: flex; flex-direction: column; gap: 4px; }}
    .settings-connection-row {{
      color: var(--fg-3, #3d5570); display: flex; font-size: 12px; gap: 8px;
    }}
    .settings-connection-row code {{ color: var(--fg-2, #7a9ab8); word-break: break-all; }}
    .settings-connection-key {{
      flex: 0 0 110px; font-size: 10px; letter-spacing: 0.05em;
      line-height: 1.8; text-transform: uppercase;
    }}
    .settings-foot {{
      align-items: center; border-top: 1px solid var(--border, #152030);
      display: flex; gap: 10px; padding-top: 12px;
    }}
    .settings-reset {{
      background: var(--bg-raised, #111a2e); border: 1px solid var(--border-strong, #1e3050);
      border-radius: 4px; color: var(--fg-1, #dce8f0); cursor: pointer;
      font-size: 12px; padding: 6px 12px;
    }}
    .settings-reset-note {{ color: var(--fg-3, #3d5570); font-size: 11px; }}
    .settings-local-only-badge {{
      background: var(--bg-raised, #111a2e);
      border: 1px solid var(--amber-dim, #805010);
      border-left: 3px solid var(--amber, #f09030);
      border-radius: 4px; color: var(--fg-1, #dce8f0); font-size: 11px;
      letter-spacing: 0.04em; padding: 4px 10px; position: fixed;
      right: 16px; top: 54px; z-index: 955;
    }}
    /* Quiet hours dampen ambient salience presentation only (spec §Resolved
       Q18): reduced intensity of ambient cues inside the window. Opacity
       only — never removal, never suppression. */
    body.quiet-hours-dampened .reentry-ambient,
    body.quiet-hours-dampened .resurface-candidate,
    body.quiet-hours-dampened .workspace-freshness {{
      opacity: 0.45;
    }}
  </style>
  <div class="settings-local-only-badge" id="settings-local-only-badge"
    data-testid="settings-local-only-badge" data-diverged="false"
    data-authority="render-only" aria-live="polite"
    hidden>{LOCAL_ONLY_BADGE_LABEL}</div>
  <aside class="settings-drawer" id="settings-drawer"
    data-testid="settings-drawer" data-region="settings-drawer"
    data-overlay-id="settings" data-drawer-side="right" data-open="false"
    data-authority="mixed" data-storage-scope="per-section"
    data-diverged="false" data-quiet-hours="inactive"
    data-sections="{sections}"
    data-canonical-font-size="{_e(DISPLAY_PREF_CANONICAL["fontSize"])}"
    data-canonical-line-height="{_e(DISPLAY_PREF_CANONICAL["lineHeight"])}"
    data-canonical-reading-width="{_e(DISPLAY_PREF_CANONICAL["readingWidth"])}"
    data-canonical-focus-mode="false"
    {_frame_root}
    role="dialog" aria-modal="false" aria-hidden="true"
    inert
    aria-label="Settings">
    {_frame_header}
    {guidance_callout_markup('settings')}
    <p class="settings-authority-note" data-testid="settings-authority-note">
      Display, Listening, Behaviour and Connection preferences re-render
      identical content — they never touch the vault and are always resettable.
      The Vault section below is the exception: it writes scoped vault settings
      to the runtime (governed, confirm-gated), not a local preference.</p>
    <section class="settings-section" data-testid="settings-section-display"
      data-settings-section="display" data-authority="render-only">
      <h3 class="settings-section-title">Display</h3>{_display_section_form()}
    </section>{_listening_section()}{_behaviour_section()}{_connection_section(fields)}{_vault_section()}
    <footer class="settings-foot">
      <button type="button" class="settings-reset"
        data-testid="settings-reset" data-intent="settings.reset"
        aria-label="Reset preferences to canonical"
        onclick="settingsDrawer.reset()">Reset to canonical</button>
      <span class="settings-reset-note">Reset-to-canonical is always
        available.</span>
    </footer>
  </aside>"""


def settings_drawer_script() -> str:
    """The in-page controller mirroring the pure model above.

    Must be emitted after :func:`overlay_host.overlay_host_script` (it
    registers as the host's ``settings`` occupant) and after the shipped
    #1675 display-preference script (whose storage and apply mechanism it
    consolidates in presentation only — it drives those controls through
    the DOM and never writes their storage key).

    Boundary, by construction: localStorage only (`§Resolved Q19`); no
    network call of any kind; no timers — quiet hours are recomputed on
    load and on preference change only, so no machinery exists that could
    grow into scheduling (spec §Resolved Q18); attribute/class/value
    application only — the document column is never touched.
    """
    return f"""
  <script>
  /* settings-drawer-controller */
  (function() {{
    var drawer = document.getElementById('settings-drawer');
    if (!drawer || !window.overlayHost) {{ return; }}
    var badge = document.getElementById('settings-local-only-badge');
    var STORAGE_KEY = '{SETTINGS_STORAGE_KEY}';
    // Mirrors settings_drawer.SETTINGS_CANONICAL.
    var CANONICAL = {{
      listeningModality: 'read',
      listeningSpeed: '1',
      guidanceDefault: false,
      quietHoursEnabled: false,
      quietHoursStart: '22:00',
      quietHoursEnd: '07:00'
    }};
    // The shipped #1675 canonical render, read from the drawer markup
    // (generated from settings_drawer.DISPLAY_PREF_CANONICAL) — the drawer
    // carries no display-preference storage of its own.
    var DISPLAY_CANONICAL = {{
      fontSize: drawer.getAttribute('data-canonical-font-size'),
      lineHeight: drawer.getAttribute('data-canonical-line-height'),
      readingWidth: drawer.getAttribute('data-canonical-reading-width'),
      focusMode: drawer.getAttribute('data-canonical-focus-mode') === 'true'
    }};
    function el(testid) {{
      return drawer.querySelector('[data-testid="' + testid + '"]');
    }}
    function readPrefs() {{
      // Local UI storage home only (spec §Resolved Q19): browser-local
      // state, never vault Markdown/frontmatter, never a save/projection
      // endpoint.
      try {{
        var raw = window.localStorage ? window.localStorage.getItem(STORAGE_KEY) : null;
        return raw ? Object.assign({{}}, CANONICAL, JSON.parse(raw)) : Object.assign({{}}, CANONICAL);
      }} catch (e) {{ return Object.assign({{}}, CANONICAL); }}
    }}
    function writePrefs(prefs) {{
      try {{
        if (window.localStorage) {{
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
        }}
      }} catch (e) {{}}
    }}
    function minutesOf(hhmm) {{
      var m = /^(\\d\\d):(\\d\\d)$/.exec(String(hhmm || ''));
      if (!m) {{ return null; }}
      return (parseInt(m[1], 10) * 60) + parseInt(m[2], 10);
    }}
    // Mirrors settings_drawer.quiet_hours_active: a pure presentation-window
    // check. Quiet hours dampen ambient salience rendering only — there are
    // no notifications, so nothing is scheduled, suppressed, or batched, and
    // no timer exists in this controller.
    function quietHoursActive(nowMinutes, prefs) {{
      if (!prefs.quietHoursEnabled) {{ return false; }}
      var start = minutesOf(prefs.quietHoursStart);
      var end = minutesOf(prefs.quietHoursEnd);
      if (start === null || end === null || start === end) {{ return false; }}
      if (start < end) {{ return nowMinutes >= start && nowMinutes < end; }}
      return nowMinutes >= start || nowMinutes < end;
    }}
    function displayControl(name) {{
      return document.querySelector('[data-testid="display-pref-' + name + '"]');
    }}
    function displayPrefsFromControls() {{
      var fontSize = displayControl('font-size');
      var lineHeight = displayControl('line-height');
      var readingWidth = displayControl('reading-width');
      var focusMode = displayControl('focus-mode');
      return {{
        fontSize: fontSize ? fontSize.value : DISPLAY_CANONICAL.fontSize,
        lineHeight: lineHeight ? lineHeight.value : DISPLAY_CANONICAL.lineHeight,
        readingWidth: readingWidth ? readingWidth.value : DISPLAY_CANONICAL.readingWidth,
        focusMode: focusMode ? Boolean(focusMode.checked) : DISPLAY_CANONICAL.focusMode
      }};
    }}
    // Mirrors settings_drawer.preferences_diverge.
    function diverged(prefs) {{
      var d = displayPrefsFromControls();
      var key;
      for (key in DISPLAY_CANONICAL) {{
        if (String(d[key]) !== String(DISPLAY_CANONICAL[key])) {{ return true; }}
      }}
      for (key in CANONICAL) {{
        if (String(prefs[key]) !== String(CANONICAL[key])) {{ return true; }}
      }}
      return false;
    }}
    function syncBadge(prefs) {{
      var on = diverged(prefs);
      drawer.setAttribute('data-diverged', on ? 'true' : 'false');
      if (badge) {{
        badge.setAttribute('data-diverged', on ? 'true' : 'false');
        if (on) {{ badge.removeAttribute('hidden'); }}
        else {{ badge.setAttribute('hidden', ''); }}
      }}
    }}
    function applyPrefs(prefs) {{
      // Render-only application: attributes, classes, and control values.
      // The document column and the canonical content hash are untouched.
      document.body.setAttribute('data-listening-modality', prefs.listeningModality);
      var rate = document.querySelector('[data-testid="tts-rate"]');
      if (rate) {{ rate.value = prefs.listeningSpeed; }}
      if (document.body.getAttribute('data-guidance-session-override') !== 'true') {{
        if (prefs.guidanceDefault) {{ document.body.setAttribute('data-guidance', 'on'); }}
        else {{ document.body.removeAttribute('data-guidance'); }}
      }}
      var now = new Date();
      var active = quietHoursActive((now.getHours() * 60) + now.getMinutes(), prefs);
      document.body.classList.toggle('quiet-hours-dampened', active);
      drawer.setAttribute('data-quiet-hours', active ? 'active' : 'inactive');
    }}
    function syncControls(prefs) {{
      var modality = el('settings-listening-modality');
      var speed = el('settings-listening-speed');
      var guidance = el('settings-guidance-default');
      var quietOn = el('settings-quiet-hours-enabled');
      var quietStart = el('settings-quiet-hours-start');
      var quietEnd = el('settings-quiet-hours-end');
      if (modality) {{ modality.value = prefs.listeningModality; }}
      if (speed) {{ speed.value = prefs.listeningSpeed; }}
      if (guidance) {{ guidance.checked = Boolean(prefs.guidanceDefault); }}
      if (quietOn) {{ quietOn.checked = Boolean(prefs.quietHoursEnabled); }}
      if (quietStart) {{ quietStart.value = prefs.quietHoursStart; }}
      if (quietEnd) {{ quietEnd.value = prefs.quietHoursEnd; }}
    }}
    function prefsFromControls(current) {{
      var modality = el('settings-listening-modality');
      var speed = el('settings-listening-speed');
      var guidance = el('settings-guidance-default');
      var quietOn = el('settings-quiet-hours-enabled');
      var quietStart = el('settings-quiet-hours-start');
      var quietEnd = el('settings-quiet-hours-end');
      return {{
        listeningModality: modality ? modality.value : current.listeningModality,
        listeningSpeed: speed ? speed.value : current.listeningSpeed,
        guidanceDefault: guidance ? Boolean(guidance.checked) : Boolean(current.guidanceDefault),
        quietHoursEnabled: quietOn ? Boolean(quietOn.checked) : Boolean(current.quietHoursEnabled),
        quietHoursStart: (quietStart && minutesOf(quietStart.value) !== null)
          ? quietStart.value : current.quietHoursStart,
        quietHoursEnd: (quietEnd && minutesOf(quietEnd.value) !== null)
          ? quietEnd.value : current.quietHoursEnd
      }};
    }}
    var prefs = readPrefs();
    function setOpen(open) {{
      drawer.setAttribute('data-open', open ? 'true' : 'false');
      drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
      // A closed drawer is only translated offscreen, so without `inert` its
      // controls stay in the tab order and the a11y tree. Toggle `inert` so a
      // closed drawer cannot receive focus (offscreen-but-reachable trap).
      if (open) {{ drawer.removeAttribute('inert'); }}
      else {{ drawer.setAttribute('inert', ''); }}
    }}
    // Host occupant: the host owns mount/dismiss (settings.open / Esc /
    // scrim / close -> the document anchor; no route reset, no data loss).
    window.overlayHost.register('settings', {{
      open: function() {{ setOpen(true); }},
      close: function() {{ setOpen(false); }}
    }});
    function reset() {{
      // settings.reset — reset-to-canonical is always available. The shipped
      // #1675 mechanism stays the only writer of display state: the drawer
      // sets the shipped controls back to canonical and dispatches a change
      // event so the form's own handler applies and persists them.
      var fontSize = displayControl('font-size');
      var lineHeight = displayControl('line-height');
      var readingWidth = displayControl('reading-width');
      var focusMode = displayControl('focus-mode');
      if (fontSize) {{ fontSize.value = DISPLAY_CANONICAL.fontSize; }}
      if (lineHeight) {{ lineHeight.value = DISPLAY_CANONICAL.lineHeight; }}
      if (readingWidth) {{ readingWidth.value = DISPLAY_CANONICAL.readingWidth; }}
      if (focusMode) {{ focusMode.checked = DISPLAY_CANONICAL.focusMode; }}
      var form = document.querySelector('[data-testid="display-preferences"]');
      if (form) {{ form.dispatchEvent(new Event('change', {{ bubbles: true }})); }}
      prefs = Object.assign({{}}, CANONICAL);
      writePrefs(prefs);
      syncControls(prefs);
      applyPrefs(prefs);
      syncBadge(prefs);
    }}
    window.settingsDrawer = {{
      open: function() {{ window.overlayHost.mount('settings'); }},
      close: function() {{ window.overlayHost.dismiss(); }},
      reset: reset
    }};
    drawer.addEventListener('change', function() {{
      // settings.set — drawer-owned preferences persist to the Local UI
      // storage home; display changes bubbling up from the consolidated
      // #1675 form stay owned by its shipped handler (which already ran on
      // the form itself) — only the divergence badge is recomputed here.
      prefs = prefsFromControls(prefs);
      writePrefs(prefs);
      applyPrefs(prefs);
      syncBadge(prefs);
    }});
    document.addEventListener('DOMContentLoaded', function() {{
      syncControls(prefs);
      applyPrefs(prefs);
      syncBadge(prefs);
    }});
  }})();
  /* /settings-drawer-controller */
  </script>"""
