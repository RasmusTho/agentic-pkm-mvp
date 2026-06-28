"""Vault settings panel client defaults/parsing wiring (#2016).

The 2026-06-14 review-comment closure audit (parent #1984) flagged two
client-side defects in ``vault_settings_panel.py``:

- ``reload()`` discarded the fetched projection and was not invoked on initial
  load, leaving the no-vault default panel even when a vault was selected; and
- structured (``array``/``object``) settings risked posting a raw string,
  400ing valid ``workflowStatuses`` edits.

These tests pin the fixed behavior: the panel applies the fetched projection
on load and after actions (served as a same-origin fragment the page server
renders from the runtime projection), and structured values are parsed to JSON
before the write POST. The render helper stays pure (constraint); the wiring is
asserted through the page server's fragment route and the controller script.
"""

from __future__ import annotations

import io
import json
import re
from typing import Any

from tests.companion_ui._visible_text import visible_text as _visible_text

from companion_ui.workspace.serve_dev_page import make_handler
from companion_ui.workspace.vault_settings_panel import (
    VAULT_SETTINGS_ENDPOINT,
    VAULT_SETTINGS_FRAGMENT_PICKER_PARAM,
    VAULT_SETTINGS_FRAGMENT_ROUTE,
    vault_settings_panel_fragment,
    vault_settings_panel_markup,
    vault_settings_panel_script,
)

# The front-door no-vault picker tags its fragment fetch with the picker marker;
# the hidden settings drawer fetches the bare route (#2485 drawer-scope).
_FRONT_DOOR_FRAGMENT_ROUTE = (
    f"{VAULT_SETTINGS_FRAGMENT_ROUTE}?{VAULT_SETTINGS_FRAGMENT_PICKER_PARAM}=1"
)


class _FakeClient:
    def __init__(self, get_responses: dict[str, Any] | None = None) -> None:
        self.get_responses = get_responses or {}
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append((url, params))
        return self.get_responses.get(url, {})


def _drive_get(handler_cls: type, path: str) -> bytes:
    instance = handler_cls.__new__(handler_cls)
    instance.path = path
    instance.headers = {}
    chunks: list[bytes] = []
    instance.wfile = io.BytesIO()
    instance.wfile.write = chunks.append  # type: ignore[method-assign]
    instance.send_response = lambda *_: None  # type: ignore[method-assign]
    instance.send_header = lambda *_: None  # type: ignore[method-assign]
    instance.end_headers = lambda: None  # type: ignore[method-assign]
    instance.do_GET()
    return b"".join(chunks)


def _selected_projection() -> dict[str, Any]:
    return {
        "context": {
            "status": "selected",
            "active_vault_name": "my-selected-vault",
            "active_vault_path": "/vaults/selected",
            "machine_role": "primary",
            "permissions": {"writeMarkdownSettings": True},
        },
        "definitions": [
            {
                "key": "workflowStatuses",
                "type": "array",
                "scope": "vault",
                "editable": True,
            }
        ],
        "settings": [
            {
                "key": "workflowStatuses",
                "value": ["todo", "doing", "done"],
                "source_file": ".vault/settings.md",
            }
        ],
        "validation_errors": [],
        "recent_vaults": [],
    }


