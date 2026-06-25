"""Vault selector and scoped Markdown settings panel for Companion UI.

This module renders controls only. Vault selection, initialization, reload,
permission checks, and Markdown settings writes are owned by the runtime API.
"""

from __future__ import annotations

import html as _html
import json
from typing import Any


VAULT_SETTINGS_ENDPOINT = "/api/companion/vault/settings"
VAULT_SELECT_ENDPOINT = "/api/companion/vault/select"
VAULT_INITIALIZE_ENDPOINT = "/api/companion/vault/initialize"
VAULT_RELOAD_ENDPOINT = "/api/companion/vault/reload"

# Page-server route serving the server-rendered panel fragment (the
# /memory-review precedent). The controller fetches this after load and after
# every action so the rendered panel reflects the fetched projection instead of
# discarding it; rendering stays a pure, testable Python function.
VAULT_SETTINGS_FRAGMENT_ROUTE = "/vault-settings"

# Query marker the front-door no-vault picker appends to its fragment fetch so
# the page server can distinguish *its* reload from the hidden settings drawer's
# reload of the same route (#2485 Codex drawer-scope finding). Both surfaces
# share VAULT_SETTINGS_FRAGMENT_ROUTE, but only the inline front-door picker may
# fold the panel into picker_mode on a no-active status. The drawer — which only
# legitimately opens over a selected vault — must keep its self-contained calm
# panel (status header + context preserved) on a fetch failure / transient
# no-active response, never collapse into the headless picker. Presentation-only
# marker; it never re-classifies status or changes open/init/reload semantics
# (#2312).
VAULT_SETTINGS_FRAGMENT_PICKER_PARAM = "picker"

# Canonical set of runtime vault statuses that mean "no active vault is bound".
# Each of these resolves to the no-vault front-door picker surface (#2485 D1):
# the single DS picker with no legacy settings form, no duplicate "No vault
# selected" heading, and no raw ``unknown`` identity spans. The front-door
# render *and* the /vault-settings fragment reload path must agree on this set
# so the single-surface guarantee survives open/init/reload, not just first
# paint. Selection/init/reload *semantics* are owned by the runtime (#2312);
# this constant only governs which statuses get the picker *presentation*.
NO_ACTIVE_VAULT_STATUSES = frozenset({"none", "missing", "uninitialized"})


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _setting_value(settings: dict[str, dict[str, Any]], key: str) -> Any:
    record = settings.get(key) or {}
    return record.get("value")


def _status_copy(status: str) -> tuple[str, str]:
    return {
        "none": ("No vault selected", "Open an existing vault or initialize a new one."),
        "selected": ("Vault selected", "Scoped settings are loaded from Markdown files."),
        "missing": ("Vault missing", "The selected path does not exist."),
        "uninitialized": ("Vault uninitialized", "Initialize missing settings files before editing."),
        "invalid": ("Vault invalid", "Resolve the settings error, then reload."),
    }.get(status, ("Vault status unknown", "Reload the runtime vault context."))


def _recent_label(item: dict[str, Any]) -> str:
    """Calm visible label for a recent-vault row.

    A recent entry can arrive with no known name and no usable path (or a
    placeholder ``unknown`` label). Rather than surface the raw ``unknown``
    token to the human, render a calm empty-state label (#2485 D1). Behaviour
    (the ``data-vault-path`` the row selects) is unchanged.
    """
    name = str(item.get("vault_name") or "").strip()
    if name and name.lower() != "unknown":
        return name
    path = str(item.get("path") or "").strip()
    if path:
        return path
    return "Unnamed vault"


def _recent_vaults(recent_vaults: list[dict[str, Any]]) -> str:
    if not recent_vaults:
        return (
            '<div class="vault-recent-vaults" data-testid="vault-recent-vaults" '
            'data-count="0"><span>Open recent vault</span></div>'
        )
    rows = "".join(
        f"""
        <button type="button" class="vault-recent-vault"
          data-testid="vault-recent-vault" data-intent="vault.select"
          data-api-method="POST" data-api-path="{VAULT_SELECT_ENDPOINT}"
          data-vault-path="{_e(item.get("path") or "")}">
          <span>{_e(_recent_label(item))}</span>
          <code>{_e(item.get("path") or "")}</code>
        </button>"""
        for item in recent_vaults
        if isinstance(item, dict)
    )
    return f'<div class="vault-recent-vaults" data-testid="vault-recent-vaults" data-count="{len(recent_vaults)}"><span>Open recent vault</span>{rows}</div>'


