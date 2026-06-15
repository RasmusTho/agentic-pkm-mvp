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

from companion_ui.workspace.serve_dev_page import make_handler
from companion_ui.workspace.vault_settings_panel import (
    VAULT_SETTINGS_ENDPOINT,
    VAULT_SETTINGS_FRAGMENT_ROUTE,
    vault_settings_panel_fragment,
    vault_settings_panel_markup,
    vault_settings_panel_script,
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

    # The initial server-rendered panel also carries the fragment route and the
    # applied projection so the first paint already reflects the vault context.
    markup = vault_settings_panel_markup(projection)
    assert f'data-fragment-path="{VAULT_SETTINGS_FRAGMENT_ROUTE}"' in markup
    assert "my-selected-vault" in markup
    assert 'data-vault-status="selected"' in markup


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