def test_panel_renders_fetched_projection() -> None:
    """The panel applies the fetched projection on load and after actions
    (#2016 AC3): reload() re-renders from the runtime projection instead of
    discarding it, and runs on initial load."""
    projection = _selected_projection()

    # The page server serves the panel fragment rendered from the runtime
    # projection (the surface reload() swaps in).
    client = _FakeClient(get_responses={VAULT_SETTINGS_ENDPOINT: projection})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")
    body = _drive_get(handler_cls, VAULT_SETTINGS_FRAGMENT_ROUTE).decode("utf-8")
    assert client.get_calls == [(VAULT_SETTINGS_ENDPOINT, {})]
    # The served fragment reflects the fetched projection, not the no-vault
    # default — it is exactly the pure helper's output.
    assert body == vault_settings_panel_fragment(projection)
    assert 'data-testid="vault-settings-body"' in body
    assert 'data-vault-status="selected"' in body
    assert "my-selected-vault" in body
    assert 'data-testid="vault-setting-row"' in body
    assert "workflowStatuses" in body

    # An unreachable runtime renders the calm no-vault default — no fabricated
    # vault state.
    class _ErrClient(_FakeClient):
        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            from companion_ui.workspace.workspace_http_client import (
                WorkspaceClientError,
            )

            raise WorkspaceClientError("connection refused")

    err_handler = make_handler(client=_ErrClient(), api_base_url="http://runtime")
    err_body = _drive_get(err_handler, VAULT_SETTINGS_FRAGMENT_ROUTE).decode("utf-8")
    assert 'data-vault-status="none"' in err_body

    # The controller fetches the fragment and applies it on load and after
    # actions — it does not discard the projection.
    script = vault_settings_panel_script()
    assert VAULT_SETTINGS_FRAGMENT_ROUTE in script
    assert "applyFragment" in script
    # reload() is invoked on initial load.
    assert re.search(r"\breload\(\);", script), "reload() must run on initial load"
    # Every action chains through reload() so the panel re-renders after it.
    assert ".then(reload)" in script
    # Controls inside the swapped body (Reload button, recent-vault buttons)
    # use delegated handling so they survive the fragment swap — a directly
    # attached listener would be lost after the first reload (#2016 Codex).
    # #2590 Codex P2a: the delegate is bound to the controller's OWN root, NOT
    # document — applyFragment() never replaces root, so a root-scoped delegate
    # still survives the body swap, while a document-wide one would also catch
    # the sibling Choose-a-vault picker overlay's reload/select/initialize and
    # double-fire the shared vault intents.
    assert "root.querySelector('[data-testid=\"vault-reload\"]')" not in script
    assert (
        "event.target.closest('[data-testid=\"vault-reload\"]')" in script
    ), "the Reload button must still be handled via event delegation"
    assert "root.addEventListener('click'" in script, (
        "click delegation must be scoped to root, not document (#2590 P2a)"
    )
    assert "document.addEventListener('click'" not in script, (
        "no document-wide click delegate may catch the picker overlay (#2590 P2a)"
    )

    # The initial server-rendered panel also carries the fragment route and the
    # applied projection so the first paint already reflects the vault context.
    markup = vault_settings_panel_markup(projection)
    assert f'data-fragment-path="{VAULT_SETTINGS_FRAGMENT_ROUTE}"' in markup
    assert "my-selected-vault" in markup
    assert 'data-vault-status="selected"' in markup


def test_recents_empty_state_no_raw_unknown() -> None:
    """Recents with no known label render a calm empty state, never the literal
    "unknown / unknown" (#2485 D1).

    A recent-vault entry can arrive with neither a ``vault_name`` nor a usable
    ``path`` (or a placeholder ``unknown`` label). The picker must render a calm
    empty-state label for that row, not surface the raw ``unknown`` token to the
    human. This asserts on *visible text* only, so a hidden data-* attribute
    cannot keep the test green while the raw word renders on screen."""
    projection = {
        "context": {"status": "none"},
        "recent_vaults": [
            {"vault_name": None, "path": None},
            {"vault_name": "unknown", "path": None},
            {"vault_name": "", "path": ""},
        ],
        "definitions": [],
        "settings": [],
        "validation_errors": [],
    }
    # The picker-mode markup is the no-vault front-door render.
    markup = vault_settings_panel_markup(projection, picker_mode=True)
    visible = _visible_text(markup)

    # No label-less recent row leaks the raw "unknown" token to the human.
    assert "unknown" not in visible, (
        "label-less recents must render a calm empty state, not raw 'unknown'"
    )
    # The recents region still renders (the affordance is preserved), and the
    # calm empty-state label is what shows for a label-less row.
    assert 'data-testid="vault-recent-vaults"' in markup
    assert "unnamed vault" in visible

    # A genuinely empty recents list keeps the existing calm prompt with no raw
    # "unknown".
    empty = vault_settings_panel_markup(
        {"context": {"status": "none"}, "recent_vaults": []}, picker_mode=True
    )
    assert "unknown" not in _visible_text(empty)


def test_structured_value_parsed_before_post() -> None:
    """Structured (array/object) settings post parsed JSON, not a raw string
    (#2016 AC4)."""
    script = vault_settings_panel_script()

    # parseSettingValue parses array/object setting types from the textarea
    # JSON before the write POST; it does not forward the raw string.
    assert "function parseSettingValue" in script
    assert "JSON.parse(raw" in script
    assert "settingType === 'array' || settingType === 'object'" in script

    # The write path calls parseSettingValue and posts its parsed result.
    assert "value = parseSettingValue(form, input)" in script
    assert "JSON.stringify({ key: key, value: value })" in script

    # Invalid JSON for a structured value is surfaced and the post is aborted —
    # never silently posted as a raw string.
    assert "invalid JSON for" in script
    # The structured types are rendered as a JSON textarea so the round-trip is
    # parse-able JSON, not a free-form string field.
    array_projection = {
        "context": {"status": "selected"},
        "definitions": [
            {"key": "workflowStatuses", "type": "array", "editable": True}
        ],
        "settings": [
            {"key": "workflowStatuses", "value": ["a", "b"]}
        ],
    }
    markup = vault_settings_panel_markup(array_projection)
    textarea = re.search(
        r'<textarea[^>]*data-testid="vault-setting-input-workflowStatuses"[^>]*>'
        r"(.*?)</textarea>",
        markup,
        re.S,
    )
    assert textarea, "array settings render as a JSON textarea"
    # The JSON round-trips through the textarea (HTML-escaped in the markup).
    import html as _html

    assert ["a", "b"] == json.loads(_html.unescape(textarea.group(1)))