def _action_forms(context: dict[str, Any], recent_vaults: list[dict[str, Any]]) -> str:
    path = str(context.get("active_vault_path") or "")
    can_initialize = str(context.get("status") or "") in NO_ACTIVE_VAULT_STATUSES
    initialize_status = "available" if can_initialize else "disabled"
    initialize_disabled = "" if can_initialize else " disabled aria-disabled=\"true\""
    return f"""
      <section class="vault-settings-actions" data-testid="vault-settings-actions">
        <form class="vault-settings-form" data-testid="vault-open-form"
          data-intent="vault.select" data-api-method="POST"
          data-api-path="{VAULT_SELECT_ENDPOINT}">
          <label>Open existing vault
            <input data-testid="vault-open-path" name="path" value="{_e(path)}"
              autocomplete="off" placeholder="Path to an existing vault">
          </label>
          <button type="submit" data-testid="vault-open-submit">Open</button>
        </form>
        <form class="vault-settings-form" data-testid="vault-init-form"
          data-intent="vault.initialize" data-api-method="POST"
          data-api-path="{VAULT_INITIALIZE_ENDPOINT}"
          data-affordance-status="{initialize_status}">
          <label>Create/init vault
            <input data-testid="vault-init-path" name="path" value="{_e(path)}"
              autocomplete="off" placeholder="Path for a new vault">
          </label>
          <label>Role
            <select data-testid="vault-init-role" name="machineRole">
              <option value="primary">primary</option>
              <option value="satellite">satellite</option>
              <option value="readOnlySatellite">readOnlySatellite</option>
              <option value="automationNode">automationNode</option>
              <option value="testNode">testNode</option>
            </select>
          </label>
          <button type="submit" data-testid="vault-init-submit"{initialize_disabled}>Initialize</button>
        </form>
        <button type="button" data-testid="vault-reload"
          data-intent="vault.reload" data-api-method="POST"
          data-api-path="{VAULT_RELOAD_ENDPOINT}">Reload</button>
        {_recent_vaults(recent_vaults)}
      </section>"""


def _identity_rows(context: dict[str, Any], *, picker_mode: bool = False) -> str:
    # On the no-vault picker front door (picker_mode) there is, by definition,
    # no selected vault — the name/path/role identity spans would render the
    # literal "unknown / unknown" the design review flagged (#2485 D1). Suppress
    # the identity spans there and keep only the settings-folder affordance,
    # which the picker scope requires. Behaviour is unchanged; this is
    # presentation-only.
    if picker_mode:
        return f"""
      <section class="vault-settings-identity" data-testid="vault-settings-identity"
        data-picker-mode="true">
        <button type="button" data-testid="vault-settings-folder-open"
          data-intent="vault.settingsFolder.open" data-affordance-status="ui-only"
          data-settings-folder="{_e(context.get("settings_path") or "")}">Open settings folder</button>
      </section>"""
    permissions = context.get("permissions") if isinstance(context.get("permissions"), dict) else {}
    permission_rows = "".join(
        f'<span class="vault-permission" data-testid="vault-permission-{_e(key)}" '
        f'data-enabled="{str(bool(value)).lower()}">{_e(key)}: {_e(str(bool(value)).lower())}</span>'
        for key, value in permissions.items()
    )
    return f"""
      <section class="vault-settings-identity" data-testid="vault-settings-identity">
        <span data-testid="vault-name">{_e(context.get("active_vault_name") or "unknown")}</span>
        <code data-testid="vault-path">{_e(context.get("active_vault_path") or "")}</code>
        <code data-testid="vault-settings-folder">{_e(context.get("settings_path") or "")}</code>
        <span data-testid="vault-machine-role">{_e(context.get("machine_role") or "unknown")}</span>
        <div class="vault-permissions" data-testid="vault-permissions">{permission_rows}</div>
        <button type="button" data-testid="vault-settings-folder-open"
          data-intent="vault.settingsFolder.open" data-affordance-status="ui-only"
          data-settings-folder="{_e(context.get("settings_path") or "")}">Open settings folder</button>
      </section>"""


