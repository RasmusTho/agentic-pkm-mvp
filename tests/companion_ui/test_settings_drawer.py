"""Settings drawer — Local UI preference drawer (#1789, SEP-07).

One coherent home for the Local UI preferences without changing their
authority class (`docs/SYSTEM_ENTRY_POINT/SETTINGS_DRAWER.md`;
`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md` §Resolved Q18 — quiet hours,
§Resolved Q19 — settings storage home, §Intent vocabulary ``settings.*``;
`companion-ui/docs/DISPLAY_PREFERENCE_LOCAL_STATE_CONTRACT.md`):

- a right drawer mounted on the shared overlay host (``settings.open``),
  dismissing back to the document anchor with no route reset;
- Display consolidates the shipped #1675 controls in presentation only —
  same testids, same storage mechanism, never re-implemented;
- Listening (modality/speed) is render-only pacing over the shipped
  read-back; Behaviour holds the guidance default and quiet hours, which
  dampen ambient salience presentation only; Connection is read-only;
- canonical Markdown hash byte-unchanged across any preference change; no
  preference write reaches a save/projection endpoint or the vault;
  ``local-only render`` badge on divergence; reset-to-canonical always
  available.

Like ``test_overlay_host.py``, the pure model in ``settings_drawer.py`` is
the contract the in-page controller mirrors; tests assert both.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from companion_ui.workspace.overlay_host import (
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    OverlayHostState,
    dismiss,
    mount,
)
from companion_ui.workspace.guidance_layer import guidance_layer_script
from companion_ui.workspace.serve_dev_page import render_index_html
from companion_ui.workspace.settings_drawer import (
    DISPLAY_PREF_CANONICAL,
    LISTENING_MODALITIES,
    LISTENING_SPEEDS,
    LOCAL_ONLY_BADGE_LABEL,
    QUIET_HOURS_PRESENTATION_KEYS,
    SETTINGS_CANONICAL,
    SETTINGS_INTENTS,
    SETTINGS_SECTIONS,
    SETTINGS_STORAGE_KEY,
    apply_preference,
    connection_posture_rows,
    parse_time_to_minutes,
    preferences_diverge,
    quiet_hours_active,
    quiet_hours_presentation,
    reset_to_canonical,
)

# ---------------------------------------------------------------------------
# Fixtures (workspace fields mirror test_overlay_host / test_display_preferences)
# ---------------------------------------------------------------------------

CANONICAL_BODY = "# Note\n\nCanonical source paragraph."


def _fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Settings Note",
        "note_path": "Notes/settings.md",
        "artifact_id": "art-settings",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-settings",
        "body": CANONICAL_BODY,
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-settings",
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


def _drawer_markup(html: str) -> str:
    match = re.search(
        r'<aside class="settings-drawer".*?</aside>', html, re.S
    )
    assert match, "settings drawer must render in the shell"
    return match.group(0)


def _section(html: str, section: str) -> str:
    match = re.search(
        rf'<section[^>]*data-settings-section="{section}".*?</section>',
        html,
        re.S,
    )
    assert match, f"settings section {section!r} must render"
    return match.group(0)


def _controller_script(html: str) -> str:
    start = html.index("/* settings-drawer-controller */")
    end = html.index("/* /settings-drawer-controller */", start)
    return html[start:end]


# ---------------------------------------------------------------------------
# AC1: the drawer renders all four sections; the shipped #1675 display
# controls keep working unregressed (consolidated in presentation only)
# ---------------------------------------------------------------------------


def test_drawer_sections_render_and_display_prefs_work() -> None:
    html = _render()
    drawer = _drawer_markup(html)

    # The drawer is the overlay host's `settings` occupant: right drawer,
    # rendered closed, dismissing back to the document anchor.
    assert 'data-testid="settings-drawer"' in drawer
    assert 'data-overlay-id="settings"' in drawer
    assert 'data-drawer-side="right"' in drawer
    assert 'data-open="false"' in drawer
    # #2590: the drawer is a real (writable) settings surface with mixed
    # authority declared per section, not a single frame-wide read-only
    # render. The root carries data-authority="mixed"; the frame renders
    # NO frame-wide status pill (it would mislabel the writable sections).
    assert 'data-authority="mixed"' in drawer
    assert 'data-testid="overlay-frame-status-pill"' not in drawer
    assert 'data-intent="overlay.dismiss"' in drawer
    assert "settings" in SHIPPED_OVERLAY_OCCUPANTS
    assert "overlayHost.register('settings'" in _controller_script(html)

    # All declared sections render, in the declared order. #2590 adds the
    # "vault" section (the relocated scoped-settings editor) after connection.
    assert SETTINGS_SECTIONS == (
        "display",
        "listening",
        "behaviour",
        "connection",
        "vault",
    )
    positions = []
    for section in SETTINGS_SECTIONS:
        marker = f'data-settings-section="{section}"'
        assert marker in drawer, f"missing section {section!r}"
        positions.append(drawer.index(marker))
    assert positions == sorted(positions), "sections must render in declared order"

    # The shipped #1675 display controls live inside the drawer — same
    # testids, same defaults, exactly once in the rendered markup (moved,
    # not forked; scripts may reference the testids in selectors).
    display_section = _section(drawer, "display")
    markup_only = re.sub(r"<script\b[^>]*>[\s\S]*?</script\b[^>]*>", "", html, flags=re.I)
    for testid in (
        "display-preferences",
        "display-pref-font-size",
        "display-pref-line-height",
        "display-pref-reading-width",
        "display-pref-focus-mode",
    ):
        assert f'data-testid="{testid}"' in display_section
        assert markup_only.count(f'data-testid="{testid}"') == 1, (
            f"{testid} must not be duplicated by the drawer"
        )
    assert 'data-storage-scope="browser-local"' in display_section
    assert 'data-authority="render-only"' in display_section
    assert 'value="16px"' in display_section
    assert 'value="1.65"' in display_section
    assert 'value="68ch"' in display_section

    # The shipped #1675 storage/apply mechanism is untouched: same storage
    # key, same persistence call, still present on the page.
    assert "companion.displayPreferences.v1" in html
    assert "localStorage.setItem(storageKey" in html

    # Listening controls carry the declared modality/speed vocabulary.
    listening = _section(drawer, "listening")
    assert 'data-testid="settings-listening-modality"' in listening
    assert 'data-testid="settings-listening-speed"' in listening
    for modality in LISTENING_MODALITIES:
        assert f'value="{modality}"' in listening
    for speed in LISTENING_SPEEDS:
        assert f'value="{speed}"' in listening
    assert ("read", "listen", "sequential", "bimodal") == LISTENING_MODALITIES

    # Behaviour holds the stored guidance default and quiet hours.
    behaviour = _section(drawer, "behaviour")
    assert 'data-testid="settings-guidance-default"' in behaviour
    assert 'data-testid="settings-quiet-hours-enabled"' in behaviour
    assert 'data-testid="settings-quiet-hours-start"' in behaviour
    assert 'data-testid="settings-quiet-hours-end"' in behaviour

    # settings.set / settings.reset intents are declared on the controls.
    assert SETTINGS_INTENTS == {
        "open": "settings.open",
        "set": "settings.set",
        "reset": "settings.reset",
    }
    assert 'data-intent="settings.set"' in drawer
    assert 'data-intent="settings.reset"' in drawer

    # CUIDR-04 (#2447) keeps the *topbar* to IDENTITY + Capture only — settings
    # is not a SHIPPED_TOPBAR_SURFACES surface. NAV-1 (ui-audit) adds a direct
    # Settings launcher to the composed *bottom bar* so preferences are reachable
    # without first opening the System Map; the map settings node remains too.
    assert "settings" not in SHIPPED_TOPBAR_SURFACES
    bottom_bar = re.search(
        r'<[^>]*data-region="bottom-bar"[^>]*>(.*?)</(?:div|footer|nav)>',
        html,
        re.S,
    )
    assert bottom_bar is not None, "composed bottom bar must render"
    assert 'data-testid="workspace-surface-icon-settings"' in bottom_bar.group(1), (
        "NAV-1: the Settings launcher must sit in the composed bottom bar"
    )
    assert "settings.open" in bottom_bar.group(1)
    map_node = re.search(
        r'<button[^>]*data-surface-id="settings"[^>]*>', html
    )
    assert map_node, "settings must be reachable via the System Map overlay node"
    assert 'data-intent="settings.open"' in map_node.group(0)

    # Pure host model: settings mounts and dismisses back to the anchor with
    # the anchor context preserved by construction.
    state = OverlayHostState(
        anchor_note_path="Notes/settings.md",
        route="/?note_path=Notes/settings.md",
        staged_suggestion_ids=("s-1",),
        open_loop_count=2,
    )
    mounted = mount(state, "settings")
    assert mounted.stack == ("settings",)
    back = dismiss(mounted)
    assert back == state


# ---------------------------------------------------------------------------
# NAV-2 / NAV-4 (ui-audit): direct bottom-bar launchers for History/Receipts,
# Memory, and Search (⌘K). NAV-1 added the Settings launcher to the composed
# bottom bar so preferences were reachable without first opening the System
# Map; NAV-2 extends that to the remaining frequently-used secondary surfaces
# (History/Receipts, Memory) and NAV-4 adds the Search / ⌘K palette pill. The
# map is the complete index, not the only door — every launcher reuses the
# existing intent + host occupant, and the System Map node stays too.
# ---------------------------------------------------------------------------


def _bottom_bar(html: str) -> str:
    match = re.search(
        r'<[^>]*data-region="bottom-bar"[^>]*>(.*?)</(?:div|footer|nav)>',
        html,
        re.S,
    )
    assert match is not None, "composed bottom bar must render"
    return match.group(1)


def test_bottom_bar_direct_launchers_nav2_nav4() -> None:
    html = _render()
    bottom_bar = _bottom_bar(html)

    # AC1: History/Receipts, Memory, and Search are each reachable in 1 click
    # from the working shell — direct launchers in the composed bottom bar,
    # not only via the map. Each emits the surface's existing open intent.
    for testid, intent in (
        ("workspace-surface-icon-receipts", "receipts.open"),
        ("workspace-surface-icon-memory", "memory.open"),
        ("workspace-surface-icon-cmd", "cmd.open"),
    ):
        assert f'data-testid="{testid}"' in bottom_bar, (
            f"NAV-2/NAV-4: the {testid} launcher must sit in the composed bottom bar"
        )
        assert f'data-intent="{intent}"' in bottom_bar, (
            f"NAV-2/NAV-4: the bottom-bar launcher must emit {intent}"
        )

    # NAV-4: the Search pill carries the ⌘K hint in its title so the
    # keyboard-first fast path is discoverable from the visible affordance.
    cmd_launcher = re.search(
        r'<button[^>]*data-testid="workspace-surface-icon-cmd"[^>]*>',
        bottom_bar,
    )
    assert cmd_launcher, "NAV-4: the Search / ⌘K launcher must render"
    assert "⌘K" in cmd_launcher.group(0), (
        "NAV-4: the Search launcher title must carry the ⌘K hint"
    )

    # AC2: launchers reuse existing intents/host occupants — no invented
    # surfaces. receipts.open / memory.open / cmd.open are the shipped
    # overlay-open intents; the launchers mount the same registered occupants.
    for intent, occupant in (
        ("receipts.open", "receipts"),
        ("memory.open", "memory"),
        ("cmd.open", "cmd"),
    ):
        assert occupant in SHIPPED_OVERLAY_OCCUPANTS, (
            f"{occupant} must be a shipped overlay occupant the launcher reuses"
        )
        assert f"overlayHost.mount('{occupant}')" in bottom_bar, (
            f"the bottom-bar launcher must mount the existing {occupant} occupant"
        )

    # AC2: the System Map nodes are retained — additive direct access, not a
    # removal. Each surface still has its routing node in the map overlay.
    for surface_id, intent in (
        ("receipts", "receipts.open"),
        ("memory", "memory.open"),
        ("palette", "cmd.open"),
    ):
        map_node = re.search(
            rf'<button[^>]*data-surface-id="{surface_id}"[^>]*>', html
        )
        assert map_node, (
            f"{surface_id} must remain reachable via the System Map overlay node"
        )
        assert f'data-intent="{intent}"' in map_node.group(0)


def test_search_pill_gated_to_registered_palette_no_dead_affordance() -> None:
    # NAV-4 no-dead-affordance regression (Codex P2, PR #2636). The `cmd`
    # palette occupant only registers on a loaded-note shell — panel_palette
    # emits nothing and the controller skips registration when fields is None.
    # The vault-selection-required and error shells render with fields is None,
    # so a visible Search pill there would mount nothing = dead chrome. The
    # Search pill must be ABSENT in those shells, while History / Memory /
    # Settings (always-registered occupants) stay PRESENT.
    fields_none_shells = {
        "vault-selection-required": render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="",
            vault_selection_required={
                "title": "Choose a vault",
                "message": "Pick a vault to continue.",
                "context": {"status": "none"},
                "recent_vaults": [],
                "actions": [],
            },
        ),
        "error": render_index_html(
            api_base_url="http://127.0.0.1:18001",
            note_path="",
            error="Runtime unreachable",
        ),
    }
    for shell_name, shell_html in fields_none_shells.items():
        assert 'data-testid="workspace-surface-icon-cmd"' not in shell_html, (
            f"NAV-4: the Search / ⌘K pill must not render on the {shell_name} "
            "shell — its `cmd` palette occupant is not registered there"
        )
        assert 'data-intent="cmd.open"' not in shell_html, (
            f"no element may advertise cmd.open on the {shell_name} shell "
            "(the palette occupant is absent there)"
        )
        # The always-registered occupants keep their direct launchers, so this
        # is a tightening of Search alone, not a regression of NAV-1/NAV-2.
        for testid in (
            "workspace-surface-icon-receipts",
            "workspace-surface-icon-memory",
            "workspace-surface-icon-settings",
        ):
            assert f'data-testid="{testid}"' in shell_html, (
                f"NAV-1/NAV-2: the {testid} launcher must still render on the "
                f"{shell_name} shell (its occupant registers regardless of fields)"
            )


# ---------------------------------------------------------------------------
# White-input AC (#2448, D4): no input renders with default white chrome
# against the dark theme. The settings time inputs are brought onto the dark
# palette via a design-system class / variables; no inline white background.
# ---------------------------------------------------------------------------


def test_settings_time_inputs_on_dark_palette() -> None:
    html = _render()
    drawer = _drawer_markup(html)
    behaviour = _section(drawer, "behaviour")

    # Every <input type="time"> carries a design-system style hook — a DS class
    # or a CSS variable — so it never renders default white chrome.
    time_inputs = re.findall(r"<input[^>]*type=\"time\"[^>]*>", behaviour)
    assert time_inputs, "the behaviour section must render the quiet-hours time inputs"
    for tag in time_inputs:
        assert "settings-time-input" in tag, (
            f"every time input must carry the design-system class: {tag}"
        )

    # The DS class pins the time field onto the dark palette via design-system
    # variables (background var(--bg-raised), color var(--fg-1)).
    assert ".settings-time-input" in html
    assert "var(--bg-raised" in html
    assert "var(--fg-1" in html

    # The S2 rail textarea (active-note body-update input) is brought onto the
    # dark palette too — no default white textarea chrome inside the dark rail
    # (#2448 D4 / S2-rail).
    rail_textarea = re.search(
        r'<textarea[^>]*data-testid="workspace-active-note-body-update-input"[^>]*>',
        html,
    )
    assert rail_textarea, "the rail body-update textarea must render in the shell"
    assert "rail-textarea" in rail_textarea.group(0), (
        f"the rail textarea must carry the design-system class: {rail_textarea.group(0)}"
    )
    assert ".rail-textarea" in html
    # The DS rule pins it to the dark palette via design-system variables.
    rail_css = html.split(".rail-textarea {", 1)[1].split("}", 1)[0] if ".rail-textarea {" in html else ""
    assert "var(--bg-raised" in rail_css and "var(--fg-1" in rail_css, (
        "the .rail-textarea rule must use the dark-palette DS variables"
    )

    # No input anywhere on the page carries an inline white background against
    # the dark theme.
    for white in ("background: white", "background:#fff", "background: #fff", "background:white"):
        assert white not in html, f"no input may carry inline {white!r} on the dark theme"


# ---------------------------------------------------------------------------
# AC2: any preference change leaves the canonical Markdown/content hash
# byte-unchanged
# ---------------------------------------------------------------------------


def test_preferences_leave_canonical_hash_byte_unchanged() -> None:
    canonical_hash = hashlib.sha256(CANONICAL_BODY.encode("utf-8")).hexdigest()

    html_before = _render()

    # Exercise every declared preference away from canonical through the
    # pure model — the only mutation surface preferences have.
    display_prefs, settings_prefs = reset_to_canonical()
    settings_prefs = apply_preference(settings_prefs, "listeningModality", "bimodal")
    settings_prefs = apply_preference(settings_prefs, "listeningSpeed", "1.3")
    settings_prefs = apply_preference(settings_prefs, "guidanceDefault", True)
    settings_prefs = apply_preference(settings_prefs, "quietHoursEnabled", True)
    settings_prefs = apply_preference(settings_prefs, "quietHoursStart", "21:30")
    settings_prefs = apply_preference(settings_prefs, "quietHoursEnd", "06:00")

    # Preference state can never carry document content: only declared
    # preference keys exist in the model.
    assert set(settings_prefs) == set(SETTINGS_CANONICAL)
    assert set(display_prefs) == set(DISPLAY_PREF_CANONICAL)
    with pytest.raises(ValueError):
        apply_preference(settings_prefs, "body", "smuggled content")
    with pytest.raises(ValueError):
        apply_preference(settings_prefs, "contentHash", "sha256-forged")

    # The canonical bytes are untouched and the server render is identical:
    # preferences have no server-side channel at all.
    assert (
        hashlib.sha256(CANONICAL_BODY.encode("utf-8")).hexdigest() == canonical_hash
    )
    html_after = _render()
    assert html_after == html_before

    # The rendered note body keeps the canonical paragraph verbatim without
    # restating the machine content hash in visible markup.
    rendered = re.search(
        r'<div class="note-body-content"[^>]*data-testid="workspace-note-rendered"'
        r'[^>]*>(.*?)</div>',
        html_after,
        re.S,
    )
    assert rendered, "rendered note body must render"
    assert 'data-content-hash="sha256-settings"' not in rendered.group(0)
    assert "Canonical source paragraph." in rendered.group(1)

    # The controller applies preferences as attributes/classes/values only —
    # it has no way to rewrite rendered content.
    script = _controller_script(html_after)
    assert "innerHTML" not in script
    assert "workspace-note-rendered" not in script
    assert "note-body" not in script


# ---------------------------------------------------------------------------
# AC3: no preference change calls a save/projection endpoint or reaches the
# vault
# ---------------------------------------------------------------------------


def test_no_preference_write_reaches_save_or_vault() -> None:
    html = _render()
    drawer = _drawer_markup(html)
    script = _controller_script(html)

    # No network surface of any kind in the controller (§Resolved Q19):
    # browser-local storage is the only persistence.
    assert "fetch(" not in script
    assert "XMLHttpRequest" not in script
    assert "/api/" not in script
    assert "window.localStorage" in script
    assert "localStorage.setItem(STORAGE_KEY" in script
    assert SETTINGS_STORAGE_KEY in script

    # Consolidation, not a fork: the drawer never writes the shipped #1675
    # storage key — the shipped mechanism stays the single owner of display
    # state (the drawer drives its controls via the DOM and a change event).
    assert "companion.displayPreferences.v1" not in script
    assert "companion.displayPreferences.v1" not in drawer
    assert SETTINGS_STORAGE_KEY != "companion.displayPreferences.v1"
    assert "dispatchEvent" in script

    # No save/projection endpoints anywhere near the drawer.
    for endpoint in (
        "/api/companion/note/save",
        "/api/panel/checkbox-projection",
        "/api/panel/confirm",
        "/api/companion/capture",
    ):
        assert endpoint not in script
        assert endpoint not in drawer
    assert "<form action" not in drawer
    assert 'method="post"' not in drawer.lower()

    # The pure model is I/O-free state arithmetic on declared keys only.
    _, settings_prefs = reset_to_canonical()
    updated = apply_preference(settings_prefs, "listeningSpeed", "1.15")
    assert updated["listeningSpeed"] == "1.15"
    assert settings_prefs["listeningSpeed"] == "1", "apply_preference is pure"


def test_apply_prefs_preserves_session_guidance_override() -> None:
    html = _render()
    settings_script = _controller_script(html)
    guidance_script = guidance_layer_script()

    assert "data-guidance-session-override', 'true'" in guidance_script
    assert "data-guidance-session-override') !== 'true'" in settings_script

    override_guard = re.search(
        r"if \(document\.body\.getAttribute\('data-guidance-session-override'\) !== 'true'\) \{"
        r"(.*?)\n      \}",
        settings_script,
        re.S,
    )
    assert override_guard, "applyPrefs must guard stored guidance default application"
    guarded_body = override_guard.group(1)
    assert "prefs.guidanceDefault" in guarded_body
    assert "setAttribute('data-guidance', 'on')" in guarded_body
    assert "removeAttribute('data-guidance')" in guarded_body

    before_guard = settings_script.split(
        "data-guidance-session-override') !== 'true'", 1
    )[0]
    assert "data-guidance', 'on'" not in before_guard
    assert "removeAttribute('data-guidance')" not in before_guard


# ---------------------------------------------------------------------------
# AC4: `local-only render` badge on divergence; gone on reset-to-canonical
# ---------------------------------------------------------------------------


def test_local_only_badge_on_divergence_and_reset() -> None:
    html = _render()
    drawer = _drawer_markup(html)
    script = _controller_script(html)

    # The badge renders (hidden) with the exact contract label, outside the
    # drawer so divergence stays visible while the drawer is closed.
    assert LOCAL_ONLY_BADGE_LABEL == "local-only render"
    badge = re.search(
        r'<div class="settings-local-only-badge"[^>]*>([^<]*)</div>', html
    )
    assert badge, "local-only render badge must be in the shell"
    assert LOCAL_ONLY_BADGE_LABEL in badge.group(1)
    assert 'data-diverged="false"' in badge.group(0)
    assert "hidden" in badge.group(0)

    # Pure model: canonical state shows no badge; any divergence shows it;
    # reset-to-canonical clears it.
    display_prefs, settings_prefs = reset_to_canonical()
    assert preferences_diverge(display_prefs, settings_prefs) is False

    diverged_display = dict(display_prefs, fontSize="20px")
    assert preferences_diverge(diverged_display, settings_prefs) is True

    diverged_settings = apply_preference(settings_prefs, "listeningSpeed", "0.85")
    assert preferences_diverge(display_prefs, diverged_settings) is True

    display_prefs, settings_prefs = reset_to_canonical()
    assert preferences_diverge(display_prefs, settings_prefs) is False

    # Reset-to-canonical is always available: an unconditional drawer
    # affordance with the declared intent.
    reset_button = re.search(
        r'<button[^>]*data-testid="settings-reset"[^>]*>', drawer
    )
    assert reset_button, "reset-to-canonical must always be rendered"
    assert 'data-intent="settings.reset"' in reset_button.group(0)
    assert "hidden" not in reset_button.group(0)
    assert "disabled" not in reset_button.group(0)

    # The controller mirrors the pure model: divergence is computed against
    # the canonical values declared on the markup, toggles the badge, and
    # reset routes display state through the shipped #1675 handler.
    assert "data-canonical-font-size" in drawer
    assert "data-canonical-line-height" in drawer
    assert "data-canonical-reading-width" in drawer
    assert "data-canonical-focus-mode" in drawer
    assert "function diverged(" in script
    assert "syncBadge" in script
    assert "function reset(" in script


# ---------------------------------------------------------------------------
# AC5: quiet hours dampen ambient salience presentation only — no
# notification, scheduler, or suppression machinery exists
# ---------------------------------------------------------------------------


def test_quiet_hours_dampen_presentation_only() -> None:
    # Pure window check, wrap-around aware (spec example: 22:00–07:00).
    start = parse_time_to_minutes("22:00")
    end = parse_time_to_minutes("07:00")
    for now, expected in (
        ("23:00", True),
        ("02:30", True),
        ("06:59", True),
        ("07:00", False),
        ("12:00", False),
        ("21:59", False),
        ("22:00", True),
    ):
        assert (
            quiet_hours_active(
                parse_time_to_minutes(now),
                enabled=True,
                start_minutes=start,
                end_minutes=end,
            )
            is expected
        ), f"22:00–07:00 window at {now}"

    # Non-wrapping window, disabled state, and the degenerate window.
    assert quiet_hours_active(
        parse_time_to_minutes("14:00"),
        enabled=True,
        start_minutes=parse_time_to_minutes("13:00"),
        end_minutes=parse_time_to_minutes("15:00"),
    )
    assert not quiet_hours_active(
        parse_time_to_minutes("16:00"),
        enabled=True,
        start_minutes=parse_time_to_minutes("13:00"),
        end_minutes=parse_time_to_minutes("15:00"),
    )
    assert not quiet_hours_active(
        parse_time_to_minutes("23:00"),
        enabled=False,
        start_minutes=start,
        end_minutes=end,
    )
    assert not quiet_hours_active(
        parse_time_to_minutes("23:00"),
        enabled=True,
        start_minutes=start,
        end_minutes=start,
    )
    with pytest.raises(ValueError):
        parse_time_to_minutes("25:99")

    # The complete vocabulary of what quiet hours may do is one presentation
    # directive — nothing exists that could schedule, suppress, or batch.
    _, settings_prefs = reset_to_canonical()
    active_prefs = apply_preference(settings_prefs, "quietHoursEnabled", True)
    view = quiet_hours_presentation(parse_time_to_minutes("23:00"), active_prefs)
    assert set(view) == set(QUIET_HOURS_PRESENTATION_KEYS) == {"ambient_dampened"}
    assert view["ambient_dampened"] is True
    assert quiet_hours_presentation(
        parse_time_to_minutes("12:00"), active_prefs
    ) == {"ambient_dampened": False}
    assert quiet_hours_presentation(
        parse_time_to_minutes("23:00"), settings_prefs
    ) == {"ambient_dampened": False}

    # No machinery in the controller: no timers (recomputed on load and on
    # preference change only), no notification API surface.
    html = _render()
    script = _controller_script(html)
    assert "setTimeout(" not in script
    assert "setInterval(" not in script
    assert "Notification" not in script
    assert "requestPermission" not in script
    assert "serviceWorker" not in script

    # Dampening is opacity-only presentation on ambient cues — never
    # removal, never suppression (mirrors the shipped focus-mode rule).
    dampen_rule = re.search(
        r"body\.quiet-hours-dampened \.reentry-ambient,\s*"
        r"body\.quiet-hours-dampened \.resurface-candidate,\s*"
        r"body\.quiet-hours-dampened \.workspace-freshness\s*\{([^}]*)\}",
        html,
        re.S,
    )
    assert dampen_rule, "quiet hours must be a local presentation class"
    assert "opacity:" in dampen_rule.group(1)
    assert "display:" not in dampen_rule.group(1)
    assert "visibility:" not in dampen_rule.group(1)


# ---------------------------------------------------------------------------
# AC6: the connection section is read-only and never offers vault selection
# ---------------------------------------------------------------------------


def test_connection_posture_is_read_only() -> None:
    html = _render()
    drawer = _drawer_markup(html)
    connection = _section(drawer, "connection")

    assert 'data-authority="read-only"' in connection
    assert 'data-vault-selection="never"' in connection

    # Server-declared posture values render verbatim.
    rows = connection_posture_rows(_fields())
    assert [r[2] for r in rows] == [
        "dev",
        "local-dev",
        "vault/dev",
        "local-dev",
        "resolved",
    ]
    for testid, _label, value in rows:
        assert f'data-testid="{testid}"' in connection
        assert f"<code>{value}</code>" in connection

    # Read-only means read-only: no interactive control of any kind inside
    # the section, and no vault selection affordance anywhere in the drawer.
    for forbidden in ("<input", "<select", "<button", "<form", "<a "):
        assert forbidden not in connection
    assert "data-intent" not in connection
    assert 'type="file"' not in drawer
    assert "vault.pick" not in drawer
    assert "vault.open" not in connection

    # Pure projection degrades to declared-unknown, never to a picker.
    empty_rows = connection_posture_rows({})
    assert all(value == "unknown" for _t, _l, value in empty_rows)


# ---------------------------------------------------------------------------
# #2590: the relocated scoped-settings editor renders as the drawer's "vault"
# section — a server-write surface, distinct from the render-only / read-only
# Local UI sections, that still posts vault.settings.write with the #2518
# confirm guard preserved.
# ---------------------------------------------------------------------------


def test_vault_section_hosts_relocated_scoped_settings_as_server_write() -> None:
    from companion_ui.workspace.vault_settings_panel import (
        VAULT_SETTINGS_ENDPOINT,
        VAULT_SETTINGS_FRAGMENT_ROUTE,
        VAULT_SETTINGS_FRAGMENT_SETTINGS_PARAM,
        VAULT_SETTINGS_FRAGMENT_SETTINGS_VALUE,
    )

    html = _render()
    drawer = _drawer_markup(html)

    # The vault section renders inside the Settings drawer, after connection.
    assert 'data-settings-section="vault"' in drawer
    assert 'data-testid="settings-section-vault"' in drawer
    assert drawer.index('data-settings-section="connection"') < drawer.index(
        'data-settings-section="vault"'
    )

    # It is a SERVER-WRITE surface — distinct from the render-only / read-only /
    # local-ui authority of the other sections, so the drawer's render-only badge
    # logic does not mislabel it.
    vault_open = drawer.index('data-settings-section="vault"')
    vault_tag = drawer[drawer.rindex("<section", 0, vault_open) : drawer.index(">", vault_open)]
    assert 'data-authority="server-write"' in vault_tag

    # The relocated editor host is the controller's resolved root + carries the
    # settings-scoped fragment-reload path and the settings-write endpoint.
    assert 'data-testid="vault-settings-section"' in drawer
    assert f'data-api-path="{VAULT_SETTINGS_ENDPOINT}"' in drawer
    expected_fragment = (
        f"{VAULT_SETTINGS_FRAGMENT_ROUTE}"
        f"?{VAULT_SETTINGS_FRAGMENT_SETTINGS_PARAM}={VAULT_SETTINGS_FRAGMENT_SETTINGS_VALUE}"
    )
    assert f'data-fragment-path="{expected_fragment}"' in drawer

    # The scoped-settings editor body (the vault.settings.write surface) is
    # mounted here — re-homed, not dropped.
    assert 'data-testid="vault-settings-body"' in drawer
    assert 'data-intent="vault.settings.write"' in html

    # The switch / foreign-form chrome (typed paths, Role select) does NOT leak
    # onto the settings surface — vault switching is the Choose-a-vault overlay.
    assert 'data-testid="vault-open-path"' not in drawer
    assert 'data-testid="vault-init-path"' not in drawer
    assert 'data-testid="vault-init-role"' not in drawer

    # The write controller (single owner of vault.settings.write) is emitted on
    # the loaded-note page, with the #2518 init/confirm guard preserved.
    assert "vault-settings-panel-controller" in html
    assert "vault_init_confirmation_required" in html

    # Authority labeling stays truthful (#2590 Codex P2): the drawer's authority
    # note no longer blanket-claims "never touch the vault" — it scopes that to
    # the preference sections and names the Vault section as the server-write
    # exception, so a real runtime write is not mislabeled as a local preference.
    note_start = drawer.index('data-testid="settings-authority-note"')
    note = " ".join(drawer[note_start : drawer.index("</p>", note_start)].split())
    assert "Vault section" in note
    assert "writes scoped vault settings to the runtime" in note


def test_vault_section_write_posts_to_settings_endpoint_with_confirm_preserved() -> None:
    """The relocated editor still posts vault.settings.write to
    /api/companion/vault/settings, and the #2518 init-confirm round-trip is
    intact in the same controller (re-homed write path, not a new one)."""
    from companion_ui.workspace.vault_settings_panel import (
        VAULT_SETTINGS_ENDPOINT,
        vault_settings_panel_script,
        vault_settings_section_markup,
    )

    section = vault_settings_section_markup(
        {
            "context": {"status": "selected"},
            "definitions": [
                {
                    "key": "allowWritesToVault",
                    "type": "boolean",
                    "scope": "vault",
                    "editable": True,
                }
            ],
            "settings": [{"key": "allowWritesToVault", "value": True}],
            "validation_errors": [],
        }
    )
    # The relocated editor renders the scoped Save form posting vault.settings.write.
    assert 'data-intent="vault.settings.write"' in section
    assert f'data-api-path="{VAULT_SETTINGS_ENDPOINT}"' in section
    assert 'data-testid="vault-setting-save-allowWritesToVault"' in section

    script = vault_settings_panel_script()
    # The single write controller binds the relocated section as its root.
    assert '[data-testid="vault-settings-section"]' in script
    # vault.settings.write posts to the settings endpoint.
    assert (
        "form.matches('[data-intent=\"vault.select\"],"
        "[data-intent=\"vault.initialize\"],"
        "[data-intent=\"vault.settings.write\"]')" in script
    )
    assert "JSON.stringify({ key: key, value: value })" in script
    # The #2518 init-confirm guard is preserved in the same controller.
    assert "vault_init_confirmation_required" in script


def test_vault_section_editor_on_dark_palette_no_white_chrome() -> None:
    """The relocated Settings -> Vault editor wears the dark input/button palette
    under the drawer host — no default-browser white chrome (#2590 Codex P2b).

    The .vault-setting-row grid + the dark palette were previously scoped only
    under .vault-settings-panel (emitted by vault_settings_panel_markup), which
    the loaded-note page no longer renders. The relocated section must carry the
    shared editor styles itself, scoped to .vault-settings-section-host, so the
    editor never falls back to white chrome on the dark theme (mirrors the
    settings time-input no-white-chrome AC, #2448 D4).
    """
    html = _render()
    drawer = _drawer_markup(html)

    # The editor styles resolve under the new drawer host.
    assert ".vault-setting-row {" in drawer
    assert ".vault-settings-section-host input" in drawer
    assert ".vault-settings-section-host select" in drawer
    assert ".vault-settings-section-host textarea" in drawer
    assert ".vault-settings-section-host button" in drawer

    # The dark design-system palette (same tokens as the rest of the drawer).
    section_styles = drawer[drawer.index(".vault-setting-row {") :]
    assert "var(--bg-raised" in section_styles
    assert "var(--fg-1" in section_styles

    # No control on the page carries an inline white background on the dark theme.
    for white in (
        "background: white",
        "background:#fff",
        "background: #fff",
        "background:white",
    ):
        assert white not in html, (
            f"the relocated vault editor must not carry inline {white!r} (#2590 P2b)"
        )