# ---------------------------------------------------------------------------
# D1 (#2485): the no-vault picker presentation must survive the
# /vault-settings fragment reload path for *every* "no active vault" status,
# not just ``none``.
#
# Codex P2 (re-trigger of #2485): the front-door picker open/init/reload swap
# re-fetches the /vault-settings fragment; that follow-up projection can carry
# ``status == "missing"`` (selected path gone) or ``status == "uninitialized"``
# (settings files absent). The first cut set ``picker_mode`` only for
# ``status == "none"``, so the reload fell back to the regular settings panel
# for missing/uninitialized — re-rendering the extra status header plus the raw
# "unknown / unknown" identity spans under the no-vault hero, undoing the
# single-surface / no-raw-unknown D1 guarantee after open/init/reload.
#
# This pins the fix: the fragment route renders the single DS picker surface
# for the full canonical no-active-vault set. Presentation-only — the route
# never re-classifies status, and selection/init/reload *semantics* stay
# #2312's domain.
# ---------------------------------------------------------------------------


def _no_vault_projection(status: str) -> dict[str, Any]:
    """A /vault-settings projection for a no-active-vault status.

    The context carries no selected vault, so the non-picker render path would
    default the identity spans to the literal "unknown" tokens — exactly what
    the picker presentation must suppress on the reload path.
    """
    return {
        "context": {"status": status},
        "definitions": [],
        "settings": [],
        "validation_errors": [],
        # A label-less recent that the non-picker path would render as
        # "unknown / unknown".
        "recent_vaults": [{"vault_name": None, "path": None}],
    }


def test_fragment_reload_keeps_picker_for_all_no_vault_statuses() -> None:
    """The /vault-settings fragment renders the single DS picker surface for
    every no-active-vault status (none / missing / uninitialized), so the D1
    single-surface guarantee holds across the open/init/reload swap — not only
    on first paint (#2485 Codex picker-mode-reload).

    Asserted on the page server's real fragment route (the surface the
    controller swaps in) and on *visible text* via the parser-based stripper,
    so the test cannot stay green on the ``none``-only render: it was confirmed
    RED for ``missing`` / ``uninitialized`` before the fix.
    """
    for status in ("none", "missing", "uninitialized"):
        projection = _no_vault_projection(status)
        client = _FakeClient(get_responses={VAULT_SETTINGS_ENDPOINT: projection})
        handler_cls = make_handler(client=client, api_base_url="http://runtime")
        # The front-door picker tags its fetch with the picker marker (the drawer
        # path is covered separately, below): only the marked request may fold
        # into picker_mode (#2485 drawer-scope).
        body = _drive_get(handler_cls, _FRONT_DOOR_FRAGMENT_ROUTE).decode("utf-8")

        # The fragment is the single picker surface: it is exactly the pure
        # helper's picker-mode output (no regular settings panel fallback).
        assert body == vault_settings_panel_fragment(projection, picker_mode=True), (
            f"status {status!r}: fragment reload must render the picker surface"
        )

        visible = _visible_text(body)

        # No raw "unknown" identity/recent token leaks to the human — the
        # picker suppresses the identity spans the non-picker path would emit.
        assert "unknown" not in visible, (
            f"status {status!r}: no literal 'unknown' may show on the reload picker"
        )

        # The duplicate status header is suppressed: in picker mode the hero
        # owns the single heading, so the panel emits no status-label header.
        assert 'data-testid="vault-status-label"' not in body, (
            f"status {status!r}: the reload picker must not re-render a status header"
        )

        # No default-browser select/checkbox setting chrome leaks in: there is
        # no selected vault, so the settings editor renders no fields.
        assert 'data-testid="vault-setting-row"' not in body, (
            f"status {status!r}: no settings-editor fields on the no-vault picker"
        )

        # Picker affordances are all preserved (presentation-only).
        assert 'data-testid="vault-open-form"' in body
        assert 'data-testid="vault-init-form"' in body
        assert 'data-testid="vault-recent-vaults"' in body
        assert 'data-testid="vault-settings-folder-open"' in body
        # The fragment carries the no-vault status it was given (never
        # re-classified by the route).
        assert f'data-vault-status="{status}"' in body