def _validation_errors(errors: list[dict[str, Any]]) -> str:
    if not errors:
        return '<div class="vault-settings-errors" data-testid="vault-settings-errors" data-count="0"></div>'
    rows = "".join(
        f'<li data-testid="vault-settings-error" data-key="{_e(error.get("key") or "")}" '
        f'data-scope="{_e(error.get("scope") or "")}">'
        f'<code>{_e(error.get("source_file") or "")}</code><span>{_e(error.get("message") or "")}</span></li>'
        for error in errors
    )
    return f'<ul class="vault-settings-errors" data-testid="vault-settings-errors" data-count="{len(errors)}">{rows}</ul>'


def _input_for_definition(definition: dict[str, Any], value: Any, disabled: bool) -> str:
    key = str(definition.get("key") or "")
    setting_type = str(definition.get("type") or "string")
    type_attr = f' data-setting-type="{_e(setting_type)}"'
    disabled_attr = ' disabled aria-disabled="true"' if disabled else ""
    if setting_type == "boolean":
        checked = " checked" if bool(value) else ""
        return (
            f'<input type="checkbox" data-testid="vault-setting-input-{_e(key)}" '
            f'name="{_e(key)}"{type_attr}{checked}{disabled_attr}>'
        )
    if definition.get("allowed_values"):
        options = "".join(
            f'<option value="{_e(option)}"{" selected" if option == value else ""}>{_e(option)}</option>'
            for option in definition.get("allowed_values") or []
        )
        return f'<select data-testid="vault-setting-input-{_e(key)}" name="{_e(key)}"{type_attr}{disabled_attr}>{options}</select>'
    if setting_type in {"array", "object"}:
        raw = json.dumps(value, ensure_ascii=False)
        return f'<textarea data-testid="vault-setting-input-{_e(key)}" name="{_e(key)}"{type_attr}{disabled_attr}>{_e(raw)}</textarea>'
    return (
        f'<input data-testid="vault-setting-input-{_e(key)}" name="{_e(key)}" '
        f'value="{_e("" if value is None else value)}"{type_attr}{disabled_attr}>'
    )


def _settings_editor(projection: dict[str, Any], status: str) -> str:
    definitions = projection.get("definitions") if isinstance(projection.get("definitions"), list) else []
    settings_list = projection.get("settings") if isinstance(projection.get("settings"), list) else []
    settings = {
        str(item.get("key")): item
        for item in settings_list
        if isinstance(item, dict) and item.get("key")
    }
    rows = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        key = str(definition.get("key") or "")
        record = settings.get(key) or {}
        editable = bool(definition.get("editable"))
        disabled = status != "selected" or not editable
        blocked = str(definition.get("write_blocked_reason") or "")
        rows.append(
            f"""
        <form class="vault-setting-row" data-testid="vault-setting-row"
          data-setting-key="{_e(key)}" data-setting-scope="{_e(definition.get("scope") or "")}"
          data-setting-type="{_e(definition.get("type") or "string")}"
          data-setting-file="{_e(definition.get("file") or "")}" data-editable="{str(editable).lower()}"
          data-blocked-reason="{_e(blocked)}" data-intent="vault.settings.write"
          data-api-method="POST" data-api-path="{VAULT_SETTINGS_ENDPOINT}">
          <label><span>{_e(key)}</span>{_input_for_definition(definition, _setting_value(settings, key), disabled)}</label>
          <code data-testid="vault-setting-source-{_e(key)}">{_e(record.get("source_file") or record.get("source") or "")}</code>
          <button type="submit" data-testid="vault-setting-save-{_e(key)}"{' disabled aria-disabled="true"' if disabled else ""}>Save</button>
          <span data-testid="vault-setting-blocked-{_e(key)}">{_e(blocked)}</span>
        </form>"""
        )
    return f'<section class="vault-settings-editor" data-testid="vault-settings-editor">{"".join(rows)}</section>'


