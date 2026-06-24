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
    assert "root.querySelector('[data-testid=\"vault-reload\"]')" not in script
    assert (
        "event.target.closest('[data-testid=\"vault-reload\"]')" in script
    ), "the Reload button must be handled via document-delegated click"

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