def test_drawer_fragment_keeps_self_contained_panel_on_no_active_status() -> None:
    """The /vault-settings fragment fetched WITHOUT the front-door picker marker
    (i.e. the hidden settings drawer's reload of the same route) must render the
    self-contained calm panel — status header + identity context preserved — for
    a no-active / empty status, NEVER the headless front-door picker (#2485 Codex
    drawer-scope finding).

    Regression: this PR's first cut set ``picker_mode`` for EVERY no-active
    fragment response, so a drawer fetch that failed (``data = {}`` → status
    defaults to ``none``) or transiently returned a no-active status collapsed
    the drawer into the headless open/init picker, dropping its status header and
    context. Confirmed RED before the marker-scoping fix (the drawer path got
    picker_mode); GREEN after.

    Asserted on the page server's real fragment route (the surface the controller
    swaps in), driving the bare route (no ``?picker=1``) and — for the failure
    case — an unreachable client so ``data`` defaults to ``{}`` → status ``none``.
    """
    no_active_statuses = ("none", "missing", "uninitialized")

    # 1) Drawer reload of a no-active projection (bare route): self-contained
    #    panel, NOT picker_mode.
    for status in no_active_statuses:
        projection = _no_vault_projection(status)
        client = _FakeClient(get_responses={VAULT_SETTINGS_ENDPOINT: projection})
        handler_cls = make_handler(client=client, api_base_url="http://runtime")
        body = _drive_get(handler_cls, VAULT_SETTINGS_FRAGMENT_ROUTE).decode("utf-8")

        # The drawer fragment is exactly the pure helper's *non-picker* output:
        # the self-contained calm panel, not the folded front-door picker.
        assert body == vault_settings_panel_fragment(projection, picker_mode=False), (
            f"status {status!r}: drawer fragment must stay the self-contained panel"
        )
        # The self-contained panel keeps its status header (which the headless
        # picker suppresses).
        assert 'data-testid="vault-status-label"' in body, (
            f"status {status!r}: drawer panel must keep its status header"
        )
        # The fragment carries the no-vault status it was given (never
        # re-classified by the route).
        assert f'data-vault-status="{status}"' in body
        # And it is NOT the front-door picker the marked route would render.
        assert body != vault_settings_panel_fragment(projection, picker_mode=True)

    # 2) Drawer reload whose fetch FAILS: data defaults to {} → status "none";
    #    still the self-contained calm panel, never the headless picker.
    class _ErrClient(_FakeClient):
        def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
            from companion_ui.workspace.workspace_http_client import (
                WorkspaceClientError,
            )

            raise WorkspaceClientError("connection refused")

    err_handler = make_handler(client=_ErrClient(), api_base_url="http://runtime")
    err_body = _drive_get(err_handler, VAULT_SETTINGS_FRAGMENT_ROUTE).decode("utf-8")
    assert err_body == vault_settings_panel_fragment({}, picker_mode=False)
    assert 'data-testid="vault-status-label"' in err_body, (
        "drawer fetch-failure panel must keep its status header (calm panel, "
        "not the headless picker)"
    )
    assert 'data-vault-status="none"' in err_body

    # 3) Same failure on the FRONT-DOOR marked route still folds into picker_mode
    #    (the round-1/round-2 single-surface behaviour is not regressed).
    front_door_err_handler = make_handler(
        client=_ErrClient(), api_base_url="http://runtime"
    )
    front_door_err_body = _drive_get(
        front_door_err_handler, _FRONT_DOOR_FRAGMENT_ROUTE
    ).decode("utf-8")
    assert front_door_err_body == vault_settings_panel_fragment({}, picker_mode=True)
    assert 'data-testid="vault-status-label"' not in front_door_err_body, (
        "front-door picker suppresses the status header even on fetch failure"
    )

    # 4) The two render entrypoints tag their fragment path correctly: the inline
    #    front-door picker carries the marker; the hidden drawer does not.
    no_active = _no_vault_projection("none")
    picker_markup = vault_settings_panel_markup(no_active, picker_mode=True)
    drawer_markup = vault_settings_panel_markup(
        _selected_projection(), hidden_by_default=True, picker_mode=False
    )
    assert f'data-fragment-path="{_FRONT_DOOR_FRAGMENT_ROUTE}"' in picker_markup
    assert f'data-fragment-path="{VAULT_SETTINGS_FRAGMENT_ROUTE}"' in drawer_markup
    assert VAULT_SETTINGS_FRAGMENT_PICKER_PARAM not in drawer_markup