def _panel_body(projection: dict[str, Any], *, picker_mode: bool = False) -> str:
    """Inner panel content rendered from the fetched projection.

    Shared by :func:`vault_settings_panel_markup` (initial server render) and
    :func:`vault_settings_panel_fragment` (the reload/after-action re-render),
    so the projection is applied on load and after every action — never
    discarded.

    When ``picker_mode`` is set the panel renders as the no-vault front-door
    picker folded beneath the styled ``vault-selection-required`` hero
    (#2485 D1). The hero already owns the single "No vault selected" heading, so
    the panel's own status header is suppressed to avoid a duplicate heading,
    and the identity spans (which would read "unknown / unknown" with no vault)
    are suppressed too. The open / init / recents / settings-folder affordances
    all still render — this is presentation-only and does not change picker
    behaviour (that is #2312's domain).
    """
    context = projection.get("context") if isinstance(projection.get("context"), dict) else {"status": "none"}
    status = str(context.get("status") or "none")
    title, summary = _status_copy(status)
    errors = projection.get("validation_errors") if isinstance(projection.get("validation_errors"), list) else []
    recent_vaults = projection.get("recent_vaults") if isinstance(projection.get("recent_vaults"), list) else []
    # The hero owns the single "No vault selected" heading in picker mode; emit
    # no second status header here.
    head = (
        ""
        if picker_mode
        else f"""
    <header class="vault-settings-head" data-testid="vault-settings-head">
      <span data-testid="vault-status-label">{_e(title)}</span>
      <p data-testid="vault-status-summary">{_e(summary)}</p>
      <p data-testid="vault-validation-error">{_e(context.get("validation_error") or "")}</p>
    </header>"""
    )
    # The no-vault picker surface (picker_mode) is the single front-door DS
    # picker: open / init / recents / settings-folder affordances only. The
    # Markdown settings editor (default-browser ``<form>`` chrome, inputs,
    # Save buttons) belongs to a *selected* vault. The real /vault-settings
    # endpoint builds ``definitions`` from the registry even for
    # none/missing/uninitialized, so rendering ``_settings_editor`` in picker
    # mode would regrow disabled settings rows / form chrome into the hero
    # after every fragment reload — re-violating #2485 D1 ("no default-browser
    # form chrome remains"). Suppress it entirely here; selected-vault
    # rendering is unchanged.
    editor = "" if picker_mode else _settings_editor(projection, status)
    return f"""{head}
    {_action_forms(context, recent_vaults)}
    {_identity_rows(context, picker_mode=picker_mode)}
    {_validation_errors(errors)}
    {editor}"""


def _panel_status(projection: dict[str, Any]) -> str:
    context = projection.get("context") if isinstance(projection.get("context"), dict) else {"status": "none"}
    return str(context.get("status") or "none")


def vault_settings_panel_fragment(
    projection: dict[str, Any] | None = None,
    *,
    picker_mode: bool = False,
) -> str:
    """Server-rendered inner panel fragment from the fetched projection.

    Served at :data:`VAULT_SETTINGS_FRAGMENT_ROUTE`; the controller swaps this
    into the panel after load and after every action so the rendered panel
    reflects the runtime projection instead of discarding it.

    ``picker_mode`` folds the panel into the no-vault picker front door: it
    drops the duplicate status heading and the "unknown" identity spans while
    preserving every picker affordance (#2485 D1).
    """
    projection = projection if isinstance(projection, dict) else {}
    return (
        '<div class="vault-settings-body" data-testid="vault-settings-body" '
        f'data-vault-status="{_e(_panel_status(projection))}">'
        f"{_panel_body(projection, picker_mode=picker_mode)}</div>"
    )


def vault_settings_panel_markup(
    projection: dict[str, Any] | None = None,
    *,
    hidden_by_default: bool = False,
    picker_mode: bool = False,
) -> str:
    projection = projection if isinstance(projection, dict) else {}
    status = _panel_status(projection)
    hidden_attrs = (
        ' hidden aria-hidden="true" inert data-default-hidden="true"'
        if hidden_by_default
        else ""
    )
    display_mode = "drawer" if hidden_by_default else "inline"
    open_state = "false" if hidden_by_default else "true"
    # Only the inline front-door picker tags its fragment fetch with the picker
    # marker; the hidden drawer fetches the bare route so a transient no-active
    # response never collapses it into the headless picker (#2485 drawer-scope).
    fragment_path = (
        f"{VAULT_SETTINGS_FRAGMENT_ROUTE}?{VAULT_SETTINGS_FRAGMENT_PICKER_PARAM}=1"
        if picker_mode
        else VAULT_SETTINGS_FRAGMENT_ROUTE
    )
    close_button = (
        """
    <button type="button" class="vault-settings-panel-close"
      data-testid="vault-settings-panel-close"
      data-intent="vault.settings.close"
      aria-label="Close vault settings"
      onclick="companionVaultSettings.close()">&times;</button>"""
        if hidden_by_default
        else ""
    )
    return f"""
  <style>
    .vault-settings-panel {{
      border-top: 1px solid var(--border, #152030);
      display: grid; gap: 12px; padding: 14px 16px;
    }}
    .vault-settings-panel[hidden] {{ display: none !important; }}
    .vault-settings-panel[data-display-mode="drawer"] {{
      background: var(--bg-surface, #0b1220);
      border: 1px solid var(--border-strong, #1e3050);
      border-radius: 8px;
      bottom: 16px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.35);
      max-width: calc(100vw - 32px);
      overflow: auto;
      position: fixed;
      right: 16px;
      top: 64px;
      width: min(520px, calc(100vw - 32px));
      z-index: 38;
    }}
    .vault-settings-panel-close {{
      justify-self: end;
      min-width: 32px;
    }}
    .vault-settings-panel code {{ overflow-wrap: anywhere; }}
    .vault-settings-actions, .vault-settings-identity, .vault-settings-editor {{
      display: grid; gap: 8px;
    }}
    .vault-settings-form, .vault-setting-row {{
      align-items: end; display: grid; gap: 8px; grid-template-columns: minmax(0, 1fr) auto;
    }}
    .vault-setting-row {{ grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; }}
    .vault-settings-panel input, .vault-settings-panel select, .vault-settings-panel textarea {{
      background: var(--bg-raised, #111a2e); border: 1px solid var(--border-strong, #1e3050);
      border-radius: 4px; color: var(--fg-1, #dce8f0); padding: 5px 8px; width: 100%;
    }}
    .vault-settings-panel button {{
      background: var(--bg-raised, #111a2e); border: 1px solid var(--border-strong, #1e3050);
      border-radius: 4px; color: var(--fg-1, #dce8f0); cursor: pointer; padding: 6px 10px;
    }}
    .vault-settings-panel button[disabled] {{ cursor: not-allowed; opacity: 0.55; }}
    .vault-permissions {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .vault-permission {{ border: 1px solid var(--border, #152030); border-radius: 4px; padding: 3px 6px; }}
    @media (max-width: 700px) {{
      .vault-settings-panel[data-display-mode="drawer"] {{
        bottom: 8px;
        max-width: none;
        right: 8px;
        top: 56px;
        width: calc(100vw - 16px);
      }}
    }}
  </style>
  <section class="vault-settings-panel" id="workspace-vault-settings-panel"
    data-testid="vault-settings-panel"{hidden_attrs}
    data-display-mode="{display_mode}" data-open="{open_state}"
    data-vault-status="{_e(status)}" data-api-path="{VAULT_SETTINGS_ENDPOINT}"
    data-fragment-path="{fragment_path}" data-api-method="GET"
    role="dialog" aria-label="Vault settings" tabindex="-1">
    {close_button}
    {vault_settings_panel_fragment(projection, picker_mode=picker_mode)}
  </section>"""