# ---------------------------------------------------------------------------
# D1 (#2485): Codex round 2 — the picker surface must NOT regrow the Markdown
# settings editor (default-browser <form> chrome / inputs / Save buttons) even
# when the projection carries non-empty ``definitions``.
#
# The real /vault-settings endpoint builds ``definitions`` from the registry
# for EVERY status, including none/missing/uninitialized. The prior
# fragment-reload test only proved the picker stays single-surface for *empty*
# ``definitions`` — a static-pass / reality-fail gap: with real (non-empty)
# definitions the picker render still appended ``_settings_editor(...)``, so
# after the controller swaps the fragment in, the no-vault hero regrows
# disabled settings rows and form chrome, re-violating D1 ("no default-browser
# form chrome remains; single picker surface"). The fix suppresses
# ``_settings_editor`` entirely in picker mode.
# ---------------------------------------------------------------------------


def _no_vault_projection_with_definitions(status: str) -> dict[str, Any]:
    """A no-active-vault projection shaped like the REAL /vault-settings
    endpoint: registry-built ``definitions`` are present even with no selected
    vault. This is the reality the empty-``definitions`` tests never exercised.
    """
    return {
        "context": {"status": status},
        "definitions": [
            {
                "key": "workflowStatuses",
                "type": "array",
                "scope": "vault",
                "editable": True,
                "file": ".vault/settings.md",
            },
            {
                "key": "autoLinkOnSave",
                "type": "boolean",
                "scope": "vault",
                "editable": True,
                "file": ".vault/settings.md",
            },
        ],
        "settings": [],
        "validation_errors": [],
        "recent_vaults": [{"vault_name": None, "path": None}],
    }


def test_picker_mode_suppresses_settings_editor_with_real_definitions() -> None:
    """Picker mode never renders the Markdown settings editor, even when the
    projection carries non-empty registry ``definitions`` (the real endpoint
    shape). RED before the fix (the editor was unconditionally appended);
    GREEN after suppressing it in picker mode (#2485 D1, Codex round 2)."""
    for status in ("none", "missing", "uninitialized"):
        projection = _no_vault_projection_with_definitions(status)

        # Exercise both render entrypoints (initial markup + reload fragment).
        markup = vault_settings_panel_markup(projection, picker_mode=True)
        fragment = vault_settings_panel_fragment(projection, picker_mode=True)

        for surface_name, surface in (("markup", markup), ("fragment", fragment)):
            # No settings-editor container and no per-setting form rows.
            assert 'data-testid="vault-settings-editor"' not in surface, (
                f"{surface_name} {status!r}: no settings editor in picker mode"
            )
            assert 'data-testid="vault-setting-row"' not in surface, (
                f"{surface_name} {status!r}: no settings rows in picker mode"
            )
            # No default-browser settings-form chrome / inputs / Save buttons
            # for the registry definitions.
            assert 'class="vault-setting-row"' not in surface
            assert "vault.settings.write" not in surface, (
                f"{surface_name} {status!r}: no settings-write form chrome"
            )
            assert 'data-testid="vault-setting-input-workflowStatuses"' not in surface
            assert 'data-testid="vault-setting-input-autoLinkOnSave"' not in surface
            assert 'data-testid="vault-setting-save-workflowStatuses"' not in surface

            # No Save button leaks to the human on the picker surface.
            assert ">save</" not in _visible_text(surface), (
                f"{surface_name} {status!r}: no settings 'Save' button visible"
            )

            # Picker affordances are all preserved (presentation-only).
            assert 'data-testid="vault-open-form"' in surface
            assert 'data-testid="vault-init-form"' in surface
            assert 'data-testid="vault-recent-vaults"' in surface
            assert 'data-testid="vault-settings-folder-open"' in surface


def test_selected_vault_still_renders_settings_editor() -> None:
    """Suppressing the editor is scoped to picker mode only: a selected vault
    (non-picker render) still renders the Markdown settings editor unchanged
    (#2485 D1, Codex round 2 — guard against over-suppression)."""
    markup = vault_settings_panel_markup(_selected_projection())
    assert 'data-testid="vault-settings-editor"' in markup
    assert 'data-testid="vault-setting-row"' in markup
    assert 'data-testid="vault-setting-input-workflowStatuses"' in markup