def vault_settings_panel_script() -> str:
    return f"""
  <script>
  /* vault-settings-panel-controller */
  (function() {{
    var root = document.querySelector('[data-testid="vault-settings-panel"]');
    if (!root) {{ return; }}
    function vaultSettingsTriggers() {{
      return Array.prototype.slice.call(document.querySelectorAll('[data-intent="vault.settings.open"]'));
    }}
    function syncDrawerState(open) {{
      root.setAttribute('data-open', open ? 'true' : 'false');
      vaultSettingsTriggers().forEach(function(trigger) {{
        trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
      }});
    }}
    function openDrawer() {{
      root.removeAttribute('hidden');
      root.removeAttribute('aria-hidden');
      root.removeAttribute('inert');
      syncDrawerState(true);
      try {{ root.focus(); }} catch (err) {{}}
    }}
    function closeDrawer() {{
      if (root.getAttribute('data-default-hidden') === 'true') {{
        root.setAttribute('hidden', '');
        root.setAttribute('aria-hidden', 'true');
        root.setAttribute('inert', '');
      }}
      syncDrawerState(false);
      var triggers = vaultSettingsTriggers();
      if (triggers[0]) {{ try {{ triggers[0].focus(); }} catch (err) {{}} }}
    }}
    window.companionVaultSettings = {{
      open: openDrawer,
      close: closeDrawer,
      toggle: function() {{
        if (root.hasAttribute('hidden')) {{ openDrawer(); }}
        else {{ closeDrawer(); }}
      }}
    }};
    syncDrawerState(!root.hasAttribute('hidden'));
    function jsonFetch(path, options) {{
      return fetch(path, Object.assign({{ headers: {{ 'Content-Type': 'application/json' }} }}, options || {{}}))
        .then(function(response) {{
          if (!response.ok) {{ return response.text().then(function(text) {{ throw new Error(text || response.status); }}); }}
          return response.json();
        }});
    }}
    var fragmentPath = root.getAttribute('data-fragment-path') || '{VAULT_SETTINGS_FRAGMENT_ROUTE}';
    function applyFragment(html) {{
      var body = root.querySelector('[data-testid="vault-settings-body"]');
      if (!body) {{
        body = document.createElement('div');
        body.setAttribute('data-testid', 'vault-settings-body');
        root.appendChild(body);
      }}
      body.outerHTML = html;
      var fresh = root.querySelector('[data-testid="vault-settings-body"]');
      if (fresh) {{
        var status = fresh.getAttribute('data-vault-status');
        if (status) {{ root.setAttribute('data-vault-status', status); }}
      }}
      root.removeAttribute('data-load-error');
    }}
    function reload() {{
      // Apply the fetched projection to the panel — never discard it. The
      // page server renders the panel fragment from the runtime projection;
      // the controller swaps it in on load and after every action.
      return fetch(fragmentPath, {{ method: 'GET' }})
        .then(function(response) {{
          if (!response.ok) {{ throw new Error(String(response.status)); }}
          return response.text();
        }})
        .then(applyFragment)
        .catch(function(err) {{
          root.setAttribute('data-load-error', String(err && err.message || err));
        }});
    }}
    function parseSettingValue(form, input) {{
      if (!input) {{ return null; }}
      if (input.type === 'checkbox') {{ return input.checked; }}
      var settingType = form.getAttribute('data-setting-type') || input.getAttribute('data-setting-type') || 'string';
      var raw = input.value;
      if (settingType === 'array' || settingType === 'object') {{
        try {{
          return JSON.parse(raw || (settingType === 'array' ? '[]' : '{{}}'));
        }} catch (err) {{
          form.setAttribute('data-write-error', 'invalid JSON for ' + settingType);
          throw err;
        }}
      }}
      return raw;
    }}
    // #2518: in-band confirm gesture for initializing into a NON-EMPTY folder.
    // The init endpoint returns 409 vault_init_confirmation_required when the
    // chosen folder already holds the human's content; the init submit reads
    // that structured response and surfaces a confirm affordance instead of
    // failing silently. Confirming re-submits with confirm:true (the human's
    // explicit, understood choice — a single-actor, in-band guard, not a
    // governance approval loop).
    function clearInitConfirm(form) {{
      var existing = form.querySelector('[data-testid="vault-init-confirm"]');
      if (existing && existing.parentNode) {{ existing.parentNode.removeChild(existing); }}
    }}
    function renderInitConfirm(form, detail) {{
      clearInitConfirm(form);
      var wrap = document.createElement('div');
      wrap.className = 'vault-init-confirm';
      wrap.setAttribute('data-testid', 'vault-init-confirm');
      wrap.setAttribute('role', 'alert');
      var msg = document.createElement('p');
      msg.setAttribute('data-testid', 'vault-init-confirm-message');
      msg.textContent = (detail && detail.message) || 'This folder already contains files. Initializing will add a settings/ scaffold to your existing vault.';
      var confirmButton = document.createElement('button');
      confirmButton.setAttribute('type', 'button');
      confirmButton.setAttribute('data-testid', 'vault-init-confirm-submit');
      confirmButton.textContent = 'Confirm initialize';
      confirmButton.addEventListener('click', function() {{
        form.setAttribute('data-init-confirmed', 'true');
        if (typeof form.requestSubmit === 'function') {{ form.requestSubmit(); }}
        else {{ form.dispatchEvent(new Event('submit', {{ cancelable: true, bubbles: true }})); }}
      }});
      wrap.appendChild(msg);
      wrap.appendChild(confirmButton);
      form.appendChild(wrap);
    }}
    function submitVaultInitialize(form, endpoint, basePayload) {{
      var payload = Object.assign({{}}, basePayload);
      if (form.getAttribute('data-init-confirmed') === 'true') {{ payload.confirm = true; }}
      // One-shot: clear the flag so editing the path re-warns on the next submit.
      form.removeAttribute('data-init-confirmed');
      fetch(endpoint, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }}).then(function(response) {{
        return response.text().then(function(text) {{
          var data = null;
          try {{ data = text ? JSON.parse(text) : null; }} catch (e) {{ data = null; }}
          return {{ ok: response.ok, status: response.status, data: data, text: text }};
        }});
      }}).then(function(res) {{
        if (res.ok) {{ clearInitConfirm(form); form.removeAttribute('data-submit-error'); reload(); return; }}
        var detail = res.data && res.data.detail;
        if (res.status === 409 && detail && detail.error === 'vault_init_confirmation_required') {{
          renderInitConfirm(form, detail);
          return;
        }}
        var message = (detail && (detail.message || (typeof detail === 'string' ? detail : null))) || res.text || String(res.status);
        form.setAttribute('data-submit-error', message);
      }}).catch(function(err) {{ form.setAttribute('data-submit-error', String(err.message || err)); }});
    }}
    document.addEventListener('submit', function(event) {{
      var form = event.target;
      if (!form || !form.matches('[data-intent="vault.select"],[data-intent="vault.initialize"],[data-intent="vault.settings.write"]')) {{ return; }}
      event.preventDefault();
      if (form.getAttribute('data-intent') === 'vault.settings.write') {{
        var key = form.getAttribute('data-setting-key');
        var input = form.querySelector('[name="' + key + '"]');
        var value;
        try {{
          value = parseSettingValue(form, input);
        }} catch (err) {{
          return;
        }}
        jsonFetch('{VAULT_SETTINGS_ENDPOINT}', {{
          method: 'POST',
          body: JSON.stringify({{ key: key, value: value }})
        }}).then(reload).catch(function(err) {{ form.setAttribute('data-write-error', String(err.message || err)); }});
        return;
      }}
      var path = form.querySelector('[name="path"]');
      var role = form.querySelector('[name="machineRole"]');
      var endpoint = form.getAttribute('data-api-path');
      var basePayload = {{
        path: path ? path.value : '',
        machine_role: role ? role.value : undefined,
        machineRole: role ? role.value : undefined
      }};
      // Initialize has its own confirm-aware path (#2518); select keeps the
      // generic reload-chaining submit.
      if (form.getAttribute('data-intent') === 'vault.initialize') {{
        submitVaultInitialize(form, endpoint, basePayload);
        return;
      }}
      jsonFetch(endpoint, {{
        method: 'POST',
        body: JSON.stringify(basePayload)
      }}).then(reload).catch(function(err) {{ form.setAttribute('data-submit-error', String(err.message || err)); }});
    }});
    // Delegated on document so the handlers survive fragment swaps:
    // applyFragment() replaces the panel body (which contains both the recent-
    // vault buttons and the Reload button), so a directly-attached listener
    // would be lost after the first reload (#2016 Codex review).
    document.addEventListener('click', function(event) {{
      var vaultSettingsTrigger = event.target && event.target.closest('[data-intent="vault.settings.open"]');
      if (vaultSettingsTrigger && window.companionVaultSettings) {{
        event.preventDefault();
        window.companionVaultSettings.toggle();
        return;
      }}
      var recent = event.target && event.target.closest('[data-testid="vault-recent-vault"]');
      if (recent) {{
        jsonFetch('{VAULT_SELECT_ENDPOINT}', {{
          method: 'POST',
          body: JSON.stringify({{ path: recent.getAttribute('data-vault-path') || '' }})
        }}).then(reload).catch(function(err) {{ recent.setAttribute('data-submit-error', String(err.message || err)); }});
        return;
      }}
      var reloadButton = event.target && event.target.closest('[data-testid="vault-reload"]');
      if (reloadButton) {{
        jsonFetch('{VAULT_RELOAD_ENDPOINT}', {{ method: 'POST', body: '{{}}' }}).then(reload).catch(function(err) {{
          root.setAttribute('data-reload-error', String(err.message || err));
        }});
      }}
    }});
    // Apply the fetched projection on initial load so the panel renders the
    // runtime vault context instead of the no-vault default shell.
    reload();
  }})();
  /* /vault-settings-panel-controller */
  </script>"""


__all__ = [
    "VAULT_INITIALIZE_ENDPOINT",
    "VAULT_RELOAD_ENDPOINT",
    "VAULT_SELECT_ENDPOINT",
    "VAULT_SETTINGS_ENDPOINT",
    "VAULT_SETTINGS_FRAGMENT_ROUTE",
    "VAULT_SETTINGS_FRAGMENT_PICKER_PARAM",
    "vault_settings_panel_fragment",
    "vault_settings_panel_markup",
    "vault_settings_panel_script",
]