def test_no_vault_picker_page_has_no_separating_margin() -> None:
    """The picker hero + folded panel render as ONE continuous surface: the
    consolidated head-level ``.vault-selection-required`` rule (``margin: 0
    auto``) is the sole rule, and the old separating section-local
    ``margin: 48px auto`` is gone (#2485 D1, Codex round 2 CSS finding).

    Before the fix a section-local ``<style>`` with the SAME specificity was
    emitted in the body *after* the head rule, so its ``margin: 48px auto`` won
    on source order and separated the panel from the hero.
    """
    from companion_ui.workspace.serve_dev_page import render_index_html

    payload = {
        "state": "vault_selection_required",
        "reason": "no_vault_bound",
        "message": "No vault is selected. Open a vault to continue.",
        "configured_vault_root": "/Users/me/Vaults/Niflheim",
        "requested_note_path": "",
        "context": {"status": "none"},
        "recent_vaults": [],
        "actions": [],
    }
    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="",
        vault_selection_required=payload,
    )
    # The old separating margin is gone everywhere on the no-vault page.
    assert "margin: 48px auto" not in html, (
        "the separating 48px section margin must not reappear on the picker"
    )
    # The consolidated continuous-surface rule is present.
    assert "margin: 0 auto" in html


def test_init_form_surfaces_nonempty_confirm_gesture() -> None:
    """The init form surfaces an in-band confirm gesture for the non-empty 409 (#2518).

    Initializing a non-empty existing folder returns
    ``409 vault_init_confirmation_required``. The controller must NOT swallow
    that as a generic submit error: the init submit has its own confirm-aware
    path that reads the structured response, renders a confirm affordance
    carrying the server message, and re-submits the init with ``confirm: true``
    only after the human confirms. A first (unconfirmed) submit forces no
    confirm, so an empty/new target is unaffected (preserves #2312 AC1).
    """
    script = vault_settings_panel_script()

    # The init submit is a dedicated, confirm-aware path (not the generic
    # jsonFetch(...).then(reload) the select form uses).
    assert "function submitVaultInitialize" in script
    # It reads the structured 409 reason rather than treating every non-ok
    # response as an opaque submit error.
    assert "vault_init_confirmation_required" in script
    assert "res.status === 409" in script
    # It renders an in-band confirm affordance (container + message + confirm
    # control) instead of failing silently. The container testid appears in the
    # querySelector form; the message/submit testids appear as setAttribute
    # values.
    assert 'data-testid="vault-init-confirm"' in script
    assert "vault-init-confirm-message" in script
    assert "vault-init-confirm-submit" in script
    # The confirm control re-submits the init with confirm:true, and the flag is
    # one-shot (cleared each submit) so changing the path re-warns.
    assert "payload.confirm = true" in script
    assert "data-init-confirmed" in script

    # Codex #2520 P1: the confirmation is bound to the exact path it was shown
    # for. confirm:true is sent only when the stored confirm-path matches the
    # path now being submitted, so editing the path after a 409 and clicking the
    # stale Confirm re-warns for the new folder instead of bypassing the guard.
    assert "data-init-confirm-path" in script
    assert "confirmedFor === basePayload.path" in script

    # The select form keeps the generic reload-chaining path (init's dedicated
    # path must not remove it): an action still chains through reload().
    assert ".then(reload)" in script


# ---------------------------------------------------------------------------
# #2590: the loaded-note vault drawer is brought into the Choose-a-vault idiom.
# The "V" chip opens the reused switch overlay (no typed-path/Role chrome); the
# scoped-settings editor relocates to the Settings drawer's vault section and
# still posts vault.settings.write with the #2518 confirm preserved. Coverage is
# RE-HOMED, not dropped.
# ---------------------------------------------------------------------------


def _loaded_note_fields() -> dict[str, Any]:
    return {
        "title": "Loaded Note",
        "note_path": "Notes/loaded.md",
        "artifact_id": "art-loaded",
        "artifact_kind": "human_note",
        "content_hash": "sha256-loaded",
        "body": "# Loaded\n\nbody",
        "panel_rail": "rail",
        "runtime_vault_name": "Niflheim",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "guard_canvas_enabled": True,
    }


def test_loaded_note_vault_surface_uses_switch_overlay_not_foreign_form() -> None:
    """The "V" chip opens the reused Choose-a-vault switch overlay; the retired
    foreign-form drawer (typed open/init paths, Role select, the old toggle) is
    gone from the loaded-note path."""
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(
        api_base_url="http://runtime",
        note_path="Notes/loaded.md",
        fields=_loaded_note_fields(),
    )

    # The chip retargets to the switch overlay (one graphical language).
    assert 'data-intent="vault.switch.open"' in html
    assert 'data-intent="vault.settings.open"' not in html
    assert 'aria-controls="workspace-vault-switch-host"' in html

    # The reused Choose-a-vault overlay is hosted (hidden) as the switch surface.
    assert 'data-testid="vault-switch-host"' in html
    assert 'data-testid="vault-selection-required"' in html
    assert 'data-reason="switch"' in html
    assert 'data-testid="vault-picker"' in html

    # The retired foreign-form drawer + its chrome are gone from the page.
    assert '<section class="vault-settings-panel"' not in html
    assert "window.companionVaultSettings" not in html
    assert 'data-testid="vault-open-path"' not in html
    assert 'data-testid="vault-init-path"' not in html
    assert 'data-testid="vault-init-role"' not in html


def test_settings_only_fragment_serves_editor_without_foreign_chrome() -> None:
    """The Settings-drawer vault section tags its fragment fetch with the
    settings-scope marker; the route returns the scoped-settings editor only —
    no typed-path/Role/init/reload/recents/identity chrome — and the
    vault.settings.write Save still posts to the settings endpoint."""
    from companion_ui.workspace.vault_settings_panel import (
        VAULT_SETTINGS_FRAGMENT_SETTINGS_PARAM,
        VAULT_SETTINGS_FRAGMENT_SETTINGS_VALUE,
    )

    projection = _selected_projection()
    client = _FakeClient(get_responses={VAULT_SETTINGS_ENDPOINT: projection})
    handler_cls = make_handler(client=client, api_base_url="http://runtime")
    settings_route = (
        f"{VAULT_SETTINGS_FRAGMENT_ROUTE}"
        f"?{VAULT_SETTINGS_FRAGMENT_SETTINGS_PARAM}={VAULT_SETTINGS_FRAGMENT_SETTINGS_VALUE}"
    )
    body = _drive_get(handler_cls, settings_route).decode("utf-8")

    # The settings-scope fragment equals the settings_only render — editor only.
    assert body == vault_settings_panel_fragment(projection, settings_only=True)
    assert 'data-testid="vault-settings-body"' in body
    assert 'data-testid="vault-setting-row"' in body
    assert f'data-api-path="{VAULT_SETTINGS_ENDPOINT}"' in body
    assert "workflowStatuses" in body

    # No switch / foreign-form chrome leaks onto the settings surface.
    assert 'data-testid="vault-open-path"' not in body
    assert 'data-testid="vault-init-path"' not in body
    assert 'data-testid="vault-init-role"' not in body
    assert 'data-testid="vault-recent-vaults"' not in body
    assert 'data-testid="vault-settings-identity"' not in body


# ---------------------------------------------------------------------------
# #2590 Codex P2a: on a loaded note BOTH the Choose-a-vault picker controller
# and the relocated-settings write controller are emitted. The picker overlay
# carries its OWN vault.select / vault.initialize / vault.reload buttons; the
# settings write controller must NOT also catch them (a document-wide delegate
# would double-fire the shared vault intents, e.g. two POST /vault/reload). The
# settings controller's delegated handlers are therefore scoped to its own root
# (the relocated drawer section, a SIBLING of the picker overlay), so the picker
# controller is the SOLE owner of select/initialize/reload in the switch overlay.
# ---------------------------------------------------------------------------


def test_settings_controller_delegates_on_own_root_not_document() -> None:
    """The write controller binds its submit/click delegates to ``root`` (its
    own section), never to ``document`` — so it cannot catch the sibling picker
    overlay's reload/select/initialize buttons (#2590 P2a)."""
    script = vault_settings_panel_script()

    # Delegation is bound to the controller's resolved root, not document.
    assert "root.addEventListener('submit'" in script
    assert "root.addEventListener('click'" in script
    assert "document.addEventListener('submit'" not in script, (
        "submit delegation must be root-scoped, not document-wide (#2590 P2a)"
    )
    assert "document.addEventListener('click'" not in script, (
        "click delegation must be root-scoped, not document-wide (#2590 P2a)"
    )

    # The reload button is still handled via delegation (survives the body swap)
    # — just on root, since applyFragment() never replaces root itself.
    assert "event.target.closest('[data-testid=\"vault-reload\"]')" in script


def test_loaded_note_picker_overlay_owns_reload_solely() -> None:
    """On a loaded-note page the switch overlay's reload (and select/initialize)
    is wired to exactly ONE controller (#2590 P2a).

    BOTH controllers are emitted on a loaded note. The picker controller scopes
    its click handler to the overlay element (``picker.addEventListener``); the
    settings write controller scopes its handlers to its own ``root``. Because
    the overlay and the relocated settings section are SIBLING subtrees, no
    settings-controller delegate can fire for an overlay button — so the overlay
    reload posts ``/vault/reload`` once, not twice.
    """
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(
        api_base_url="http://runtime",
        note_path="Notes/loaded.md",
        fields=_loaded_note_fields(),
    )

    # Both controllers are present on the loaded note.
    assert "vault-picker-controller" in html
    assert "vault-settings-panel-controller" in html

    # The picker controller owns the overlay reload via an overlay-scoped click
    # handler (picker.addEventListener), NOT document.
    assert "picker.addEventListener('click'" in html

    # Isolate the settings write controller's script block — the page also emits
    # an unrelated vault-switch-reveal handler that legitimately listens on
    # document for the V-chip's vault.switch.open trigger (it only opens/closes
    # the overlay; it never fires a vault intent). The relevant guarantee is that
    # the SETTINGS WRITE controller's reload/select/initialize delegates are NOT
    # document-wide (that is what would double-fire).
    settings_controller = html[
        html.index("/* vault-settings-panel-controller */") : html.index(
            "/* /vault-settings-panel-controller */"
        )
    ]
    assert "document.addEventListener('click'" not in settings_controller, (
        "a document-wide click delegate would double-fire the picker overlay's "
        "reload/select (#2590 P2a)"
    )
    assert "document.addEventListener('submit'" not in settings_controller, (
        "a document-wide submit delegate would double-fire the picker overlay's "
        "select/initialize (#2590 P2a)"
    )

    # The settings controller's delegates are scoped to its own root instead.
    assert "root.addEventListener('click'" in settings_controller
    assert "root.addEventListener('submit'" in settings_controller


# ---------------------------------------------------------------------------
# #2590 Codex P2b: the relocated scoped-settings editor (now in the Settings
# drawer's vault section) must carry the editor styles wherever it renders, or
# it falls back to default-browser white chrome on the dark theme. The
# ``.vault-setting-row`` grid + dark input/select/textarea/button palette must
# resolve under the new drawer host (``.vault-settings-section-host``), and no
# control may render an inline white background.
# ---------------------------------------------------------------------------


def test_relocated_settings_section_carries_dark_editor_styles() -> None:
    """The relocated Settings -> Vault section emits the scoped-settings editor
    styles targeting the drawer host, with no default white chrome (#2590 P2b)."""
    from companion_ui.workspace.vault_settings_panel import (
        vault_settings_section_markup,
    )

    section = vault_settings_section_markup(_selected_projection())

    # The section carries its own editor style block (loaded-note pages no
    # longer render vault_settings_panel_markup's block).
    assert "<style>" in section

    # The .vault-setting-row grid + dark palette resolve under the NEW drawer
    # host, not only the retired .vault-settings-panel host.
    assert ".vault-setting-row {" in section
    assert ".vault-settings-section-host input" in section
    assert ".vault-settings-section-host select" in section
    assert ".vault-settings-section-host textarea" in section
    assert ".vault-settings-section-host button" in section

    # The palette is the single design-system dark palette (same tokens the
    # no-vault picker's settings use) — not a fork.
    assert "var(--bg-raised" in section
    assert "var(--fg-1" in section

    # No control renders an inline white background on the dark theme (mirrors
    # the settings-drawer no-white-chrome assertion).
    for white in (
        "background: white",
        "background:#fff",
        "background: #fff",
        "background:white",
    ):
        assert white not in section, (
            f"the relocated editor must not carry inline {white!r} on the dark theme"
        )


def test_loaded_note_page_dresses_relocated_editor_no_white_chrome() -> None:
    """End-to-end on a loaded-note page: the relocated editor's dark palette is
    present under the drawer host and no input leaks white chrome (#2590 P2b)."""
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(
        api_base_url="http://runtime",
        note_path="Notes/loaded.md",
        fields=_loaded_note_fields(),
    )

    # The relocated editor host renders inside the drawer with the dark palette.
    assert 'data-testid="vault-settings-section"' in html
    assert ".vault-settings-section-host input" in html
    assert ".vault-settings-section-host button" in html

    # No input/button anywhere on the page carries an inline white background.
    for white in (
        "background: white",
        "background:#fff",
        "background: #fff",
        "background:white",
    ):
        assert white not in html, (
            f"no control may carry inline {white!r} on the dark theme (#2590 P2b)"
        )
