"""Minimal browser dev server for the real-note workspace page (#1103).

DEV/STAGING ONLY — not for production use.

Does not implement auth, TLS, reverse proxy, or public exposure.
Calls the configured runtime API through WorkspaceHttpClient
(GET /api/companion/orientation for re-entry, GET /api/companion/workspace
for active artifacts). Does not read vault files directly.
Vault binding is determined by the runtime environment, not by this server.

Environment variables:
    HOST                   Bind address         (default: 0.0.0.0)
    PORT                   Bind port            (default: 8111)
    COMPANION_API_BASE_URL Runtime API base URL (default: http://127.0.0.1:18001)

Runtime API port map (docs/ENVIRONMENTS.md):
    prod → 18000
    dev  → 18001
    test → 18002

Companion UI dev server port map:
    dev  → 8111
    test → 8112
    prod → 8113

Default server/LAN bind:
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=0.0.0.0 PORT=8111 \\
        python -m companion_ui.workspace.serve_dev_page

Loopback-only opt-out:
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \\
        python -m companion_ui.workspace.serve_dev_page

Browser requests use same-origin Companion UI routes; the dev server calls
COMPANION_API_BASE_URL server-side so remote clients never need direct access
to the runtime localhost port.
"""

import html as _html
import json
import os
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

from companion_ui.renderer import (
    PropertiesRenderer,
    VaultMarkdownDocument,
    link_preview_css,
    note_outline_css,
    note_outline_script,
    parse_vault_markdown,
    render_note_outline,
    render_vault_markdown,
)
from companion_ui.renderer.link_resolver import VaultLinkResolver
from companion_ui.workspace.capture_modal import (
    capture_modal_markup,
    capture_modal_script,
)
from companion_ui.workspace.entry_state import (
    EntryStateResolution,
    entry_state_attributes,
    resolve_entry_state,
)
from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_layer_script,
    guidance_layer_style,
    guidance_toggle_markup,
)
from companion_ui.workspace.memory_review_drawer import (
    MEMORY_REVIEW_FRAGMENT_ROUTE,
    MEMORY_REVIEW_QUEUE_ENDPOINT,
    memory_review_drawer_markup,
    memory_review_drawer_script,
    memory_review_queue_fragment,
    memory_review_unavailable_fragment,
)
from companion_ui.workspace.overlay_host import (
    DEFAULT_POSTURE_EMPHASIS,
    coarse_vault_posture,
    overlay_host_markup,
    overlay_host_script,
)
from companion_ui.workspace.panel_palette import (
    panel_palette_markup,
    panel_palette_script,
)
from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.receipts_history import (
    RECEIPTS_HISTORY_FRAGMENT_ROUTE,
    RECEIPTS_PROJECTION_ENDPOINT,
    receipts_history_fragment,
    receipts_history_modal_markup,
    receipts_history_script,
    receipts_history_unavailable_fragment,
)
from companion_ui.workspace.settings_drawer import (
    settings_drawer_markup,
    settings_drawer_script,
)
from companion_ui.workspace.system_map_overlay import (
    system_map_overlay_markup,
    system_map_overlay_script,
)
from companion_ui.workspace.vault_settings_panel import (
    VAULT_INITIALIZE_ENDPOINT,
    VAULT_RELOAD_ENDPOINT,
    VAULT_SELECT_ENDPOINT,
    VAULT_SETTINGS_ENDPOINT,
    VAULT_SETTINGS_FRAGMENT_ROUTE,
    vault_settings_panel_fragment,
    vault_settings_panel_markup,
    vault_settings_panel_script,
)
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientError,
    WorkspaceClientHTTPError,
)

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8111
_DEFAULT_API_BASE_URL = "http://127.0.0.1:18001"
_DEFAULT_API_TIMEOUT_SECONDS = 2.0
_TRUTHY_ENV = {"1", "true", "yes", "on"}


class CompanionThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded HTTP server for local/LAN Companion UI browser clients."""

    daemon_threads = True


def load_config() -> dict:
    """Load server configuration from environment variables.

    Returns a dict with keys: host, port, api_base_url.
    Defaults: HOST=0.0.0.0, PORT=8111, COMPANION_API_BASE_URL=http://127.0.0.1:18001.
    """
    try:
        api_timeout_seconds = float(
            os.environ.get(
                "COMPANION_API_TIMEOUT_SECONDS",
                str(_DEFAULT_API_TIMEOUT_SECONDS),
            )
        )
    except (TypeError, ValueError):
        api_timeout_seconds = _DEFAULT_API_TIMEOUT_SECONDS
    return {
        "host": os.environ.get("HOST", _DEFAULT_HOST),
        "port": int(os.environ.get("PORT", str(_DEFAULT_PORT))),
        "api_base_url": os.environ.get("COMPANION_API_BASE_URL", _DEFAULT_API_BASE_URL),
        "api_timeout_seconds": max(0.25, api_timeout_seconds),
    }


def orientation_ambient_refresh_enabled() -> bool:
    return os.environ.get("COMPANION_ORIENTATION_AMBIENT_REFRESH", "").strip().lower() in _TRUTHY_ENV


def _e(value: str) -> str:
    """HTML-escape a string for safe inline output."""
    return _html.escape(str(value))


# Canonical companion kind values from COMPANION_NOTE_CONTRACT.md.
# Exact match only — substring checks risk false-positives on arbitrary kind strings
# (e.g. "non_companion_attachment"). Extend this set as new companion kinds are
# introduced via the contract, not via loose substring heuristics.
_COMPANION_KINDS: frozenset[str] = frozenset({"companion_note"})


# Maximum characters for any single rail item label / reason / relation field.
# Prevents operator/agent note body content from leaking into the rail verbatim.
_RAIL_ITEM_MAX: int = 280


def _cap(text: str, max_len: int = _RAIL_ITEM_MAX) -> str:
    """Truncate *text* to *max_len* characters, appending '…' if clipped."""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + "…"


# ---------------------------------------------------------------------------
# Daily-use visibility helpers (#1361)
# ---------------------------------------------------------------------------

_REVIEW_STATE_LABELS: dict[str, str] = {
    "needs_review": "needs review",
    "reviewed": "reviewed",
    "in_progress": "in progress",
    "deferred": "deferred",
    "approved": "approved",
    "rejected": "rejected",
}

_LIFECYCLE_STATE_LABELS: dict[str, str] = {
    "active": "active",
    "inbox": "inbox",
    "workbench": "workbench",
    "archive": "archive",
    "seedling": "seedling",
    "evergreen": "evergreen",
}

_NOTE_TYPE_LABELS: dict[str, str] = {
    "human_note": "note",
    "companion_note": "companion",
    "log_entry": "log",
    "reference": "reference",
}


def _humanize_fm_pair(key: str, value: str) -> str | None:
    """Return a human label for a frontmatter key/value pair, or None to skip."""
    if key == "review_state":
        label = _REVIEW_STATE_LABELS.get(value, value.replace("_", " "))
        return f"review · {label}"
    if key == "lifecycle_state":
        label = _LIFECYCLE_STATE_LABELS.get(value, value.replace("_", " "))
        return f"lifecycle · {label}"
    if key in ("note_type", "kind"):
        label = _NOTE_TYPE_LABELS.get(value, value.replace("_", " "))
        return f"type · {label}"
    if key == "zone":
        return f"zone · {value.replace('_', ' ')}"
    return None


def _should_hide_note_by_default(note: dict) -> bool:
    """Return True for companion/UUID notes hidden from navigation by default."""
    import re as _re
    kind = str(note.get("kind") or "").strip()
    if kind in _COMPANION_KINDS:
        return True
    path = str(note.get("note_path") or "").strip()
    filename = path.split("/")[-1]
    filename_stem = filename
    for ext in (".md", ".MD"):
        if filename_stem.endswith(ext):
            filename_stem = filename_stem[: -len(ext)]
            break
    uuid_pat = _re.compile(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        _re.IGNORECASE,
    )
    return bool(uuid_pat.match(filename_stem))


def _status_label(value: object, *, fallback: str = "unknown") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def _human_state_label(state: str, mapping: dict[str, str], *, fallback: str = "Unavailable") -> str:
    token = str(state or "").strip().lower()
    return mapping.get(token, fallback)


def _human_reason(reason: str) -> str:
    token = str(reason or "").strip()
    return {
        "not_declared": "runtime has not enabled this capability",
        "disabled": "runtime configuration marks this capability unavailable",
        "canvas_disabled": "Canvas editing is disabled by runtime configuration",
    }.get(token, token.replace("_", " ") if token else "reason unavailable")


def _split_frontmatter(body: str) -> tuple[list[str], str]:
    """Split a frontmatter prefix off ``body`` using the renderer parser.

    Returns ``(frontmatter_lines, remaining_body)``. If the body does not begin
    with a ``---``/``---`` fenced block, returns ``([], body)`` unchanged.
    """
    document = parse_vault_markdown(body)
    if document.frontmatter is None:
        return [], body
    return document.frontmatter.splitlines(), document.body_markdown


def _render_hidden_frontmatter_marker(document: VaultMarkdownDocument) -> str:
    """Render frontmatter as a humanized disclosure section (daily-use #1361)."""
    if document.frontmatter is None:
        return (
            '<section class="note-frontmatter note-frontmatter-empty" '
            'data-testid="workspace-note-frontmatter" '
            'data-frontmatter-present="false" '
            'aria-hidden="true" style="display:none">'
            '<span class="frontmatter-label">No frontmatter</span>'
            "</section>"
        )
    summary_items: list[str] = []
    rows: list[str] = []
    for line in document.frontmatter.splitlines():
        stripped = line.rstrip()
        if not stripped:
            continue
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            human = _humanize_fm_pair(key.strip(), val.strip())
            if human:
                summary_items.append(_e(human))
        rows.append(
            '<div class="frontmatter-line">'
            f'<code>{_e(stripped)}</code>'
            "</div>"
        )
    summary_text = " · ".join(summary_items) if summary_items else "properties"
    body_html = "".join(rows) or '<span class="frontmatter-label">(empty frontmatter)</span>'
    return (
        '<section class="note-frontmatter" '
        'data-testid="workspace-note-frontmatter" '
        'data-frontmatter-present="true">'
        '<details class="frontmatter-disclosure" data-testid="workspace-frontmatter-disclosure">'
        '<summary class="frontmatter-summary" data-testid="workspace-frontmatter-summary">'
        f"{summary_text}"
        "</summary>"
        f"{body_html}"
        "</details>"
        "</section>"
    )


def _render_note_frontmatter_region(document: VaultMarkdownDocument):  # type: ignore[return]
    """Return (hidden_marker_html, rendered_properties).

    AC1 / AC2 (#1260): the body region must not display YAML frontmatter as
    prose; frontmatter-derived metadata remains visible in dedicated chrome.
    #1337: the visible properties are wrapped in a breadcrumb disclosure; the
    hidden marker is kept in-place for downstream selectors.
    """
    hidden_marker = _render_hidden_frontmatter_marker(document)
    rendered_props = PropertiesRenderer(
        test_id="workspace-note-properties",
        include_empty=False,
    ).render(document)
    return hidden_marker, rendered_props


def _render_workspace_breadcrumb(
    *,
    note_path: str,
    artifact_id: str,
    content_hash: str,
    identity_state: str,
    identity_source: str,
    artifact_kind: str,
    owns_identity: bool,
    companion_html: str,
    rendered_props,
) -> str:
    """Breadcrumb line under the note title with a properties ▾ disclosure.

    §7.3 / #1337: replaces the chip strip (path · artifact · hash) with a
    single breadcrumb line; artifact id and hash move inside the disclosure.
    """
    # Path segments — keep raw slashes as separators for readability. The
    # incoming note_path is already HTML-escaped, so fully unescape before
    # re-escaping each segment once; only reversing &amp; would double-escape
    # every other metacharacter (e.g. an apostrophe -> literal "&#x27;").
    path_segments = _html.unescape(note_path).split("/")
    path_html = " / ".join(_e(p) for p in path_segments if p)

    # Pull up to 2 inline meta items from frontmatter (kind + review_state)
    _META_KEYS = ("kind", "review", "review_state")
    meta_items: list[str] = []
    for field in (rendered_props.fields or ()):
        if field.key in _META_KEYS and field.values:
            label = _e(field.key)
            val = _e(", ".join(field.values[:2]))
            meta_items.append(
                f'<span class="breadcrumb-meta-item">{label}&nbsp;{val}</span>'
            )
        if len(meta_items) >= 2:
            break

    meta_html = "".join(
        f'<span class="breadcrumb-sep">&middot;</span>{item}' for item in meta_items
    )

    # Artifact/hash chips move inside the disclosure
    artifact_chip = ""
    if artifact_id:
        artifact_chip = (
            f'<span class="prov-item artifact-identity-pill"'
            f' data-testid="workspace-artifact-identity-pill"'
            f' data-identity-state="{identity_state}"'
            f' data-identity-source="{identity_source}"'
            f' data-artifact-kind="{artifact_kind}"'
            f' data-owns-identity="{"true" if owns_identity else "false"}">'
            f'<span class="prov-label">artifact</span>'
            f"<code>{artifact_id}</code>"
            f'<span class="identity-meta">{identity_state}</span>'
            f'<span class="identity-meta">{identity_source}</span>'
            f"{companion_html}"
            f"</span>"
        )
    hash_chip = ""
    if content_hash:
        hash_chip = (
            f'<span class="prov-item content-hash-pill"'
            f' data-testid="workspace-content-hash-pill">'
            f'<span class="prov-label">hash</span>'
            f"<code>{content_hash}</code>"
            f"</span>"
        )
    identity_chips_html = ""
    if artifact_chip or hash_chip:
        identity_chips_html = (
            f'<div class="breadcrumb-identity-chips">{artifact_chip}{hash_chip}</div>'
        )

    # Fully unescape the already-escaped note_path so the data attribute is
    # escaped exactly once; JS reads data-note-path as the real path (line ~1291),
    # so a double-escaped value would hand JS the wrong path.
    raw_path = _html.unescape(note_path)
    return (
        f'<div class="workspace-breadcrumb" data-testid="workspace-breadcrumb" data-note-path="{_e(raw_path)}">'
        f'<span class="breadcrumb-path">{path_html}</span>'
        f"{meta_html}"
        f'<details class="workspace-properties-disclosure"'
        f' data-testid="workspace-properties-disclosure"'
        f" aria-expanded=\"false\">"
        f'<summary class="breadcrumb-disclosure-trigger">properties&nbsp;&#9660;</summary>'
        f'<div class="properties-disclosure-body">'
        f"{identity_chips_html}"
        f"{rendered_props.html}"
        f"</div>"
        f"</details>"
        f"</div>"
    )


def _compute_primary_posture(
    *,
    writeguard_blocked: bool,
    vault_unresolved: bool,
    canvas_enabled: bool,
    workspace_update_available: bool,
    guard_degraded: bool,
) -> tuple[str, str]:
    """Resolve a single primary posture token + human-facing label.

    Order of precedence (most severe wins):
        blocked > unavailable > degraded > ok

    AC3 / AC4 (#1260): consolidate competing safety/status rows into one
    primary posture surface; degraded/blocked/unavailable visibly distinct
    from ok.
    """
    if writeguard_blocked:
        return "blocked", "Blocked"
    if vault_unresolved:
        return "unavailable", "Unavailable"
    if guard_degraded or not canvas_enabled or not workspace_update_available:
        return "degraded", "Degraded"
    return "ok", "Online"



def _workspace_header_freshness(fields: dict) -> tuple[str, str]:
    raw = (
        fields.get("workspace_loaded_at")
        or fields.get("runtime_last_ingest_at")
        or fields.get("updated")
        or fields.get("last_modified")
    )
    if raw:
        full = str(raw)
        match = re.search(r"(\d{2}):(\d{2})", full)
        if match:
            return f"as of {match.group(1)}:{match.group(2)}", full
    now = datetime.now().astimezone()
    return f"as of {now:%H:%M}", now.isoformat(timespec="minutes")


def _render_workspace_header_strip(
    *,
    fields: dict,
    posture: str,
    posture_label: str,
    runtime_environment: str,
    runtime_channel: str,
    runtime_trace_id: str,
    vault_name: str,
    vault_channel: str,
    vault_provenance: str,
    writeguard_status: str,
    canvas_enabled: bool,
    update_flow_available: bool,
    guard_degraded: bool,
    workspace_update_available: bool,
    workspace_update_state: str,
    workspace_update_reason: str,
    workspace_update_scope: str,
    workspace_update_governance_actions_enabled: bool,
    workspace_update_config_mode: str,
    orientation_freshness: str = "",
    orientation_as_of: str = "",
    orientation_trace_id: str = "",
) -> str:
    freshness_label, freshness_title = _workspace_header_freshness(fields)
    canvas_token = "canvas off" if not canvas_enabled else "canvas on"
    runtime_token = "runtime degraded" if posture in {"blocked", "degraded", "unavailable"} else "ok"
    pill_label = canvas_token if not canvas_enabled else runtime_token
    is_prod = bool(fields.get("is_production_ui")) or str(
        fields.get("runtime_environment_label") or ""
    ).lower() == "prod"
    dev_ribbon = (
        ""
        if is_prod
        else '<span class="workspace-dev-ribbon" data-testid="workspace-dev-ribbon">DEV</span>'
    )
    vp_lower = str(vault_provenance).lower()
    if vp_lower == "unreachable":
        vault_state = "unreachable"
    elif vp_lower == "unresolved":
        vault_state = "unresolved"
    else:
        vault_state = "ok"
    # §5.2 — Browse Vault routes to the canonical left-pane browse surface, not
    # the modal overlay (which is a narrow responsive fallback only).
    browse_target = "#vault-browser-left-pane"
    # #1785 (SEP-03) — unified-topbar consolidation over the shipped header:
    # anchor pill (current note identity), posture pill (local posture
    # emphasis, rendering only — the switch overlay has not shipped), surface
    # icons for shipped surfaces only, and the coarse vault-status dot.
    anchor_note_path = str(fields.get("note_path") or "")
    anchor_title = _plain_workspace_heading_text(
        str(fields.get("title") or anchor_note_path or "No note open")
    )
    coarse_posture = coarse_vault_posture(
        vault_state=vault_state, primary_posture=posture
    )
    telemetry_rows = [
        ("workspace-runtime-channel", "runtime_environment_label", "runtime", runtime_environment),
        ("workspace-runtime-channel-api", "runtime_api_base_url_label", "channel", runtime_channel),
        ("workspace-vault-identity", "runtime_vault_name", "vault", vault_name),
        ("workspace-vault-channel", "runtime_vault_channel", "vault channel", vault_channel),
        (
            "workspace-vault-provenance",
            "runtime_vault_provenance",
            "vault provenance",
            _e(vault_provenance),
        ),
        ("workspace-writeguard-state", "runtime_writeguard_status", "WriteGuard", writeguard_status),
        (
            "workspace-canvas-enabled-state",
            "runtime_canvas_enabled",
            "Canvas",
            "enabled" if canvas_enabled else "disabled",
        ),
        (
            "workspace-update-flow-state",
            "runtime_update_flow_available",
            "Update flow",
            "available" if update_flow_available else "disabled",
        ),
        (
            "workspace-guard-degraded-state",
            "runtime_guard_degraded",
            "guard",
            "degraded" if guard_degraded else "normal",
        ),
        (
            "workspace-update-flow-state-detail",
            "runtime_workspace_update_state",
            "workspace update",
            workspace_update_state,
            f'data-update-state="{workspace_update_state}"',
        ),
        (
            "workspace-update-flow-availability",
            "runtime_workspace_update_available",
            "workspace update available",
            "available" if workspace_update_available else "disabled",
        ),
        (
            "workspace-update-flow-scope",
            "runtime_workspace_update_scope",
            "workspace update scope",
            workspace_update_scope,
        ),
        (
            "workspace-update-flow-reason",
            "runtime_workspace_update_reason",
            "update reason",
            workspace_update_reason,
        ),
        (
            "workspace-update-flow-config-mode",
            "runtime_workspace_update_config_mode",
            "update config",
            workspace_update_config_mode,
        ),
        (
            "workspace-update-governance-state",
            "runtime_governance_via_update_enabled",
            "governance via update",
            "enabled" if workspace_update_governance_actions_enabled else "disabled",
        ),
        (
            "workspace-runtime-trace-id",
            "runtime_trace_id",
            "trace",
            runtime_trace_id or "unavailable",
        ),
    ]
    telemetry_html = "".join(
        f"""
          <div class="workspace-runtime-popover-row" data-testid="{testid}" data-runtime-field="{field}"{' ' + extra if (extra := row[4] if len(row) > 4 else '') else ''}>
            <span class="workspace-runtime-popover-key">{label}</span>
            <code>{value}</code>
          </div>"""
        for row in telemetry_rows
        for testid, field, label, value in [row[:4]]
    )
    # Relocated telemetry from the removed "Re-entry snapshot" meta row
    # (#2171/#2245): freshness/as_of/trace_id rendered as read-only projection
    # rows in the popover when the orientation payload supplies them.
    # Zero-state: omit entirely when absent — no placeholder row.
    _of = (orientation_freshness or "").strip()
    _oa = (orientation_as_of or "").strip()
    _ot = (orientation_trace_id or "").strip()
    if _of:
        telemetry_html += f"""
          <div class="workspace-runtime-popover-row workspace-runtime-popover-row--projection"
            data-testid="workspace-freshness-as-of"
            data-runtime-field="orientation_freshness"
            data-authority="read-only-projection">
            <span class="workspace-runtime-popover-key">freshness</span>
            <code>{_e(_of)}</code>
          </div>"""
    if _oa:
        telemetry_html += f"""
          <div class="workspace-runtime-popover-row workspace-runtime-popover-row--projection"
            data-testid="workspace-orientation-as-of"
            data-runtime-field="orientation_as_of"
            data-authority="read-only-projection">
            <span class="workspace-runtime-popover-key">as of</span>
            <code>{_e(_oa)}</code>
          </div>"""
    if _ot:
        telemetry_html += f"""
          <div class="workspace-runtime-popover-row workspace-runtime-popover-row--projection"
            data-testid="workspace-orientation-trace-id"
            data-runtime-field="orientation_trace_id"
            data-authority="read-only-projection">
            <span class="workspace-runtime-popover-key">orientation trace</span>
            <code>{_e(_ot)}</code>
          </div>"""
    return f"""
      <header
        class="workspace-header-strip primary-posture posture-tone-{posture}"
        data-testid="workspace-primary-posture"
        data-posture="{posture}"
        data-region="workspace-header">
        <div class="workspace-header-row" data-testid="workspace-header-row">
          <a class="workspace-wordmark" data-testid="workspace-wordmark" href="/" aria-label="Return to vault root">Yggdrasil</a>
          <a class="workspace-vault-chip" data-testid="workspace-vault-chip" data-state="{vault_state}" data-vault-provenance="{_e(vault_provenance)}" href="{browse_target}">
            <span class="workspace-vault-dot" data-testid="workspace-vault-status-dot" data-coarse-posture="{coarse_posture}" aria-hidden="true"></span>
            <span>{vault_name} · vault {vault_state}</span>
          </a>
          <span class="workspace-anchor-pill" data-testid="workspace-anchor-pill" data-region="document-anchor" data-anchor-note-path="{_e(anchor_note_path)}" title="Document anchor">{_e(anchor_title)}</span>
          <span class="workspace-posture-pill" data-testid="workspace-posture-pill" data-posture-emphasis="{DEFAULT_POSTURE_EMPHASIS}" data-authority="local-ui" title="Posture emphasis (local rendering only)">{DEFAULT_POSTURE_EMPHASIS}</span>
          <details class="workspace-runtime-status" data-testid="workspace-runtime-status">
            <summary
              class="workspace-runtime-pill"
              data-testid="workspace-runtime-pill"
              aria-label="Show runtime telemetry">
              <span>{pill_label}</span>
              <span class="workspace-runtime-human-label">{posture_label}</span>
            </summary>
            <span id="workspace-runtime-telemetry"
              data-testid="workspace-runtime-telemetry"
              aria-hidden="true"></span>
            <div class="workspace-runtime-status-popover" data-testid="workspace-runtime-status-popover">
              {telemetry_html}
            </div>
          </details>
          <span class="workspace-freshness" data-testid="workspace-freshness" title="{_e(freshness_title)}">{_e(freshness_label)}</span>
          <span class="workspace-header-spacer" aria-hidden="true"></span>
          <nav class="workspace-surface-icons" data-testid="workspace-surface-icons" data-region="surface-icons" aria-label="Surfaces">
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-vault" data-surface="vault" data-intent="vault.open" title="Vault browser" aria-label="Open vault browser" onclick="vaultBrowser.focus()">&#9636;</button>
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-map" data-surface="map" data-intent="map.open" title="System map" aria-label="Open system map" onclick="overlayHost.mount('map')">❖</button>
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-memory" data-surface="memory" data-intent="memory.open" title="Memory candidate review" aria-label="Open memory candidate review drawer" onclick="overlayHost.mount('memory')">&#9670;</button>
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-receipts" data-surface="receipts" data-intent="receipts.open" title="Receipts history" aria-label="Open read-only receipts history" onclick="overlayHost.mount('receipts')">&#9776;</button>
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-settings" data-surface="settings" data-intent="settings.open" title="Settings" aria-label="Open settings drawer" onclick="overlayHost.mount('settings')">&#9881;</button>
            <button type="button" class="workspace-surface-icon" data-testid="workspace-surface-icon-help" data-surface="help" title="Help" aria-label="Open help" onclick="companionHelp.open()">?</button>
            {guidance_toggle_markup('topbar')}
          </nav>
          <button class="workspace-quick-open" data-testid="workspace-quick-open" type="button" aria-disabled="true" title="Quick-open is visual only in this slice">
            <kbd>/</kbd><span>⌘K</span>
          </button>
          <button class="workspace-browse-vault" data-testid="workspace-browse-vault" type="button" data-browse-target="vault-browser-pane" onclick="vaultBrowser.focus()">Browse vault</button>
          {dev_ribbon}
        </div>
      </header>
      <!-- Guidance layer (#1788, SEP-06): the shell callout — explanation
           only, hidden unless the shell root carries data-guidance="on". -->
      {guidance_callout_markup('shell')}"""


def _render_rail_empty_state(
    *,
    panel_proposal_count: int,
    panel_proposals: list[dict] | None,
    canvas_session_state: str,
    panel_state: str,
    panel_message: str,
    find_candidates_count: int,
    reorient_present: bool,
    resurface_count: int,
    governance_receipts_count: int,
    suggestion_state: str,
) -> str:
    """Render a single no-active-session card when the rail is fully idle.

    AC7 (#1260): empty/inactive rail cards collapse to a single clear
    no-active-session/unavailable state. Individual section placeholders may
    still render; this card is the consolidated signal that nothing is active.
    """
    active = (
        panel_proposal_count > 0
        or bool(panel_proposals)
        or canvas_session_state not in {"idle", "", "unknown"}
        or panel_state not in {"idle", "", "unknown"}
        or bool(panel_message)
        or find_candidates_count > 0
        or reorient_present
        or resurface_count > 0
        or governance_receipts_count > 0
        or suggestion_state not in {"idle", "", "unknown"}
    )
    if active:
        return ""
    return (
        '<div class="rail-empty-state" '
        'data-testid="workspace-rail-empty-state" '
        'data-rail-state="empty">'
        "No active session. Nothing pending in Panel, Canvas, or governance."
        "</div>"
    )


def _render_read_only_pill() -> str:
    return (
        '<div class="workspace-read-only-pill" data-testid="workspace-read-only-pill"'
        ' title="Canvas off · runtime configuration · view in Panel">'
        "▍ read-only"
        "</div>"
    )


def _render_vault_unreachable_banner(last_sync: str = "") -> str:
    sync_label = f"last sync {last_sync}" if last_sync else "last sync unavailable"
    return (
        f'<div class="workspace-vault-unreachable-banner" data-testid="workspace-vault-unreachable-banner">'
        f"<span>Vault unreachable — {sync_label}. Showing cached view.</span>"
        f'<a href="#workspace-runtime-status" class="banner-retry-link" data-testid="workspace-vault-retry">retry</a>'
        f"</div>"
    )


def _render_note_not_found(note_path: str) -> str:
    safe_path = _e(note_path)
    return (
        f'<div class="workspace-note-not-found" data-testid="workspace-note-not-found">'
        f"<h1>Note not found</h1>"
        f"<code>{safe_path}</code>"
        f"<p>No artifact at {safe_path}. The vault may have moved or this link may be stale.</p>"
        f'<div class="not-found-actions">'
        f'<button type="button" class="not-found-browse" data-browse-target="vault-browser-pane" onclick="vaultBrowser.focus()">Browse vault</button>'
        f'<button type="button" class="not-found-last-note" data-testid="workspace-open-last-note">Open last note</button>'
        f"</div>"
        f"</div>"
    )


def _render_note_body_empty_state(note_path: str) -> str:
    safe_path = _e(note_path)
    return (
        '<div class="note-body-empty" data-testid="workspace-note-body-empty" '
        'data-empty-reason="artifact-body-empty">'
        "<h2>No note body loaded</h2>"
        f"<p>The runtime returned an empty body for <code>{safe_path}</code>.</p>"
        "</div>"
    )


def _render_body_edit_panel(update_flow_available: bool, note_path: str, raw_body: str = "") -> str:
    if not update_flow_available:
        # Direct human editing is always available via the note's own Read/Edit
        # editor (independent of the Canvas/update flow), so the old "Editing is
        # not enabled in this workspace" absence card is no longer shown — it
        # contradicted the always-available editor and read as unsolicited
        # read-only nagging. The Canvas-mediated composer below is dev-only.
        return ""
    # #1416 — render the dev composer as an opt-in disclosure that is collapsed
    # by default. In the fixed-height shell (#1397) a sibling that grows with its
    # content squeezes the note reading surface; a collapsed <details> contributes
    # only its summary row so the note body keeps its reading height, and the
    # expanded body is height-bounded with internal scroll (CSS) so it still
    # cannot consume the reading layout's space. testid markers are preserved.
    return f"""<details class="body-edit-panel" data-testid="workspace-body-edit-panel"
         data-update-flow="available">
  <summary class="body-edit-summary" data-testid="workspace-body-edit-summary">
    <span class="body-edit-label">Edit note body</span>
    <span class="body-edit-note">Opt-in &middot; keeps the reading surface primary</span>
  </summary>
  <div class="body-edit-body">
    <div class="body-edit-header">
      <span class="body-edit-note">Frontmatter and UUID are preserved. WriteGuard is authoritative.</span>
    </div>
    <div class="body-edit-codemirror" id="body-edit-codemirror"
         data-testid="workspace-body-edit-textarea"
         data-note-path="{note_path}"
         data-raw-body="{_e(raw_body)}"></div>
    <div class="body-edit-actions">
      <button class="body-edit-submit"
              data-testid="workspace-body-edit-submit"
              onclick="bodyEditor.submit()">Apply update</button>
      <button class="body-edit-reset"
              data-testid="workspace-body-edit-reset"
              onclick="bodyEditor.reset()">Reset</button>
    </div>
    <div class="body-edit-status" id="body-edit-status"
         data-testid="workspace-body-edit-status"></div>
  </div>
</details>"""


_LEFT_PANEL_MODES = ("browse", "outline", "context", "collapsed")


def _render_left_context_panel(
    *,
    vault_browser_html: str,
    outline_html: str,
    has_headings: bool,
    note_path_val: str,
    identity_state_label: str,
) -> str:
    """Render the single adaptive left context panel (#1399, handoff §4).

    One panel, four modes (browse / outline / context / collapsed); only one
    mode region is visible at a time. Opening a note prefers ``outline`` when
    the note has headings, otherwise ``collapsed`` so the panel does not cold
    open into a noisy browser dump. Mode labels are human-facing; internal mode
    keys stay in ``data-*`` attributes.
    """

    default_mode = "outline" if has_headings else "collapsed"

    def _region(mode: str, label_testid: str, inner: str) -> str:
        hidden = "" if mode == default_mode else " hidden"
        return (
            f'<div class="left-panel-mode left-panel-mode--{mode}" '
            f'data-left-panel-mode-region="{mode}" data-mode="{mode}" '
            f'data-testid="workspace-left-panel-mode-{mode}" role="tabpanel"'
            f"{hidden}>{inner}</div>"
        )

    # §4.3 — context mode is compact, not a metadata dump.
    context_inner = (
        '<div class="left-panel-context" data-testid="workspace-left-panel-context">'
        '<div class="left-panel-context-row">'
        '<span class="lpc-label">Path</span>'
        f'<span class="lpc-value">{note_path_val or "—"}</span></div>'
        '<div class="left-panel-context-row">'
        '<span class="lpc-label">Identity</span>'
        f'<span class="lpc-value">{identity_state_label}</span></div>'
        '<p class="left-panel-context-empty">Nothing needs attention for this note.</p>'
        "</div>"
    )

    def _tab(mode: str, label: str) -> str:
        selected = "true" if mode == default_mode else "false"
        return (
            f'<button type="button" class="left-panel-mode-tab" role="tab" '
            f'data-mode="{mode}" data-testid="workspace-left-panel-tab-{mode}" '
            f'aria-selected="{selected}" '
            f"onclick=\"leftPanel.setMode('{mode}')\">{label}</button>"
        )

    switcher = (
        '<div class="left-panel-mode-switcher" role="tablist" '
        'data-testid="workspace-left-panel-mode-switcher">'
        f"{_tab('browse', 'Browse')}"
        f"{_tab('outline', 'Outline')}"
        f"{_tab('context', 'Context')}"
        '<button type="button" class="left-panel-collapse" '
        'data-testid="workspace-left-panel-collapse" aria-label="Collapse panel" '
        "onclick=\"leftPanel.collapse()\">&#10216;</button>"
        "</div>"
    )

    reopen_hidden = "" if default_mode == "collapsed" else " hidden"
    reopen = (
        '<button type="button" class="left-panel-reopen" '
        'data-testid="workspace-left-panel-reopen" '
        f"onclick=\"leftPanel.reopen()\"{reopen_hidden}>Open panel</button>"
    )

    return (
        '<nav class="vault-browser-left-pane" id="vault-browser-left-pane" '
        'data-testid="workspace-vault-browser-left-pane" '
        'data-region="vault-browser-pane" data-browser-role="canonical" '
        f'data-left-panel-modes="{" ".join(_LEFT_PANEL_MODES)}" '
        f'data-left-panel-mode="{default_mode}">'
        f"{switcher}"
        f"{_region('browse', 'browse', vault_browser_html)}"
        f"{_region('outline', 'outline', outline_html)}"
        f"{_region('context', 'context', context_inner)}"
        f"{reopen}"
        "</nav>"
    )


def _mermaid_runtime_script() -> str:
    """Sandboxed client runtime that renders ``pre.vault-mermaid`` placeholders.

    #1344: the Mermaid bundle is imported only when at least one placeholder is
    present (AC4). Valid source renders to inline SVG (AC2); a Mermaid throw
    rewrites the figure to the #1340 failed-embed partial shape (AC3) — the same
    ``data-testid="failed-embed" data-kind="mermaid"`` DOM the server emits — so
    there is no second error visual. ``securityLevel: 'strict'`` disables click
    directives and HTML injection. Returned as a plain string (not an f-string)
    so the JS braces are not double-escaped by the page template.
    """
    return """
  <script type="module">
  (async function () {
    var blocks = document.querySelectorAll('.note-body pre.vault-mermaid');
    if (!blocks.length) { return; }            // AC4: no bundle unless needed
    var mermaid;
    try {
      mermaid = (await import('https://esm.sh/mermaid@10.9.1')).default;
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'dark',
        suppressErrorRendering: true   // do not inject Mermaid's global error graphic
      });
    } catch (e) { return; }                    // load failure: keep source placeholder
    function esc(s) {
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    function degrade(figure, source) {
      figure.className = 'vault-mermaid-block failed-embed failed-embed--mermaid';
      figure.setAttribute('data-testid', 'failed-embed');
      figure.setAttribute('data-kind', 'mermaid');
      figure.setAttribute('data-embed-state', 'failed');
      figure.setAttribute('data-mermaid-state', 'failed');
      figure.setAttribute('data-diagnostic-code', 'mermaid_render_error');
      figure.innerHTML =
        '<div class="failed-embed-main">' +
        '<span class="failed-embed-tag">MERMAID</span>' +
        '<span class="failed-embed-message">Diagram source available &mdash; ' +
        'interactive render unavailable in this view.</span></div>' +
        '<details class="vault-mermaid-source" data-testid="vault-mermaid-source">' +
        '<summary>view source</summary>' +
        '<pre class="vault-code-block vault-mermaid-source-code" data-language="mermaid">' +
        '<code class="language-mermaid">' + esc(source) + '</code></pre></details>';
    }
    for (var i = 0; i < blocks.length; i++) {
      var pre = blocks[i];
      var figure = pre.closest('.vault-mermaid-block') || pre.parentNode;
      var code = pre.querySelector('code');
      var source = (code ? code.textContent : pre.textContent) || '';
      var renderId = 'vault-mermaid-svg-' + i;
      try {
        var out = await mermaid.render(renderId, source);
        var holder = document.createElement('div');
        holder.className = 'vault-mermaid-rendered';
        holder.setAttribute('data-testid', 'vault-mermaid-rendered');
        holder.innerHTML = out.svg;
        pre.replaceWith(holder);
        if (figure && figure.setAttribute) { figure.setAttribute('data-mermaid-state', 'rendered'); }
      } catch (err) {
        // Belt-and-suspenders: drop any orphan error node Mermaid may have left.
        var orphan = document.getElementById(renderId) || document.getElementById('d' + renderId);
        if (orphan && orphan.parentNode) { orphan.parentNode.removeChild(orphan); }
        if (figure && figure.setAttribute) { degrade(figure, source); }
      }
    }
  })();
  </script>"""


def _display_preferences_script() -> str:
    """Browser-local display preferences for the rendered reading surface."""

    return """
  <script>
  (function () {
    var storageKey = 'companion.displayPreferences.v1';
    var defaults = {
      fontSize: '16px',
      lineHeight: '1.65',
      readingWidth: '68ch',
      focusMode: false
    };
    function readPrefs() {
      try {
        var raw = window.localStorage ? window.localStorage.getItem(storageKey) : null;
        return raw ? Object.assign({}, defaults, JSON.parse(raw)) : Object.assign({}, defaults);
      } catch (e) {
        return Object.assign({}, defaults);
      }
    }
    function writePrefs(prefs) {
      try {
        if (window.localStorage) {
          window.localStorage.setItem(storageKey, JSON.stringify(prefs));
        }
      } catch (e) {}
    }
    function applyPrefs(prefs) {
      var root = document.documentElement;
      root.style.setProperty('--display-font-size', prefs.fontSize || defaults.fontSize);
      root.style.setProperty('--display-line-height', prefs.lineHeight || defaults.lineHeight);
      root.style.setProperty('--display-reading-width', prefs.readingWidth || defaults.readingWidth);
      document.body.classList.toggle('display-pref-focus', Boolean(prefs.focusMode));
    }
    function syncControls(prefs) {
      var fontSize = document.querySelector('[data-testid="display-pref-font-size"]');
      var lineHeight = document.querySelector('[data-testid="display-pref-line-height"]');
      var readingWidth = document.querySelector('[data-testid="display-pref-reading-width"]');
      var focusMode = document.querySelector('[data-testid="display-pref-focus-mode"]');
      if (fontSize) fontSize.value = prefs.fontSize;
      if (lineHeight) lineHeight.value = prefs.lineHeight;
      if (readingWidth) readingWidth.value = prefs.readingWidth;
      if (focusMode) focusMode.checked = Boolean(prefs.focusMode);
    }
    function prefsFromControls(current) {
      var fontSize = document.querySelector('[data-testid="display-pref-font-size"]');
      var lineHeight = document.querySelector('[data-testid="display-pref-line-height"]');
      var readingWidth = document.querySelector('[data-testid="display-pref-reading-width"]');
      var focusMode = document.querySelector('[data-testid="display-pref-focus-mode"]');
      return {
        fontSize: fontSize ? fontSize.value : current.fontSize,
        lineHeight: lineHeight ? lineHeight.value : current.lineHeight,
        readingWidth: readingWidth ? readingWidth.value : current.readingWidth,
        focusMode: focusMode ? Boolean(focusMode.checked) : Boolean(current.focusMode)
      };
    }
    var prefs = readPrefs();
    applyPrefs(prefs);
    document.addEventListener('DOMContentLoaded', function () {
      syncControls(prefs);
      var panel = document.querySelector('[data-testid="display-preferences"]');
      if (!panel) return;
      panel.addEventListener('change', function () {
        prefs = prefsFromControls(prefs);
        applyPrefs(prefs);
        writePrefs(prefs);
      });
    });
  })();
  </script>"""


def _note_readback_script() -> str:
    """Local-first TTS/read-back controls for the rendered note surface."""

    return """
  <script>
  (function () {
    var proposalFieldOrder = ['decision', 'recommendation', 'why', 'risk', 'source', 'choices', 'status'];
    var currentAudio = null;
    function el(sel) { return document.querySelector(sel); }
    function status(text, state) {
      var node = el('[data-testid="tts-readback-status"]');
      if (!node) return;
      node.textContent = text || '';
      node.setAttribute('data-state', state || 'idle');
    }
    function rate() {
      var control = el('[data-testid="tts-rate"]');
      var parsed = control ? parseFloat(control.value) : 1;
      return Number.isFinite(parsed) ? parsed : 1;
    }
    function textOf(node) {
      return node ? String(node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
    }
    function selectedText() {
      var selection = window.getSelection ? window.getSelection() : null;
      return selection ? String(selection.toString() || '').trim() : '';
    }
    function proposalText() {
      var surface = el('.panel-decision-surface');
      if (!surface) return '';
      return proposalFieldOrder.map(function (field) {
        var node = surface.querySelector('[data-panel-decision-field="' + field + '"]');
        return textOf(node);
      }).filter(Boolean).join('. ');
    }
    function draftText() {
      var editor = document.getElementById('note-source-editor');
      return editor ? String(editor.value || '') : '';
    }
    function sourceNoteText() {
      var body = el('.note-body-content');
      if (!body) { return ''; }
      var clone = body.cloneNode(true);
      Array.prototype.slice.call(clone.querySelectorAll('.panel-decision-surface')).forEach(function (node) {
        node.remove();
      });
      return textOf(clone);
    }
    function cacheStatus(plan) {
      return plan && plan.cached ? 'cached' : 'not cached';
    }
    function renderSpeechPlan(plan) {
      var node = el('[data-testid="tts-plan-inspection"]');
      if (!node || !plan) { return; }
      var warnings = Array.isArray(plan.warnings) ? plan.warnings.slice() : [];
      if (plan.mixed_language) {
        warnings.push('mixed_language');
      }
      if (plan.provider_available === false) {
        warnings.push('provider_available false');
      }
      if (warnings.indexOf('skipped code block') >= 0) {
        warnings.push('skipped code blocks were omitted from read-back');
      }
      var segments = Array.isArray(plan.segments) ? plan.segments : [];
      var segmentRows = segments.map(function (segment) {
        return '<li>' + escapeHtml(segment.language || plan.language || 'unknown') +
          ' / ' + escapeHtml(segment.provider || plan.provider || 'unknown') +
          ' / ' + escapeHtml(segment.voice_id || plan.voice_id || 'unknown') +
          ' / ' + escapeHtml(cacheStatus(plan)) +
          ': ' + escapeHtml(segment.text || '') + '</li>';
      }).join('');
      var warningRows = warnings.map(function (warning) {
        return '<li class="tts-warning">' + escapeHtml(warning) + '</li>';
      }).join('');
      node.hidden = false;
      node.innerHTML =
        '<div class="tts-plan-text">' + escapeHtml(plan.normalized_text || '') + '</div>' +
        '<ul class="tts-plan-segments">' + segmentRows + '</ul>' +
        '<ul class="tts-plan-warnings">' + warningRows + '</ul>';
    }
    function escapeHtml(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }
    function postJson(path, payload) {
      return fetch(path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok) {
            var detail = data && data.detail ? data.detail : data;
            var message = detail && detail.reason ? detail.reason : 'Local TTS unavailable.';
            throw new Error(message);
          }
          return data;
        });
      });
    }
    function readText(text, label) {
      var normalized = String(text || '').trim();
      if (!normalized) {
        status('Nothing selected for read-back.', 'empty');
        return;
      }
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }
      status('Planning local TTS.', 'planning');
      postJson('/api/companion/tts/plan', {text: normalized, rate: rate()})
        .then(function (plan) {
          renderSpeechPlan(plan);
          if (!plan.cached && plan.provider_available === false) {
            throw new Error(plan.provider_reason || 'Local TTS provider/model unavailable.');
          }
          status('Synthesizing local audio.', 'synthesizing');
          return postJson('/api/companion/tts/synthesize', {text: normalized, rate: rate()});
        })
        .then(function (result) {
          if (!result.audio_url) {
            throw new Error(result.reason || 'Local TTS did not return audio.');
          }
          currentAudio = new Audio(result.audio_url);
          currentAudio.onended = function () { status('Read-back finished.', 'idle'); };
          currentAudio.onerror = function () { status('Read-back failed.', 'error'); };
          status(label || 'Reading local audio.', result.cached ? 'cached' : 'playing');
          return currentAudio.play();
        })
        .catch(function (err) {
          status(err && err.message ? err.message : 'Local TTS unavailable.', 'unavailable');
        });
    }
    window.noteReadback = {
      readFullNote: function () { readText(sourceNoteText(), 'Reading note source.'); },
      readSelection: function () { readText(selectedText(), 'Reading selected source text.'); },
      readProposal: function () { readText(proposalText(), 'Reading Panel proposal fields.'); },
      readDraft: function () { readText(draftText(), 'Reading editor draft.'); },
      pause: function () {
        if (currentAudio) {
          currentAudio.pause();
          status('Read-back paused.', 'paused');
        }
      },
      resume: function () {
        if (currentAudio) {
          currentAudio.play();
          status('Read-back resumed.', 'playing');
        }
      },
      stop: function () {
        if (currentAudio) {
          currentAudio.pause();
          currentAudio.currentTime = 0;
          currentAudio = null;
          status('Read-back stopped.', 'idle');
        }
      }
    };
    document.addEventListener('DOMContentLoaded', function () {
      status('Local TTS idle.', 'idle');
    });
  })();
  </script>"""


def _note_editor_script() -> str:
    """Direct human note editor: Read <-> Edit toggle over a plain textarea.

    Edit mode swaps the rendered body for the raw source in a native
    ``<textarea spellcheck>`` (OS-grade spellcheck — far better than any JS
    editor and impossible inside CodeMirror). Save POSTs to the same-origin
    ``/api/companion/note/save`` proxy (frontmatter preserved server-side, no
    Canvas/writeguard ceremony) and reloads to pick up the re-rendered note.
    Returned as a plain string so JS braces are not double-escaped by the page
    template.
    """
    return """
  <script>
  (function () {
    function el(sel) { return document.querySelector(sel); }
    function setStatus(cls, text) {
      var s = el('.note-edit-status');
      if (s) { s.className = 'note-edit-status' + (cls ? ' ' + cls : ''); s.textContent = text || ''; }
    }
    function proposalButton(id, action) {
      return document.querySelector('[data-correction-id="' + id + '"][data-correction-action="' + action + '"]');
    }
    window.noteEditor = {
      start: function () {
        var ta = document.getElementById('note-source-editor');
        if (!ta) { return; }
        var content = el('.note-body-content');
        var bar = el('[data-testid="workspace-note-edit-bar"]');
        var actions = el('[data-testid="workspace-note-edit-actions"]');
        var toggle = el('.note-edit-toggle');
        if (content) { content.hidden = true; }
        ta.hidden = false;
        if (bar) { bar.open = true; }
        if (actions) { actions.hidden = false; }
        if (toggle) { toggle.hidden = true; }
        setStatus('', '');
        ta.focus();
      },
      cancel: function () {
        var ta = document.getElementById('note-source-editor');
        var content = el('.note-body-content');
        var bar = el('[data-testid="workspace-note-edit-bar"]');
        var actions = el('[data-testid="workspace-note-edit-actions"]');
        var toggle = el('.note-edit-toggle');
        if (ta) { ta.hidden = true; ta.value = ta.defaultValue; }
        if (content) { content.hidden = false; }
        if (bar) { bar.open = false; }
        if (actions) { actions.hidden = true; }
        if (toggle) { toggle.hidden = false; }
        setStatus('', '');
      },
      applyCorrection: function (id) {
        var ta = document.getElementById('note-source-editor');
        var button = proposalButton(id, 'accept');
        if (!ta || !button) { return; }
        var start = parseInt(button.getAttribute('data-range-start') || '-1', 10);
        var end = parseInt(button.getAttribute('data-range-end') || '-1', 10);
        var proposed = button.getAttribute('data-proposed-text') || '';
        if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end < start) { return; }
        ta.value = ta.value.slice(0, start) + proposed + ta.value.slice(end);
        ta.dataset.correctionReviewState = 'accepted';
        var card = button.closest('[data-testid="text-correction-proposal"]');
        if (card) { card.setAttribute('data-review-state', 'accepted-local-draft'); }
        setStatus('', 'Correction applied to the local draft. Save explicitly to update the note.');
      },
      keepCorrection: function (id) {
        var button = proposalButton(id, 'keep-mine');
        if (!button) { return; }
        var card = button.closest('[data-testid="text-correction-proposal"]');
        if (card) { card.setAttribute('data-review-state', 'kept-mine'); }
        setStatus('', 'Kept your text. No durable change was written.');
      },
      save: function () {
        var ta = document.getElementById('note-source-editor');
        if (!ta) { return; }
        // Strip any URL fragment/anchor from the note identity — the canonical
        // note path never includes a #section-anchor (#1447).
        var notePath = (ta.getAttribute('data-note-path') || '').split('#')[0];
        setStatus('', 'Saving\\u2026');
        fetch('/api/companion/note/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            note_path: notePath,
            new_body: ta.value,
            expected_content_hash: ta.getAttribute('data-content-hash') || null
          })
        }).then(function (r) {
          return r.json().then(function (d) { return { ok: r.ok, status: r.status, data: d }; });
        }).then(function (res) {
          if (res.ok) {
            setStatus('ok', 'Saved. Reloading\\u2026');
            window.location.reload();
            return;
          }
          var d = res.data || {};
          var detail = d.detail || d;
          if (d.error === 'runtime_api_error' && typeof d.message === 'string') {
            try {
              var wrapped = JSON.parse(d.message);
              if (wrapped && typeof wrapped === 'object') {
                detail = wrapped.detail || wrapped;
              }
            } catch (e) {}
          }
          var err = detail.error || d.error || '';
          var rawMsg = detail.message || d.message || '';
          // Keep the raw machine detail inspectable (console + hover) without
          // showing raw JSON to the human (#1447).
          try { console.error('note save failed', res.status, d); } catch (e) {}
          var human;
          if (res.status === 404 && /not\\s*found/i.test(rawMsg) && err !== 'note_not_found') {
            human = 'Saving is not available on this runtime yet \\u2014 it needs the latest build (restart the runtime API).';
          } else if (err === 'note_not_found' || res.status === 404) {
            human = 'Note not found for: ' + notePath + '. Reload the note and try again.';
          } else if (err === 'content_hash_mismatch') {
            human = 'This note changed elsewhere since you opened it. Reload and re-apply your edit.';
          } else if (err === 'runtime_write_blocked') {
            human = 'The runtime has writes blocked right now (degraded state). Try again shortly.';
          } else if (err === 'path_escape' || err === 'invalid_note_path' || err === 'not_a_note_file') {
            human = 'That note path is not valid for editing.';
          } else if (err === 'frontmatter_in_body') {
            human = 'The body must not contain a frontmatter block (it is preserved automatically).';
          } else {
            human = 'Save failed (HTTP ' + res.status + '). See the browser console for details.';
          }
          var s = document.querySelector('.note-edit-status');
          if (s && rawMsg) { s.setAttribute('title', rawMsg); }
          setStatus('error', human);
        }).catch(function (e) {
          setStatus('error', 'Network error \\u2014 the runtime may be unreachable. ' + (e && e.message ? e.message : ''));
        });
      }
    };
  })();
  </script>"""


def _canvas_coauthor_script(canvas_enabled: bool) -> str:
    """Live canvas co-authoring loop wiring (#1733).

    The user states an intent; the served page POSTs ``{intent: ...}`` to
    ``/api/canvas/sessions/{id}/coauthor`` (endpoint read off the form's
    ``data-api-path``) and renders the server-applied body + change summary —
    server declares, UI renders, no local body composition. A governance-bearing
    409 (``status="routed_to_panel"``) surfaces a read-only "view in Panel"
    affordance keyed to the returned ``intent_id`` and applies no body edit. A
    503 shows a calm, non-destructive notice. Receipts are never invented.

    Emitted only when canvas is enabled; with the flag off there is no intent
    input, no co-author control, and no ``/coauthor`` call. Returned as a plain
    string so JS braces are not double-escaped by the page template.
    """
    if not canvas_enabled:
        return ""
    return """
  <script>
  (function() {
    var form = document.querySelector('[data-testid="workspace-canvas-coauthor"]');
    if (!form) return;
    var submit = form.querySelector('[data-testid="workspace-canvas-coauthor-submit"]');
    var intentInput = form.querySelector('[data-testid="workspace-canvas-coauthor-intent"]');
    var notice = form.querySelector('[data-testid="workspace-canvas-coauthor-notice"]');
    var result = form.querySelector('[data-testid="workspace-canvas-coauthor-result"]');
    var appliedBody = form.querySelector('[data-testid="workspace-canvas-coauthor-applied-body"]');
    var changeSummary = form.querySelector('[data-testid="workspace-canvas-coauthor-change-summary"]');
    var handoff = form.querySelector('[data-testid="workspace-canvas-coauthor-handoff"]');
    var viewInPanel = form.querySelector('[data-testid="workspace-canvas-view-in-panel"]');
    if (!submit) return;

    function showNotice(message) {
      if (!notice) return;
      notice.hidden = false;
      notice.setAttribute('data-notice-state', 'provider_unavailable');
      notice.textContent = message;
    }

    function clearTransient() {
      if (notice) { notice.hidden = true; notice.setAttribute('data-notice-state', 'idle'); notice.textContent = ''; }
      if (handoff) { handoff.hidden = true; handoff.setAttribute('data-handoff-state', 'idle'); }
      if (viewInPanel) { viewInPanel.setAttribute('data-intent-id', ''); }
    }

    function renderApplied(data) {
      // Server-declared body only; the UI composes nothing locally.
      if (result) result.setAttribute('data-result-state', 'applied');
      if (appliedBody) appliedBody.textContent = (data && data.applied_body) || '';
      if (changeSummary) changeSummary.textContent = (data && data.change_summary) || '';
    }

    function renderRoutedToPanel(data) {
      // Governance-bearing 409: do NOT apply a body edit; surface the
      // view-in-Panel affordance keyed to the server-provided intent_id.
      var intentId = (data && data.intent_id) || '';
      if (handoff) { handoff.hidden = false; handoff.setAttribute('data-handoff-state', 'routed_to_panel'); }
      if (viewInPanel) viewInPanel.setAttribute('data-intent-id', intentId);
      if (result) result.setAttribute('data-result-state', 'routed_to_panel');
    }

    function renderExploratory(data) {
      // Exploratory 200 (status='exploratory_no_edit'): read-only, non-mutating.
      // Must NOT render an applied edit — the note body is unchanged and there is
      // no applied_body/change_summary to show. Surface the server-declared
      // detail as a non-mutating notice instead.
      if (result) result.setAttribute('data-result-state', 'exploratory_no_edit');
      if (notice) {
        notice.hidden = false;
        notice.setAttribute('data-notice-state', 'exploratory_no_edit');
        notice.textContent = (data && data.detail)
          || 'Exploratory intent — read-only response; note body left unchanged.';
      }
    }

    submit.addEventListener('click', function() {
      if (submit.getAttribute('data-submitting') === 'true') return;
      var intent = intentInput ? intentInput.value : '';
      if (!intent) return;
      var endpoint = form.getAttribute('data-api-path') || submit.getAttribute('data-api-path');
      if (!endpoint) return;
      clearTransient();
      submit.setAttribute('data-submitting', 'true');
      fetch(endpoint, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({intent: intent})
      })
        .then(function(response) {
          return response.json().then(function(data) {
            return {status: response.status, ok: response.ok, data: data};
          }).catch(function() {
            return {status: response.status, ok: response.ok, data: {}};
          });
        })
        .then(function(res) {
          submit.removeAttribute('data-submitting');
          if (res.status === 409 && res.data && res.data.status === 'routed_to_panel') {
            renderRoutedToPanel(res.data);
            return;
          }
          if (res.status === 503) {
            showNotice('Co-authoring provider is unavailable right now. Nothing was changed.');
            return;
          }
          if (res.ok && res.data && res.data.status === 'exploratory_no_edit') {
            renderExploratory(res.data);
            return;
          }
          if (res.ok) {
            renderApplied(res.data);
            return;
          }
          showNotice('Co-authoring request failed. Nothing was changed.');
        })
        .catch(function() {
          submit.removeAttribute('data-submitting');
          showNotice('Co-authoring request failed. Nothing was changed.');
        });
    });
  })();
  </script>"""


def _correction_proposals_for_editor(editor_body: str) -> list[dict[str, object]]:
    proposals: list[dict[str, object]] = []
    for original, proposed, tier, reason, meaning_cue in (
        (
            "recieve",
            "receive",
            0,
            "orthographic spelling proposal",
            "receive means to get or accept something.",
        ),
        (
            "form",
            "from",
            1,
            "real-word/context flag",
            "Check whether `form` is intended, or possibly `from` in this sentence.",
        ),
    ):
        match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(original)}(?![A-Za-z0-9_])", editor_body)
        if match is None:
            continue
        start = match.start()
        proposals.append(
            {
                "id": f"correction-{len(proposals) + 1}",
                "tier": tier,
                "original_text": original,
                "proposed_text": proposed,
                "range": {"start": start, "end": start + len(original)},
                "reason": reason,
                "meaning_cue": meaning_cue,
                "posture": "proposal-class",
                "auto_apply": False,
            }
        )
    return proposals


def _render_text_correction_proposals(editor_body: str) -> str:
    proposals = _correction_proposals_for_editor(editor_body)
    if not proposals:
        return (
            '<section class="text-correction-proposals" '
            'data-testid="text-correction-proposals" '
            'data-authority="proposal-class-ui-internal" '
            'data-backend-api="none" data-proposal-count="0" hidden></section>'
        )
    rows: list[str] = []
    for proposal in proposals:
        span = proposal["range"]
        assert isinstance(span, dict)
        proposal_id = str(proposal["id"])
        tier = int(proposal["tier"])
        original = str(proposal["original_text"])
        proposed = str(proposal["proposed_text"])
        rows.append(
            f"""
            <article class="text-correction-proposal"
              data-testid="text-correction-proposal"
              data-correction-id="{_e(proposal_id)}"
              data-correction-tier="{tier}"
              data-auto-apply="false"
              data-review-state="pending">
              <div class="correction-token-row">
                <span data-testid="text-correction-original">{_e(original)}</span>
                <span aria-hidden="true">→</span>
                <span data-testid="text-correction-proposed">{_e(proposed)}</span>
              </div>
              <div class="correction-meta">
                <span data-testid="text-correction-tier">tier {tier}</span>
                <span data-testid="text-correction-reason">{_e(proposal["reason"])}</span>
                <span data-testid="text-correction-meaning-cue">{_e(proposal["meaning_cue"])}</span>
              </div>
              <div class="correction-actions">
                <button type="button"
                  data-correction-id="{_e(proposal_id)}"
                  data-correction-action="accept"
                  data-range-start="{int(span["start"])}"
                  data-range-end="{int(span["end"])}"
                  data-proposed-text="{_e(proposed)}"
                  onclick="noteEditor.applyCorrection('{_e(proposal_id)}')">
                  Accept proposal
                </button>
                <button type="button"
                  data-correction-id="{_e(proposal_id)}"
                  data-correction-action="keep-mine"
                  onclick="noteEditor.keepCorrection('{_e(proposal_id)}')">
                  Keep mine
                </button>
              </div>
            </article>"""
        )
    return f"""
          <section class="text-correction-proposals"
            data-testid="text-correction-proposals"
            data-authority="proposal-class-ui-internal"
            data-backend-api="none"
            data-proposal-count="{len(rows)}">
            {"".join(rows)}
          </section>"""


def _coerce_vault_link_index(value: object) -> dict[str, list[str]]:
    """Normalize an optional active-vault link index for the link resolver.

    Accepts ``{target: note_path}`` or ``{target: [note_path, ...]}`` and returns
    a mapping the ``VaultLinkResolver`` accepts. Unknown/None shapes yield an
    empty index (links stay diagnostic), preserving prior behavior (#1345).
    """
    if not isinstance(value, dict):
        return {}
    index: dict[str, list[str]] = {}
    for key, candidates in value.items():
        if isinstance(candidates, str):
            paths = [candidates]
        elif isinstance(candidates, (list, tuple)):
            paths = [str(path) for path in candidates if path]
        else:
            continue
        if paths:
            index[str(key)] = paths
    return index


def _plain_workspace_heading_text(text: str) -> str:
    text = text.strip(" #\t")
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _render_note_section(fields: dict) -> str:
    """Render the workspace shell from render_fields() output.

    Uses Yggdrasil design tokens. Stable data-testid / data-region attributes
    match the region constants in real_note_workspace_shell.py for future
    Canvas/Panel integration.
    """
    title = _e(_plain_workspace_heading_text(str(fields.get("title", "") or "")))
    raw_note_path = str(fields.get("note_path", "") or "")
    note_path_val = _e(raw_note_path)
    artifact_id = _e(fields.get("artifact_id", ""))
    content_hash = _e(fields.get("content_hash", ""))
    artifact_kind = _e(_status_label(fields.get("artifact_kind"), fallback="human_note"))
    identity_source = _e(_status_label(fields.get("artifact_identity_source")))
    identity_state_raw = _status_label(fields.get("artifact_identity_state"))
    identity_state = _e(identity_state_raw)
    companion_of = _e(fields.get("artifact_companion_of") or "")
    owns_identity = bool(fields.get("artifact_owns_identity", True))
    runtime_environment = _e(_status_label(fields.get("runtime_environment_label")))
    runtime_channel = _e(_status_label(fields.get("runtime_api_base_url_label"), fallback="local-dev"))
    runtime_trace_id = _e(fields.get("runtime_trace_id") or "")
    vault_name = _e(fields.get("runtime_vault_name") or "unresolved")
    vault_channel = _e(fields.get("runtime_vault_channel") or "unknown")
    vault_provenance = fields.get("runtime_vault_provenance") or "unresolved"
    raw_body = str(fields.get("body", "") or "")
    # #1345/#1431 — seed the link resolver with the active-vault link index so
    # vault-internal wikilinks resolve and navigate. The index arrives either as
    # the read-only link-index API's note-path list (#1431) — the resolver
    # expands each path into its lookup keys — or as a pre-built {target: paths}
    # mapping. Absent index → empty resolver, identical to the prior default
    # (every link stays diagnostic).
    raw_link_index = fields.get("vault_link_index")
    if isinstance(raw_link_index, (list, tuple)):
        link_index: list[str] | dict[str, list[str]] = [
            str(path) for path in raw_link_index if path
        ]
    else:
        link_index = _coerce_vault_link_index(raw_link_index)
    link_resolver = VaultLinkResolver(link_index)
    rendered_body = render_vault_markdown(
        raw_body,
        note_path=raw_note_path,
        link_resolver=link_resolver,
        panel_selectable_options=fields.get("panel_selectable_options") or [],
        content_hash=content_hash,
    )
    body = rendered_body.html
    body_empty_state_html = (
        _render_note_body_empty_state(raw_note_path)
        if not raw_body.strip() and not bool(fields.get("note_not_found", False))
        else ""
    )
    # Frontmatter-stripped source for the direct human editor (the save endpoint
    # preserves frontmatter and rejects a frontmatter block in the body).
    editor_body = str(getattr(rendered_body.document, "body_markdown", "") or "")
    text_correction_proposals_html = _render_text_correction_proposals(editor_body)
    outline_html = render_note_outline(rendered_body.document)
    has_headings = bool(tuple(rendered_body.document.headings))
    hidden_frontmatter_html, rendered_props = _render_note_frontmatter_region(rendered_body.document)
    panel_rail = _e(fields.get("panel_rail", "Panel / agent rail placeholder"))
    canvas_session_id = _e(fields.get("canvas_session_id") or "")
    canvas_state = _e(fields.get("canvas_session_state", "idle"))
    canvas_user_present = bool(fields.get("canvas_user_present", False))
    canvas_can_edit_body = bool(fields.get("canvas_can_edit_body", False))
    recovery_needed = bool(fields.get("canvas_recovery_needed", False))
    recovery_acknowledged = bool(fields.get("canvas_recovery_acknowledged", False))
    conflict_detected = bool(fields.get("canvas_conflict_detected", False))
    session_log_path = _e(fields.get("canvas_session_log_path") or "")
    undo_available = bool(fields.get("canvas_undo_available", False))
    applied_edit_count = int(fields.get("canvas_applied_edit_count", 0) or 0)
    undone_edit_count = int(fields.get("canvas_undone_edit_count", 0) or 0)
    persistence = str(fields.get("canvas_session_persistence", ""))
    panel_render = fields.get("panel_render") or {}
    panel_state_raw = str(panel_render.get("state") or fields.get("panel_state", "idle"))
    panel_state = _e(panel_state_raw)
    canvas_session_state_raw = str(fields.get("canvas_session_state", "idle") or "idle")
    panel_label = _e(panel_render.get("label") or panel_rail)
    panel_message_raw = str(panel_render.get("message") or "")
    panel_message = _e(panel_message_raw)
    proposal_count = int(fields.get("panel_proposal_count", 0) or 0)
    panel_proposals = fields.get("panel_proposals") or []
    # Relocated open-loops count badge on the panel rail (#2247,
    # TELEMETRY_RELOCATION-03): visible only in shell_active (a note is open);
    # omitted when zero or absent (no zero-state). Routes to memory.open.
    # data-authority="read-only-projection" — projection only, no mutation.
    _open_loops_count = int(fields.get("orientation_open_loops_count") or 0)
    panel_rail_open_loops_html = (
        f'<div class="panel-rail-open-loops" data-region="panel-rail-open-loops" '
        f'data-testid="panel-rail-open-loops" data-authority="read-only-projection">'
        f'<button type="button" class="panel-rail-open-loops-badge" '
        f'data-intent="memory.open" '
        f'onclick="if (window.overlayHost) {{ overlayHost.mount(\'memory\'); }}">'
        f'{_open_loops_count} open loop{"s" if _open_loops_count != 1 else ""}</button>'
        f'</div>'
        if _open_loops_count > 0
        else ""
    )
    writeguard_status = _e(fields.get("guard_writeguard_status", "ok"))
    writeguard_blocked = writeguard_status.lower() == "blocked"
    canvas_enabled = bool(fields.get("guard_canvas_enabled", True))
    update_flow_available = bool(fields.get("guard_update_flow_available", False))
    guard_degraded = bool(fields.get("guard_degraded", False))
    workspace_update_available = bool(fields.get("guard_workspace_update_available", False))
    workspace_update_state = _e(fields.get("guard_workspace_update_state") or "disabled")
    workspace_update_reason = _e(fields.get("guard_workspace_update_reason") or "not_declared")
    workspace_update_scope = _e(fields.get("guard_workspace_update_scope") or "active_note_body")
    workspace_update_governance_actions_enabled = bool(
        fields.get("guard_workspace_update_governance_actions_enabled", False)
    )
    workspace_update_config_mode = _e(fields.get("guard_workspace_update_config_mode") or "inherited")
    active_note_body_update_enabled = bool(
        fields.get("active_note_body_update_enabled", workspace_update_available)
    )
    active_note_body_update_state = _e(fields.get("active_note_body_update_state") or "idle")
    active_note_body_update_message = _e(fields.get("active_note_body_update_message") or "")
    identity_caution_html = ""
    if identity_state_raw.startswith("unresolved"):
        identity_caution_html = (
            '<div class="identity-caution" data-testid="workspace-artifact-identity-caution">'
            "<span>Identity unresolved</span>"
            "<small>Governed actions may be blocked until resolved.</small>"
            "</div>"
        )
    companion_html = (
        f'<span class="identity-meta" data-testid="workspace-companion-of">companion of {companion_of}</span>'
        if companion_of
        else ""
    )
    vault_unreachable = bool(fields.get("vault_unreachable", False)) or str(vault_provenance).lower() == "unreachable"
    vault_unresolved = (
        str(vault_provenance).lower() == "unresolved"
        or str(fields.get("runtime_vault_name") or "").lower() == "unresolved"
    )
    note_not_found = bool(fields.get("note_not_found", False))
    posture_token, posture_label = _compute_primary_posture(
        writeguard_blocked=writeguard_blocked,
        vault_unresolved=vault_unresolved,
        canvas_enabled=canvas_enabled,
        workspace_update_available=workspace_update_available,
        guard_degraded=guard_degraded,
    )
    effective_vault_provenance = "unreachable" if vault_unreachable else str(vault_provenance)
    workspace_header_strip_html = _render_workspace_header_strip(
        fields=fields,
        posture=posture_token,
        posture_label=posture_label,
        runtime_environment=runtime_environment,
        runtime_channel=runtime_channel,
        runtime_trace_id=runtime_trace_id,
        vault_name=vault_name,
        vault_channel=vault_channel,
        vault_provenance=effective_vault_provenance,
        writeguard_status=writeguard_status,
        canvas_enabled=canvas_enabled,
        update_flow_available=update_flow_available,
        guard_degraded=guard_degraded,
        workspace_update_available=workspace_update_available,
        workspace_update_state=workspace_update_state,
        workspace_update_reason=workspace_update_reason,
        workspace_update_scope=workspace_update_scope,
        workspace_update_governance_actions_enabled=workspace_update_governance_actions_enabled,
        workspace_update_config_mode=workspace_update_config_mode,
        orientation_freshness=str(fields.get("orientation_freshness") or ""),
        orientation_as_of=str(fields.get("orientation_as_of") or ""),
        orientation_trace_id=str(fields.get("orientation_trace_id") or ""),
    )
    breadcrumb_html = _render_workspace_breadcrumb(
        note_path=note_path_val,
        artifact_id=artifact_id,
        content_hash=content_hash,
        identity_state=identity_state,
        identity_source=identity_source,
        artifact_kind=artifact_kind,
        owns_identity=owns_identity,
        companion_html=companion_html,
        rendered_props=rendered_props,
    )
    vault_unreachable_banner_html = (
        _render_vault_unreachable_banner(
            last_sync=fields.get("vault_last_sync_label") or fields.get("runtime_last_ingest_at") or ""
        )
        if vault_unreachable
        else ""
    )
    # Direct human editing is always available, so "Canvas off" no longer means
    # the note is read-only — the misleading read-only pill is suppressed (#1447).
    # A genuine write-blocked state surfaces with explicit copy at save time.
    read_only_pill_html = ""
    note_not_found_html = _render_note_not_found(raw_note_path) if note_not_found else ""
    rail_empty_state_html = _render_rail_empty_state(
        panel_proposal_count=proposal_count,
        panel_proposals=panel_proposals,
        canvas_session_state=canvas_session_state_raw,
        panel_state=panel_state_raw,
        panel_message=panel_message_raw,
        find_candidates_count=len(fields.get("find_candidates") or []),
        reorient_present=bool(fields.get("reorient_sections")),
        resurface_count=len(fields.get("resurface_candidates") or []),
        governance_receipts_count=len(fields.get("governance_receipts") or []),
        suggestion_state=str(fields.get("suggestion_state", "idle") or "idle"),
    )

    # §§8–9 — right rail compaction. The rail stays expanded only when it has
    # actionable or safety-critical content. Otherwise the idle/unavailable
    # cards collapse behind one compact posture treatment.
    _panel_last_response = fields.get("panel_last_response") or {}
    # #1419 — only genuinely safety-affecting state is "critical". Generic
    # guard_degraded (e.g. Canvas disabled) and vault_unreachable are passive
    # capability/availability states: the former is non-actionable, the latter
    # already has its own prominent unreachable banner. They must not force the
    # rail open or read as "needs attention".
    rail_safety_critical = (
        writeguard_blocked
        or recovery_needed
        or conflict_detected
    )
    # Reorient counts as actionable only when it carries real items (an
    # orientation step), not when it is the idle/empty recall payload (#1419).
    _reorient = fields.get("reorient_sections") or {}
    reorient_actionable = any(_reorient.get(name) for name in _reorient)
    # Commitments count as actionable when the surface has something the human
    # should see now: active commitments (populated) or an honest degraded /
    # not-shown notice. A healthy-empty surface stays idle (#2075).
    _commitments = fields.get("commitments_surface") or {}
    commitments_actionable = str(_commitments.get("state") or "") in {
        "populated",
        "degraded",
        "not-shown",
    }
    rail_actionable = bool(
        rail_safety_critical
        or proposal_count > 0
        or bool(panel_proposals)
        or bool(_panel_last_response)
        or canvas_session_state_raw not in {"idle", "", "unknown"}
        or panel_state_raw not in {"idle", "", "unknown"}
        or bool(panel_message_raw)
        or len(fields.get("find_candidates") or []) > 0
        or reorient_actionable
        or len(fields.get("resurface_candidates") or []) > 0
        or commitments_actionable
        or len(fields.get("governance_receipts") or []) > 0
        or len(fields.get("suggestion_cards") or []) > 0
        or str(fields.get("suggestion_state", "idle") or "idle") not in {"idle", "", "unknown"}
    )
    rail_posture_token = "active" if rail_actionable else "idle"
    if rail_safety_critical:
        rail_posture_copy = "Companion &middot; needs attention"
    elif rail_actionable:
        rail_posture_copy = "Companion &middot; active"
    else:
        rail_posture_copy = "Companion &middot; idle — no active proposals."

    guard_messages: list[str] = []
    if writeguard_status.lower() == "blocked":
        guard_messages.append("WriteGuard blocked")
    if not canvas_enabled:
        guard_messages.append("Canvas disabled")
    if not workspace_update_available:
        guard_messages.append("Workspace update disabled")
    guard_html = ""
    if guard_messages:
        guard_html = (
            '<div class="rail-alert rail-alert-blocked" '
            'data-testid="workspace-guard-indicator">'
            + _e(" / ".join(guard_messages))
            + "</div>"
        )
    persistence_html = ""
    if persistence == "in_memory":
        persistence_html = (
            '<div class="rail-alert rail-alert-muted" '
            'data-testid="workspace-session-persistence">'
            "Session persistence: in_memory"
            "</div>"
        )
    proposal_text = f"{proposal_count} proposal{'s' if proposal_count != 1 else ''}"
    panel_message_html = ""
    if panel_message:
        panel_message_html = (
            '<div class="panel-message" data-testid="workspace-panel-message">'
            + panel_message
            + "</div>"
        )
    proposal_rows_html = _render_panel_proposal_rows(
        fields.get("panel_proposals") or [],
        writeguard_blocked=writeguard_blocked,
    )
    panel_response_html = _render_panel_confirm_response(
        fields.get("panel_last_response") or {},
    )
    suggestion_flow_html = _render_suggestion_flow_region(fields)
    suggestion_cards_html = _render_suggestion_cards(fields.get("suggestion_cards") or [])
    portrait_sheet_html = _render_portrait_sheet(fields.get("portrait_sheet") or {})
    shortcut_html = _render_keyboard_shortcuts(fields.get("keyboard_shortcuts") or {})
    governance_receipts_html = _render_governance_receipts(
        fields.get("governance_receipts") or []
    )
    find_mode_html = _render_find_mode(
        fields.get("find_candidates") or [],
        payload_available=bool(fields.get("find_payload_available", False)),
    )
    reorient_mode_html = _render_reorient_mode(fields.get("reorient_sections") or {})
    resurface_mode_html = _render_resurface_mode(
        fields.get("resurface_candidates") or [],
        degraded=guard_degraded,
    )
    commitments_mode_html = _render_commitments_mode(
        fields.get("commitments_surface")
    )
    act_mode_html = _render_act_mode(
        proposals=fields.get("panel_proposals") or [],
        response=fields.get("panel_last_response") or {},
        writeguard_blocked=writeguard_blocked,
    )
    vault_browser_html = _render_vault_browser(
        note_path=fields.get("note_path") or "",
        notes=fields.get("vault_browser_notes") or [],
        query=str(fields.get("vault_browser_query") or ""),
        total_notes=int(fields.get("vault_browser_total_notes") or 0),
        filtered_notes=int(fields.get("vault_browser_filtered_notes") or 0),
        error=fields.get("vault_browser_error"),
        read_only=bool(fields.get("vault_browser_read_only", True)),
        identity_available=bool(fields.get("vault_browser_identity_available", False)),
        vault_name=str(fields.get("vault_browser_vault_name") or "unresolved"),
        vault_channel=str(fields.get("vault_browser_vault_channel") or "unknown"),
        vault_provenance=str(fields.get("vault_browser_vault_provenance") or "unresolved"),
        active_filters=dict(fields.get("vault_browser_active_filters") or {}),
        pagination=dict(fields.get("vault_browser_pagination") or {}),
    )
    suggested_insertions_html = _render_suggested_insertions(
        fields.get("suggested_insertions") or []
    )
    canvas_controls_html = _render_canvas_session_controls(
        note_path=note_path_val,
        session_id=canvas_session_id,
        session_state=canvas_state,
        can_edit_body=canvas_can_edit_body,
        user_present=canvas_user_present,
        content_hash=content_hash,
        recovery_needed=recovery_needed,
        recovery_acknowledged=recovery_acknowledged,
        conflict_detected=conflict_detected,
        canvas_enabled=canvas_enabled,
        workspace_update_available=workspace_update_available,
        workspace_update_reason=workspace_update_reason,
        writeguard_blocked=writeguard_blocked,
        session_log_path=session_log_path,
        undo_available=undo_available,
        applied_edit_count=applied_edit_count,
        undone_edit_count=undone_edit_count,
    )
    active_note_body_update_html = _render_active_note_body_update_flow(
        note_path=note_path_val,
        content_hash=content_hash,
        enabled=active_note_body_update_enabled,
        state=active_note_body_update_state,
        message=active_note_body_update_message,
        reason=workspace_update_reason,
    )
    canvas_state_copy = _e(
        "Disabled"
        if not canvas_enabled or writeguard_blocked
        else _human_state_label(
            canvas_session_state_raw,
            {
                "idle": "No active Canvas session",
                "active": "Canvas session active",
                "composing": "Canvas session active",
                "paused": "Canvas session paused",
                "closed": "Canvas session closed",
            },
            fallback="Canvas session unavailable",
        )
    )
    panel_state_copy = _e(
        _human_state_label(
            panel_state_raw,
            {
                "idle": "No active Panel proposal",
                "running": "Panel is preparing proposals",
                "proposals-staged": "Panel proposal ready",
                "proposal_staged": "Panel proposal ready",
                "blocked": "Panel blocked",
            },
            fallback="Panel state unavailable",
        )
    )

    left_context_panel_html = _render_left_context_panel(
        vault_browser_html=vault_browser_html,
        outline_html=outline_html,
        has_headings=has_headings,
        note_path_val=note_path_val,
        identity_state_label=identity_state,
    )

    # §§8–9 — compact posture chip + the detailed rail cards. When the rail is
    # not actionable, the idle cards collapse behind one details affordance so
    # the rail stops acting as a permanent status dump.
    rail_posture_html = (
        '<div class="rail-posture" data-testid="workspace-rail-posture" '
        f'data-rail-posture="{rail_posture_token}">{rail_posture_copy}</div>'
    )
    rail_cards_inner = f"""
        <div class="rail-state-row" data-testid="workspace-canvas-state">
          <span class="rail-state-label">Canvas</span>
          <span class="rail-state-value" data-canvas-state="{canvas_state}">{canvas_state_copy}</span>
        </div>
        {canvas_controls_html}
        {active_note_body_update_html}
        <div class="rail-state-row">
          <span class="rail-state-label">Panel</span>
          <span class="rail-state-value" data-testid="workspace-panel-label">{panel_label}</span>
          <span class="rail-state-count" data-testid="workspace-panel-proposal-count">{proposal_text}</span>
        </div>
        {panel_message_html}
        {proposal_rows_html}
        {panel_response_html}
        {suggestion_flow_html}
        {suggestion_cards_html}
        {shortcut_html}
        {governance_receipts_html}
        {find_mode_html}
        {reorient_mode_html}
        {resurface_mode_html}
        {commitments_mode_html}
        {act_mode_html}
        {guard_html}
        {persistence_html}
        {panel_rail}
        {rail_empty_state_html}"""
    if rail_actionable:
        rail_body_html = (
            f'<div class="rail-placeholder-body">{rail_cards_inner}\n      </div>'
        )
    else:
        rail_body_html = (
            '<div class="rail-placeholder-body">'
            '<details class="rail-idle-details" data-testid="workspace-rail-idle-details">'
            '<summary class="rail-idle-summary">Companion details</summary>'
            f"{rail_cards_inner}\n      </details></div>"
        )

    return f"""
  <div class="workspace-layout workspace-layout--three-col">
    {left_context_panel_html}
    <div class="workspace-main">
      {workspace_header_strip_html}
      {vault_unreachable_banner_html}
      <header
        class="note-header active-note-header"
        data-testid="workspace-note-header"
        data-region="note-header">
        <h1 class="note-title">{title}</h1>
        {breadcrumb_html}
        {identity_caution_html}
      </header>
      {hidden_frontmatter_html}
      {note_not_found_html}
      <div
        class="note-reading-layout note-reading-layout--single"
        data-testid="workspace-note-reading-layout">
        <button class="workspace-outline-ribbon" data-testid="workspace-outline-ribbon"
          aria-label="open outline" data-layout-visible="800-1099"
          onclick="leftPanel.setMode('outline')">☰ outline</button>
        <div class="note-body" data-testid="workspace-note-body" data-region="note-body"
          data-read-only="false">
          <div class="note-body-readonly-indicator"
            data-testid="workspace-note-body-readonly-indicator"
            data-read-only="false" hidden>read-only</div>
          <div class="note-body-readonly-reason"
            data-testid="workspace-note-body-readonly-reason"
            aria-live="polite"
            hidden>
            Editing is currently disabled by runtime configuration.&#160;<a
              href="#workspace-runtime-telemetry"
              data-testid="workspace-note-body-readonly-why">Why?</a>
          </div>
          {read_only_pill_html}
          <details class="tts-readback-controls"
            data-testid="tts-readback-controls"
            data-authority="read-only-projection"
            data-source-scope="source-and-proposal">
            <summary class="tts-readback-summary">Read aloud</summary>
            <div class="tts-readback-panel">
              <label class="tts-rate-control">
                <span>Rate</span>
                <select data-testid="tts-rate" aria-label="Read-back rate">
                  <option value="0.85">0.85</option>
                  <option value="1" selected>1.0</option>
                  <option value="1.15">1.15</option>
                  <option value="1.3">1.3</option>
                </select>
              </label>
              <button type="button" data-testid="tts-read-full-note"
                data-tts-action="read-full-note" data-tts-requires-speech="true"
                onclick="noteReadback.readFullNote()">Read note</button>
              <button type="button" data-testid="tts-read-selection"
                data-tts-action="read-selection" data-tts-requires-speech="true"
                onclick="noteReadback.readSelection()">Selection</button>
              <button type="button" data-testid="tts-read-proposal"
                data-tts-action="read-proposal" data-tts-requires-speech="true"
                onclick="noteReadback.readProposal()">Proposal</button>
              <button type="button" data-testid="tts-pause"
                data-tts-action="pause" data-tts-requires-speech="true"
                onclick="noteReadback.pause()">Pause</button>
              <button type="button" data-testid="tts-resume"
                data-tts-action="resume" data-tts-requires-speech="true"
                onclick="noteReadback.resume()">Resume</button>
              <button type="button" data-testid="tts-stop"
                data-tts-action="stop" data-tts-requires-speech="true"
                onclick="noteReadback.stop()">Stop</button>
              <span class="tts-readback-status" data-testid="tts-readback-status"
                data-state="idle" aria-live="polite">Read-back idle.</span>
            </div>
          </details>
          <div class="tts-plan-inspection"
            data-testid="tts-plan-inspection"
            data-authority="read-only-projection"
            aria-live="polite"
            hidden></div>
          <!-- The shipped #1675 display-preference controls moved into the
               Settings drawer (#1789, SEP-07) — presentation consolidation
               only; their storage/apply mechanism below is unchanged. -->
          <details class="note-edit-bar" data-testid="workspace-note-edit-bar">
            <summary class="note-edit-summary">
              <button type="button" class="note-edit-toggle"
              data-testid="workspace-note-edit-toggle"
              onclick="noteEditor.start()">&#9998;&#160;Edit</button>
            </summary>
            <div class="note-edit-actions" data-testid="workspace-note-edit-actions" hidden>
              <button type="button" class="note-edit-readback"
                data-testid="workspace-note-edit-read-draft"
                data-tts-action="read-draft" data-tts-requires-speech="true"
                onclick="noteReadback.readDraft()">Read draft</button>
              <button type="button" class="note-edit-save"
                data-testid="workspace-note-edit-save"
                onclick="noteEditor.save()">Save</button>
              <button type="button" class="note-edit-cancel"
                data-testid="workspace-note-edit-cancel"
                onclick="noteEditor.cancel()">Cancel</button>
              <span class="note-edit-status" data-testid="workspace-note-edit-status"
                aria-live="polite"></span>
            </div>
            {text_correction_proposals_html}
          </details>
          <div class="note-body-content" data-testid="workspace-note-rendered">{body_empty_state_html}{body}</div>
          <textarea class="note-source-editor" id="note-source-editor"
            data-testid="workspace-note-source-editor"
            spellcheck="true" autocapitalize="sentences" autocorrect="off"
            autocomplete="off" wrap="soft"
            aria-label="Edit note source"
            data-note-path="{note_path_val}" data-content-hash="{content_hash}"
            hidden>{_e(editor_body)}</textarea>
          {suggested_insertions_html}
        </div>
      </div>
      {_render_body_edit_panel(update_flow_available, note_path_val, raw_body)}
    </div>
    <aside
      class="agent-rail"
      data-testid="workspace-agent-rail"
      data-region="agent-rail"
      data-layout-desktop="side-rail">
      <div class="rail-header" data-testid="workspace-panel-column-header">
        <span class="rail-label" data-panel-state="{panel_state}">{'Panel&nbsp;&middot;&nbsp;idle' if panel_state_raw == 'idle' else 'Panel'}</span>
        <span class="rail-badge" data-testid="workspace-panel-state" data-panel-state="{panel_state}">{panel_state_copy}</span>
      </div>
      {rail_posture_html}
      {rail_body_html}
      {panel_rail_open_loops_html}
    </aside>
    <div class="workspace-panel-peek" data-testid="workspace-panel-peek"
      data-layout-visible="1100-1299"
      data-panel-proposal-count="{proposal_count}">{f'<span class="peek-badge" data-testid="workspace-panel-peek-badge">{proposal_count}</span>' if proposal_count else ""}</div>
    <div class="workspace-sheet-triggers" data-layout-visible="max-799">
      <button class="workspace-outline-sheet-trigger" data-testid="workspace-outline-sheet-trigger"
        aria-label="open outline">&#9776; Outline</button>
      <button class="workspace-panel-sheet-trigger" data-testid="workspace-panel-sheet-trigger"
        aria-label="open panel">Panel</button>
    </div>
    {portrait_sheet_html}
  </div>"""


def _render_active_note_body_update_flow(
    *,
    note_path: str,
    content_hash: str,
    enabled: bool,
    state: str,
    message: str,
    reason: str,
) -> str:
    safe_state = _e(state or "idle")
    safe_message = _e(message)
    if not enabled:
        # Render a hidden absence marker — keeps testid selectors functional while
        # not adding a duplicate "unavailable" banner (daily-use dedup, #1361).
        return (
            '<section'
            ' class="active-note-body-update-flow active-note-body-update-flow--disabled"'
            ' data-testid="workspace-active-note-body-update-flow"'
            ' data-flow-state="disabled"'
            f' data-reason="{_e(reason)}">'
            '<div'
            ' class="active-note-body-update-blocked active-note-body-update-blocked--quiet"'
            ' data-testid="workspace-active-note-body-update-state-blocked"'
            ' hidden>'
            "</div>"
            "</section>"
        )

    status_html = ""
    if safe_state == "success":
        status_html = (
            '<div class="active-note-body-update-success" '
            'data-testid="workspace-active-note-body-update-state-success">'
            + (safe_message or "Body update saved.")
            + "</div>"
        )
    elif safe_state == "blocked":
        status_html = (
            '<div class="active-note-body-update-blocked" '
            'data-testid="workspace-active-note-body-update-state-blocked">'
            + (safe_message or "Body update blocked by runtime guard.")
            + "</div>"
        )
    elif safe_state == "failure":
        status_html = (
            '<div class="active-note-body-update-failure" '
            'data-testid="workspace-active-note-body-update-state-failure">'
            + (safe_message or "Body update failed.")
            + "</div>"
        )

    # #1346 AC5 — visible unsaved-edit signal. Rendered hidden by default and
    # revealed when the editor has uncommitted content (client `oninput`), or
    # shown immediately when the page model reports the `staged` state. It is an
    # unsaved indicator only — it submits no write and does not alter writeguard.
    staged_hidden = "" if safe_state == "staged" else " hidden"
    staged_message = safe_message if (safe_state == "staged" and safe_message) else "Unsaved edit — commit to save."
    staged_html = (
        '<div class="active-note-body-update-staged" '
        'data-testid="workspace-active-note-body-update-state-staged"'
        f"{staged_hidden}>{staged_message}</div>"
    )
    reveal_staged = (
        "var s=this.closest('.active-note-body-update-flow')"
        ".querySelector('[data-testid=\\'workspace-active-note-body-update-state-staged\\']');"
        "if(s){s.hidden=this.value.length===0;}"
    )
    return f"""
        <section
          class="active-note-body-update-flow"
          data-testid="workspace-active-note-body-update-flow"
          data-flow-state="enabled">
          <label for="active_note_body_update_input">Active note body update</label>
          <textarea
            id="active_note_body_update_input"
            data-testid="workspace-active-note-body-update-input"
            oninput="{reveal_staged}"
            aria-label="Active note body update input"></textarea>
          <button
            type="button"
            data-testid="workspace-active-note-body-update-submit"
            data-api-method="POST"
            data-api-path="/api/companion/workspace/update"
            data-note-path="{_e(note_path)}"
            data-content-hash="{_e(content_hash)}">Update body</button>
          {staged_html}
          {status_html}
        </section>"""


def _render_inspector_links(note: dict) -> str:
    """Render read-only relation data declared by the runtime payload."""
    sentinel = object()
    relations_raw = note.get("relations", sentinel)
    declared_state = str(note.get("relations_state") or "").strip()
    if relations_raw is sentinel:
        relation_state = declared_state or "unavailable"
        return (
            '<section class="inspector-links" '
            'data-testid="workspace-vault-browser-inspector-links" '
            f'data-relation-state="{_e(relation_state)}" '
            'data-affordance-status="read-only">'
            '<span class="inspector-label">links</span>'
            '<span class="inspector-links-unavailable">Relation index unavailable.</span>'
            '</section>'
        )

    relations: list[dict] = [r for r in list(relations_raw or []) if isinstance(r, dict)]
    if not relations:
        return (
            '<section class="inspector-links" '
            'data-testid="workspace-vault-browser-inspector-links" '
            'data-relation-state="empty" '
            'data-affordance-status="read-only">'
            '<span class="inspector-label">links</span>'
            '<span class="inspector-links-empty">No link relations found for this artifact.</span>'
            '</section>'
        )

    relation_rows: list[str] = []
    for relation in relations:
        signals = [
            signal
            for signal in list(relation.get("ranking_signals") or relation.get("signals") or [])
            if isinstance(signal, dict)
        ]
        primary_signal = signals[0] if signals else {}
        relation_type = str(primary_signal.get("signal") or "related")
        provenance = str(primary_signal.get("provenance") or "")
        signal_html = "".join(
            (
                '<span class="inspector-link-signal" '
                'data-testid="vault-browser-inspector-link-signal" '
                f'data-signal="{_e(str(signal.get("signal") or ""))}" '
                f'data-weight="{_e(str(signal.get("weight") or ""))}" '
                f'data-provenance="{_e(str(signal.get("provenance") or ""))}">'
                f'{_e(str(signal.get("signal") or ""))}'
                '</span>'
            )
            for signal in signals
        )
        relation_rows.append(
            '<article class="inspector-link-relation" '
            'data-testid="vault-browser-inspector-link-relation" '
            f'data-mode="{_e(str(relation.get("data_mode") or "read_only"))}" '
            f'data-note-path="{_e(str(relation.get("note_path") or ""))}" '
            f'data-relation-type="{_e(relation_type)}" '
            f'data-provenance="{_e(provenance)}">'
            f'<span class="inspector-link-title">{_e(str(relation.get("title") or "Related artifact"))}</span>'
            f'<code class="inspector-link-path">{_e(str(relation.get("note_path") or ""))}</code>'
            f'{signal_html}'
            '</article>'
        )
    return (
        '<section class="inspector-links" '
        'data-testid="workspace-vault-browser-inspector-links" '
        'data-relation-state="ready" '
        'data-affordance-status="read-only">'
        '<span class="inspector-label">links</span>'
        + "".join(relation_rows)
        + '</section>'
    )


def _render_inspector_zone_field(note: dict) -> str:
    """Render the zone field with its #1488 source/authority/provenance/degradation envelope.

    The UI reads the server-declared zone envelope verbatim and never re-derives zone authority
    locally (#1555). A path-derived ``runtime_projection`` zone is rendered visibly distinct from a
    durable ``durable_vault_metadata`` (frontmatter) zone, and the provenance/degradation are made
    inspectable so a ``frontmatter_absent`` / ``frontmatter_invalid`` zone is never presented as
    authoritative. No zone-based ordering/overlay is introduced.
    """
    zone_val = note.get("zone")
    if zone_val is None:
        return ""
    authority_role = str(note.get("zone_authority_role") or "").strip()
    source = str(note.get("zone_source") or "").strip()
    provenance = str(note.get("zone_provenance") or "").strip()
    degradation = str(note.get("zone_degradation") or "").strip()

    authority_labels = {
        "durable_vault_metadata": "frontmatter",
        "runtime_projection": "derived from path",
        "unavailable": "unavailable",
    }
    authority_label = authority_labels.get(authority_role, "")
    badge_html = ""
    if authority_label:
        badge_html = (
            '<span class="inspector-zone-authority" '
            'data-testid="workspace-vault-browser-inspector-zone-authority" '
            f'data-authority-role="{_e(authority_role)}">'
            f'{_e(authority_label)}'
            '</span>'
        )

    # Provenance + degradation are surfaced whenever the zone is not a clean durable source, so a
    # degraded (path-derived) zone exposes where it came from rather than masquerading as durable.
    detail_html = ""
    if degradation and degradation != "none":
        detail_title = f"source: {source} · provenance: {provenance} · degradation: {degradation}"
        detail_html = (
            '<span class="inspector-zone-provenance" '
            'data-testid="workspace-vault-browser-inspector-zone-provenance" '
            f'data-provenance="{_e(provenance)}" '
            f'data-degradation="{_e(degradation)}" '
            f'title="{_e(detail_title)}">'
            f'{_e(f"{provenance} ({degradation})")}'
            '</span>'
        )

    return (
        '<div data-testid="workspace-vault-browser-inspector-zone" class="inspector-field" '
        f'data-zone-source="{_e(source)}" '
        f'data-zone-authority-role="{_e(authority_role)}" '
        f'data-zone-provenance="{_e(provenance)}" '
        f'data-zone-degradation="{_e(degradation)}">'
        '<span class="inspector-label">zone</span>'
        f'<span class="inspector-zone-value">{_e(str(zone_val))}</span>'
        f'{badge_html}'
        f'{detail_html}'
        '</div>'
    )


def _render_artifact_inspector(
    note: dict,
    *,
    vault_name: str,
    vault_channel: str,
) -> str:
    """Render a read-only artifact inspector panel for the selected note.

    Tabs/sections: Metadata, Health, Provenance, Links, Receipts.
    Inspector is read-only; no edit controls rendered. Client uses normalized server
    payload only — no frontmatter parsing here (#1255).
    """
    title = _e(str(note.get("title") or ""))
    path = _e(str(note.get("note_path") or ""))
    kind_val = note.get("kind")
    review_state_val = note.get("review_state")
    trust_val = note.get("trust")
    uuid_val = note.get("uuid")
    origin_val = note.get("origin")
    source_ref_val = note.get("source_ref")
    created_val = note.get("created")
    updated_val = note.get("updated")
    frontmatter_valid = bool(note.get("frontmatter_valid", True))
    missing_fields: list[str] = list(note.get("missing_required_fields") or [])

    uuid_html = (
        f'<div data-testid="workspace-vault-browser-inspector-uuid" '
        f'class="inspector-field">'
        f'<span class="inspector-label">uuid</span>'
        f'<code>{_e(str(uuid_val))}</code>'
        f'</div>'
    ) if uuid_val else ""

    def _field_row(testid: str, label: str, val: object) -> str:
        if val is None:
            return ""
        return (
            f'<div data-testid="{testid}" class="inspector-field">'
            f'<span class="inspector-label">{_e(label)}</span>'
            f'<span>{_e(str(val))}</span>'
            f'</div>'
        )

    metadata_rows = "".join([
        _field_row("workspace-vault-browser-inspector-kind", "kind", kind_val),
        _render_inspector_zone_field(note),
        _field_row("workspace-vault-browser-inspector-review-state", "review state", review_state_val),
        _field_row("workspace-vault-browser-inspector-trust", "trust", trust_val),
        _field_row("workspace-vault-browser-inspector-origin", "origin", origin_val),
        _field_row("workspace-vault-browser-inspector-source-ref", "source ref", source_ref_val),
        _field_row("workspace-vault-browser-inspector-created", "created", created_val),
        _field_row("workspace-vault-browser-inspector-updated", "updated", updated_val),
    ])

    health_state = "valid" if frontmatter_valid and not missing_fields else "invalid"
    missing_label = ", ".join(missing_fields) if missing_fields else ""
    health_detail = (
        f'<span class="inspector-health-missing">{_e(missing_label)}</span>'
        if missing_label
        else ""
    )
    health_copy = "Frontmatter valid." if health_state == "valid" else f"Invalid or missing required fields: {_e(missing_label or 'unknown')}."
    health_html = (
        f'<div data-testid="workspace-vault-browser-inspector-health" '
        f'class="inspector-health" data-health-state="{health_state}">'
        f'<span class="inspector-label">health</span>'
        f'<span class="inspector-health-copy">{health_copy}</span>'
        f'{health_detail}'
        f'</div>'
    )

    artifact_identity_html = (
        f'<div data-testid="workspace-vault-browser-inspector-artifact-identity" '
        f'class="inspector-identity-artifact">'
        f'<span class="inspector-label">artifact identity</span>'
        f'{uuid_html}'
        f'{_field_row("workspace-vault-browser-inspector-origin-in-identity", "origin", origin_val)}'
        f'</div>'
    )

    vault_identity_html = (
        f'<div data-testid="workspace-vault-browser-inspector-vault-identity" '
        f'class="inspector-identity-vault">'
        f'<span class="inspector-label">vault/channel</span>'
        f'<span>{_e(vault_name)}/{_e(vault_channel)}</span>'
        f'</div>'
    )

    links_html = _render_inspector_links(note)
    actions_html = _render_vault_actions(note)
    receipts_html = _render_inspector_receipts(note)
    operational_loop_html = _render_operational_loop(note)
    posture_html = _render_inspector_review_posture(note)
    agent_memory_posture_html = _render_inspector_agent_memory_posture(note)

    is_companion_note = kind_val in _COMPANION_KINDS
    inspector_kind_attr = f' data-kind="{_e(str(kind_val))}"' if kind_val else ""
    inspector_companion_attr = ' data-companion="true"' if is_companion_note else ""

    return (
        f'<section class="vault-browser-inspector" '
        f'data-testid="workspace-vault-browser-inspector" '
        f'data-affordance-status="read-only"'
        f'{inspector_kind_attr}{inspector_companion_attr}>'
        f'<header class="inspector-header">'
        f'<span data-testid="workspace-vault-browser-inspector-title" '
        f'class="inspector-title">{title}</span>'
        f'<code data-testid="workspace-vault-browser-inspector-path" '
        f'class="inspector-path">{path}</code>'
        f'</header>'
        f'<div class="inspector-metadata">{metadata_rows}</div>'
        f'{health_html}'
        f'<div class="inspector-provenance">'
        f'{artifact_identity_html}'
        f'{vault_identity_html}'
        f'</div>'
        f'{posture_html}'
        f'{agent_memory_posture_html}'
        f'{receipts_html}'
        f'{operational_loop_html}'
        f'{actions_html}'
        f'{links_html}'
        f'</section>'
    )


def _render_operational_loop(note: dict) -> str:
    """Render the inspect -> queue -> confirm -> receipt operational loop.

    This ties the otherwise-isolated inspector, queue-review, Panel-confirmation,
    and receipt surfaces into one coherent, human-inspectable control loop. The
    receipt posture is *derived* from the server-supplied receipt payload and is
    rendered read-only: the Companion UI is a projection of receipt visibility,
    never the durable approval/execution authority.

    Receipt posture mirrors the inspector receipt-state semantics so an empty
    receipt list is never misread as a queued/pending confirmation (an empty list
    means the source is connected but no governed records exist, not that a
    proposal was staged):
        - 'receipts' key absent       -> unavailable (receipt source not connected)
        - 'receipts' key present, []  -> no_receipts (source connected, none found)
        - 'receipts' key present, [..] -> durable_receipt_visible (confirmed, durable)
    """
    _SENTINEL = object()
    receipts_raw = note.get("receipts", _SENTINEL)
    if receipts_raw is _SENTINEL:
        posture = "unavailable"
    elif not receipts_raw:
        posture = "no_receipts"
    else:
        posture = "durable_receipt_visible"

    stages = ("inspect", "queue", "confirm", "receipt")
    stage_html = "".join(
        f'<li class="loop-stage" data-loop-stage="{_e(stage)}">{_e(stage)}</li>'
        for stage in stages
    )
    return (
        '<div class="operational-loop" '
        'data-testid="workspace-operational-loop" '
        'data-authority-role="derived" '
        'data-affordance-status="read-only" '
        f'data-receipt-posture="{_e(posture)}">'
        '<span class="operational-loop-label">operational loop</span>'
        f'<ol class="operational-loop-stages">{stage_html}</ol>'
        '</div>'
    )


def _render_inspector_review_posture(note: dict) -> str:
    """Render review posture from existing note metadata (review_state, trust).

    These fields come from the normalized server payload (#1253). Unreviewed
    material is displayed with explicit posture but is NOT action-authorizing;
    the authority guard remains server-side.
    """
    review_state = note.get("review_state")
    trust = note.get("trust")
    if not review_state and not trust:
        return ""
    review_html = (
        f'<span class="posture-field" data-testid="workspace-vault-browser-inspector-posture-review-state">'
        f'{_e(str(review_state))}</span>'
    ) if review_state else ""
    trust_html = (
        f'<span class="posture-field" data-testid="workspace-vault-browser-inspector-posture-trust">'
        f'{_e(str(trust))}</span>'
    ) if trust else ""
    return (
        '<div class="inspector-review-posture" '
        'data-testid="workspace-vault-browser-inspector-review-posture" '
        'data-review-authority="non_authoritative" '
        'data-affordance-status="read-only">'
        '<span class="posture-label">review posture</span>'
        f'{review_html}'
        f'{trust_html}'
        '</div>'
    )


def _render_inspector_agent_memory_posture(note: dict) -> str:
    """Render non-authoritative agent-memory posture from server payload."""
    _SENTINEL = object()
    posture_raw = note.get("agent_memory_posture", _SENTINEL)
    if posture_raw is _SENTINEL:
        return (
            '<div class="inspector-agent-memory-posture" '
            'data-testid="workspace-vault-browser-inspector-agent-memory-posture" '
            'data-agent-memory-authority="non_authoritative" '
            'data-agent-memory-state="unavailable" '
            'data-affordance-status="read-only">'
            '<span class="posture-label">agent memory posture</span>'
            '<span class="posture-field">source unavailable</span>'
            '</div>'
        )

    posture: dict = dict(posture_raw or {})
    state = str(posture.get("state") or "no_agent_memory")
    counts = dict(posture.get("counts") or {})
    items = list(posture.get("items") or [])
    count_labels = ", ".join(
        f"{key}: {int(counts.get(key) or 0)}"
        for key in ("pending", "promoted", "rejected", "revised")
    )
    rows = []
    for item in items:
        status = str(item.get("status") or "")
        rows.append(
            '<div class="agent-memory-posture-row" '
            'data-testid="vault-browser-agent-memory-posture-row" '
            f'data-agent-memory-status="{_e(status)}">'
            f'<span data-testid="vault-browser-agent-memory-candidate-id">{_e(str(item.get("candidate_id") or ""))}</span>'
            f'<span data-testid="vault-browser-agent-memory-status">{_e(status)}</span>'
            f'<span data-testid="vault-browser-agent-memory-review-state">{_e(str(item.get("review_state") or ""))}</span>'
            f'<span data-testid="vault-browser-agent-memory-type">{_e(str(item.get("memory_type") or ""))}</span>'
            '</div>'
        )
    empty = (
        '<span class="posture-field" data-testid="vault-browser-agent-memory-empty">'
        'No agent-memory posture found for this artifact.</span>'
        if not rows
        else ""
    )
    return (
        '<div class="inspector-agent-memory-posture" '
        'data-testid="workspace-vault-browser-inspector-agent-memory-posture" '
        'data-agent-memory-authority="non_authoritative" '
        f'data-agent-memory-state="{_e(state)}" '
        'data-affordance-status="read-only">'
        '<span class="posture-label">agent memory posture</span>'
        f'<span class="posture-field" data-testid="vault-browser-agent-memory-counts">{_e(count_labels)}</span>'
        f'{empty}'
        + "".join(rows)
        + '</div>'
    )


_RECEIPT_STATES = {"queued", "applied", "blocked", "rejected", "failed"}


def _render_inspector_receipts(note: dict) -> str:
    """Render agent receipts from the vault browser note payload.

    State determination:
        - 'receipts' key absent from payload   → unavailable (source not connected)
        - 'receipts' key present, value = []   → no_receipts (source connected, none found)
        - 'receipts' key present, non-empty    → render each receipt read-only

    All states are rendered inside data-testid="workspace-vault-browser-inspector-receipts".
    No write/mutation controls are rendered. Receipt identity (receipt_id, trace_id)
    is kept separate from artifact identity (uuid, path) per the contract.
    """
    _SENTINEL = object()
    receipts_raw = note.get("receipts", _SENTINEL)

    if receipts_raw is _SENTINEL:
        # Source not connected yet — honest unavailable state
        return (
            '<div class="inspector-receipts" '
            'data-testid="workspace-vault-browser-inspector-receipts" '
            'data-receipt-state="unavailable" '
            'data-affordance-status="read-only">'
            '<span class="receipts-label">agent receipts</span>'
            '<span class="receipts-unavailable">Receipt source not connected. '
            'No receipt data available for this artifact.</span>'
            '</div>'
        )

    receipts: list[dict] = list(receipts_raw) if receipts_raw else []
    if not receipts:
        return (
            '<div class="inspector-receipts" '
            'data-testid="workspace-vault-browser-inspector-receipts" '
            'data-receipt-state="no_receipts" '
            'data-affordance-status="read-only">'
            '<span class="receipts-label">agent receipts</span>'
            '<span class="receipts-empty">No receipts found for this artifact.</span>'
            '</div>'
        )

    rows: list[str] = []
    for idx, receipt in enumerate(receipts):
        receipt_id = str(receipt.get("receipt_id") or "")
        state = str(receipt.get("state") or "unknown")
        action_type = str(receipt.get("action_type") or "")
        trace_id = str(receipt.get("trace_id") or "")
        action_id = str(receipt.get("action_id") or "")
        artifact_uuid = str(receipt.get("artifact_uuid") or "")
        requested_by = str(receipt.get("requested_by") or "")
        approved_by = str(receipt.get("approved_by") or "")
        status = str(receipt.get("status") or state or "")
        timestamp = str(receipt.get("timestamp") or "")
        receipt_state = state if state in _RECEIPT_STATES else "unknown"
        detail_id = f"vault-browser-receipt-detail-{idx}"
        detail_fields = (
            ("receipt-id", "receipt_id", receipt_id),
            ("trace-id", "trace_id", trace_id),
            ("action-id", "action_id", action_id),
            ("artifact-uuid", "artifact_uuid", artifact_uuid),
            ("requested-by", "requested_by", requested_by),
            ("approved-by", "approved_by", approved_by),
            ("status", "status", status),
            ("timestamp", "timestamp", timestamp),
        )
        detail_rows = "".join(
            f'<dt class="receipt-detail-label">{_e(label)}</dt>'
            f'<dd data-testid="vault-browser-receipt-detail-{_e(testid_suffix)}" '
            f'class="receipt-detail-value">{_e(value)}</dd>'
            for testid_suffix, label, value in detail_fields
        )
        rows.append(
            f'<div class="receipt-row" '
            f'data-testid="vault-browser-receipt-row" '
            f'data-receipt-state="{_e(receipt_state)}" '
            f'data-detail-id="{_e(detail_id)}" '
            f'data-expanded="false" '
            f'aria-expanded="false" '
            f'role="button" '
            f'tabindex="0" '
            f'onclick="vaultBrowserToggleReceiptDetail(this)" '
            f'onkeydown="if(event.key===\'Enter\'||event.key===\' \')'
            f'{{event.preventDefault();vaultBrowserToggleReceiptDetail(this);}}">'
            f'<span data-testid="vault-browser-receipt-id" class="receipt-id">{_e(receipt_id)}</span>'
            f'<span data-testid="vault-browser-receipt-state" class="receipt-state">{_e(state)}</span>'
            f'<span data-testid="vault-browser-receipt-action-type" class="receipt-action">{_e(action_type)}</span>'
            + (
                f'<span data-testid="vault-browser-receipt-trace-id" class="receipt-trace">{_e(trace_id)}</span>'
                if trace_id else ""
            )
            + '</div>'
            f'<dl class="receipt-detail" '
            f'data-testid="vault-browser-receipt-detail" '
            f'id="{_e(detail_id)}" '
            f'hidden '
            f'aria-hidden="true" '
            f'data-expanded="false">'
            f'{detail_rows}'
            f'</dl>'
        )
    return (
        '<div class="inspector-receipts" '
        'data-testid="workspace-vault-browser-inspector-receipts" '
        f'data-receipt-state="{_e(receipts[0].get("state", "unknown") if receipts else "no_receipts")}" '
        'data-affordance-status="read-only">'
        '<span class="receipts-label">agent receipts</span>'
        + "".join(rows)
        + '</div>'
    )


def _render_vault_related_results(results: list[dict]) -> str:
    if not results:
        return (
            '<div class="vault-related-results" '
            'data-testid="vault-browser-find-related-results" '
            'data-mode="read_only" '
            'data-state="idle"></div>'
        )
    rows: list[str] = []
    for result in results:
        signals = result.get("ranking_signals") or result.get("signals") or []
        signal_html = "".join(
            (
                '<span class="vault-related-signal" '
                'data-testid="vault-browser-find-related-signal" '
                f'data-signal="{_e(str(signal.get("signal") or ""))}" '
                f'data-weight="{_e(str(signal.get("weight") or ""))}" '
                f'data-provenance="{_e(str(signal.get("provenance") or ""))}">'
                f'{_e(str(signal.get("signal") or ""))}: {_e(str(signal.get("value") or ""))}'
                '</span>'
            )
            for signal in signals
            if isinstance(signal, dict)
        )
        rows.append(
            f'<article class="vault-related-result" '
            f'data-testid="vault-browser-find-related-result" '
            f'data-mode="{_e(str(result.get("data_mode") or "read_only"))}" '
            f'data-note-path="{_e(str(result.get("note_path") or ""))}" '
            f'data-ranking-score="{_e(str(result.get("ranking_score") or 0))}">'
            f'<span class="vault-related-title">{_e(str(result.get("title") or "Related artifact"))}</span>'
            f'<code class="vault-related-path">{_e(str(result.get("note_path") or ""))}</code>'
            f'<span class="vault-related-score" '
            f'data-testid="vault-browser-find-related-score">'
            f'{_e(str(result.get("ranking_score") or 0))}</span>'
            f'<span class="vault-related-signals">{signal_html}</span>'
            f'</article>'
        )
    return (
        '<div class="vault-related-results" '
        'data-testid="vault-browser-find-related-results" '
        'data-mode="read_only" '
        'data-state="ready">'
        + "".join(rows)
        + '</div>'
    )


def _render_vault_actions(note: dict) -> str:
    """Render the VaultAction display model for the selected browser artifact.

    Each action carries:
        data-mode              — action class (read_only, ui_only, bounded_system_write,
                                 governance_write, agent_proposal, blocked)
        data-affordance-status — whether the action is currently operable
        data-blocked / data-blocked-reason
                               — present when action is disallowed for this artifact
        data-requires-receipt / data-requires-confirmation
                               — governance safety contract attributes (#1256)

    Governance and write-class actions are disabled/blocked with explicit reasons in
    this slice. No new write path is opened without guard/receipt semantics.
    """
    note_path = str(note.get("note_path") or "").strip()
    artifact_uuid = str(note.get("uuid") or "").strip()
    has_artifact_scope = bool(note_path or artifact_uuid)

    def _action(
        testid: str,
        label: str,
        mode: str,
        *,
        affordance: str = "unavailable",
        blocked: bool = False,
        blocked_reason: str = "",
        disabled: bool = False,
        disabled_reason: str = "",
        requires_receipt: bool = False,
        requires_confirmation: bool = False,
        data_href: str = "",
        data_path: str = "",
        data_api_method: str = "",
        data_api_path: str = "",
        data_note_path: str = "",
        data_artifact_uuid: str = "",
        onclick: str = "",
    ) -> str:
        blocked_attr = (
            f' data-blocked="true" data-blocked-reason="{_e(blocked_reason)}"'
            if blocked
            else ""
        )
        disabled_attr = (
            f' data-disabled="true" data-disabled-reason="{_e(disabled_reason)}"'
            if disabled and not blocked
            else ""
        )
        receipt_attr = ' data-requires-receipt="true"' if requires_receipt else ""
        confirm_attr = ' data-requires-confirmation="true"' if requires_confirmation else ""
        href_attr = f' data-href="{_e(data_href)}"' if data_href else ""
        path_attr = f' data-path="{_e(data_path)}"' if data_path else ""
        api_method_attr = f' data-api-method="{_e(data_api_method)}"' if data_api_method else ""
        api_path_attr = f' data-api-path="{_e(data_api_path)}"' if data_api_path else ""
        note_path_attr = f' data-note-path="{_e(data_note_path)}"' if data_note_path else ""
        artifact_uuid_attr = (
            f' data-artifact-uuid="{_e(data_artifact_uuid)}"'
            if data_artifact_uuid
            else ""
        )
        onclick_attr = f' onclick="{_e(onclick)}"' if onclick else ""
        return (
            f'<div class="vault-action" '
            f'data-testid="{testid}" '
            f'data-mode="{mode}" '
            f'data-affordance-status="{affordance}"'
            f"{blocked_attr}"
            f"{disabled_attr}"
            f"{receipt_attr}"
            f"{confirm_attr}"
            f"{href_attr}"
            f"{path_attr}"
            f"{api_method_attr}"
            f"{api_path_attr}"
            f"{note_path_attr}"
            f"{artifact_uuid_attr}"
            f'{onclick_attr}>'
            f'<span class="vault-action-label">{_e(label)}</span>'
            f"</div>"
        )

    workspace_href = f"?note_path={quote(note_path, safe='/')}" if note_path else ""
    actions = [
        _action(
            "vault-action-open-note",
            "Open note",
            "read_only",
            affordance="available" if note_path else "unavailable",
            data_href=workspace_href,
            onclick="window.location.href=this.dataset.href" if note_path else "",
        ),
        _action(
            "vault-action-copy-path",
            "Copy path",
            "ui_only",
            affordance="available" if note_path else "unavailable",
            data_path=note_path,
            onclick="navigator.clipboard.writeText(this.dataset.path)" if note_path else "",
        ),
        _action(
            "vault-action-find-related",
            "Find related (read-only)",
            "read_only",
            affordance="available" if has_artifact_scope else "unavailable",
            disabled=not has_artifact_scope,
            disabled_reason=(
                "" if has_artifact_scope else "Artifact scope unavailable for Find."
            ),
            data_api_method="GET" if has_artifact_scope else "",
            data_api_path="/api/companion/vault-related" if has_artifact_scope else "",
            data_note_path=note_path,
            data_artifact_uuid=artifact_uuid,
            onclick="vaultBrowserFindRelated(this)" if has_artifact_scope else "",
        ),
        _action(
            "vault-action-queue-review",
            "Queue for review",
            "governance_write",
            affordance="available" if has_artifact_scope else "unavailable",
            disabled=not has_artifact_scope,
            disabled_reason=(
                "" if has_artifact_scope else "Artifact scope unavailable for queue_review."
            ),
            data_api_method="POST" if has_artifact_scope else "",
            data_api_path=(
                "/api/companion/vault-browser/actions/queue-review"
                if has_artifact_scope
                else ""
            ),
            data_note_path=note_path,
            data_artifact_uuid=artifact_uuid,
            onclick="vaultBrowserQueueReview(this)" if has_artifact_scope else "",
            requires_receipt=True,
            requires_confirmation=True,
        ),
    ]
    return (
        '<div class="vault-action-strip" '
        'data-testid="workspace-vault-browser-inspector-actions">'
        + "".join(actions)
        + "</div>"
        + _render_vault_related_results(list(note.get("related_results") or []))
    )


def _render_filter_chips(
    notes: list[dict],
    active_filters: dict[str, list[str]],
) -> str:
    """Render deterministic filter chips for available metadata dimensions."""
    _CHIP_DIMS: list[tuple[str, str]] = [
        ("kind", "Kind"),
        ("zone", "Zone"),
        ("review_state", "Review"),
        ("trust", "Trust"),
    ]
    chips_html: list[str] = []
    for field, label in _CHIP_DIMS:
        values: list[str] = []
        seen: set[str] = set()
        for note in notes:
            val = note.get(field)
            if val and str(val) not in seen:
                seen.add(str(val))
                values.append(str(val))
        if not values:
            continue
        active_set = set(active_filters.get(field, []))
        multi_active = len(active_set) > 1
        for val in sorted(values):
            is_active = val in active_set
            deselect_span = (
                '<span class="filter-chip-remove" aria-label="remove filter" data-testid="filter-chip-remove">×</span>'
                if is_active and multi_active
                else ""
            )
            chips_html.append(
                f'<span class="filter-chip" '
                f'data-testid="vault-browser-filter-chip" '
                f'data-key="{_e(field)}" '
                f'data-value="{_e(val)}" '
                f'data-active="{"true" if is_active else "false"}" '
                f'onclick="vbToggleFilter(this)" '
                f'style="cursor:pointer">'
                f'{_e(label)}: {_e(val)}'
                f'{deselect_span}'
                f'</span>'
            )
    if not chips_html:
        return ""
    # #1417 — the Kind:/Zone:/Review:/Trust: facets are filtering controls, not a
    # default reading surface. Keep them (and their wiring) but tuck them behind a
    # collapsed "Filters" disclosure so they do not dump raw metadata into the
    # default Browse view.
    return (
        '<details class="vault-browser-filters-disclosure">'
        '<summary class="vault-browser-filters-summary" '
        'data-testid="workspace-vault-browser-filters-toggle">Filters</summary>'
        '<div class="vault-browser-filters" data-testid="workspace-vault-browser-filters">'
        + "".join(chips_html)
        + "</div>"
        "</details>"
    )


def _build_vault_tree(notes: list[dict]) -> dict:
    """Build a nested folder tree from server-provided note paths (#1425).

    Returns ``{"folders": {name: subtree}, "files": [(note, filename, path)]}``.
    Insertion order is preserved (folders first-seen, files in order).
    """
    root: dict = {"folders": {}, "files": []}
    for note in notes:
        path = str(note.get("note_path") or "").strip()
        if not path:
            continue
        parts = path.split("/")
        folders, filename = parts[:-1], parts[-1]
        node = root
        for folder in folders:
            node = node["folders"].setdefault(folder, {"folders": {}, "files": []})
        node["files"].append((note, filename, path))
    return root


def _render_vault_tree(
    node: dict,
    *,
    note_path: str,
    active_folder_paths: set[str],
    base: str,
) -> str:
    parts: list[str] = []
    # Folders first (Obsidian-like), then files at this level.
    for name, child in node["folders"].items():
        full = f"{base}/{name}" if base else name
        is_open = full in active_folder_paths
        children = _render_vault_tree(
            child, note_path=note_path, active_folder_paths=active_folder_paths, base=full
        )
        parts.append(
            f'<li class="vault-tree-folder" data-testid="workspace-vault-browser-group" '
            f'data-folder="{_e(full)}">'
            f'<details class="vault-tree-folder-details"{" open" if is_open else ""}>'
            f'<summary class="vault-tree-folder-summary">{_e(name)}</summary>'
            f'<ul class="vault-tree-children">{children}</ul>'
            "</details></li>"
        )
    for note, filename, path in node["files"]:
        parts.append(_render_vault_note_row(note, filename, path, note_path))
    return "".join(parts)


def _render_vault_note_row(note: dict, filename: str, path: str, note_path: str) -> str:
    """Render one clean note row: name only (filename stem); metadata hidden (#1417/#1425)."""
    title = _e(note.get("title") or filename)
    stem = filename[:-3] if filename.lower().endswith(".md") else filename
    zone = _e(note.get("zone") or "root")
    href = "/?note_path=" + quote(path, safe="/")
    active = "true" if path == note_path else "false"

    hidden_badge_attrs = ' class="note-badge note-badge--nav-hidden" data-nav-visible="false"'
    kind_val = note.get("kind")
    kind_badge = (
        f'<span{hidden_badge_attrs} '
        f'data-testid="workspace-vault-browser-note-kind">{_e(str(kind_val))}</span>'
        if kind_val else ""
    )
    review_state_val = note.get("review_state")
    review_badge = (
        f'<span{hidden_badge_attrs} '
        f'data-testid="workspace-vault-browser-note-review-state">{_e(str(review_state_val))}</span>'
        if review_state_val else ""
    )
    trust_val = note.get("trust")
    trust_badge = (
        f'<span{hidden_badge_attrs} '
        f'data-testid="workspace-vault-browser-note-trust">{_e(str(trust_val))}</span>'
        if trust_val else ""
    )
    frontmatter_valid = note.get("frontmatter_valid", True)
    missing_fields = note.get("missing_required_fields") or []
    health_badge = ""
    if not frontmatter_valid or missing_fields:
        missing_label = ", ".join(missing_fields) if missing_fields else "invalid"
        health_label = "metadata" if missing_fields else "invalid"
        health_badge = (
            f'<span class="note-badge note-badge--health note-badge--health-invalid" '
            f'data-testid="workspace-vault-browser-note-health" '
            f'data-missing-fields="{_e(missing_label)}" '
            f'title="Missing required fields: {_e(missing_label)}">{health_label}</span>'
        )
    badges_html = kind_badge + review_badge + trust_badge + health_badge

    kind_safe = _e(str(kind_val)) if kind_val else ""
    is_companion = kind_val in _COMPANION_KINDS
    row_extra_class = " vault-browser-row--companion" if is_companion else ""
    row_kind_attr = f' data-kind="{kind_safe}"' if kind_safe else ""
    row_companion_attr = ' data-companion="true"' if is_companion else ""
    nav_hidden = _should_hide_note_by_default(note)
    row_hidden_attr = " hidden" if nav_hidden else ""
    row_nav_attr = ' data-nav-visible="false"' if nav_hidden else ""
    selection_control = (
        f'<input type="checkbox" class="vault-browser-selection-toggle" '
        f'data-testid="workspace-vault-browser-selection-toggle" '
        f'data-mode="ui_only" data-selected="false" data-note-path="{_e(path)}" '
        f'aria-label="Select {_e(stem)}" '
        f'onclick="vaultBrowserToggleSelection(event, this)">'
    )

    # Obsidian-clean row: the visible label is the filename stem (disambiguates
    # same-titled notes); the frontmatter title is the tooltip. The full path and
    # raw metadata stay in hidden elements (data-* preserved for tests).
    return (
        f'<li class="vault-browser-row{row_extra_class}" '
        f'data-testid="workspace-vault-browser-note-row" data-active="{active}" '
        f'data-selected="false"'
        f'{row_kind_attr}{row_companion_attr}{row_nav_attr}{row_hidden_attr}>'
        f'{selection_control}'
        f'<a href="{href}" class="vault-browser-row-title" '
        f'data-testid="workspace-vault-browser-note-link" title="{title}">{_e(stem)}</a>'
        f'<code class="vault-browser-row-path" data-testid="workspace-vault-browser-note-path" '
        f'title="{_e(path)}" hidden>{_e(filename)}</code>'
        f'<span data-testid="workspace-vault-browser-note-zone" '
        f'class="vault-browser-zone-label">{zone}</span>'
        f"{badges_html}</li>"
    )


def _pagination_link(
    *,
    note_path: str,
    query: str,
    active_filters: dict[str, list[str]],
    cursor: str | None,
    limit: object,
) -> str:
    params: dict[str, object] = {}
    if note_path:
        params["note_path"] = note_path
    if query:
        params["q"] = query
    for key, values in active_filters.items():
        if values:
            params[key] = values
    if cursor:
        params["cursor"] = cursor
    if limit:
        params["limit"] = str(limit)
    return "/?" + urlencode(params, doseq=True)


def _render_vault_browser_pagination(
    *,
    note_path: str,
    query: str,
    active_filters: dict[str, list[str]],
    pagination: dict,
) -> str:
    if not pagination:
        return ""
    next_cursor = str(pagination.get("next_cursor") or "")
    previous_cursor = str(pagination.get("previous_cursor") or "")
    page_size = pagination.get("page_size") or ""
    returned = int(pagination.get("returned_notes") or 0)
    total = int(pagination.get("total_filtered_notes") or 0)
    has_next = bool(pagination.get("has_next"))
    has_previous = bool(pagination.get("has_previous"))
    next_html = (
        '<a class="vault-browser-pagination-next" '
        'data-testid="workspace-vault-browser-pagination-next" '
        f'data-next-cursor="{_e(next_cursor)}" '
        f'href="{_e(_pagination_link(note_path=note_path, query=query, active_filters=active_filters, cursor=next_cursor, limit=page_size))}">'
        "Next"
        "</a>"
        if has_next and next_cursor
        else (
            '<span class="vault-browser-pagination-next" '
            'data-testid="workspace-vault-browser-pagination-next" '
            'data-disabled="true">Next</span>'
        )
    )
    previous_html = (
        '<a class="vault-browser-pagination-previous" '
        'data-testid="workspace-vault-browser-pagination-previous" '
        f'data-has-previous="{str(has_previous).lower()}" '
        f'data-previous-cursor="{_e(previous_cursor)}" '
        f'href="{_e(_pagination_link(note_path=note_path, query=query, active_filters=active_filters, cursor=previous_cursor or None, limit=page_size))}">'
        "Previous"
        "</a>"
        if has_previous
        else (
            '<span class="vault-browser-pagination-previous" '
            'data-testid="workspace-vault-browser-pagination-previous" '
            'data-has-previous="false" '
            'data-disabled="true">Previous</span>'
        )
    )
    return (
        '<nav class="vault-browser-pagination" '
        'data-testid="workspace-vault-browser-pagination" '
        f'data-mode="{_e(str(pagination.get("mode") or "cursor"))}" '
        f'data-has-next="{str(has_next).lower()}" '
        f'data-has-previous="{str(has_previous).lower()}">'
        f'<span data-testid="workspace-vault-browser-pagination-summary">'
        f"{returned} shown from {total} matches"
        "</span>"
        f"{previous_html}{next_html}"
        "</nav>"
    )


def _render_vault_browser(
    *,
    note_path: str,
    notes: list[dict],
    query: str,
    total_notes: int,
    filtered_notes: int,
    error: object,
    read_only: bool,
    identity_available: bool,
    vault_name: str,
    vault_channel: str,
    vault_provenance: str,
    active_filters: dict[str, list[str]] | None = None,
    pagination: dict | None = None,
) -> str:
    query_text = _e(query or "")
    identity_label = f"{vault_name}/{vault_channel}"
    identity_html = (
        f'<span data-testid="workspace-vault-browser-active-identity">{_e(identity_label)}</span>'
    )
    if error:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-error">'
            + _e(str(error))
            + "</div>"
        )
    elif not identity_available:
        state_html = (
            '<div class="vault-browser-state" '
            'data-testid="workspace-vault-browser-state-identity-unavailable">'
            "Vault identity unavailable; browsing context is unresolved."
            "</div>"
        )
    elif filtered_notes == 0:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-empty">'
            "No notes matched the current filter."
            "</div>"
        )
    else:
        state_html = (
            '<div class="vault-browser-state" data-testid="workspace-vault-browser-state-ready">'
            f"{filtered_notes} matches from {total_notes} markdown notes."
            "</div>"
        )

    # Daily-use visibility: companion/UUID notes are rendered hidden in the DOM
    # (preserving data-kind/data-companion attributes for test compatibility)
    # but excluded from the visible nav list (#1361).
    hidden_count = sum(1 for n in notes if _should_hide_note_by_default(n))

    # §6 — group rows by folder so the list stays scannable at 40+ artifacts.
    # Insertion order is preserved (dicts are ordered) so any server ordering
    # intent survives; each folder header is emitted once.
    # #1425 — render an Obsidian-style nested, collapsible folder tree built from
    # the server-provided note paths. Folders on the path to the active note are
    # expanded by default; the rest are collapsed.
    tree = _build_vault_tree(notes)
    active_folder_paths: set[str] = set()
    if note_path and "/" in note_path:
        acc = ""
        for seg in note_path.split("/")[:-1]:
            acc = f"{acc}/{seg}" if acc else seg
            active_folder_paths.add(acc)
    tree_html = _render_vault_tree(
        tree, note_path=note_path, active_folder_paths=active_folder_paths, base=""
    )
    list_html = (
        '<ul class="vault-browser-list vault-tree" data-testid="workspace-vault-browser-list">'
        + tree_html
        + "</ul>"
        if (tree["folders"] or tree["files"])
        else ""
    )
    read_only_text = "read-only" if read_only else "mutating"
    # Calm provenance label for daily-use visibility; raw value in data attribute.
    # Badge already shows "read-only" when read_only=True; provenance omits the
    # redundant qualifier to avoid duplication (#2240-a).
    calm_provenance = "fallback · filesystem index" if read_only else "filesystem index"
    filters_html = _render_filter_chips(notes, active_filters or {})
    pagination_html = _render_vault_browser_pagination(
        note_path=note_path,
        query=query or "",
        active_filters=active_filters or {},
        pagination=pagination or {},
    )
    selection_summary_html = (
        '<div class="vault-browser-selection-summary" '
        'data-testid="workspace-vault-browser-selection-summary" '
        'data-mode="ui_only" data-selected-count="0" aria-live="polite">'
        "0 selected"
        "</div>"
        if notes
        else ""
    )
    selected_note = next((n for n in notes if str(n.get("note_path") or "").strip() == note_path), None)
    # #1427 — keep the inspector out of the default browse view. The tree is the
    # surface; the inspector metadata/actions sit behind a collapsed disclosure
    # so the pane reads like a file tree, not a debug dump (fields stay in DOM).
    _inspector_panel = (
        _render_artifact_inspector(selected_note, vault_name=vault_name, vault_channel=vault_channel)
        if selected_note is not None
        else ""
    )
    inspector_html = (
        '<details class="vault-browser-inspector-disclosure">'
        '<summary class="vault-browser-inspector-summary" '
        'data-testid="workspace-vault-browser-inspector-toggle">Note details</summary>'
        f"{_inspector_panel}"
        "</details>"
        if _inspector_panel
        else ""
    )
    hidden_html = (
        f'<span class="vault-browser-hidden-count" '
        f'data-testid="workspace-vault-browser-hidden-count" '
        f'data-hidden="{hidden_count}">'
        f'{hidden_count} system/companion note{"s" if hidden_count != 1 else ""} hidden'
        "</span>"
        if hidden_count > 0
        else ""
    )
    return f"""
        <details class="vault-browser" data-testid="workspace-vault-browser" open>
          <summary data-testid="workspace-vault-browser-toggle">Browse vault notes</summary>
          <div class="vault-browser-meta" data-testid="workspace-vault-browser-meta">
            {identity_html}
            <span data-testid="workspace-vault-browser-read-only">{read_only_text}</span>
            <span data-testid="workspace-vault-browser-query">{query_text}</span>
            <span class="vault-browser-provenance-calm"
                  data-testid="workspace-vault-browser-provenance"
                  data-raw-provenance="{_e(vault_provenance)}">{_e(calm_provenance)}</span>
          </div>
          {hidden_html}
          {filters_html}
          {state_html}
          {selection_summary_html}
          {list_html}
          {pagination_html}
          {inspector_html}
        </details>"""


def _render_suggestion_flow_region(fields: dict) -> str:
    suggestion_state = _e(fields.get("suggestion_state", "idle"))
    dom_alias = _e(fields.get("suggestion_dom_alias", suggestion_state))
    composer_enabled = bool(fields.get("suggestion_composer_enabled", True))
    _suggestion_state_raw = str(fields.get("suggestion_state", "idle"))
    _is_suggestion_idle = _suggestion_state_raw in ("idle", "thinking", "blocked")
    composer_text = (
        ""  # suppress composer status copy when no suggestion is staged
        if _is_suggestion_idle
        else (
            "Suggestion composer can be used when a suggestion is staged."
            if composer_enabled
            else "Suggestion composer is locked by the current suggestion state."
        )
    )
    suggestion_copy = _human_state_label(
        str(fields.get("suggestion_state", "idle")),
        {
            "idle": "Suggestions are idle.",
            "thinking": "Suggestions are being prepared.",
            "staged_body": "Body suggestion staged.",
            "staged_governance": "Governance suggestion staged.",
            "blocked": "Suggestions are blocked.",
        },
        fallback="Suggestion state is unavailable.",
    )
    transitions = fields.get("suggestion_allowed_transitions") or []
    transition_html = "".join(
        (
            '<span class="suggestion-transition" '
            f'data-testid="workspace-suggestion-transition" data-transition-to="{_e(target)}">'
            "</span>"
        )
        for target in transitions
    )
    composer_state_token = "enabled" if composer_enabled else "locked"
    return f"""
        <div
          class="suggestion-flow"
          data-testid="workspace-suggestion-flow"
          data-suggestion-state="{suggestion_state}"
          data-suggestion-dom-alias="{dom_alias}"
          data-composer-state="{composer_state_token}">
          <div class="rail-state-row">
            <span class="rail-state-label">Suggestions</span>
            <span class="rail-state-value">{_e(suggestion_copy)}</span>
          </div>
          <div class="suggestion-composer-state" data-composer-state="{composer_state_token}">{composer_text}</div>
          <div class="suggestion-transitions">{transition_html}</div>
        </div>"""


def _render_portrait_sheet(sheet: dict) -> str:
    if not sheet:
        return ""
    # ARIA defines only the lowercase tokens true/false; emit them directly
    # rather than stringifying a Python bool (which yields "True"/"False").
    hidden = "false" if sheet.get("is_visible") else "true"
    return f"""
    <aside
      class="portrait-sheet"
      data-testid="{_e(sheet.get("data_testid", "portrait-sheet"))}"
      data-layout-portrait="bottom-sheet"
      data-suggestion-id="{_e(sheet.get("suggestion_id", ""))}"
      data-rail-state="{_e(sheet.get("rail_state", ""))}"
      data-current-snap="{_e(sheet.get("current_snap", ""))}"
      data-height-hint="{_e(sheet.get("height_hint", ""))}"
      data-auto-snap-target="{_e(sheet.get("auto_snap_target", ""))}"
      data-forbidden-auto-snap="{_e(sheet.get("forbidden_auto_snap", ""))}"
      data-touch-target-min-height="{_e(sheet.get("touch_target_min_height", ""))}"
      data-receipts-strip-position="{_e(sheet.get("receipts_strip_position", ""))}"
      aria-hidden="{hidden}">
    </aside>"""


def _render_keyboard_shortcuts(shortcuts: dict) -> str:
    bindings = shortcuts.get("key_bindings") or {}
    if not bindings:
        return ""
    # Only show shortcut map when a suggestion is actively staged — not during idle,
    # thinking, blocked, or terminal states.
    rail_state = shortcuts.get("rail_state", "")
    if rail_state not in ("staged_body", "staged_governance", "staged"):
        return ""
    rows = "".join(
        (
            '<span class="shortcut-hint" data-testid="workspace-shortcut" '
            f'data-intent="{_e(intent)}" data-key="{_e(key)}">{_e(key)}</span>'
        )
        for intent, key in bindings.items()
    )
    return f"""
        <div
          class="shortcut-map"
          data-testid="workspace-shortcut-map"
          data-variant="{_e(shortcuts.get("variant", ""))}"
          data-rail-state="{_e(shortcuts.get("rail_state", ""))}"
          data-ignore-input-focus="true">
          {rows}
        </div>"""


def _render_find_mode(candidates: list[dict], *, payload_available: bool = False) -> str:
    if not candidates:
        state_value = "empty" if payload_available else "unavailable"
        affordance_status = "read-only" if payload_available else "unavailable"
        testid = "find-empty-state" if payload_available else "find-unavailable-state"
        copy = (
            "Find returned no candidates for this note. This is an empty read-side result, not an action."
            if payload_available
            else "Find is unavailable because no backend candidate payload is available yet."
        )
        return """
        <section
          class="find-mode"
          data-testid="find-mode"
          data-affordance-status="{affordance_status}"
          data-capability="find">
          <div class="rail-state-row">
            <span class="rail-state-label">Find</span>
            <span class="rail-state-value">{state_value}</span>
          </div>
          <div class="find-unavailable" data-testid="{testid}">
            {copy}
          </div>
        </section>""".format(
            affordance_status=affordance_status,
            state_value=state_value,
            testid=testid,
            copy=copy,
        )
    rows: list[str] = []
    for candidate in candidates:
        handoff = ""
        handoff_status = str(candidate.get("panel_handoff_status") or "unavailable")
        if handoff_status not in {"read-only", "staged", "actionable", "unavailable"}:
            handoff_status = "unavailable"
        if candidate.get("panel_handoff", True):
            handoff = (
                '<button type="button" class="find-panel-handoff" '
                'data-testid="find-panel-handoff" '
                'data-intent="find.panelHandoff" '
                f'data-affordance-status="{_e(handoff_status)}" '
                'data-runtime-backed="false" '
                'aria-disabled="true" disabled>'
                f"Panel {handoff_status}</button>"
            )
        citation_state = "missing" if candidate.get("citation_missing") else "available"
        rows.append(
            f"""
        <article
          class="find-candidate"
          data-testid="find-candidate"
          data-affordance-status="read-only"
          data-runtime-backed="true"
          data-candidate-id="{_e(candidate.get("candidate_id", ""))}">
          <div class="find-candidate-title">{_e(candidate.get("title", ""))}</div>
          <div class="find-candidate-snippet">{_e(candidate.get("snippet", ""))}</div>
          <div class="find-candidate-meta">
            <span
              data-testid="find-candidate-citation"
              data-citation-state="{_e(citation_state)}">
              {_e(candidate.get("citation", ""))}
            </span>
            <span data-testid="find-candidate-scope">{_e(candidate.get("scope", ""))}</span>
          </div>
          <div class="find-candidate-why" data-testid="find-candidate-why">
            {_e(candidate.get("why", ""))}
          </div>
          {handoff}
        </article>"""
        )
    return f"""
        <section
          class="find-mode"
          data-testid="find-mode"
          data-affordance-status="read-only"
          data-capability="find">
          <div class="rail-state-row">
            <span class="rail-state-label">Find</span>
            <span class="rail-state-value">{len(candidates)} candidates</span>
          </div>
          {"".join(rows)}
        </section>"""


def _render_reorient_mode(sections: dict[str, list[dict]]) -> str:
    open_loops_count = len(sections.get("open_loops") or []) if sections else 0
    has_content = bool(sections) and any(sections.get(name) for name in sections)
    if not has_content:
        # Idle: single line with collapsed recall disclosure (AC3 §8.3)
        return """
        <section
          class="reorient-mode panel-section"
          data-testid="reorient-mode"
          data-section-state="idle"
          data-affordance-status="read-only"
          data-capability="reorient">
          <div class="rail-state-row">
            <span class="rail-state-label">Reorient</span>
            <details class="reorient-recall-disclosure" data-testid="reorient-recall-disclosure"
              aria-expanded="false">
              <summary class="reorient-recall-trigger"
                aria-expanded="false"
                data-testid="reorient-recall-trigger">recall&nbsp;&#9660;</summary>
              <div class="reorient-recall-body" data-testid="reorient-recall-body" hidden>
                <div class="reorient-empty" data-testid="reorient-empty-state">
                  Reorient is available, but no orientation payload is available for this note yet.
                </div>
              </div>
            </details>
          </div>
        </section>"""

    labels = {
        "facts": "Facts",
        "inferences": "Inferences",
        "candidates": "Candidates",
        "stale_context": "Stale context",
        "recent_deltas": "Recent deltas",
        "open_loops": "Open loops",
    }
    groups = [
        ("where-am-i", "Where am I?", ("facts", "inferences")),
        ("what-changed", "What changed?", ("recent_deltas", "stale_context")),
        ("what-next", "What next?", ("candidates", "open_loops")),
    ]
    section_html: list[str] = []
    for group_id, group_label, section_names in groups:
        rows: list[str] = []
        for name in section_names:
            items = sections.get(name) or []
            if not items:
                continue
            item_kind = {
                "facts": "fact",
                "inferences": "inference",
                "candidates": "candidate",
                "stale_context": "stale-caution",
                "recent_deltas": "recent-delta",
                "open_loops": "open-loop",
            }[name]
            for item in items:
                handoff = ""
                if item.get("panel_handoff"):
                    handoff = (
                        '<button type="button" class="reorient-panel-handoff" '
                        'data-testid="reorient-panel-handoff" '
                        'data-intent="reorient.panelHandoff" '
                        'data-affordance-status="read-only" '
                        'data-runtime-backed="false" '
                        'aria-disabled="true" disabled>'
                        "Panel handoff candidate</button>"
                    )
                rows.append(
                    f"""
              <li
                class="reorient-item"
                data-testid="reorient-item"
                data-reorient-section="{_e(name)}"
                data-reorient-kind="{_e(item_kind)}">
                <span class="reorient-kind" data-testid="reorient-kind">{_e(labels[name])}</span>
                <span class="reorient-item-label">{_e(_cap(item.get("label", "")))}</span>
                <a
                  class="reorient-source"
                  data-testid="reorient-source-link"
                  href="#"
                  data-source-link="{_e(item.get("source_link", ""))}">
                  {_e(item.get("source_link", ""))}
                </a>
                {handoff}
              </li>"""
                )
        section_html.append(
            f"""
            <section
              class="reorient-section"
              data-testid="reorient-section"
              data-reorient-group="{_e(group_id)}">
              <div class="reorient-section-title">{_e(group_label)}</div>
              <ul class="reorient-list">{"".join(rows)}</ul>
            </section>"""
        )
    return f"""
        <section
          class="reorient-mode panel-section"
          data-testid="reorient-mode"
          data-section-state="active"
          data-affordance-status="read-only"
          data-capability="reorient">
          <div class="rail-state-row">
            <span class="rail-state-label">Reorient</span>
            <details class="reorient-recall-disclosure" data-testid="reorient-recall-disclosure"
              aria-expanded="false">
              <summary class="reorient-recall-trigger"
                aria-expanded="false"
                data-testid="reorient-recall-trigger">{open_loops_count} open loop{"s" if open_loops_count != 1 else ""}&nbsp;&middot;&nbsp;recall&nbsp;&#9660;</summary>
              <div class="reorient-recall-body" data-testid="reorient-recall-body">
                {"".join(section_html)}
              </div>
            </details>
          </div>
        </section>"""


def _render_resurface_mode(candidates: list[dict], *, degraded: bool = False) -> str:
    if not candidates:
        affordance_status = "unavailable" if degraded else "read-only"
        state_label = "degraded" if degraded else "empty"
        state_testid = "resurface-degraded-state" if degraded else "resurface-empty-state"
        state_copy = (
            "Resurface is degraded because the runtime reported degraded guard state; "
            "no candidate payload is actionable here."
            if degraded
            else "No Resurface candidates are available for this note. Nothing needs action here."
        )
        return f"""
        <section
          class="resurface-mode"
          data-testid="resurface-mode"
          data-affordance-status="{affordance_status}"
          data-capability="resurface">
          <div class="rail-state-row">
            <span class="rail-state-label">Resurface</span>
            <span class="rail-state-value">{state_label}</span>
          </div>
          <div class="resurface-empty" data-testid="{state_testid}">
            {state_copy}
          </div>
        </section>"""
    rows: list[str] = []
    for candidate in candidates:
        signals = "".join(
            (
                '<span class="resurface-signal" data-testid="resurface-signal">'
                f"{_e(signal)}</span>"
            )
            for signal in candidate.get("signal_labels", [])
        )
        actions = "".join(
            (
                '<button type="button" class="resurface-action" '
                f'data-testid="resurface-action-{intent}" '
                f'data-intent="resurface.{intent}" '
                'data-affordance-status="unavailable" '
                'data-runtime-backed="false" '
                'data-persistence-backed="false" '
                'aria-disabled="true" disabled>'
                f"{label} unavailable (no persistence)</button>"
            )
            for intent, label in (
                ("dismiss", "Dismiss"),
                ("snooze", "Snooze"),
                ("pin", "Pin"),
            )
        )
        rows.append(
            f"""
          <article
            class="resurface-candidate"
            data-testid="resurface-candidate"
            data-affordance-status="read-only"
            data-runtime-backed="true"
            data-candidate-id="{_e(candidate.get("candidate_id", ""))}">
            <div class="resurface-title" data-testid="resurface-candidate-label">
              {_e(_cap(candidate.get("label", "")))}
            </div>
            <div class="resurface-why" data-testid="resurface-why-now">
              {_e(_cap(candidate.get("why_now", "")))}
            </div>
            <div class="resurface-relation" data-testid="resurface-relation">
              {_e(_cap(candidate.get("relation_to_active_artifact", "")))}
            </div>
            <a
              class="resurface-source"
              data-testid="resurface-source-link"
              href="#"
              data-source-link="{_e(candidate.get("source_link", ""))}">
              {_e(candidate.get("source_link", ""))}
            </a>
            <div class="resurface-signals">{signals}</div>
            <div class="resurface-actions">{actions}</div>
          </article>"""
        )
    return f"""
        <section
          class="resurface-mode"
          data-testid="resurface-mode"
          data-affordance-status="read-only"
          data-capability="resurface">
          <div class="rail-state-row">
            <span class="rail-state-label">Resurface</span>
            <span class="rail-state-value">low-pressure</span>
          </div>
          {"".join(rows)}
        </section>"""


# Maps the render kind to its styling class (the design's three redundant
# signals — grouping, label, styling).
_COMMITMENT_RENDER_KIND_CLASS: dict[str, str] = {
    "next": "k-next",
    "waiting": "k-wait",
    "review": "k-review",
}


def _commitment_render_kind(item: dict) -> str:
    """Derive the render kind that drives styling + provenance.

    Keyed off the bucket *family* and the commitment *state* — NOT the raw
    ``commitment_kind``. The API waiting bucket selects by state
    (``query_next_and_waiting_commitments``), so a commitment can be *waiting* by
    state while its kind is e.g. ``project``; it must still read as waiting
    (dashed amber + depends-on provenance) rather than falling back to
    next-action. The literal ``waiting`` kind is also honoured as a fallback.
    """
    family = str(item.get("family") or "")
    if family == "review-cycle":
        return "review"
    if str(item.get("state") or "") == "waiting" or str(item.get("kind") or "") == "waiting":
        return "waiting"
    return "next"


def _commitment_provenance_html(*, render_kind: str, item: dict) -> str:
    """Render the optional secondary provenance line for a commitment.

    Honest by omission: a line is emitted only when its server-declared value is
    present. Waiting items show what they depend on (and since when); review
    items show their cadence (and how long since the last review). Nothing here
    is computed or guessed in the render — relative ages arrive pre-computed.
    """
    if render_kind == "waiting":
        waiting_on = str(item.get("waiting_on") or "").strip()
        if not waiting_on:
            return ""
        since = str(item.get("waiting_since") or "").strip()
        text = f"depends on: {_e(_cap(waiting_on))}"
        if since:
            text += f" &middot; since {_e(since)}"
        return (
            '<div class="commitment-prov" data-testid="commitment-provenance">'
            f"{text}</div>"
        )
    if render_kind == "review":
        cadence = str(item.get("review_cadence") or "").strip()
        last = str(item.get("last_reviewed_relative") or "").strip()
        if not cadence and not last:
            return ""
        parts: list[str] = []
        if cadence:
            parts.append(f"cadence: {_e(cadence)}")
        if last:
            parts.append(f"last {_e(last)}")
        return (
            '<div class="commitment-prov" data-testid="commitment-provenance">'
            f"{' &middot; '.join(parts)}</div>"
        )
    return ""


def _render_commitment_item(item: dict) -> str:
    """Render one read-only commitment row. No mutation affordance.

    Carries the render ``family`` and ``kind`` markers so the next-action vs
    review-cycle distinction — and the within-Next ``waiting`` vs ``next_action``
    distinction — is observable per-item, not only via the enclosing group. The
    kind tag echoes the API kind verbatim (the design's explicit-label signal).
    """
    family = str(item.get("family") or "")
    commitment_id = _e(str(item.get("commitment_id") or ""))
    kind = str(item.get("kind") or "")
    summary = str(item.get("summary") or "")
    target_ref = str(item.get("target_ref") or "")
    render_kind = _commitment_render_kind(item)
    kind_class = _COMMITMENT_RENDER_KIND_CLASS[render_kind]
    cyclical = (
        '<span class="commitment-cycle" aria-hidden="true">&#8635;</span>'
        if render_kind == "review"
        else ""
    )
    if summary:
        summary_html = (
            '<div class="commitment-summary" data-testid="commitment-summary">'
            f"{cyclical}{_e(_cap(summary))}</div>"
        )
    elif not target_ref:
        # Id-only commitment (no summary, no target_ref): still a real active
        # commitment the durable read returned, so it must remain a legible
        # keyed row rather than collapsing the surface into a false ``empty``
        # state. Surface its identifier so the row is not visually blank.
        summary_html = (
            '<div class="commitment-summary commitment-summary-fallback" '
            'data-testid="commitment-summary-fallback">'
            f"{cyclical}{commitment_id}</div>"
        )
    else:
        summary_html = ""
    kind_tag = (
        '<span class="commitment-kind-tag" data-testid="commitment-kind-tag">'
        f"{_e(kind)}</span>"
        if kind
        else ""
    )
    target_html = (
        '<div class="commitment-target" data-testid="commitment-target" '
        f'data-target-ref="{_e(target_ref)}">'
        f'<span class="commitment-arrow" aria-hidden="true">&#8594;</span>'
        f"{_e(_cap(target_ref))}</div>"
        if target_ref
        else ""
    )
    prov_html = _commitment_provenance_html(render_kind=render_kind, item=item)
    return f"""
            <article
              class="commitment-item {kind_class}"
              data-testid="commitment-item"
              data-commitment-family="{_e(family)}"
              data-commitment-kind="{_e(kind)}"
              data-commitment-id="{commitment_id}"
              data-affordance-status="read-only">
              <div class="commitment-item-top">
                {summary_html}
                {kind_tag}
              </div>
              {target_html}
              {prov_html}
            </article>"""


def _render_commitment_group(
    *, family: str, label: str, sublabel: str, items: list[dict]
) -> str:
    """Render one commitment family group (next-action or review-cycle).

    The group is always emitted when the surface is populated so the two
    families remain visually distinct regions even when one is momentarily
    empty; an empty family shows a quiet read-only placeholder rather than
    vanishing (so the absence of one family is legible, not implied). A count
    chip surfaces how many items the family holds without an alarm semantics.
    """
    family_class = "g-next" if family == "next-action" else "g-review"
    if items:
        body = "".join(_render_commitment_item(item) for item in items)
    else:
        none_copy = (
            "No next-actions or waiting items."
            if family == "next-action"
            else "No review-cycle returns this period."
        )
        body = (
            '<div class="commitment-group-empty" '
            f'data-testid="commitment-group-empty-{_e(family)}">'
            f"{none_copy}</div>"
        )
    return f"""
          <section
            class="commitment-group {family_class}"
            data-testid="commitment-group-{_e(family)}"
            data-commitment-family="{_e(family)}"
            data-affordance-status="read-only">
            <div class="commitment-group-head">
              <span class="commitment-group-label" data-testid="commitment-group-label-{_e(family)}">{_e(label)}</span>
              <span class="commitment-group-sub">{_e(sublabel)}</span>
              <span class="commitment-group-count" data-testid="commitment-group-count-{_e(family)}">{len(items)}</span>
            </div>
            {body}
          </section>"""


def _render_commitments_mode(surface: dict | None) -> str:
    """Render the read-only commitment surface (#2075, parent #1960).

    Consumes the normalized slice-2 ``runtime.commitments`` field and renders it
    read-only — strictly no mutation / state-transition affordance. Visually
    distinguishes the next-action family (next + waiting) from the review-cycle
    family (review_return) via separate labelled groups and per-item markers.
    Degrades honestly: a missing field renders ``not-shown`` and a degraded
    durable read renders ``unavailable`` with the reason — never a confident
    empty surface (cross-task invariant CI-2).
    """
    state = str((surface or {}).get("state") or "not-shown")

    if state == "not-shown":
        return """
        <section
          class="commitments-mode"
          data-testid="commitments-mode"
          data-commitment-state="not-shown"
          data-affordance-status="unavailable"
          data-capability="commitments">
          <div class="rail-state-row">
            <span class="rail-state-label">Commitments</span>
            <span class="rail-state-value">unavailable</span>
          </div>
          <div class="commitments-notice" data-testid="commitments-not-shown-state">
            Commitments are not shown — this runtime did not provide the commitment surface.
          </div>
        </section>"""

    if state == "degraded":
        reason = _e(str((surface or {}).get("degraded_reason") or "unknown"))
        return f"""
        <section
          class="commitments-mode"
          data-testid="commitments-mode"
          data-commitment-state="degraded"
          data-affordance-status="unavailable"
          data-capability="commitments">
          <div class="rail-state-row">
            <span class="rail-state-label">Commitments</span>
            <span class="rail-state-value">unavailable</span>
          </div>
          <div
            class="commitments-notice"
            data-testid="commitments-degraded-state"
            data-degraded-reason="{reason}">
            Commitments are unavailable — the durable read is degraded
            ({reason}). This is not a sign that you have none.
          </div>
        </section>"""

    if state == "empty":
        # Affirmative, confident zero — a healthy "you have none", visually
        # distinct (vault-green dot, "0 active") from the amber degraded/absent
        # states so the two are never confusable.
        empty_as_of = _e(str((surface or {}).get("as_of") or "").strip())
        empty_foot = (
            '<div class="commitments-foot" data-testid="commitments-as-of">'
            '<span class="commitments-foot-ok">commitments ok</span> &middot; 0 active'
            + (f" &middot; as of {empty_as_of}" if empty_as_of else "")
            + "</div>"
        )
        return f"""
        <section
          class="commitments-mode"
          data-testid="commitments-mode"
          data-commitment-state="empty"
          data-affordance-status="read-only"
          data-read-only="true"
          data-capability="commitments">
          <div class="rail-state-row">
            <span class="rail-state-label">Commitments</span>
            <span class="rail-state-value">clear</span>
          </div>
          <div class="commitments-empty" data-testid="commitments-empty-state">
            <span class="commitments-empty-dot" aria-hidden="true"></span>
            <span class="commitments-empty-msg">No active commitments.</span>
          </div>
          {empty_foot}
        </section>"""

    # populated
    next_action_items = list((surface or {}).get("next_action") or [])
    review_cycle_items = list((surface or {}).get("review_cycle") or [])
    next_group = _render_commitment_group(
        family="next-action",
        label="Next",
        sublabel="mine to do",
        items=next_action_items,
    )
    review_group = _render_commitment_group(
        family="review-cycle",
        label="Review",
        sublabel="returns to you",
        items=review_cycle_items,
    )
    as_of = _e(str((surface or {}).get("as_of") or "").strip())
    foot_html = (
        '<div class="commitments-foot" data-testid="commitments-as-of">'
        f'as of {as_of} &middot; <span class="commitments-foot-ok">commitments ok</span>'
        "</div>"
        if as_of
        else ""
    )
    return f"""
        <section
          class="commitments-mode"
          data-testid="commitments-mode"
          data-commitment-state="populated"
          data-affordance-status="read-only"
          data-read-only="true"
          data-capability="commitments">
          <div class="rail-state-row">
            <span class="rail-state-label">Commitments</span>
            <span class="rail-state-value">read-only</span>
          </div>
          {next_group}
          {review_group}
          {foot_html}
        </section>"""


def _render_act_mode(
    *,
    proposals: list[dict],
    response: dict,
    writeguard_blocked: bool,
) -> str:
    if not proposals and not response:
        return ""

    proposal_rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence") or {}
        proposal_id = _e(proposal.get("proposal_id", ""))
        artifact_id = _e(proposal.get("artifact_id", ""))
        affordances = proposal.get("affordances") or {}
        proposal_status = str(proposal.get("status") or "staged")
        proposal_available = proposal_status in {"staged", "corrected"} and not writeguard_blocked
        proposal_affordance_status = "active" if proposal_available else "blocked" if writeguard_blocked else "unavailable"
        actions = "".join(
            (
                '<button type="button" class="act-panel-action" '
                f'data-testid="act-{label}" '
                f'data-panel-action="{_e(label)}" '
                'data-api-method="POST" '
                'data-api-path="/api/panel/confirm" '
                f'data-affordance-status="{proposal_affordance_status}" '
                f'data-proposal-id="{proposal_id}" '
                f'data-artifact-id="{artifact_id}" '
                'data-writeguard-bypass="false">'
                f"{_e(label)}</button>"
            )
            for label in ("confirm", "correct", "reject")
            if affordances.get(label, True) and proposal_available
        )
        if not proposal_available:
            actions = (
                '<span class="act-panel-unavailable" '
                'data-testid="act-panel-unavailable" '
                f'data-affordance-status="{proposal_affordance_status}">'
                f"{_e(proposal_status)} proposal unavailable</span>"
            )
        proposal_rows.append(
            f"""
          <article
            class="act-proposal"
            data-testid="act-proposal-review"
            data-affordance-status="{proposal_affordance_status}"
            data-proposal-id="{proposal_id}"
            data-artifact-id="{artifact_id}">
            <div class="act-proposal-title">{_e(proposal.get("description", ""))}</div>
            <div class="act-bundle" data-testid="act-action-bundle-context">
              <span>{_e(evidence.get("trigger_summary", ""))}</span>
              <span>{_e(evidence.get("action_class", ""))}</span>
              <span>{_e(evidence.get("cognition_route", ""))}</span>
            </div>
            <div class="act-flow" data-testid="act-governed-flow">
              intent &rarr; propose &rarr; decide &rarr; execute &rarr; receipt
            </div>
            <div class="act-actions">{actions}</div>
          </article>"""
        )

    receipt_html = ""
    if response:
        receipt = response.get("receipt") or {}
        block_reason = response.get("block_reason") or {}
        receipt_message = (
            receipt.get("message")
            or receipt.get("outcome")
            or block_reason.get("message")
            or response.get("outcome")
            or response.get("status")
            or ""
        )
        receipt_html = f"""
          <div class="act-receipt" data-testid="act-durable-receipt">
            <span data-testid="act-receipt-status">{_e(response.get("status", ""))}</span>
            <span data-testid="act-receipt-outcome">{_e(response.get("outcome", ""))}</span>
            <span>{_e(receipt_message)}</span>
          </div>"""

    return f"""
        <section
          class="act-mode"
          data-testid="act-mode"
          data-authority-surface="panel"
          data-affordance-status="{'blocked' if writeguard_blocked else 'active'}"
          data-writeguard-bypass="false">
          <div class="rail-state-row">
            <span class="rail-state-label">Act</span>
            <span class="rail-state-value">Panel confirm path</span>
          </div>
          {"".join(proposal_rows)}
          {receipt_html}
        </section>"""


def _render_suggestion_cards(cards: list[dict]) -> str:
    rows: list[str] = []
    for card in cards:
        intents = card.get("available_intents") or []
        actions = "".join(
            (
                '<button type="button" class="suggestion-action" '
                f'data-intent="{_e(intent)}">{_e(_suggestion_action_label(intent))}</button>'
            )
            for intent in intents
        )
        role = f' role="{_e(card.get("aria_role"))}"' if card.get("aria_role") else ""
        notice = ""
        if card.get("classification_notice"):
            notice = (
                '<div class="suggestion-card-notice" '
                'data-testid="suggestion-card-classification">'
                + _e(card.get("classification_notice"))
                + "</div>"
            )
        denial = ""
        if card.get("denial_reason"):
            denial = (
                '<div class="suggestion-card-denial" data-testid="suggestion-card-denial">'
                + _e(card.get("denial_reason"))
                + "</div>"
            )
        rows.append(
            f"""
        <div
          class="suggestion-card"
          data-testid="suggestion-card"
          data-variant="{_e(card.get("data_variant", ""))}"
          data-suggestion-id="{_e(card.get("data_suggestion_id", ""))}"{role}>
          <div class="suggestion-card-title">{_e(card.get("title", ""))}</div>
          <div class="suggestion-card-preview">{_e(card.get("preview_text", ""))}</div>
          {notice}
          {denial}
          <div class="suggestion-card-actions">{actions}</div>
        </div>"""
        )
    return "\n".join(rows)


def _render_governance_receipts(receipts: list[dict]) -> str:
    rows: list[str] = []
    for receipt in receipts:
        rows.append(
            f"""
        <button
          type="button"
          class="receipt-pill"
          data-testid="{_e(receipt.get("data_testid", "receipt-pill"))}"
          data-receipt-id="{_e(receipt.get("data_receipt_id", ""))}"
          data-suggestion-id="{_e(receipt.get("data_suggestion_id", ""))}"
          data-artifact-id="{_e(receipt.get("data_artifact_id", ""))}"
          data-status="{_e(receipt.get("data_status", ""))}"
          data-intent="{_e(receipt.get("data_intent", "governance.openReceipt"))}"
          aria-label="{_e(receipt.get("aria_label", ""))}">
          <span class="receipt-pill-label">{_e(receipt.get("label", ""))}</span>
          <span class="receipt-pill-time">{_e(receipt.get("display_timestamp", ""))}</span>
        </button>"""
        )
    if not rows:
        return ""
    return f"""
        <div class="receipts-strip" data-testid="receipts-strip" aria-live="polite">
          {"".join(rows)}
        </div>"""


def _suggestion_action_label(intent: str) -> str:
    return {
        "suggestion.apply": "Apply",
        "suggestion.discard": "Discard",
        "suggestion.inspect": "Inspect",
        "governance.queue": "Queue",
        "blocked.acknowledge": "Acknowledge",
    }.get(intent, intent)


def _render_suggested_insertions(insertions: list[dict]) -> str:
    rows: list[str] = []
    for insertion in insertions:
        if not insertion.get("is_visible", True):
            continue
        rows.append(
            f"""
        <ins
          class="suggested-insertion"
          data-testid="suggested-insertion-block"
          data-suggestion-id="{_e(insertion.get("data_suggestion_id", ""))}"
          data-state="{_e(insertion.get("data_state", ""))}"
          aria-label="{_e(insertion.get("aria_label", ""))}">
          <span class="suggested-insertion-label">{_e(insertion.get("label", ""))}</span>
          <span class="suggested-insertion-text">{_e(insertion.get("proposed_text", ""))}</span>
        </ins>"""
        )
    return "\n".join(rows)


def _render_canvas_session_controls(
    *,
    note_path: str,
    session_id: str,
    session_state: str,
    can_edit_body: bool,
    user_present: bool,
    content_hash: str,
    recovery_needed: bool,
    recovery_acknowledged: bool,
    conflict_detected: bool,
    canvas_enabled: bool,
    workspace_update_available: bool,
    workspace_update_reason: str,
    writeguard_blocked: bool,
    session_log_path: str,
    undo_available: bool,
    applied_edit_count: int,
    undone_edit_count: int,
) -> str:
    canvas_blocked = not canvas_enabled or writeguard_blocked or (not workspace_update_available)
    edit_api_path = f"/api/canvas/sessions/{session_id}/edits" if session_id else ""
    undo_api_path = f"/api/canvas/sessions/{session_id}/edits/last" if session_id else ""
    coauthor_api_path = f"/api/canvas/sessions/{session_id}/coauthor" if session_id else ""
    present_text = (
        "User is present for Canvas editing."
        if user_present
        else "No active Canvas session."
    )
    log_text = session_log_path or "no session log"
    unavailable_reasons: list[tuple[str, str, str]] = []
    if not canvas_enabled:
        base_reason = "Canvas editing is currently disabled by runtime configuration."
    elif writeguard_blocked:
        base_reason = "Canvas editing is blocked by WriteGuard."
    elif not workspace_update_available:
        base_reason = (
            "Body editing is unavailable because workspace update is disabled: "
            f"{_human_reason(workspace_update_reason)}."
        )
    else:
        base_reason = "Canvas action is unavailable in the current session state."

    if session_id and canvas_enabled:
        close_html = f"""
          <button
            type="button"
            data-testid="workspace-canvas-close"
            data-affordance-status="active"
            data-capability="canvas.closeSession"
            data-api-method="DELETE"
            data-api-path="/api/canvas/sessions/{session_id}">Close</button>"""
    else:
        close_html = ""
        unavailable_reasons.append(
            (
                "close-session",
                "canvas.closeSession",
                base_reason if not canvas_enabled else "No active Canvas session to close.",
            )
        )

    if canvas_enabled and not session_id:
        start_html = f"""
          <button
            type="button"
            data-testid="workspace-canvas-start"
            data-affordance-status="active"
            data-capability="canvas.openSession"
            data-api-method="POST"
            data-api-path="/api/canvas/sessions"
            data-note-path="{note_path}">Start</button>"""
    else:
        start_html = ""
        unavailable_reasons.append(("start-session", "canvas.openSession", base_reason if not canvas_enabled else "A Canvas session is already active."))

    if can_edit_body and not canvas_blocked:
        edit_button_html = f"""
          <button
            type="button"
            data-testid="workspace-canvas-edit-submit"
            data-affordance-status="active"
            data-capability="canvas.applyBodyEdit"
            data-api-method="POST"
            data-api-path="{edit_api_path}"
            data-content-hash="{content_hash}">Apply body edit</button>"""
    else:
        edit_button_html = ""
        unavailable_reasons.append(("apply-body-edit", "canvas.applyBodyEdit", base_reason))

    if undo_available and not canvas_blocked:
        undo_button_html = f"""
          <button
            type="button"
            data-testid="workspace-canvas-undo"
            data-affordance-status="active"
            data-capability="canvas.undoBodyEdit"
            data-api-method="DELETE"
            data-api-path="{undo_api_path}">Undo</button>"""
    else:
        undo_button_html = ""
        unavailable_reasons.append(("undo-body-edit", "canvas.undoBodyEdit", "No undo is available for this session state." if not canvas_blocked else base_reason))

    # When every action is blocked by the same global reason (canvas disabled or
    # writeguard), show ONE visible consolidated message instead of the same text
    # N times.  Individual capability markers are preserved as aria-hidden spans
    # so that test selectors and JavaScript affordance-checking still work.
    globally_blocked = not canvas_enabled or writeguard_blocked
    if globally_blocked and unavailable_reasons:
        hidden_markers = "".join(
            (
                '<span class="canvas-action-unavailable" '
                'aria-hidden="true" style="display:none" '
                f'data-action="{_e(action)}" '
                f'data-capability="{_e(capability)}" '
                f'data-affordance-status="unavailable"></span>'
            )
            for action, capability, _reason in unavailable_reasons
        )
        unavailable_html = (
            '<div class="canvas-action-unavailable canvas-globally-unavailable" '
            'data-testid="workspace-canvas-action-unavailable" '
            'data-action="all" '
            'data-capability="canvas" '
            f'data-affordance-status="unavailable">{_e(base_reason)}</div>'
            + hidden_markers
        )
        # Early return: skip presence text, composer, undo_state, and log counts —
        # none of those are meaningful when canvas is globally blocked.
        # Retain workspace-canvas-body-edit-unavailable in DOM (suppressed) so test
        # selectors and affordance-checking still work (#1361).
        suppressed_composer = (
            '<div'
            ' class="canvas-body-edit-unavailable canvas-body-edit-unavailable--suppressed"'
            ' data-testid="workspace-canvas-body-edit-unavailable"'
            ' data-affordance-status="blocked"'
            ' hidden>'
            "</div>"
        ) if not canvas_enabled else ""
        return f"""
        <div class="canvas-controls" data-testid="workspace-canvas-session-controls">
          {unavailable_html}
          {suppressed_composer}
          <div class="canvas-provenance" data-testid="workspace-canvas-provenance"
               aria-hidden="true" style="display:none">
            <code data-testid="workspace-canvas-session-log-path">{log_text}</code>
            <span data-testid="workspace-canvas-edit-count">{applied_edit_count}</span>
            <span data-testid="workspace-canvas-undone-count">{undone_edit_count}</span>
          </div>
        </div>"""
    else:
        unavailable_html = "".join(
            (
                '<div class="canvas-action-unavailable" '
                'data-testid="workspace-canvas-action-unavailable" '
                f'data-action="{_e(action)}" '
                f'data-capability="{_e(capability)}" '
                'data-affordance-status="unavailable">'
                f"{_e(reason)}</div>"
            )
            for action, capability, reason in unavailable_reasons
        )
    undo_state_html = (
        '<span class="canvas-undo-state" data-testid="workspace-canvas-undo-state">'
        + ("Undo available" if undo_available else "No undo available")
        + "</span>"
    )
    composer_html = ""
    if can_edit_body and not canvas_blocked:
        composer_html = f"""
          <form
            class="canvas-body-edit-composer"
            data-testid="workspace-canvas-body-edit-composer"
            data-affordance-status="active"
            data-capability="canvas.applyBodyEdit"
            data-api-method="POST"
            data-api-path="{edit_api_path}"
            data-requires-preview="true">
            <label for="canvas_new_body">Body edit draft</label>
            <textarea
              id="canvas_new_body"
              name="new_body"
              data-testid="workspace-canvas-body-edit-textarea"
              aria-label="Body edit draft"></textarea>
            <input type="hidden" name="content_hash" value="{content_hash}">
            <div
              class="canvas-body-edit-preview"
              data-testid="workspace-canvas-body-edit-preview"
              data-preview-state="required">
              Preview required before apply. Runtime owns the writer path.
            </div>
            <div class="canvas-body-edit-actions">
              <button
                type="button"
                data-testid="workspace-canvas-edit-discard"
                data-affordance-status="active"
                data-runtime-backed="false"
                data-api-method="LOCAL">Discard draft</button>
            </div>
          </form>"""
    else:
        unavailable_copy = "Body edit composer unavailable until Canvas has an active editable session."
        if not workspace_update_available:
            unavailable_copy = (
                "Body edit composer disabled by workspace update capability: "
                f"{_human_reason(workspace_update_reason)}."
            )
        if canvas_blocked and not canvas_enabled:
            # Suppressed: canvas is disabled — guard alert already communicates this.
            # Retain testid in DOM for test compatibility but keep visually hidden.
            composer_html = (
                '<div'
                ' class="canvas-body-edit-unavailable canvas-body-edit-unavailable--suppressed"'
                ' data-testid="workspace-canvas-body-edit-unavailable"'
                ' data-affordance-status="blocked"'
                ' hidden>'
                "</div>"
            )
        else:
            composer_html = """
          <div
            class="canvas-body-edit-unavailable"
            data-testid="workspace-canvas-body-edit-unavailable"
            data-affordance-status="blocked">
            """ + unavailable_copy + """
          </div>"""
    recovery_html = ""
    if conflict_detected:
        recovery_state = "acknowledged" if recovery_acknowledged else "needs acknowledgement"
        recovery_reason = "recovery needed" if recovery_needed else "paused/interrupted"
        recovery_html = f"""
          <div class="canvas-recovery-conflict" data-testid="workspace-canvas-recovery-conflict">
            <span data-testid="workspace-canvas-conflict-session-state">{session_state}</span>
            <span>{recovery_reason}</span>
            <span data-testid="workspace-canvas-recovery-state">{recovery_state}</span>
            <span data-testid="workspace-canvas-recovery-copy">
              Acknowledge recovery before applying body edits.
            </span>
            <button
              type="button"
              data-testid="workspace-canvas-recovery-ack"
              data-affordance-status="blocked"
              data-runtime-backed="false"
              data-blocked-reason="Canvas recovery acknowledgement runtime route is not shipped"
              disabled>Acknowledge</button>
          </div>"""
    # Live agentic co-authoring loop (#1733). Gated strictly by canvas_enabled and
    # an active session: the user states an intent, the server composes and applies
    # the body (server declares, UI renders). A governance-bearing 409 routes to
    # Panel; a 503 surfaces a calm, non-destructive notice. No local body
    # composition, no governance inference, receipts never invented.
    coauthor_html = ""
    if canvas_enabled and session_id and can_edit_body and not canvas_blocked:
        coauthor_html = f"""
          <form
            class="canvas-coauthor"
            data-testid="workspace-canvas-coauthor"
            data-affordance-status="active"
            data-capability="canvas.coauthor"
            data-api-method="POST"
            data-api-path="{coauthor_api_path}">
            <label for="canvas_coauthor_intent">Co-authoring intent</label>
            <input
              type="text"
              id="canvas_coauthor_intent"
              name="intent"
              data-testid="workspace-canvas-coauthor-intent"
              aria-label="Co-authoring intent"
              placeholder="e.g. tighten the intro paragraph">
            <button
              type="button"
              data-testid="workspace-canvas-coauthor-submit"
              data-affordance-status="active"
              data-capability="canvas.coauthor"
              data-runtime-backed="true"
              data-api-method="POST"
              data-api-path="{coauthor_api_path}">Co-author</button>
            <div
              class="canvas-coauthor-notice"
              data-testid="workspace-canvas-coauthor-notice"
              data-notice-state="idle"
              hidden></div>
            <div
              class="canvas-coauthor-result"
              data-testid="workspace-canvas-coauthor-result"
              data-result-state="idle">
              <pre
                class="canvas-coauthor-applied-body"
                data-testid="workspace-canvas-coauthor-applied-body"></pre>
              <span
                class="canvas-coauthor-change-summary"
                data-testid="workspace-canvas-coauthor-change-summary"></span>
            </div>
            <div
              class="canvas-coauthor-handoff"
              data-testid="workspace-canvas-coauthor-handoff"
              data-handoff-state="idle"
              hidden>
              <a
                href="#workspace-panel-label"
                data-testid="workspace-canvas-view-in-panel"
                data-affordance-status="read-only"
                data-authority-role="server_declared"
                data-intent-id="">view in Panel</a>
            </div>
          </form>"""
    return f"""
        <div class="canvas-controls" data-testid="workspace-canvas-session-controls">
          {start_html}
          {close_html}
          {edit_button_html}
          {undo_button_html}
          {unavailable_html}
          <span class="canvas-presence" data-testid="workspace-canvas-user-present" data-user-present="{'true' if user_present else 'false'}">{present_text}</span>
          {composer_html}
          {coauthor_html}
          {recovery_html}
          {undo_state_html}
          <div class="canvas-provenance" data-testid="workspace-canvas-provenance">
            <span class="canvas-provenance-label">log</span>
            <code data-testid="workspace-canvas-session-log-path">{log_text}</code>
            <span data-testid="workspace-canvas-edit-count">{applied_edit_count} edit{'s' if applied_edit_count != 1 else ''}</span>
            <span data-testid="workspace-canvas-undone-count">{undone_edit_count} undone</span>
          </div>
        </div>"""


def _render_panel_proposal_rows(
    proposals: list[dict],
    *,
    writeguard_blocked: bool,
) -> str:
    if not proposals:
        return ""

    # Action row order: Apply (confirm) → Discard (reject) → Defer (correct) per §8 design
    _ACTION_LABELS = {"confirm": "Apply", "reject": "Discard", "correct": "Defer"}
    _ACTION_ORDER = ("confirm", "reject", "correct")
    _ACTION_CSS = {
        "confirm": "panel-action-apply",
        "reject": "panel-action-discard",
        "correct": "panel-action-defer",
    }

    rows: list[str] = []
    for proposal in proposals:
        evidence = proposal.get("evidence") or {}
        affordances = proposal.get("affordances") or {}
        proposal_status = str(proposal.get("status") or "staged")
        proposal_available = proposal_status in {"staged", "corrected"} and not writeguard_blocked
        affordance_status = "active" if proposal_available else "blocked" if writeguard_blocked else "unavailable"
        section_state = "active" if proposal_available else "idle"
        enabled_affordances = [
            label
            for label in _ACTION_ORDER
            if affordances.get(label) and proposal_available
        ]
        proposal_id = _e(proposal.get("proposal_id", ""))
        artifact_id = _e(proposal.get("artifact_id", ""))
        # Provenance line: agent · ISO-timestamp · confidence N (AC4)
        prov_agent = _e(str(proposal.get("agent") or proposal.get("author") or "hugin"))
        prov_ts_raw = str(proposal.get("created_at") or proposal.get("timestamp") or "")
        prov_ts = _e(prov_ts_raw[:16]) if prov_ts_raw else _e(datetime.now().strftime("%Y-%m-%dT%H:%M"))
        prov_conf = _e(str(proposal.get("confidence") or "—"))
        provenance_html = (
            f'<div class="panel-section-provenance" data-testid="workspace-panel-provenance">'
            f"{prov_agent}&nbsp;&middot;&nbsp;{prov_ts}&nbsp;&middot;&nbsp;confidence&nbsp;{prov_conf}"
            f"</div>"
        )
        # Server-declared proposal-scoped origin attribution (CHAT-PANEL-HANDOFF-02).
        # Surfaced only when the runtime declared it; the UI never infers it.
        proposal_origin = proposal.get("proposal_origin")
        origin_html = ""
        if proposal_origin:
            origin_label = (
                "canvas co-authoring"
                if proposal_origin == "canvas_coauthoring"
                else str(proposal_origin)
            )
            origin_html = (
                '<div class="panel-proposal-origin" '
                'data-testid="workspace-panel-proposal-origin" '
                f'data-proposal-origin="{_e(str(proposal_origin))}">'
                f"origin:&nbsp;{_e(origin_label)}"
                "</div>"
            )
        # Server-declared reflected receipt posture (CHAT-PANEL-HANDOFF-03).
        # Read-only: the canvas-originated proposal's executed receipt reflected
        # back into the originating context, correlated by intent_id. Surfaced
        # only when the server supplied it; the UI invents no receipt.
        reflected_receipt = proposal.get("reflected_receipt")
        reflected_receipt_html = ""
        if isinstance(reflected_receipt, dict) and reflected_receipt:
            rr_state = str(reflected_receipt.get("state") or "")
            rr_visibility = str(reflected_receipt.get("receipt_visibility") or "")
            rr_receipt_id = str(reflected_receipt.get("receipt_id") or "")
            rr_outcome = str(reflected_receipt.get("outcome") or "")
            rr_intent_id = str(reflected_receipt.get("intent_id") or "")
            if rr_state == "receipt_visible":
                rr_label = f"receipt: {rr_outcome or 'applied'}"
            elif rr_state == "blocked":
                rr_label = f"blocked: {rr_outcome or 'no durable receipt'}"
            else:
                rr_label = "awaiting decision"
            rr_id_html = (
                f'<span data-testid="workspace-panel-reflected-receipt-id">'
                f"{_e(rr_receipt_id)}</span>"
                if rr_receipt_id
                else ""
            )
            reflected_receipt_html = (
                '<div class="panel-proposal-reflected-receipt" '
                'data-testid="workspace-panel-reflected-receipt" '
                'data-authority-role="server_declared" '
                'data-affordance-status="read-only" '
                f'data-receipt-state="{_e(rr_state)}" '
                f'data-receipt-visibility="{_e(rr_visibility)}" '
                f'data-intent-id="{_e(rr_intent_id)}">'
                f"{_e(rr_label)}{rr_id_html}"
                "</div>"
            )
        buttons = "".join(
            (
                f'<button type="button" class="panel-proposal-action {_ACTION_CSS[label]}" '
                'data-testid="workspace-panel-action" '
                f'data-panel-action="{_e(label)}" '
                f'data-affordance-status="{affordance_status}" '
                f'data-proposal-id="{proposal_id}" '
                f'data-artifact-id="{artifact_id}" '
                'data-runtime-backed="true" '
                'data-api-method="POST" '
                'data-api-path="/api/panel/confirm">'
                f"{_ACTION_LABELS[label]}</button>"
            )
            for label in enabled_affordances
        )
        if not proposal_available:
            buttons = (
                '<span class="panel-proposal-unavailable" '
                'data-testid="workspace-panel-proposal-unavailable" '
                f'data-affordance-status="{affordance_status}">'
                f"{_e(proposal_status)} proposal unavailable</span>"
            )
        rows.append(
            f"""
        <div
          class="panel-proposal-row panel-section"
          data-testid="workspace-panel-proposal-row"
          data-section-state="{section_state}"
          data-affordance-status="{affordance_status}"
          data-proposal-id="{proposal_id}"
          data-artifact-id="{artifact_id}">
          <div class="panel-section-title">{_e(proposal.get("description", ""))}</div>
          {provenance_html if proposal_available else ""}
          {origin_html}
          {reflected_receipt_html}
          <div class="panel-proposal-meta">
            <span data-testid="workspace-panel-proposal-id">{proposal_id}</span>
            <span data-testid="workspace-panel-artifact-id">{artifact_id}</span>
            <span>{_e(proposal.get("status", ""))}</span>
          </div>
          <details class="panel-proposal-evidence" data-testid="workspace-panel-evidence" open>
            <summary data-testid="workspace-panel-evidence-disclosure">Evidence</summary>
            <span data-testid="workspace-panel-trigger-summary">{_e(evidence.get("trigger_summary", ""))}</span>
            <span data-testid="workspace-panel-action-class">{_e(evidence.get("action_class", ""))}</span>
            <span data-testid="workspace-panel-cognition-route">{_e(evidence.get("cognition_route", ""))}</span>
          </details>
          <div class="panel-proposal-affordances panel-action-row">
            {buttons}
          </div>
        </div>"""
        )
    return "\n".join(rows)


def _render_panel_confirm_response(response: dict) -> str:
    if not response:
        return ""
    status = _e(response.get("status", ""))
    receipt = response.get("receipt") or {}
    block_reason = response.get("block_reason") or {}
    receipt_html = ""
    if status in {"executed", "logged"} and receipt:
        corrected_badge = ""
        if receipt.get("message") == "corrected" or receipt.get("corrected") or response.get("corrected"):
            corrected_badge = (
                '<span class="panel-confirm-corrected" '
                'data-testid="workspace-panel-corrected-receipt">corrected</span>'
            )
        inverse_html = ""
        inverse_action = receipt.get("inverse_action") or receipt.get("inverse_action_id")
        if inverse_action:
            inverse_html = (
                '<div class="panel-confirm-inverse" '
                'data-testid="workspace-panel-inverse-action" '
                'data-affordance-status="read-only" '
                'data-runtime-backed="false">'
                + _e(inverse_action)
                + "</div>"
            )
        receipt_html = f"""
          <div
            class="panel-confirm-receipt"
            data-testid="workspace-panel-receipt"
            data-receipt-persistence="durable-runtime-projection">
            <span data-testid="workspace-panel-receipt-outcome">{_e(receipt.get("outcome") or response.get("outcome") or status)}</span>
            <span data-testid="workspace-panel-receipt-message">{_e(receipt.get("message") or receipt.get("action_taken") or status)}</span>
            <span data-testid="workspace-panel-receipt-timestamp">{_e(receipt.get("timestamp") or response.get("timestamp") or "timestamp unavailable")}</span>
            {corrected_badge}
            {inverse_html}
          </div>"""
    blocked_html = ""
    if status == "blocked" and block_reason:
        message = str(block_reason.get("message") or "")
        if block_reason.get("gate") == "same-turn" or "same-turn" in message.lower():
            message = (
                "Same-turn confirmation is not allowed. "
                "The proposal must be confirmed in a later interaction."
            )
        blocked_html = f"""
          <div class="panel-confirm-blocked" data-testid="workspace-panel-blocked-reason">
            <span data-testid="workspace-panel-block-gate">{_e(block_reason.get("gate") or "unknown")}</span>
            <span data-testid="workspace-panel-block-message">{_e(message)}</span>
          </div>"""
    return f"""
        <div class="panel-confirm-response" data-testid="workspace-panel-confirm-response">
          <span data-testid="workspace-panel-confirm-status">{status}</span>
          {receipt_html}
          {blocked_html}
        </div>"""


def _error_detail(error: str) -> dict:
    if not error.startswith("HTTP "):
        return {}
    _, _, maybe_json = error.partition(": ")
    if not maybe_json:
        return {}
    try:
        payload = json.loads(maybe_json)
    except json.JSONDecodeError:
        return {}
    detail = payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def _is_remote_page_origin(hostname: str) -> bool:
    """True when the page was loaded from a non-localhost origin (#2124).

    ``hostname`` is the host the *browser* used to load the page (the request
    ``Host`` header, minus any port). It is a client/page fact, never a runtime
    signal — the server still declares the runtime class. An empty hostname (no
    signal) is treated as local so the safe #2123 "Vault unreachable" state
    remains the default and never regresses.
    """
    host = (hostname or "").strip().lower()
    if not host:
        return False
    # Strip a trailing port if one slipped through (Host is "name:port"). A
    # bracketed IPv6 literal ("[::1]" / "[::1]:port") has >=2 colons, so the
    # single-colon guard would miss its port — parse the bracket form first.
    if host.startswith("["):
        end = host.find("]")
        host = host[1:end] if end != -1 else host.strip("[]")
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return host not in ("localhost", "127.0.0.1", "::1", "")


def _render_error_section(
    error: str, *, entry_state: str = "", page_origin_hostname: str = ""
) -> str:
    """Render a visible error state using Yggdrasil destructive tokens.

    When the resolved entry state is ``no_vault`` (#1783) the error state
    carries the declared ``entry.retry`` affordance: a plain read-only link
    back to ``/`` that re-requests orientation. No snapshot content is
    fabricated. Beside retry, the calm system-map affordance (#1787, SEP-05;
    spec §Resolved Q4) keeps the whole legible even when the runtime is
    unreachable — pull-based, opened only by this explicit `map.open`.

    When the runtime is unreachable *and* the page was loaded from a remote
    (non-localhost) origin, the unreachable state is the "wrong device" variant
    (#2124): the same 503 shape has two causes (down runtime vs. a browser on
    another device hitting the API's localhost bind), and a human on the wrong
    device needs different guidance. The distinction is derived purely from the
    page origin (``page_origin_hostname``), not from a new runtime state.
    """
    retry_html = (
        '\n    <a class="error-retry" href="/" data-intent="entry.retry"'
        ' data-testid="workspace-entry-retry">Retry</a>'
        '\n    <button type="button" class="error-map-affordance"'
        ' data-testid="workspace-entry-map-affordance" data-intent="map.open"'
        ' aria-label="Open the system map"'
        " onclick=\"overlayHost.mount('map')\">System map</button>"
        if entry_state == "no_vault"
        else ""
    )
    detail = _error_detail(error)
    error_kind = str(detail.get("error") or "")
    if error_kind == "note_not_found":
        note_path = _e(detail.get("note_path") or "")
        message = _e(detail.get("message") or "No note exists for the requested note_path")
        return f"""
  <div class="error-state note-not-found-state" data-testid="workspace-note-not-found-state">
    <span class="error-label">Note not found</span>
    <span class="error-message">
      <code>{note_path}</code> — {message}. Check the runtime-relative path and load again.
    </span>
  </div>"""
    # Application-level runtime-unavailable contract error: the runtime returns
    # HTTP 503 with ``{"detail":{"error":"runtime_unavailable",...}}`` when the
    # orientation aggregate itself is unreachable
    # (WORKSPACE_ORIENTATION_CONTRACT.md §Runtime Unavailable). Server declares,
    # UI renders: classify from the declared ``error`` kind (or a bare HTTP 503)
    # and render the designed "Vault unreachable" entry state instead of dumping
    # the raw JSON body or showing a vault-setup form the runtime cannot process
    # (#2123; edge-states.md §No vault — runtime unreachable; open-questions
    # Q23 — provenance behind a Details disclosure; Q24 — suppress the form).
    lowered = error.lower()
    contract_unavailable = error_kind == "runtime_unavailable" or lowered.startswith("http 503")
    runtime_unavailable = any(
        marker in lowered
        for marker in ("connection refused", "timed out", "timeout", "network")
    )
    # #2124 — same 503/transport shape, two causes. From a remote page origin
    # the likely cause is "wrong device" (the browser hit the API's localhost
    # bind, unreachable from that device), so render the distinct remote-access
    # state instead. A localhost (or unknown) origin keeps the unchanged states
    # below: #2123's "Vault unreachable" for the 503 contract error, and the
    # pre-existing generic/transport card otherwise.
    if (contract_unavailable or runtime_unavailable) and _is_remote_page_origin(
        page_origin_hostname
    ):
        return _render_wrong_device_state(retry_html=retry_html)
    if contract_unavailable:
        return _render_vault_unreachable_state(error, retry_html=retry_html)
    runtime_label = "Runtime unavailable" if runtime_unavailable else "API Error"
    runtime_marker = (
        '<span data-testid="workspace-runtime-unavailable-state"></span>'
        if runtime_unavailable
        else ""
    )
    return f"""
  <div class="error-state" data-testid="workspace-error-state" data-error-kind="{'runtime-unavailable' if runtime_unavailable else 'api-error'}">
    <span class="error-label">{runtime_label}</span>
    {runtime_marker}
    <span class="error-message"><code>{_e(error)}</code></span>{retry_html}
  </div>"""


def _is_runtime_unreachable(error: str) -> bool:
    """True when ``error`` denotes the runtime itself being unreachable.

    Covers both the application-level ``runtime_unavailable`` / bare HTTP 503
    contract error and a transport-level failure (connection refused / timeout /
    network). This is the single truth used to (a) render the designed
    "Vault unreachable" / "wrong device" entry state in ``_render_error_section``
    and (b) suppress the vault-setup form in ``render_index_html`` — the form is
    a false affordance the runtime cannot process while unreachable
    (#2123 AC1; open-questions Q24). Mirrors the classification in
    ``_render_error_section`` so the banner and the form stay in lockstep.
    """
    if not error:
        return False
    detail = _error_detail(error)
    error_kind = str(detail.get("error") or "")
    lowered = error.lower()
    if error_kind == "runtime_unavailable" or lowered.startswith("http 503"):
        return True
    # The transport-substring fallback applies ONLY to unstructured error
    # strings (e.g. "[Errno 61] Connection refused", which carry no JSON detail).
    # A structured error with a declared kind is not a transport failure, so it
    # must not be reclassified as unreachable just because its user data happens
    # to contain a transport word — e.g. a note_not_found payload for
    # "Network/Runbook.md" would otherwise hit the "network" marker and wrongly
    # strip the still-usable vault-setup form. This mirrors _render_error_section,
    # which resolves the declared error kind before any transport classification.
    if error_kind:
        return False
    return any(
        marker in lowered
        for marker in ("connection refused", "timed out", "timeout", "network")
    )


def _render_vault_unreachable_state(error: str, *, retry_html: str) -> str:
    """Render the designed "Vault unreachable" entry state (#2123).

    Used when the runtime aggregate declares itself unreachable via the HTTP 503
    ``runtime_unavailable`` contract error. The headline is human-readable; the
    raw provenance/trace belongs in an expandable Details disclosure, never the
    headline (open-questions Q23). The vault-setup form is suppressed because the
    runtime cannot process it (Q24). The vault — durable truth — is unaffected;
    the companion is only a client.

    Restyle (#2173): quiet-register copy — "The runtime is unreachable. Nothing
    was lost." — replaces the original alarm heading to align with the no_vault
    threshold treatment (design_handoff/2026-06-19-cold-start-threshold §no_vault
    render contract CORRECTION + restyle). Retry (entry.retry) and System map
    (map.open) are kept; no Find or Jot verb (capture has no honest offline landing).
    Alarm color stays confined to this state.

    Provenance line is fixed by the design handoff:
    ``runtime_unavailable · /api/companion/orientation · 503``.
    """
    return f"""
  <div class="error-state vault-unreachable-state"
    data-testid="workspace-vault-unreachable-state"
    data-error-kind="runtime-unavailable">
    <span class="error-glyph" aria-hidden="true">⚠</span>
    <div class="vault-unreachable-body">
      <span class="error-label vault-unreachable-heading">The runtime is unreachable. Nothing was lost.</span>
      <p class="vault-unreachable-reassurance">
        Your vault — the durable source of truth — is unaffected. The companion
        is only a client.
      </p>
      <div class="vault-unreachable-affordances">{retry_html}</div>
      <details class="error-details" data-testid="workspace-error-details">
        <summary>Details</summary>
        <code class="error-provenance"
          data-testid="workspace-error-provenance">runtime_unavailable · /api/companion/orientation · 503</code>
      </details>
    </div>
  </div>"""


def _render_wrong_device_state(*, retry_html: str) -> str:
    """Render the "different device / API not exposed" entry state (#2124).

    The page was loaded from a remote (non-localhost) origin, so the unreachable
    runtime is most likely a *wrong-device* situation: the browser's API origin
    is the runtime's localhost bind, which is not reachable from this device.
    This is a distinct human problem from a genuinely-down runtime and needs
    distinct guidance — remote-access help plus a local-only continuation —
    while (like #2123) suppressing the vault-setup form the runtime cannot
    process. The remote-vs-local signal is the page origin only; the runtime
    class is still server-declared (open-questions Q21).
    """
    return f"""
  <div class="error-state wrong-device-state"
    data-testid="workspace-wrong-device-state"
    data-error-kind="runtime-unavailable">
    <span class="error-glyph" aria-hidden="true">⚠</span>
    <div class="wrong-device-body">
      <span class="error-label wrong-device-heading">Companion runtime is on a different device</span>
      <p class="wrong-device-reassurance">
        This page loaded over the network, but the companion runtime's API is
        only exposed on its own machine by default, so this browser can't reach
        it from here. Your vault — the durable source of truth — is unaffected.
      </p>
      <div class="wrong-device-affordances">{retry_html}</div>
      <p class="wrong-device-guidance" data-testid="workspace-wrong-device-guidance">
        To use the companion from this device, expose the runtime API on the
        network (or open it on the machine running the runtime).
      </p>
      <a class="wrong-device-local-continuation"
        data-testid="workspace-wrong-device-local-continuation"
        href="/" data-intent="entry.retry">Continue on the runtime's own device</a>
    </div>
  </div>"""


def _orientation_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _orientation_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _orientation_str(value: object, fallback: str = "") -> str:
    if value is None:
        return fallback
    text = str(value)
    return text if text else fallback


def _same_orientation_display_text(left: str, right: str) -> bool:
    return " ".join(left.split()) == " ".join(right.split())


def _orientation_artifact_link(
    artifact_ref: object,
    *,
    testid: str,
    suppress_when_text: str = "",
) -> str:
    artifact = _orientation_dict(artifact_ref)
    note_path = _orientation_str(artifact.get("note_path") or artifact.get("logical_ref"))
    title = _orientation_str(artifact.get("title"), note_path or "Artifact")
    artifact_id = _orientation_str(artifact.get("artifact_id") or artifact.get("artifact_uuid"))
    link_text = (
        "Open artifact"
        if suppress_when_text and _same_orientation_display_text(title, suppress_when_text)
        else title
    )
    if not note_path:
        return (
            f'<span class="orientation-artifact-link orientation-artifact-link--empty" '
            f'data-testid="{testid}" data-artifact-id="{_e(artifact_id)}">'
            f"{_e(link_text)}</span>"
        )
    href = "/workspace?note_path=" + quote(note_path, safe="")
    return (
        f'<a class="orientation-artifact-link" data-testid="{testid}" '
        f'data-note-path="{_e(note_path)}" data-artifact-id="{_e(artifact_id)}" '
        f'href="{_e(href)}">{_e(link_text)}</a>'
    )


def _orientation_provenance(item: object, *, testid: str) -> str:
    data = _orientation_dict(item)
    source_ref = _orientation_dict(data.get("source_ref"))
    authority_role = _orientation_str(data.get("authority_role"), "unknown")
    source_kind = _orientation_str(source_ref.get("kind"), "unknown")
    source_label = _orientation_str(source_ref.get("label"), source_kind)
    source_ref_value = _orientation_str(source_ref.get("ref") or source_ref.get("trace_id"))
    return (
        f'<div class="orientation-provenance" data-testid="{testid}" '
        f'data-authority-role="{_e(authority_role)}" '
        f'data-source-kind="{_e(source_kind)}" '
        f'data-source-ref="{_e(source_ref_value)}">'
        f"{_e(authority_role)} · {_e(source_label)}</div>"
    )


def _orientation_degraded_reasons(orientation: dict) -> list[str]:
    guards = _orientation_dict(orientation.get("guards"))
    meta = _orientation_dict(orientation.get("meta"))
    raw = _orientation_list(guards.get("reasons")) or _orientation_list(
        meta.get("degraded_reasons")
    )
    return [_orientation_str(reason) for reason in raw if _orientation_str(reason)]


def _orientation_unavailable_frame(error: str) -> dict:
    """Fallback orientation frame used when only vault browsing is available."""
    return {
        "scope": {
            "kind": "workspace",
            "vault_id": "unknown",
            "channel": "unknown",
        },
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "freshness": "partial",
            "as_of": "",
            "trace_id": "orientation-unavailable",
            "degraded_reasons": ["orientation_unavailable"],
        },
        "leave_point": None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "unknown",
            "authority_role": "unavailable",
            "source_ref": {
                "kind": "runtime_error",
                "ref": "api.companion.orientation",
                "label": error or "orientation endpoint unavailable",
            },
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded",
            "degraded": True,
            "reasons": ["orientation_unavailable"],
            "authority_role": "unavailable",
            "source_ref": {
                "kind": "runtime_error",
                "ref": "api.companion.orientation",
                "label": error or "orientation endpoint unavailable",
            },
        },
        "mutation_intents": [],
    }


def _render_orientation_leave_point(leave_point: object) -> str:
    leave = _orientation_dict(leave_point)
    if not leave:
        return """
        <section class="orientation-section" data-testid="workspace-orientation-leave-point">
          <div class="orientation-section-kicker">Leave point</div>
          <p class="orientation-empty">No derived leave point is available yet.</p>
        </section>"""
    artifact = _orientation_dict(leave.get("artifact_ref"))
    status = _orientation_str(leave.get("status"))
    label = _orientation_str(
        leave.get("label") or artifact.get("title"),
        "Derived leave point",
    )
    last_seen = _orientation_str(
        leave.get("last_interaction_at") or leave.get("captured_at"),
        "time unknown",
    )
    session_id = _orientation_str(leave.get("last_session_id"))
    session_html = (
        f'<span class="orientation-muted">session {_e(session_id)}</span>'
        if session_id
        else ""
    )
    return f"""
        <section class="orientation-section orientation-section--primary"
          data-testid="workspace-orientation-leave-point"
          data-leave-point-kind="{_e(_orientation_str(leave.get("kind") or status, "derived_only"))}">
          <div class="orientation-section-kicker">Leave point</div>
          <h1 class="orientation-title">{_e(label)}</h1>
          <div class="orientation-artifact-row">
            {_orientation_artifact_link(leave.get("artifact_ref"), testid="workspace-orientation-leave-link", suppress_when_text=label)}
          </div>
          <div class="orientation-meta-row">
            <span>Last signal: {_e(last_seen)}</span>
            {session_html}
          </div>
          {_orientation_provenance(leave, testid="workspace-orientation-leave-provenance")}
        </section>"""


# Default visible items per collection in one orientation moment (SEP-02;
# SYSTEM_ENTRY_POINT_SPEC.md §Resolved Q5: scarce displayed subset, matching
# the shipped resurfacing-card default #1680). Deliberate expansion may reveal
# more, never above the server caps (WORKSPACE_ORIENTATION_CONTRACT.md
# §Bounded Collections: 8/8/5).
_ORIENTATION_DISPLAY_BUDGET = 3


def _orientation_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _orientation_capped_items(
    items: object, *, meta: object | None, cap_key: str
) -> tuple[list[dict], int]:
    """Server-capped collection items plus the declared cap.

    The UI never widens a collection past the server-declared cap; items
    beyond the cap are not rendered at all (the cap is a transport ceiling).
    """
    caps = _orientation_dict(_orientation_dict(meta).get("caps"))
    server_cap = _orientation_int(caps.get(cap_key))
    collected = [_orientation_dict(item) for item in _orientation_list(items)]
    capped = collected[:server_cap] if server_cap else collected
    return capped, server_cap


def _render_orientation_open_loops(open_loops: object, *, meta: object | None = None) -> str:
    capped, server_cap = _orientation_capped_items(
        open_loops, meta=meta, cap_key="open_loops"
    )

    def _row(loop: dict, *, testid: str, visible_default: bool) -> str:
        label = _orientation_str(loop.get("label"), "Open loop")
        return f"""
            <article class="orientation-item" data-testid="{testid}"
              data-visible-by-default="{str(visible_default).lower()}"
              data-loop-status="{_e(_orientation_str(loop.get("status"), "unknown"))}"
              data-handoff-hint="{_e(_orientation_str(loop.get("handoff_hint"), "none"))}">
              <div class="orientation-item-main">
                <h3>{_e(label)}</h3>
                {_orientation_artifact_link(loop.get("artifact_ref"), testid="workspace-orientation-open-loop-link", suppress_when_text=label)}
              </div>
              <div class="orientation-badges">
                <span>{_e(_orientation_str(loop.get("status"), "unknown"))}</span>
                <span>handoff: {_e(_orientation_str(loop.get("handoff_hint"), "none"))}</span>
              </div>
              {_orientation_provenance(loop, testid="workspace-orientation-open-loop-provenance")}
            </article>"""

    visible = capped[: _ORIENTATION_DISPLAY_BUDGET]
    overflow = capped[_ORIENTATION_DISPLAY_BUDGET :]
    rows = [
        _row(loop, testid="workspace-orientation-open-loop", visible_default=True)
        for loop in visible
    ]
    overflow_html = ""
    if overflow:
        overflow_rows = "".join(
            _row(
                loop,
                testid="workspace-orientation-open-loop-overflow",
                visible_default=False,
            )
            for loop in overflow
        )
        overflow_html = f"""
          <details class="orientation-budget-expand"
            data-testid="workspace-orientation-open-loops-expand"
            data-server-cap="{server_cap or len(capped)}"
            data-overflow-count="{len(overflow)}">
            <summary>Show {len(overflow)} more open loop(s)</summary>
            {overflow_rows}
          </details>"""
    body = "".join(rows) if rows else '<p class="orientation-empty">No open loops declared.</p>'
    return f"""
        <section class="orientation-section" id="workspace-orientation-open-loops"
          data-testid="workspace-orientation-open-loops"
          data-display-default-budget="{_ORIENTATION_DISPLAY_BUDGET}"
          data-display-overflow-count="{len(overflow)}">
          <div class="orientation-section-header">
            <div class="orientation-section-kicker">Open loops</div>
            <span class="orientation-count">{len(capped)}</span>
          </div>
          {body}
          {overflow_html}
        </section>"""


def _render_orientation_notable_changes(changes: object, *, meta: object | None = None) -> str:
    capped, server_cap = _orientation_capped_items(
        changes, meta=meta, cap_key="notable_changes"
    )

    def _row(change: dict, *, testid: str, visible_default: bool) -> str:
        label = _orientation_str(change.get("label"), "Notable change")
        summary = _orientation_str(change.get("summary"))
        changed_at = _orientation_str(change.get("changed_at"), "time unknown")
        return f"""
            <article class="orientation-item" data-testid="{testid}"
              data-visible-by-default="{str(visible_default).lower()}">
              <div class="orientation-item-main">
                <h3>{_e(label)}</h3>
                <p>{_e(summary)}</p>
                {_orientation_artifact_link(change.get("artifact_ref"), testid="workspace-orientation-notable-change-link", suppress_when_text=label)}
              </div>
              <div class="orientation-meta-row">Changed: {_e(changed_at)}</div>
              {_orientation_provenance(change, testid="workspace-orientation-notable-change-provenance")}
            </article>"""

    visible = capped[: _ORIENTATION_DISPLAY_BUDGET]
    overflow = capped[_ORIENTATION_DISPLAY_BUDGET :]
    rows = [
        _row(change, testid="workspace-orientation-notable-change", visible_default=True)
        for change in visible
    ]
    overflow_html = ""
    if overflow:
        overflow_rows = "".join(
            _row(
                change,
                testid="workspace-orientation-notable-change-overflow",
                visible_default=False,
            )
            for change in overflow
        )
        overflow_html = f"""
          <details class="orientation-budget-expand"
            data-testid="workspace-orientation-notable-changes-expand"
            data-server-cap="{server_cap or len(capped)}"
            data-overflow-count="{len(overflow)}">
            <summary>Show {len(overflow)} more notable change(s)</summary>
            {overflow_rows}
          </details>"""
    body = "".join(rows) if rows else '<p class="orientation-empty">No notable changes declared.</p>'
    return f"""
        <section class="orientation-section" id="workspace-orientation-notable-changes"
          data-testid="workspace-orientation-notable-changes"
          data-display-default-budget="{_ORIENTATION_DISPLAY_BUDGET}"
          data-display-overflow-count="{len(overflow)}">
          <div class="orientation-section-header">
            <div class="orientation-section-kicker">Notable changes</div>
            <span class="orientation-count">{len(capped)}</span>
          </div>
          {body}
          {overflow_html}
        </section>"""


def _render_orientation_resurface(
    resurface: object,
    *,
    meta: object | None = None,
    degraded_reasons: list[str] | None = None,
) -> str:
    payload = _orientation_dict(resurface)
    meta_payload = _orientation_dict(meta)
    caps = _orientation_dict(meta_payload.get("caps"))
    server_cap = int(caps.get("resurface_candidates") or 0)
    default_budget = _ORIENTATION_DISPLAY_BUDGET
    reasons = degraded_reasons or []
    posture = "degraded" if reasons else "read-only"
    reason_html = "".join(
        f'<span class="orientation-reason">{_e(reason)}</span>' for reason in reasons
    )

    def _candidate_row(candidate: dict, *, testid: str, visible_default: bool) -> str:
        label = _orientation_str(candidate.get("label"), "Resurface candidate")
        signals = "".join(
            f'<span class="orientation-signal">{_e(_orientation_str(signal))}</span>'
            for signal in _orientation_list(candidate.get("signal_labels"))
        )
        return f"""
            <article class="orientation-item"
              data-testid="{testid}"
              data-visible-by-default="{str(visible_default).lower()}">
              <div class="orientation-item-main">
                <h3>{_e(label)}</h3>
                <p class="orientation-why" data-testid="workspace-orientation-resurface-why-now">
                  {_e(_orientation_str(candidate.get("why_now")))}
                </p>
                {_orientation_artifact_link(candidate.get("artifact_ref"), testid="workspace-orientation-resurface-link", suppress_when_text=label)}
              </div>
              <div class="orientation-signals">{signals}</div>
              {_orientation_provenance(candidate, testid="workspace-orientation-resurface-provenance")}
            </article>"""

    candidates = [_orientation_dict(item) for item in _orientation_list(payload.get("candidates"))]
    capped_candidates = candidates[:server_cap] if server_cap else candidates
    default_candidates = capped_candidates[:default_budget]
    overflow_candidates = capped_candidates[default_budget:]
    rows: list[str] = []
    for candidate in default_candidates:
        rows.append(
            _candidate_row(
                candidate,
                testid="workspace-orientation-resurface-candidate",
                visible_default=True,
            )
        )
    overflow_html = ""
    if overflow_candidates:
        overflow_rows = "".join(
            _candidate_row(
                candidate,
                testid="workspace-orientation-resurface-overflow-candidate",
                visible_default=False,
            )
            for candidate in overflow_candidates
        )
        overflow_html = f"""
          <details class="orientation-resurface-expand"
            data-testid="workspace-orientation-resurface-expand"
            data-server-cap="{server_cap or len(capped_candidates)}"
            data-overflow-count="{len(overflow_candidates)}">
            <summary>Show {len(overflow_candidates)} more resurfacing card(s)</summary>
            {overflow_rows}
          </details>"""
    body = "".join(rows) if rows else '<p class="orientation-empty">No resurface candidates declared.</p>'
    return f"""
        <section class="orientation-section"
          data-testid="workspace-orientation-resurface"
          data-resurface-posture="{posture}"
          data-resurface-default-budget="{default_budget}"
          data-resurface-overflow-count="{len(overflow_candidates)}"
          data-notification="false"
          data-persistence-backed="false"
          data-authority="read-only-projection">
          <div class="orientation-section-header">
            <div class="orientation-section-kicker">Resurface</div>
            <span class="orientation-count">{len(capped_candidates)}</span>
          </div>
          {reason_html}
          {body}
          {overflow_html}
        </section>"""


def _render_orientation_governance(governance: object) -> str:
    payload = _orientation_dict(governance)
    pending_proposals = _orientation_str(payload.get("pending_proposal_count"), "0")
    pending_receipts = _orientation_str(payload.get("pending_receipt_count"), "0")
    latest_outcome = _orientation_str(payload.get("latest_receipt_outcome"), "none")
    return f"""
        <section class="orientation-section orientation-governance"
          data-testid="workspace-orientation-governance">
          <div class="orientation-section-kicker">Governance</div>
          <div class="orientation-governance-grid">
            <div><span>{_e(pending_proposals)}</span><small>pending proposals</small></div>
            <div><span>{_e(pending_receipts)}</span><small>pending receipts</small></div>
            <div><span>{_e(latest_outcome)}</span><small>latest receipt outcome</small></div>
          </div>
          {_orientation_provenance(payload, testid="workspace-orientation-governance-provenance")}
        </section>"""


# --------------------------------------------------------------------------
# Re-entry treatments per latency-ladder shape (#1784, SEP-02).
#
# The shape arrives from SEP-01's server-side resolution (entry_state.py);
# nothing here recomputes the gap. Treatments per
# SYSTEM_ENTRY_POINT_SPEC.md §Resolved Q5 / §Resolved Q9 and
# docs/SYSTEM_ENTRY_POINT/REENTRY_ORIENTATION_TREATMENT.md:
#
# - full_mist / long_mist → four-fixed-questions card (data-region=
#   "reentry-card"), counts not enumerations, server-declared traj-state pill;
# - long_mist → + delta strip (data-region="delta-strip") and right-margin
#   whisper column (suppressed narrow, collapsing into the card);
# - soft_mist → no card; caret-echo cue + one peripheral "where you stopped"
#   line only;
# - thread_fade → no card, no line; fractional rail fade only;
# - no_mist / cold_start / no_vault → no re-entry overlay of any kind.
# --------------------------------------------------------------------------

# Leave-point statuses presented as guard-held qualified resume (spec Q9).
_REENTRY_STALE_CAUSES: dict[str, str] = {
    "stale": "Source changed since this was captured.",
    "degraded": "Source resolution degraded since this was captured.",
    "artifact_missing": "The artifact this leave point referenced is missing.",
}

# Fraction the conversation/rail pane keeps during thread fade (90s–15m):
# the pane fades a fraction; the trajectory stays implicit.
_REENTRY_RAIL_FADE = "0.85"


def _reentry_caret_echo() -> str:
    """Caret-echo cue at the momentum stop point (residual ambient layer)."""
    return (
        '<span class="reentry-caret-echo" data-testid="reentry-caret-echo"'
        ' aria-hidden="true"></span>'
    )


def _reentry_counts(orientation: dict) -> dict[str, int]:
    """Server-capped counts for counts-not-enumerations rendering."""
    meta = orientation.get("meta")
    loops, _ = _orientation_capped_items(
        orientation.get("open_loops"), meta=meta, cap_key="open_loops"
    )
    changes, _ = _orientation_capped_items(
        orientation.get("notable_changes"), meta=meta, cap_key="notable_changes"
    )
    resurface, _ = _orientation_capped_items(
        _orientation_dict(orientation.get("resurface")).get("candidates"),
        meta=meta,
        cap_key="resurface_candidates",
    )
    governance = _orientation_dict(orientation.get("governance"))
    memory = _orientation_dict(orientation.get("memory"))
    return {
        "open_loops": len(loops),
        "notable_changes": len(changes),
        "resurface_candidates": len(resurface),
        "staged": _orientation_int(governance.get("pending_proposal_count")),
        "memory_candidates": _orientation_int(memory.get("pending_candidate_count")),
    }


def _reentry_leave_label(leave: dict) -> str:
    artifact = _orientation_dict(leave.get("artifact_ref"))
    return _orientation_str(
        leave.get("label") or artifact.get("title"), "Derived leave point"
    )


def _reentry_doing_label(leave: dict) -> str:
    """Human-readable heading for the re-entry 'doing' question and whisper column.

    When the runtime declares an explicit ``label`` on the leave_point, use it
    verbatim.  When absent (v1 contract), falling through to ``artifact.title``
    would render the 'doing' heading identically to the 'stopped' artifact-link
    text (issue #2241).  Return a distinct generic cue instead so the card
    never shows the same string in both slots.
    """
    declared = _orientation_str(leave.get("label"))
    return declared if declared else "Where you left off"


def _reentry_traj_state(leave: dict) -> str:
    """Server-declared trajectory state for the re-entry card pill.

    Rendered as supplied when the payload declares one; otherwise the server
    render derives it from the same declared signals as the shape: the card
    renders only for full/long-mist gaps (2h–14d), which the
    CONTINUITY_AND_DECAY.md trajectory table classifies as dormant. Never
    re-derived client-side.
    """
    declared = _orientation_str(
        leave.get("trajectory_state") or leave.get("traj_state")
    )
    if declared in ("warm", "dormant"):
        return declared
    return "dormant"


def _reentry_resume_affordance(leave: dict, *, stale: bool) -> str:
    """Resume affordance; guard-held and qualified when the leave point is stale.

    Per BLOCKED_AND_STALE_STATE_SPEC.md the guard-held state names the cause,
    states that nothing was mutated, and offers a path forward — never a
    generic error, and never a silent resume into a missing artifact.
    """
    artifact = _orientation_dict(leave.get("artifact_ref"))
    note_path = _orientation_str(artifact.get("note_path") or artifact.get("logical_ref"))
    href = "/workspace?note_path=" + quote(note_path, safe="") if note_path else ""
    status = _orientation_str(leave.get("status"))

    if not stale:
        if not href:
            return ""
        return (
            f'<a class="reentry-resume" data-testid="reentry-resume" '
            f'data-intent="entry.resume" href="{_e(href)}">Resume — jump to caret</a>'
        )

    cause = _REENTRY_STALE_CAUSES.get(status, _REENTRY_STALE_CAUSES["stale"])
    if status == "artifact_missing" or not href:
        # Never silently resume into a missing artifact: the path forward
        # re-enters through the Vault Browser instead.
        forward = (
            '<a class="reentry-resume-forward" data-testid="reentry-resume-reenter" '
            'data-intent="vault.open" href="#workspace-orientation-vault-entry">'
            "Re-enter through the vault</a>"
        )
    else:
        forward = (
            f'<a class="reentry-resume-forward" data-testid="reentry-resume" '
            f'data-intent="entry.resume" data-resume-qualified="true" '
            f'href="{_e(href)}">Open the current artifact state</a>'
        )
    return f"""
            <div class="reentry-resume-guard" data-testid="reentry-resume-guard"
              data-guard-held="true" data-guard-cause="{_e(status or "stale")}">
              <span class="reentry-guard-copy">{_e(cause)} Nothing was mutated.</span>
              {forward}
            </div>"""


def _render_reentry_delta_strip(orientation: dict) -> str:
    """Long-mist delta strip from notable_changes (display budget 3)."""
    capped, server_cap = _orientation_capped_items(
        orientation.get("notable_changes"),
        meta=orientation.get("meta"),
        cap_key="notable_changes",
    )
    visible = capped[: _ORIENTATION_DISPLAY_BUDGET]
    remaining = len(capped) - len(visible)
    items = "".join(
        f'<span class="reentry-delta-item" data-testid="reentry-delta-item">'
        f'<span class="reentry-delta-dot" aria-hidden="true"></span>'
        f"{_e(_orientation_str(change.get('label'), 'Notable change'))}</span>"
        for change in visible
    )
    more = (
        f'<span class="reentry-delta-more" data-testid="reentry-delta-more">'
        f'+{remaining} more under <a href="#workspace-orientation-notable-changes">'
        f"notable changes</a></span>"
        if remaining
        else ""
    )
    return (
        f'<div class="reentry-delta-strip" data-region="delta-strip" '
        f'data-testid="reentry-delta-strip" '
        f'data-display-default-budget="{_ORIENTATION_DISPLAY_BUDGET}" '
        f'data-server-cap="{server_cap or len(capped)}">{items}{more}</div>'
    )


def _render_reentry_card(orientation: dict, *, shape: str, stale: bool) -> str:
    """The four fixed re-entry questions (full_mist / long_mist).

    Shapes fixed per CONTINUITY_AND_DECAY.md §The Four Re-entry Questions;
    unresolved and changed render as counts with a deliberate inspect
    affordance, never enumerations (spec §Resolved Q5). The inspect affordance
    emits ``memory.open`` and mounts the memory candidate review drawer on the
    overlay host (#1793, SEP-09b); without JS it gracefully falls back to the
    open-loops orientation section.
    """
    leave = _orientation_dict(orientation.get("leave_point"))
    counts = _reentry_counts(orientation)
    leave_label = _reentry_leave_label(leave)
    doing_label = _reentry_doing_label(leave)
    traj_state = _reentry_traj_state(leave)
    delta_strip = _render_reentry_delta_strip(orientation) if shape == "long_mist" else ""
    if _orientation_str(leave.get("status")) == "artifact_missing":
        # Never a silent path into a missing artifact, not even from the
        # stop-point line — the guard-held affordance owns the way forward.
        artifact = _orientation_dict(leave.get("artifact_ref"))
        artifact_link = (
            f'<span class="orientation-artifact-link orientation-artifact-link--empty" '
            f'data-testid="reentry-stop-link">'
            f"{_e(_orientation_str(artifact.get('title'), 'Artifact'))}</span>"
        )
    else:
        # Pass doing_label (not leave_label) as the suppress guard: when the
        # runtime supplied an explicit label, doing_label == leave_label and the
        # artifact link is suppressed to "Open artifact" when they match.  When
        # the label is absent, doing_label is "Where you left off" which will
        # never match the artifact title, so the link renders the title instead
        # (issue #2241 — heading and body must not be the same string).
        artifact_link = _orientation_artifact_link(
            leave.get("artifact_ref"),
            testid="reentry-stop-link",
            suppress_when_text=doing_label,
        )
    inspect_onclick = "if (window.overlayHost) { overlayHost.mount('memory'); return false; }"
    return f"""
    <section class="reentry-card" data-region="reentry-card" data-testid="reentry-card"
      data-traj-state="{_e(traj_state)}" data-reentry-treatment="{_e(shape)}"
      data-read-only="true">
      <div class="reentry-head">
        <span class="orientation-section-kicker">Re-entry</span>
        <span class="reentry-traj-pill" data-testid="reentry-traj-pill">{_e(traj_state)}</span>
        {guidance_toggle_markup('reentry')}
      </div>
      {guidance_callout_markup('reentry')}
      <ol class="reentry-questions">
        <li class="reentry-q" data-reentry-question="doing">
          <span class="reentry-q-label">What was I doing</span>
          <span class="reentry-q-body">{_e(doing_label)}</span>
        </li>
        <li class="reentry-q" data-reentry-question="stopped">
          <span class="reentry-q-label">Where did momentum stop</span>
          <span class="reentry-q-body">{artifact_link}{_reentry_caret_echo()}</span>
        </li>
        <li class="reentry-q" data-reentry-question="unresolved">
          <span class="reentry-q-label">What remains unresolved</span>
          <span class="reentry-q-body" data-testid="reentry-unresolved-counts">
            {counts["open_loops"]} open loops · {counts["staged"]} staged
            · {counts["memory_candidates"]} memory candidates
            <a class="reentry-inspect" data-testid="reentry-inspect"
              data-intent="memory.open"
              data-memory-candidate-count="{counts["memory_candidates"]}"
              href="#workspace-orientation-open-loops"
              onclick="{inspect_onclick}">inspect</a>
          </span>
        </li>
        <li class="reentry-q" data-reentry-question="changed">
          <span class="reentry-q-label">What changed since</span>
          <span class="reentry-q-body" data-testid="reentry-changed-count">
            {counts["notable_changes"]} changes while you were away
          </span>
        </li>
      </ol>
      {delta_strip}
      <div class="reentry-actions">
        {_reentry_resume_affordance(leave, stale=stale)}
        <button class="reentry-dismiss" type="button" data-testid="reentry-dismiss"
          data-intent="entry.dismiss" data-unresolved-tension="preserved"
          onclick="entryDismiss(this)">Start fresh</button>
      </div>
    </section>"""


def _entry_dismiss_script() -> str:
    return """
  <script>
  function entryDismiss(control) {
    var card = control && control.closest('[data-region=reentry-card]');
    if (card) { card.remove(); }
    var siblingCues = document.querySelectorAll('[data-region=delta-strip], [data-region=whisper-column]');
    for (var i = 0; i < siblingCues.length; i++) {
      siblingCues[i].remove();
    }
    if (document.body) {
      document.body.dataset.entryState = 'shell_active';
      document.body.setAttribute('data-entry-state', 'shell_active');
    }
  }
  </script>"""


def _render_reentry_whisper_column(orientation: dict) -> str:
    """Right-margin whisper column (long_mist): four named items.

    Suppressed in narrow mode by the page stylesheet — the card carries the
    same four answers, so the column collapses into the card.
    """
    leave = _orientation_dict(orientation.get("leave_point"))
    counts = _reentry_counts(orientation)
    return f"""
  <aside class="reentry-whisper-col" data-region="whisper-column"
    data-testid="reentry-whisper-column" data-narrow-mode="suppressed"
    aria-hidden="true">
    <div class="reentry-whisper" data-whisper-item="doing">
      <span class="reentry-whisper-label">doing</span>
      <span class="reentry-whisper-text">{_e(_reentry_doing_label(leave))}</span>
    </div>
    <div class="reentry-whisper" data-whisper-item="unresolved">
      <span class="reentry-whisper-label">unresolved</span>
      <span class="reentry-whisper-text">{counts["open_loops"]} open loops · {counts["staged"]} staged</span>
    </div>
    <div class="reentry-whisper" data-whisper-item="changed">
      <span class="reentry-whisper-label">changed</span>
      <span class="reentry-whisper-text">{counts["notable_changes"]} deltas since you left</span>
    </div>
    <div class="reentry-whisper" data-whisper-item="resurfaced">
      <span class="reentry-whisper-label">resurfaced</span>
      <span class="reentry-whisper-text">{counts["resurface_candidates"]} why-now candidates</span>
    </div>
  </aside>"""


def _render_reentry_peripheral_line(orientation: dict) -> str:
    """Soft-mist residual cue: one peripheral "where you stopped" line.

    Per spec §Resolved Q5 the latency ladder's one-line sentence is a
    peripheral cue — no card, no metadata, never centered on the document.
    """
    leave = _orientation_dict(orientation.get("leave_point"))
    status = _orientation_str(leave.get("status"))
    label = _reentry_leave_label(leave)
    artifact = _orientation_dict(leave.get("artifact_ref"))
    note_path = _orientation_str(artifact.get("note_path") or artifact.get("logical_ref"))
    if status == "present" and note_path:
        href = "/workspace?note_path=" + quote(note_path, safe="")
        target = (
            f'<a class="orientation-artifact-link" '
            f'data-testid="reentry-peripheral-stop-link" '
            f'data-intent="entry.resume" data-note-path="{_e(note_path)}" '
            f'href="{_e(href)}">{_e(label)}</a>'
        )
    else:
        # A non-current leave point never gets a silent link into a moved or
        # missing artifact from the ambient cue.
        target = _e(label)
    return (
        f'<p class="reentry-peripheral-line" data-region="reentry-peripheral-line" '
        f'data-testid="reentry-peripheral-line">Where you stopped: '
        f"{target}{_reentry_caret_echo()}</p>"
    )


def _render_orientation_vault_entry(
    vault_browser: Optional[dict],
    *,
    error: str = "",
    resolved_vault_id: str | None = None,
) -> str:
    """Render a concrete vault entrypoint on the no-active-note surface.

    Re-entry/orientation is derived runtime context. The root workspace must
    still provide a direct path into the human vault even when the orientation
    frame is sparse, stale, or unhelpful.

    `resolved_vault_id` — when provided (cold_start path), the card uses the
    scope-resolved vault name so it matches the cold_start chip (#2240-b).
    """
    if vault_browser is None and not error:
        return ""

    payload = vault_browser or {}
    notes = [
        dict(note)
        for note in list(payload.get("notes") or [])
        if isinstance(note, dict)
    ]
    identity = _orientation_dict(payload.get("vault_identity"))
    # Use the caller-supplied resolved vault id (from scope.vault_id) when
    # available so the card identity matches the cold_start chip (#2240-b).
    _vault_name = resolved_vault_id or str(identity.get("vault_name") or "unresolved")
    browser_html = _render_vault_browser(
        note_path="",
        notes=notes,
        query=str(payload.get("query") or ""),
        total_notes=int(payload.get("total_notes") or 0),
        filtered_notes=int(payload.get("filtered_notes") or 0),
        error=error,
        read_only=bool(payload.get("read_only", True)),
        identity_available=bool(payload.get("identity_available", False)),
        vault_name=_vault_name,
        vault_channel=str(identity.get("channel") or "unknown"),
        vault_provenance=str(identity.get("provenance") or "unresolved"),
        active_filters=dict(payload.get("active_filters") or {}),
        pagination=dict(payload.get("pagination") or {}),
    )
    return f"""
        <section class="orientation-section orientation-vault-entry"
          id="workspace-orientation-vault-entry"
          data-testid="workspace-orientation-vault-entry"
          data-read-only="true">
          <div class="orientation-section-header">
            <div>
              <div class="orientation-section-kicker">Vault</div>
              <h2 class="orientation-subheading">Browse notes</h2>
            </div>
            <a class="orientation-vault-open" href="/?diagnostics=0">Root</a>
          </div>
          {browser_html}
        </section>"""


def _render_orientation_index_html(
    *,
    api_base_url: str,
    note_path: str,
    orientation: dict,
    vault_browser: Optional[dict] = None,
    vault_browser_error: str = "",
    production_profile: bool = False,
    diagnostics: bool = False,
    ambient_refresh_enabled: bool = False,
    entry_resolution: Optional[EntryStateResolution] = None,
) -> str:
    if entry_resolution is None:
        entry_resolution = resolve_entry_state(orientation=orientation)
    scope = _orientation_dict(orientation.get("scope"))
    meta = _orientation_dict(orientation.get("meta"))
    guards = _orientation_dict(orientation.get("guards"))
    reasons = _orientation_degraded_reasons(orientation)
    degraded = bool(guards.get("degraded")) or bool(reasons)
    title_suffix = "PROD" if production_profile else "DEV"
    dev_chip = "" if production_profile else '<span class="dev-chip">DEV / not production</span>'
    freshness = _orientation_str(meta.get("freshness"), "unknown")
    stale_after = _orientation_str(meta.get("stale_after"))
    as_of = _orientation_str(meta.get("as_of"))
    trace_id = _orientation_str(meta.get("trace_id"), "unknown")
    runtime_posture = _orientation_str(guards.get("runtime_posture"), "unknown")
    reason_html = "".join(
        f'<span class="orientation-reason">{_e(reason)}</span>' for reason in reasons
    )
    # Degraded is an amber banner naming the missing source(s); the rest of
    # the surface stays calm and the resolved slices still render
    # (SYSTEM_ENTRY_POINT_SPEC.md §Entry-point state model, cross-flags).
    missing_source_html = (
        f"""
          <span class="orientation-degraded-source"
            data-testid="workspace-orientation-degraded-source">
            Missing source: {_e(" · ".join(reasons))}
          </span>"""
        if reasons
        else ""
    )
    degraded_html = (
        f"""
        <section class="orientation-degraded" data-testid="workspace-orientation-degraded"
          data-tone="amber"
          data-runtime-posture="{_e(runtime_posture)}">
          <strong>Partial orientation</strong>
          <span>Runtime posture: {_e(runtime_posture)}</span>
          {missing_source_html}
          <div>{reason_html}</div>
        </section>"""
        if degraded
        else ""
    )
    # Latency-ladder re-entry treatment (#1784, SEP-02). The shape is the
    # server-resolved SEP-01 attribute; no client-side gap computation.
    shape = entry_resolution.reentry_shape if entry_resolution.state == "orienting" else None
    # cold_start (first contact / >14d cold) is the anti-dashboard posture:
    # no re-entry overlay, no orientation sections, just vault + map affordances
    # (SYSTEM_ENTRY_POINT_SPEC.md §Anti-dashboard; REENTRY_ORIENTATION_TREATMENT.md §Cold).
    is_cold = entry_resolution.state == "cold_start"
    # no_vault via the orientation-unavailable frame (orientation fetch failed,
    # vault browser still reachable) also suppresses the orientation grid and
    # re-entry overlay; renders quiet-register copy instead (#2173).
    is_no_vault = entry_resolution.state == "no_vault"
    reentry_overlay_html = ""
    whisper_html = ""
    rail_fade_attr = ""
    rail_fade_class = ""
    memory_drawer_markup_html = ""
    memory_drawer_script_html = ""
    if shape in ("full_mist", "long_mist"):
        reentry_overlay_html = _render_reentry_card(
            orientation, shape=shape, stale=entry_resolution.stale
        )
        # The re-entry card's unresolved-inspect affordance emits
        # `memory.open` (#1793, SEP-09b), so the memory review drawer ships
        # with the card — pull-based, no dead affordance on shapes without
        # the card. Dismiss returns to the orientation substrate untouched
        # (no route reset, no data loss).
        memory_drawer_markup_html = memory_review_drawer_markup()
        memory_drawer_script_html = memory_review_drawer_script()
        if shape == "long_mist":
            whisper_html = _render_reentry_whisper_column(orientation)
    elif shape == "soft_mist":
        reentry_overlay_html = _render_reentry_peripheral_line(orientation)
    elif shape == "thread_fade":
        # No card, no peripheral line: the rail pane fades a fraction and the
        # trajectory stays implicit.
        rail_fade_attr = f' data-rail-fade="{_REENTRY_RAIL_FADE}"'
        rail_fade_class = " orientation-shell--rail-faded"
    # no_mist, cold_start, and no_vault render no re-entry overlay of any kind.
    refresh_mode = "foreground_pull" if ambient_refresh_enabled else "manual"
    refresh_state = "degraded" if degraded else ("scheduled" if ambient_refresh_enabled and stale_after else "manual_refresh")
    refresh_copy = (
        "Foreground refresh scheduled from server freshness metadata."
        if ambient_refresh_enabled and stale_after and not degraded
        else "Manual refresh"
    )
    # In the no_vault entry state the manual refresh link is the declared
    # entry.retry affordance (SYSTEM_ENTRY_POINT_SPEC.md §Intent vocabulary);
    # it re-requests orientation read-only and returns the client to `boot`.
    retry_intent_attr = (
        ' data-intent="entry.retry"' if entry_resolution.state == "no_vault" else ""
    )
    refresh_html = f"""
        <section class="orientation-refresh"
          data-testid="workspace-orientation-ambient-refresh"
          data-refresh-mode="{_e(refresh_mode)}"
          data-refresh-state="{_e(refresh_state)}"
          data-read-only="true">
          <span>{_e(refresh_copy)}</span>
          <a href="/"{retry_intent_attr} data-testid="workspace-orientation-manual-refresh">Refresh</a>
          <button type="button" class="orientation-map-affordance"
            data-testid="workspace-orientation-map-affordance" data-intent="map.open"
            aria-label="Open the system map"
            onclick="overlayHost.mount('map')">System map</button>
        </section>"""
    ambient_script = _orientation_ambient_refresh_script() if ambient_refresh_enabled else ""
    vault_entry_html = _render_orientation_vault_entry(
        vault_browser,
        error=vault_browser_error,
        resolved_vault_id=_orientation_str(scope.get("vault_id")) or None,
    )
    vault_browser_script = _orientation_vault_browser_script() if vault_entry_html else ""
    # The system map overlay (#1787, SEP-05) is reachable from every entry
    # state (spec §Resolved Q4): the calm affordance above is the only opener
    # — pull-based, never unbidden. The overlay-host substrate therefore
    # ships on every orientation render; only the vault route truthfully
    # exists on the entry surfaces (the declared cold_start → shell_active
    # path), so the map offers exactly that one.
    orientation_map_routes = ("vault",) if vault_entry_html else ()
    overlay_host_overlays_html = (
        overlay_host_markup(anchor_note_path="")
        + memory_drawer_markup_html
        + system_map_overlay_markup(
            available_routes=orientation_map_routes,
            orientation_freshness=freshness if freshness not in ("unknown", "") else "",
            orientation_as_of=as_of,
            orientation_trace_id=trace_id if trace_id != "unknown" else "",
            open_loops_count=len(_orientation_list(orientation.get("open_loops"))),
        )
        # Capture modal (#1791, SEP-08b): the inline capture field on the
        # cold_start threshold and the `Jot something down` verb both route to
        # the `capture` occupant via overlayHost.mount('capture').  The modal
        # must be present on the cold_start orientation substrate so ⌘N /
        # capture.open mounts a real governed occupant instead of silently
        # no-oping.  Only cold_start needs it on the orientation page — the
        # workspace shell (#1785) ships the modal for shell_active, and the
        # orienting/no_vault states carry no capture affordance.
        + (capture_modal_markup() if is_cold else "")
        + overlay_host_script()
        + memory_drawer_script_html
        + system_map_overlay_script()
        + (capture_modal_script() if is_cold else "")
        # Guidance layer (#1788, SEP-06): the re-entry card and the map head
        # carry the ⓘ affordance on the entry surfaces, so the visibility
        # gate and the UI-local toggle controller ship with the substrate.
        + guidance_layer_style()
        + guidance_layer_script()
    )
    # cold_start threshold body (AC2, #2171).
    # Variant is determined server-side from the orientation payload: first
    # contact when leave_point is absent/missing; cold trajectory when a
    # leave_point exists but the gap exceeded 14 d.  No client-side
    # re-derivation — the orientation payload is the server-declared source.
    # #2243: "First contact / Nothing is open yet." is reserved for a genuinely
    # empty vault.  If recents_anchor is present the runtime is signalling a
    # non-empty vault; use "Returning after a while" copy regardless of
    # leave_point.status.  No UI-side filesystem probe — the emptiness signal is
    # entirely server-declared (recents_anchor presence = non-empty vault).
    cold_start_threshold_html = ""
    if is_cold:
        _cold_lp = _orientation_dict(orientation.get("leave_point"))
        _cold_lp_status = _cold_lp.get("status") if _cold_lp else None
        # Recents-anchor sub-affordance (§6, design_handoff/implementation-contracts.md).
        # Rendered only when the runtime declares the server-side recents_anchor field.
        # NEVER auto-opens; omitted entirely when the field is absent.
        # Consumes ONLY the server-declared field — no UI-side filesystem mtime probe.
        # Also serves as the server-declared vault-nonempty signal (#2243).
        _cold_recents = _orientation_dict(orientation.get("recents_anchor"))
        # recents_anchor present → vault is non-empty → use returning copy (#2243).
        _vault_nonempty = bool(_cold_recents)
        _leave_point_absent = (not _cold_lp) or _cold_lp_status == "absent"
        _is_first_contact = _leave_point_absent and not _vault_nonempty
        if _is_first_contact:
            _cold_eyebrow = "First contact"
            _cold_headline = "Nothing is open yet."
            _cold_provenance = "leave_point: absent · read-only · server-declared"
        else:
            _cold_eyebrow = "Returning after a while"
            _cold_headline = "Re-entry is through the vault."
            _cold_provenance = "trajectory: cold (&gt;14d) · leave_point: present · read-only · server-declared"
        _cold_vault_id = _e(_orientation_str(scope.get("vault_id"), "unknown"))
        _cold_recents_path = _orientation_str(_cold_recents.get("note_path")) if _cold_recents else ""
        _cold_recents_label = _orientation_str(_cold_recents.get("display_label")) if _cold_recents else ""
        if _cold_recents_path and _cold_recents_label:
            _cold_recents_href = "/workspace?note_path=" + quote(_cold_recents_path, safe="")
            _cold_recents_html = (
                f'<br><span class="cold-start-recents-anchor" data-testid="cold-start-recents-anchor">'
                f'<a data-intent="recents.open" href="{_e(_cold_recents_href)}">'
                f"Open your most recent note: {_e(_cold_recents_label)}"
                f"</a></span>"
            )
        else:
            _cold_recents_html = ""
        cold_start_threshold_html = f"""
    <div data-region="cold-start-threshold">
      <div class="cold-start-vault-chip">
        <span class="cold-start-vault-dot" aria-hidden="true"></span>
        <span class="cold-start-vault-id">{_cold_vault_id}</span>
      </div>
      <div class="cold-start-headline-block">
        <div class="cold-start-eyebrow">{_e(_cold_eyebrow)}</div>
        <h1 class="cold-start-headline">{_e(_cold_headline)}</h1>
      </div>
      <p data-region="cold-start-verbs" class="cold-start-verbs">
        <a data-intent="vault.open" onclick="vaultBrowser.focus(); return false;" href="#">Find a note</a>
        &middot;
        <a data-intent="capture.open" onclick="overlayHost.mount('capture'); return false;" href="#">Jot something down</a>
        &middot;
        <a data-intent="map.open" onclick="overlayHost.mount('map'); return false;" href="#">See the map</a>
        {_cold_recents_html}
      </p>
      <!-- Inline capture field (design item 4, #2172): on focus / ⌘N mounts
           the shipped governed capture occupant verbatim.  The warmth rule:
           the caret is the one saturated element; the door stays monochrome.
           Suppressed on no_vault: no honest landing for an offline write. -->
      <div data-region="cold-start-capture" class="cold-start-capture-line">
        <input type="text" class="cold-start-capture-input"
               data-testid="cold-start-capture-input"
               placeholder="Leave a note for future-you…"
               onfocus="overlayHost.mount('capture'); this.blur();"
               autocomplete="off" aria-label="Leave a note for future-you" />
      </div>
      <p class="cold-start-provenance">{_cold_provenance}</p>
    </div>"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion UI — Workspace Orientation [{title_suffix}]</title>
  <style>
    :root {{
      --bg-base: #070b12;
      --bg-surface: #0c1220;
      --bg-raised: #111a2e;
      --fg-1: #dce8f0;
      --fg-2: #7a9ab8;
      --fg-3: #3d5570;
      --border: #152030;
      --border-strong: #1e3050;
      --accent: #d4a843;
      --cyan: #00d4e8;
      --amber: #f09030;
      --destructive: #ff3d3d;
      --font-ui: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: var(--bg-base);
      color: var(--fg-1);
      font-family: var(--font-ui);
      line-height: 1.55;
    }}
    .topbar {{
      align-items: center;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 12px;
      padding: 8px 20px;
    }}
    .topbar-api {{
      color: var(--fg-2);
      flex: 1;
      font-family: var(--font-mono);
      font-size: 12px;
      min-width: 0;
    }}
    .api-label {{ color: var(--fg-3); letter-spacing: 0.06em; text-transform: uppercase; }}
    .dev-chip {{
      border: 1px solid rgba(212,168,67,0.45);
      border-radius: 4px;
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.06em;
      padding: 2px 8px;
      text-transform: uppercase;
    }}
    body[data-diagnostics="false"] .topbar,
    body[data-diagnostics="false"] .dev-controls-disclosure,
    body[data-diagnostics="false"] .dev-chip {{ display: none; }}
    .dev-controls-disclosure {{ background: var(--bg-surface); border-bottom: 1px solid var(--border); }}
    .dev-controls-summary {{
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 12px;
      padding: 4px 20px;
    }}
    .load-bar {{ display: flex; gap: 8px; padding: 10px 20px; }}
    .load-bar form {{ align-items: center; display: flex; gap: 8px; width: 100%; }}
    .load-bar label {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .load-bar input {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: 4px;
      color: var(--fg-1);
      flex: 1;
      min-width: 0;
      padding: 7px 10px;
    }}
    .load-bar button {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: 4px;
      color: var(--fg-1);
      cursor: pointer;
      padding: 7px 14px;
    }}
    .orientation-shell {{
      display: grid;
      gap: 16px;
      margin: 0 auto;
      max-width: 1180px;
      padding: 24px;
    }}
    .orientation-header {{
      border-bottom: 1px solid var(--border);
      display: grid;
      gap: 8px;
      padding-bottom: 16px;
    }}
    .orientation-eyebrow {{
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .orientation-heading {{
      font-size: 26px;
      font-weight: 600;
      margin: 0;
    }}
    .orientation-meta {{
      color: var(--fg-2);
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .orientation-grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
    }}
    .orientation-column {{ display: grid; gap: 16px; min-width: 0; }}
    .orientation-section {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      display: grid;
      gap: 12px;
      padding: 16px;
    }}
    .orientation-section--primary {{ border-color: var(--border-strong); }}
    .orientation-section-header {{
      align-items: center;
      display: flex;
      justify-content: space-between;
      gap: 12px;
    }}
    .orientation-section-kicker {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .orientation-title {{
      font-size: 22px;
      font-weight: 600;
      margin: 0;
    }}
    .orientation-subheading {{
      font-size: 18px;
      font-weight: 600;
      margin: 4px 0 0;
    }}
    .orientation-vault-entry {{
      grid-column: 1 / -1;
    }}
    .orientation-vault-entry .vault-browser {{
      background: transparent;
      border: 0;
      padding: 0;
    }}
    .orientation-vault-entry .vault-browser > summary {{
      display: none;
    }}
    .orientation-vault-open {{
      color: var(--cyan);
      font-family: var(--font-mono);
      font-size: 12px;
      text-decoration: none;
    }}
    .orientation-vault-open:hover {{ text-decoration: underline; }}
    .orientation-vault-entry .vault-browser-list {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 6px;
      list-style: none;
      margin: 0;
      max-height: 360px;
      overflow: auto;
      padding: 10px;
    }}
    .orientation-vault-entry .vault-tree-children {{
      list-style: none;
      margin: 4px 0 0 14px;
      padding: 0;
    }}
    .orientation-vault-entry .vault-tree-folder-summary {{
      color: var(--fg-2);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 12px;
      padding: 3px 0;
    }}
    .orientation-vault-entry .vault-browser-row {{
      align-items: center;
      display: flex;
      gap: 8px;
      min-height: 28px;
    }}
    .orientation-vault-entry .vault-browser-selection-toggle {{
      flex: 0 0 auto;
    }}
    .orientation-vault-entry .vault-browser-row-title {{
      color: var(--cyan);
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      text-decoration: none;
      white-space: nowrap;
    }}
    .orientation-vault-entry .vault-browser-row-title:hover {{ text-decoration: underline; }}
    .orientation-vault-entry .vault-browser-zone-label,
    .orientation-vault-entry .note-badge--nav-hidden {{
      display: none;
    }}
    .orientation-item {{
      border-top: 1px solid var(--border);
      display: grid;
      gap: 8px;
      padding-top: 12px;
    }}
    .orientation-item:first-of-type {{ border-top: 0; padding-top: 0; }}
    .orientation-item h3 {{ font-size: 16px; font-weight: 600; margin: 0; }}
    .orientation-item p {{ color: var(--fg-2); margin: 0; }}
    .orientation-artifact-link {{ color: var(--cyan); font-size: 14px; text-decoration: none; }}
    .orientation-artifact-link:hover {{ text-decoration: underline; }}
    .orientation-artifact-link--empty {{ color: var(--fg-3); }}
    .orientation-badges, .orientation-signals, .orientation-meta-row {{
      color: var(--fg-2);
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .orientation-badges span, .orientation-signal, .orientation-count, .orientation-reason {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 2px 6px;
    }}
    .orientation-provenance {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .orientation-empty {{ color: var(--fg-3); margin: 0; }}
    .orientation-governance-grid {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }}
    .orientation-governance-grid div {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 10px;
    }}
    .orientation-governance-grid span {{ display: block; font-size: 20px; font-weight: 600; }}
    .orientation-governance-grid small {{
      color: var(--fg-2);
      display: block;
      font-family: var(--font-mono);
      font-size: 11px;
      margin-top: 2px;
    }}
    /* Degraded is a calm amber banner naming the missing source — never an
       alarm and never the destructive token (spec cross-flag treatment;
       BLOCKED_AND_STALE_STATE_SPEC.md visual contract). */
    .orientation-degraded {{
      background: rgba(240,144,48,0.08);
      border: 1px solid rgba(240,144,48,0.35);
      border-radius: 8px;
      color: var(--fg-1);
      display: grid;
      gap: 8px;
      padding: 12px 16px;
    }}
    .orientation-degraded strong {{ color: var(--amber); }}
    .orientation-degraded-source {{ color: var(--fg-2); font-family: var(--font-mono); font-size: 12px; }}
    .orientation-refresh {{
      align-items: center;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      color: var(--fg-2);
      display: flex;
      font-family: var(--font-mono);
      font-size: 12px;
      gap: 10px;
      justify-content: space-between;
      padding: 10px 12px;
    }}
    .orientation-refresh a {{ color: var(--cyan); text-decoration: none; }}
    .orientation-refresh a:hover {{ text-decoration: underline; }}
    .orientation-budget-expand summary {{
      color: var(--fg-2);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    /* ---- Re-entry treatments per latency-ladder shape (#1784, SEP-02) ---- */
    .reentry-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-left: 2px solid var(--accent);
      border-radius: 8px;
      display: grid;
      gap: 12px;
      padding: 16px;
    }}
    .reentry-head {{ align-items: center; display: flex; gap: 12px; justify-content: space-between; }}
    .reentry-traj-pill {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.06em;
      padding: 2px 10px;
      text-transform: uppercase;
    }}
    .reentry-questions {{ display: grid; gap: 10px; list-style: none; margin: 0; padding: 0; }}
    .reentry-q {{ display: grid; gap: 2px; }}
    .reentry-q-label {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .reentry-q-body {{ color: var(--fg-1); }}
    .reentry-inspect {{
      color: var(--cyan);
      font-family: var(--font-mono);
      font-size: 12px;
      margin-left: 6px;
      text-decoration: none;
    }}
    .reentry-inspect:hover {{ text-decoration: underline; }}
    .reentry-caret-echo {{
      animation: reentry-breathe 1.6s ease-in-out infinite;
      background: var(--accent);
      display: inline-block;
      height: 1.1em;
      margin-left: 2px;
      vertical-align: text-bottom;
      width: 2px;
    }}
    @keyframes reentry-breathe {{ 0%, 100% {{ opacity: 0.25; }} 50% {{ opacity: 0.8; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .reentry-caret-echo {{ animation: none; opacity: 0.6; }}
    }}
    .reentry-actions {{ align-items: center; display: flex; flex-wrap: wrap; gap: 10px; }}
    .reentry-resume {{
      background: var(--bg-raised);
      border: 1px solid var(--accent);
      border-radius: 4px;
      color: var(--accent);
      padding: 6px 12px;
      text-decoration: none;
    }}
    .reentry-dismiss {{
      background: transparent;
      border: 1px solid var(--border-strong);
      border-radius: 4px;
      color: var(--fg-2);
      cursor: pointer;
      font: inherit;
      padding: 6px 12px;
    }}
    /* Guard-held qualified resume — amber/staged token, never destructive. */
    .reentry-resume-guard {{
      background: rgba(240,144,48,0.08);
      border: 1px solid rgba(240,144,48,0.35);
      border-radius: 6px;
      display: grid;
      gap: 6px;
      padding: 10px 12px;
    }}
    .reentry-guard-copy {{ color: var(--fg-1); font-size: 14px; }}
    .reentry-resume-forward {{ color: var(--cyan); text-decoration: none; }}
    .reentry-resume-forward:hover {{ text-decoration: underline; }}
    .reentry-delta-strip {{
      border-top: 1px dashed var(--border-strong);
      display: grid;
      gap: 6px;
      padding-top: 10px;
    }}
    .reentry-delta-item {{ align-items: center; color: var(--fg-2); display: flex; font-size: 14px; gap: 8px; }}
    .reentry-delta-dot {{ background: var(--cyan); border-radius: 50%; flex: none; height: 6px; width: 6px; }}
    .reentry-delta-more {{ color: var(--fg-3); font-family: var(--font-mono); font-size: 12px; }}
    .reentry-delta-more a {{ color: var(--cyan); text-decoration: none; }}
    .reentry-peripheral-line {{ color: var(--fg-3); font-size: 13px; margin: 0; text-align: right; }}
    .reentry-whisper-col {{
      display: grid;
      gap: 14px;
      pointer-events: none;
      position: fixed;
      right: 18px;
      top: 25vh;
      width: 180px;
    }}
    .reentry-whisper {{ display: grid; gap: 2px; }}
    .reentry-whisper-label {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .reentry-whisper-text {{ color: var(--fg-2); font-size: 13px; }}
    /* Thread fade (90s–15m): the rail pane fades a fraction; no card, no
       line — the trajectory stays implicit. */
    .orientation-shell--rail-faded .orientation-column--rail {{ opacity: {_REENTRY_RAIL_FADE}; }}
    @media (max-width: 860px) {{
      .orientation-grid {{ grid-template-columns: 1fr; }}
      .orientation-governance-grid {{ grid-template-columns: 1fr; }}
      .orientation-shell {{ padding: 16px; }}
      /* Narrow mode: the whisper column is suppressed and collapses into the
         card, which carries the same four answers. */
      .reentry-whisper-col {{ display: none; }}
    }}
    /* ---- cold_start inline capture (#2172, #2240-c) ---- */
    .cold-start-capture-line {{
      margin: 16px 0 0;
    }}
    .cold-start-capture-input {{
      background: transparent;
      border: none;
      border-bottom: 1px solid var(--border-strong);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: 15px;
      outline: none;
      padding: 4px 0;
      width: 100%;
    }}
    .cold-start-capture-input::placeholder {{
      color: var(--fg-3);
    }}
    .cold-start-capture-input:focus {{
      border-bottom-color: var(--accent);
    }}
  </style>
</head>
<body data-diagnostics="{'true' if diagnostics else 'false'}" {entry_state_attributes(entry_resolution)}>
  {_render_help_toggle()}
  <div class="topbar">
    <div class="topbar-api">
      <span class="api-label">Server-side runtime</span>
      <span title="Companion UI proxies browser actions through same-origin routes">same-origin bridge</span>
    </div>
    {dev_chip}
  </div>
  <details class="dev-controls-disclosure" data-testid="workspace-dev-controls" open>
    <summary class="dev-controls-summary" data-testid="workspace-dev-controls-toggle">dev controls</summary>
    <div class="load-bar">
      <form method="GET" action="/workspace">
        <label for="note_path">note_path</label>
        <input id="note_path" name="note_path" type="text"
          value="{_e(note_path)}" placeholder="Some/Note.md" autocomplete="off">
        <button type="submit">Load</button>
      </form>
    </div>
  </details>
  <main class="orientation-shell{rail_fade_class}" data-testid="workspace-reentry-orientation"
    data-read-only="true"
    data-contract-version="{_e(_orientation_str(meta.get("contract_version"), "unknown"))}"
    data-freshness="{_e(freshness)}"
    data-as-of="{_e(as_of)}"
    data-stale-after="{_e(stale_after)}"
    data-trace-id="{_e(trace_id)}"
    data-degraded="{str(degraded).lower()}"
    data-ambient-refresh="{'enabled' if ambient_refresh_enabled else 'disabled'}"{rail_fade_attr}>
    <header class="orientation-header">
      <div class="orientation-eyebrow">Workspace orientation</div>
      {"" if (is_cold or is_no_vault) else '<h1 class="orientation-heading">Re-entry snapshot</h1>'}
      {"" if (is_cold or is_no_vault) else f'''<div class="orientation-meta">
        <span>vault: {_e(_orientation_str(scope.get("vault_id"), "unknown"))}</span>
        <span>channel: {_e(_orientation_str(scope.get("channel"), "unknown"))}</span>
        <span>freshness: {_e(freshness)}</span>
        <span>as of: {_e(as_of or "unknown")}</span>
        <span>trace: {_e(trace_id)}</span>
      </div>'''}
    </header>
    {refresh_html}
    {degraded_html}
    {reentry_overlay_html}
    {whisper_html}
    {cold_start_threshold_html}
    {f"""<div class="vault-unreachable-threshold" data-testid="workspace-vault-unreachable-threshold">
      <span class="vault-unreachable-threshold-copy">The runtime is unreachable. Nothing was lost.</span>
    </div>""" if is_no_vault else ""}
    <div class="orientation-grid">
      {"" if (is_cold or is_no_vault) else f'''<div class="orientation-column">
        {_render_orientation_leave_point(orientation.get("leave_point"))}
        {_render_orientation_open_loops(orientation.get("open_loops"), meta=meta)}
        {_render_orientation_notable_changes(orientation.get("notable_changes"), meta=meta)}
      </div>
      <div class="orientation-column orientation-column--rail">
        {_render_orientation_governance(orientation.get("governance"))}
        {_render_orientation_resurface(
            orientation.get("resurface"),
            meta=meta,
            degraded_reasons=reasons,
        )}
      </div>'''}
      {vault_entry_html}
    </div>
  </main>
  {vault_browser_script}
  {ambient_script}
  {_entry_dismiss_script()}
  {overlay_host_overlays_html}
  {_render_help_drawer()}
  {_render_operator_drawer()}
</body>
</html>"""


def _orientation_vault_browser_script() -> str:
    return """
  <script>
  function vaultBrowserSelectionControls() {
    return Array.prototype.slice.call(
      document.querySelectorAll('[data-testid="workspace-vault-browser-selection-toggle"]')
    );
  }

  function vaultBrowserUpdateSelectionSummary() {
    var controls = vaultBrowserSelectionControls();
    var selected = controls.filter(function(control) { return control.checked; });
    var summary = document.querySelector('[data-testid="workspace-vault-browser-selection-summary"]');
    if (!summary) return;
    summary.dataset.selectedCount = String(selected.length);
    summary.textContent = selected.length === 1 ? '1 selected' : selected.length + ' selected';
  }

  function vaultBrowserToggleSelection(event, control) {
    if (event) { event.stopPropagation(); }
    if (!control) return;
    var row = control.closest('[data-testid="workspace-vault-browser-note-row"]');
    var selected = !!control.checked;
    control.dataset.selected = selected ? 'true' : 'false';
    if (row) {
      row.dataset.selected = selected ? 'true' : 'false';
    }
    vaultBrowserUpdateSelectionSummary();
  }

  document.addEventListener('DOMContentLoaded', vaultBrowserUpdateSelectionSummary);

  function vbToggleFilter(el) {
    var key = el.dataset.key;
    var val = el.dataset.value;
    var url = new URL(window.location.href);
    var params = url.searchParams;
    var existing = params.getAll(key);
    params.delete(key);
    if (existing.indexOf(val) === -1) { params.append(key, val); }
    existing.filter(function(v) { return v !== val; }).forEach(function(v) { params.append(key, v); });
    window.location.href = url.toString();
  }
  </script>"""


def _orientation_ambient_refresh_script() -> str:
    return """
  <script>
  (function() {
    var shell = document.querySelector('[data-testid="workspace-reentry-orientation"]');
    var status = document.querySelector('[data-testid="workspace-orientation-ambient-refresh"]');
    if (!shell || shell.dataset.ambientRefresh !== 'enabled') return;
    var timer = null;
    function setState(state) {
      shell.dataset.refreshState = state;
      if (status) status.dataset.refreshState = state;
    }
    function parseDue(raw) {
      var due = Date.parse(raw || '');
      return Number.isFinite(due) ? due : null;
    }
    function foreground() {
      return !document.hidden && document.visibilityState !== 'hidden';
    }
    function schedule(raw) {
      if (timer) window.clearTimeout(timer);
      var due = parseDue(raw || shell.dataset.staleAfter);
      if (due === null) {
        setState('manual_refresh');
        return;
      }
      var delay = Math.max(0, due - Date.now());
      setState(delay > 0 ? 'scheduled' : 'stale');
      timer = window.setTimeout(refreshIfForeground, delay);
    }
    function applyMetadata(data) {
      var meta = data && data.meta ? data.meta : {};
      shell.dataset.freshness = meta.freshness || 'unknown';
      shell.dataset.asOf = meta.as_of || '';
      shell.dataset.staleAfter = meta.stale_after || '';
      shell.dataset.traceId = meta.trace_id || '';
      var degraded = !!(meta.degraded_reasons && meta.degraded_reasons.length);
      shell.dataset.degraded = degraded ? 'true' : 'false';
      setState(degraded || shell.dataset.freshness === 'partial' ? 'degraded' : 'fresh');
      schedule(shell.dataset.staleAfter);
    }
    function refreshIfForeground() {
      if (!foreground()) return;
      setState('refreshing');
      fetch('/api/companion/orientation', {method: 'GET'})
        .then(function(response) {
          if (!response.ok) throw new Error('orientation refresh failed');
          return response.json();
        })
        .then(applyMetadata)
        .catch(function() {
          setState('manual_refresh');
        });
    }
    function refreshWhenStale() {
      var due = parseDue(shell.dataset.staleAfter);
      if (due !== null && Date.now() >= due) refreshIfForeground();
    }
    document.addEventListener('visibilitychange', function() {
      if (foreground()) refreshWhenStale();
    });
    window.addEventListener('focus', refreshWhenStale);
    schedule(shell.dataset.staleAfter);
  }());
  </script>"""


# --- Operator diagnostics overlay ------------------------------------------
# The Operator diagnostics overlay folds the legacy app/web dashboard
# (Status / Health / Settings validation / Recent events / Ask) into the
# Companion UI shell as an Operator-badged slide-over drawer, modeled on the
# existing Help drawer. It is NOT a daily-use surface; it is operator-only.
#
# Architecture contract (from issue #1758):
#   - Document-first / overlay-first: dims but does not dismiss the workspace;
#     closing returns the user exactly where they were.
#   - Server declares, UI renders: no vault reads, no local data composition.
#     The overlay renders only runtime-declared payloads proxied through the
#     companion server (same-origin model).
#   - No hidden semantic state: degraded/unreachable states render explicitly
#     (amber/alert), never a silent blank or stale panel.
#   - No dev/prod feature split: wired into both profiles.
#   - Pure render: render_operator_overlay_html is a pure function over payloads.
#
# Proxy endpoints added to do_GET / do_POST:
#   GET  /api/operator/status            -> COMPANION_API_BASE_URL /api/status
#   GET  /api/operator/health            -> COMPANION_API_BASE_URL /api/health
#   GET  /api/operator/settings/validate -> COMPANION_API_BASE_URL /api/settings/validate
#   GET  /api/operator/events/tail       -> COMPANION_API_BASE_URL /api/events/tail
#   POST /api/operator/ask               -> COMPANION_API_BASE_URL /api/ask
#
# The /api/operator/* prefix keeps operator routes clearly namespaced and
# distinct from /api/companion/* (workspace) routes.
#
# How to extend:
#   * Edit overlay layout/content -> render_operator_overlay_html.
#   * Change the toggle control -> _render_operator_toggle.


def render_operator_overlay_html(
    *,
    status_payload: dict | None = None,
    health_payload: dict | None = None,
    settings_payload: dict | None = None,
    events_payload: dict | None = None,
    status_error: str = "",
    health_error: str = "",
    settings_error: str = "",
    events_error: str = "",
) -> str:
    """Render the Operator diagnostics overlay as a standalone HTML fragment.

    Pure function over payload dicts — no network calls, no file I/O.
    All user-supplied values are HTML-escaped before output.

    Used both for unit-testing (fixture payloads) and for static-HTML UAT
    capture (per reference_companion_ui_local_uat).  The overlay is embedded
    inside the shell by _render_operator_drawer(); this function produces the
    *inner* content of the drawer (suitable for iframe or direct embed).
    """

    def _e(v: object) -> str:
        return _html.escape(str(v) if v is not None else "")

    def _pill(ok: object, *, ok_label: str = "ok", fail_label: str = "fail") -> str:
        if ok is True:
            return f'<span class="op-pill op-pill-ok">{ok_label}</span>'
        if ok is False:
            return f'<span class="op-pill op-pill-warn">{fail_label}</span>'
        return '<span class="op-pill">unknown</span>'

    def _degraded_banner(msg: str) -> str:
        return (
            '<div class="op-banner-degraded" '
            'data-testid="operator-degraded-banner" '
            f'data-state="degraded">{_e(msg)}</div>'
        ) if msg else ""

    # --- Status panel ---
    if status_error:
        status_html = _degraded_banner(status_error)
    elif status_payload is not None:
        sot_v = _e(status_payload.get("sot_version", "N/A"))
        ts = _e(status_payload.get("timestamp", "N/A"))
        stores = status_payload.get("stores") or []
        ingestion = status_payload.get("ingestion") or {}
        ask_s = status_payload.get("ask") or {}
        store_rows = "".join(
            f"<tr>"
            f"<td>{_e(s.get('name', ''))}</td>"
            f"<td>{_e(s.get('object_count', 0))}</td>"
            f"<td>{_e(s.get('last_ingest_at', 'N/A'))}</td>"
            f"<td>{_e(s.get('last_error_at', 'N/A'))}</td>"
            f"</tr>"
            for s in stores
        ) or '<tr><td colspan="4" class="op-muted">No stores reported.</td></tr>'
        status_html = (
            f'<div class="op-stat-row"><span>SoT version</span><span>{sot_v}</span></div>'
            f'<div class="op-stat-row"><span>Timestamp</span><span>{ts}</span></div>'
            f'<div class="op-stat-row"><span>Ingestion last run</span>'
            f'<span>{_e(ingestion.get("last_run_at", "N/A"))}</span></div>'
            f'<div class="op-stat-row"><span>Ingestion result</span>'
            f'<span>{_pill(ingestion.get("last_run_ok"))}</span></div>'
            f'<div class="op-stat-row"><span>ASK queries (24h)</span>'
            f'<span>{_e(ask_s.get("total_queries_24h", 0))}</span></div>'
            f'<div class="op-stat-row"><span>ASK avg latency</span>'
            f'<span>{_e(ask_s.get("avg_latency_ms_24h", "N/A"))}</span></div>'
            f'<table class="op-table"><thead>'
            f'<tr><th>Store</th><th>Objects</th><th>Last ingest</th><th>Last error</th></tr>'
            f'</thead><tbody>{store_rows}</tbody></table>'
        )
    else:
        status_html = '<div class="op-muted" data-testid="operator-status-empty">No data.</div>'

    # --- Health panel ---
    if health_error:
        health_html = _degraded_banner(health_error)
    elif health_payload is not None:
        ok = health_payload.get("ok")
        checks = health_payload.get("checks") or {}
        check_rows = "".join(
            f"<tr><td>{_e(name)}</td>"
            f"<td>{_pill(detail.get('ok') if isinstance(detail, dict) else None)} "
            f"{_e(detail.get('detail', '') if isinstance(detail, dict) else '')}</td></tr>"
            for name, detail in checks.items()
        ) or '<tr><td colspan="2" class="op-muted">No checks reported.</td></tr>'
        health_html = (
            f'<div class="op-stat-row"><span>Overall</span><span>{_pill(ok)}</span></div>'
            f'<table class="op-table"><thead>'
            f'<tr><th>Check</th><th>Result</th></tr>'
            f'</thead><tbody>{check_rows}</tbody></table>'
        )
    else:
        health_html = '<div class="op-muted" data-testid="operator-health-empty">No data.</div>'

    # --- Settings validation panel ---
    if settings_error:
        settings_html = _degraded_banner(settings_error)
    elif settings_payload is not None:
        ok = settings_payload.get("ok")
        issues = settings_payload.get("issues") or []
        issues_text = "\n".join(
            f"{_e(i.get('code', ''))}: {_e(i.get('message', ''))}" for i in issues
        ) or "No issues."
        settings_html = (
            f'<div class="op-stat-row"><span>Status</span><span>{_pill(ok)}</span></div>'
            f'<pre class="op-pre">{issues_text}</pre>'
        )
    else:
        settings_html = (
            '<div class="op-muted" data-testid="operator-settings-empty">No data.</div>'
        )

    # --- Recent events panel ---
    if events_error:
        events_html = _degraded_banner(events_error)
    elif events_payload is not None:
        events = events_payload.get("events") or []
        # The events-tail JSONL shape is not uniform: the common record uses
        # `event`, some use `event_type`, and the outbox uses `topic`. Fall back
        # across all three (matching the legacy dashboard) so a populated tail
        # never renders a blank Event column.
        event_rows = "".join(
            f"<tr>"
            f"<td>{_e(ev.get('timestamp', ''))}</td>"
            f"<td>{_e(ev.get('event') or ev.get('event_type') or ev.get('topic') or '')}</td>"
            f"<td>{_e(str(ev.get('trace_id', ''))[:12])}</td>"
            f"</tr>"
            for ev in events[:50]
        ) or '<tr><td colspan="3" class="op-muted">No events.</td></tr>'
        events_html = (
            f'<table class="op-table"><thead>'
            f'<tr><th>Timestamp</th><th>Event</th><th>Trace</th></tr>'
            f'</thead><tbody>{event_rows}</tbody></table>'
        )
    else:
        events_html = '<div class="op-muted" data-testid="operator-events-empty">No data.</div>'

    return f"""<style>
  .op-panels{{display:flex;flex-direction:column;gap:16px;padding:0}}
  .op-panel{{background:var(--bg-raised,#111a2e);border:1px solid var(--border,#152030);
    border-radius:6px;padding:16px}}
  .op-panel-header{{display:flex;justify-content:space-between;align-items:center;
    margin-bottom:10px}}
  .op-panel-title{{font:500 14px/1 'Space Grotesk',sans-serif;color:var(--fg-1,#dce8f0)}}
  .op-badge{{font:500 11px/1 'JetBrains Mono',monospace;
    color:var(--amber,#f09030);background:var(--amber-muted,#1a0e02);
    border:1px solid var(--amber-dim,#805010);border-radius:999px;
    padding:2px 8px;letter-spacing:.06em;text-transform:uppercase}}
  .op-stat-row{{display:flex;justify-content:space-between;gap:10px;
    margin:6px 0;font-size:13px;color:var(--fg-1,#dce8f0)}}
  .op-stat-row span:first-child{{color:var(--fg-2,#7a9ab8)}}
  .op-table{{width:100%;border-collapse:collapse;margin-top:8px;font-size:13px}}
  .op-table th,.op-table td{{text-align:left;padding:6px 8px;
    border-bottom:1px solid var(--border,#152030)}}
  .op-table th{{color:var(--fg-3,#3d5570);font-weight:600}}
  .op-muted{{color:var(--fg-3,#3d5570);font-size:13px}}
  .op-pre{{font:400 12px/1.5 'JetBrains Mono',monospace;color:var(--fg-2,#7a9ab8);
    background:var(--bg-base,#070b12);border-radius:4px;padding:8px;
    margin:6px 0 0;overflow-x:auto;white-space:pre-wrap}}
  .op-pill{{display:inline-flex;align-items:center;padding:2px 8px;
    border-radius:999px;font-size:11px;font-weight:600}}
  .op-pill-ok{{background:var(--vault,#39e87d);color:#041a10}}
  .op-pill-warn{{background:var(--amber,#f09030);color:#1a0e02}}
  .op-banner-degraded{{background:var(--amber-muted,#1a0e02);
    border:1px solid var(--amber-dim,#805010);border-radius:4px;
    color:var(--amber,#f09030);font-size:13px;padding:8px 12px;margin:4px 0}}
  .op-ask-input{{width:100%;background:var(--bg-base,#070b12);
    border:1px solid var(--border-strong,#1e3050);color:var(--fg-1,#dce8f0);
    border-radius:6px;padding:8px 12px;font-size:13px;resize:vertical;
    min-height:72px;box-sizing:border-box}}
  .op-ask-input:focus{{outline:1px solid var(--border-focus,#00d4e8)}}
  .op-ask-btn{{margin-top:8px;background:var(--cyan,#00d4e8);color:#001e28;
    border:none;border-radius:6px;padding:8px 14px;font-size:13px;
    font-weight:600;cursor:pointer}}
  .op-ask-btn:disabled{{opacity:.6;cursor:not-allowed}}
  .op-ask-answer{{background:var(--bg-base,#070b12);
    border:1px solid var(--border,#152030);border-radius:6px;
    padding:10px 12px;min-height:48px;white-space:pre-wrap;font-size:13px;
    color:var(--fg-1,#dce8f0);margin-top:10px}}
</style>
<div class="op-panels" data-testid="operator-overlay-panels">
  <div class="op-panel" data-testid="operator-panel-status">
    <div class="op-panel-header">
      <span class="op-panel-title">Status</span>
      <span class="op-badge" data-testid="operator-badge">Operator</span>
    </div>
    {status_html}
  </div>
  <div class="op-panel" data-testid="operator-panel-health">
    <div class="op-panel-header">
      <span class="op-panel-title">Health</span>
    </div>
    {health_html}
  </div>
  <div class="op-panel" data-testid="operator-panel-settings">
    <div class="op-panel-header">
      <span class="op-panel-title">Settings validation</span>
    </div>
    {settings_html}
  </div>
  <div class="op-panel" data-testid="operator-panel-events">
    <div class="op-panel-header">
      <span class="op-panel-title">Recent events</span>
    </div>
    {events_html}
  </div>
  <div class="op-panel" data-testid="operator-panel-ask">
    <div class="op-panel-header">
      <span class="op-panel-title">Ask</span>
    </div>
    <textarea class="op-ask-input" id="operator-ask-input"
      data-testid="operator-ask-input"
      placeholder="Ask the agent something..."></textarea><br>
    <button class="op-ask-btn" id="operator-ask-btn"
      data-testid="operator-ask-btn" type="button">Ask</button>
    <div class="op-ask-answer" id="operator-ask-answer"
      data-testid="operator-ask-answer">N/A</div>
  </div>
</div>
<script>
(function() {{
  var btn = document.getElementById('operator-ask-btn');
  var inp = document.getElementById('operator-ask-input');
  var ans = document.getElementById('operator-ask-answer');
  if (!btn || !inp || !ans) {{ return; }}
  btn.addEventListener('click', function() {{
    var q = inp.value.trim();
    if (!q) {{ return; }}
    btn.disabled = true;
    ans.textContent = 'Asking…';
    fetch('/api/operator/ask', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{question: q}})
    }}).then(function(r) {{
      return r.json().then(function(d) {{
        ans.textContent = d.answer || d.error || JSON.stringify(d);
        btn.disabled = false;
      }});
    }}).catch(function(e) {{
      ans.textContent = 'Error: ' + e;
      btn.disabled = false;
    }});
  }});
}}());
</script>"""


def _render_operator_toggle() -> str:
    """Fixed-position control that opens the in-shell Operator diagnostics drawer.

    Operator-badged and positioned above the Help toggle. Deliberately uses
    amber accent (operator color per help_guide.html badge legend) to signal
    it is not a daily-use surface.
    """
    return (
        '<button type="button" class="operator-toggle" '
        'data-testid="workspace-operator-toggle" aria-haspopup="dialog" '
        'aria-controls="workspace-operator-drawer" aria-expanded="false" '
        'title="Operator diagnostics" onclick="companionOperator.open()">'
        '<span aria-hidden="true">⚠</span> Operator</button>'
    )


def _render_operator_drawer() -> str:
    """Server-declared in-shell Operator diagnostics drawer.

    A slide-over panel that embeds operator diagnostics fetched same-origin
    from /operator. The toggle script only changes visibility; panel content
    is loaded lazily on first open by fetching /operator.

    The drawer dims but does not dismiss the workspace: closing returns the
    user exactly where they were (identical contract to the Help drawer).
    """
    return """
  <style>
    .operator-toggle{position:fixed;bottom:60px;right:18px;z-index:999;
      display:inline-flex;align-items:center;gap:6px;
      padding:8px 16px;font:500 13px/1 'Space Grotesk',sans-serif;
      color:var(--amber);background:var(--amber-muted);
      border:1px solid var(--amber-dim);border-radius:999px;
      cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.4)}
    .operator-toggle:hover{border-color:var(--amber)}
    .operator-drawer-backdrop{position:fixed;inset:0;
      background:rgba(7,11,18,.72);opacity:0;pointer-events:none;
      transition:opacity .18s ease;z-index:1000}
    .operator-drawer{position:fixed;top:0;right:0;height:100vh;
      width:min(640px,94vw);transform:translateX(100%);
      transition:transform .22s cubic-bezier(.4,0,.2,1);
      background:var(--bg-surface);
      border-left:1px solid var(--border-strong);
      box-shadow:-8px 0 32px rgba(0,0,0,.5);z-index:1001;
      display:flex;flex-direction:column}
    .operator-drawer-host[data-open="true"] .operator-drawer{transform:translateX(0)}
    .operator-drawer-host[data-open="true"] .operator-drawer-backdrop{
      opacity:1;pointer-events:auto}
    .operator-drawer-head{display:flex;align-items:center;gap:10px;
      padding:12px 16px;border-bottom:1px solid var(--border);
      background:var(--bg-raised)}
    .operator-drawer-title{font:500 14px/1 'Space Grotesk',sans-serif;color:var(--fg-1)}
    .operator-drawer-badge{font:500 11px/1 'JetBrains Mono',monospace;
      color:var(--amber);background:var(--amber-muted);
      border:1px solid var(--amber-dim);border-radius:999px;
      padding:2px 8px;letter-spacing:.06em;text-transform:uppercase}
    .operator-drawer-close{margin-left:auto;background:none;
      border:1px solid var(--border);color:var(--fg-2);border-radius:6px;
      width:30px;height:30px;cursor:pointer;font-size:18px;line-height:1}
    .operator-drawer-close:hover{color:var(--fg-1);border-color:var(--border-strong)}
    .operator-drawer-body{flex:1;overflow-y:auto;padding:16px;background:var(--bg-surface)}
    .operator-drawer-loading{color:var(--fg-3);font-size:13px;padding:12px 0}
  </style>
  """ + _render_operator_toggle() + """
  <div class="operator-drawer-host" id="workspace-operator-host"
       data-testid="workspace-operator-host" data-open="false"
       data-authority-role="server_declared">
    <div class="operator-drawer-backdrop" data-testid="workspace-operator-backdrop"
         onclick="companionOperator.close()"></div>
    <aside class="operator-drawer" id="workspace-operator-drawer"
           data-testid="workspace-operator-drawer" role="dialog" aria-modal="true"
           aria-label="Operator diagnostics">
      <div class="operator-drawer-head">
        <span class="operator-drawer-title">Operator diagnostics</span>
        <span class="operator-drawer-badge"
              data-testid="workspace-operator-badge">Operator</span>
        <button type="button" class="operator-drawer-close"
                data-testid="workspace-operator-close"
                aria-label="Close operator panel"
                onclick="companionOperator.close()">&times;</button>
      </div>
      <div class="operator-drawer-body" id="workspace-operator-body"
           data-testid="workspace-operator-body">
        <div class="operator-drawer-loading"
             data-testid="workspace-operator-loading">Loading…</div>
      </div>
    </aside>
  </div>
  <script>
  (function() {
    var host   = document.getElementById('workspace-operator-host');
    var body   = document.getElementById('workspace-operator-body');
    var toggle = document.querySelector('[data-testid="workspace-operator-toggle"]');
    if (!host || !body) { return; }
    var loaded = false;
    function setExpanded(state) {
      if (toggle) { toggle.setAttribute('aria-expanded', state ? 'true' : 'false'); }
    }
    function loadContent() {
      if (loaded) { return; }
      loaded = true;
      fetch('/operator', {method: 'GET'})
        .then(function(r) { return r.text(); })
        .then(function(html) {
          body.innerHTML = html;
          // Execute inline scripts inside the loaded fragment.
          Array.prototype.slice.call(body.querySelectorAll('script')).forEach(function(s) {
            var ns = document.createElement('script');
            ns.textContent = s.textContent;
            s.parentNode.replaceChild(ns, s);
          });
        })
        .catch(function(err) {
          body.innerHTML = '<div class="op-banner-degraded"'
            + ' data-testid="operator-degraded-banner" data-state="degraded">'
            + 'Operator panel unavailable: ' + String(err) + '</div>';
        });
    }
    window.companionOperator = {
      open: function() {
        loadContent();
        host.setAttribute('data-open', 'true');
        setExpanded(true);
      },
      close: function() {
        host.setAttribute('data-open', 'false');
        setExpanded(false);
        if (toggle) { try { toggle.focus(); } catch (e) {} }
      },
      toggle: function() {
        if (host.getAttribute('data-open') === 'true') { this.close(); }
        else { this.open(); }
      }
    };
    document.addEventListener('keydown', function(ev) {
      if (ev.key === 'Escape' && host.getAttribute('data-open') === 'true') {
        window.companionOperator.close();
      }
    });
  }());
  </script>"""


# --- In-shell Help drawer ---------------------------------------------------
# The Companion UI help/user guide is a single self-contained, swap-ready HTML
# document (``help_guide.html``, served at ``/help``). It is rendered inside the
# shell as a slide-over drawer rather than a separate page, so help is a first-
# class region of the single adaptive workspace, not a detached artifact.
#
# Authority boundary (server declares; UI renders): the guide content is served
# by the runtime/dev server; the drawer toggle script below only flips
# visibility and lazy-loads the iframe. No help content is composed client-side.
#
# How to extend:
#   * Edit help content -> ``help_guide.html`` (one file; keep it standalone so
#     it still opens directly and stays compatible with the screenshot system).
#   * Change the in-shell chrome (button, drawer geometry) -> this region.
_HELP_GUIDE_PATH = Path(__file__).with_name("help_guide.html")
_HELP_ASSETS_DIR = Path(__file__).with_name("help_assets")
_HELP_ASSET_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.png$")
_HELP_ASSET_CACHE: dict[str, bytes] | None = None


def _help_asset_cache() -> dict[str, bytes]:
    """Preload packaged help-guide PNGs into an in-memory name->bytes map.

    Paths come only from a filesystem enumeration of ``help_assets`` (never from
    request input), so the request path is a pure dict lookup with no path
    expression — a request name can never reach the filesystem. ``open().read()``
    is used (these are packaged UI assets, not vault content) to stay clear of
    the vault-I/O architecture guard.
    """
    global _HELP_ASSET_CACHE
    if _HELP_ASSET_CACHE is None:
        cache: dict[str, bytes] = {}
        try:
            entries = sorted(_HELP_ASSETS_DIR.iterdir())
        except OSError:
            entries = []
        for entry in entries:
            if entry.suffix == ".png" and _HELP_ASSET_NAME.fullmatch(entry.name) and entry.is_file():
                try:
                    with open(entry, "rb") as fh:
                        cache[entry.name] = fh.read()
                except OSError:
                    continue
        _HELP_ASSET_CACHE = cache
    return _HELP_ASSET_CACHE


def load_help_asset(name: str) -> bytes | None:
    """Return a help-guide image asset (PNG) by exact name, or None.

    Pure lookup into the preloaded asset map: the request-supplied ``name`` is
    only ever used as a dict key, so it cannot influence a filesystem path.
    """
    return _help_asset_cache().get(name)


def load_help_guide_html() -> str:
    """Load the standalone help/user-guide document served at ``/help``.

    ``help_guide.html`` is a packaged UI asset that ships beside this module
    (like a template), not vault content. We read it with ``open().read()``
    rather than ``Path.read_text`` to stay clear of the architecture guard that
    forbids direct vault file I/O (``read_text``/``read_bytes``) in this module;
    the dev server still never reads vault files — those flow via the runtime API.
    """
    try:
        with open(_HELP_GUIDE_PATH, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return (
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<title>Companion UI · Help</title></head><body style=\"font-family:"
            "sans-serif;padding:2rem;color:#dce8f0;background:#070b12\">"
            "<h1>Help guide unavailable</h1><p>The Companion UI help document "
            "(<code>help_guide.html</code>) could not be loaded on the server."
            "</p></body></html>"
        )


def _render_help_toggle() -> str:
    """Fixed-position control that opens the in-shell Help drawer.

    Rendered as part of the drawer region (not a per-view header) so it stays
    visible regardless of which shell layout is active — the adaptive shell
    hides the legacy ``.topbar``, so a header-embedded control would not show.
    """
    return (
        '<button type="button" class="help-toggle" '
        'data-testid="workspace-help-toggle" aria-haspopup="dialog" '
        'aria-controls="workspace-help-drawer" aria-expanded="false" '
        'title="Companion UI help" onclick="companionHelp.open()">'
        '<span aria-hidden="true">?</span> Help</button>'
    )


def _render_help_drawer() -> str:
    """Server-declared in-shell Help drawer region.

    A slide-over panel that loads the ``/help`` guide in an iframe. The toggle
    script only changes visibility and lazy-binds the iframe ``src`` on first
    open; it never composes help content locally.
    """
    return """
  <style>
    .help-toggle{position:fixed;bottom:18px;right:18px;z-index:999;
      display:inline-flex;align-items:center;gap:6px;
      padding:8px 16px;font:500 13px/1 'Space Grotesk',sans-serif;color:var(--cyan);
      background:var(--cyan-muted);border:1px solid var(--cyan-dim);border-radius:999px;
      cursor:pointer;box-shadow:0 4px 16px rgba(0,0,0,.4)}
    .help-toggle:hover{box-shadow:var(--cyan-glow);border-color:var(--border-focus)}
    .help-drawer-backdrop{position:fixed;inset:0;background:rgba(7,11,18,.62);
      opacity:0;pointer-events:none;transition:opacity .18s ease;z-index:1000}
    .help-drawer{position:fixed;top:0;right:0;height:100vh;width:min(560px,94vw);
      transform:translateX(100%);transition:transform .22s cubic-bezier(.4,0,.2,1);
      background:var(--bg-surface);border-left:1px solid var(--border-strong);
      box-shadow:-8px 0 32px rgba(0,0,0,.45);z-index:1001;display:flex;
      flex-direction:column}
    .help-drawer-host[data-open="true"] .help-drawer{transform:translateX(0)}
    .help-drawer-host[data-open="true"] .help-drawer-backdrop{opacity:1;
      pointer-events:auto}
    .help-drawer-head{display:flex;align-items:center;gap:10px;padding:12px 16px;
      border-bottom:1px solid var(--border);background:var(--bg-raised)}
    .help-drawer-title{font:500 14px/1 'Space Grotesk',sans-serif;color:var(--fg-1)}
    .help-drawer-sub{font:400 12px/1 'JetBrains Mono',monospace;color:var(--fg-3)}
    .help-drawer-close{margin-left:auto;background:none;border:1px solid var(--border);
      color:var(--fg-2);border-radius:6px;width:30px;height:30px;cursor:pointer;
      font-size:18px;line-height:1}
    .help-drawer-close:hover{color:var(--fg-1);border-color:var(--border-strong)}
    .help-drawer-frame{flex:1;border:0;width:100%;background:var(--bg-base)}
  </style>
  <div class="help-drawer-host" id="workspace-help-host"
       data-testid="workspace-help-host" data-open="false"
       data-authority-role="server_declared">
    <div class="help-drawer-backdrop" data-testid="workspace-help-backdrop"
         onclick="companionHelp.close()"></div>
    <aside class="help-drawer" id="workspace-help-drawer"
           data-testid="workspace-help-drawer" role="dialog" aria-modal="true"
           aria-label="Companion UI help">
      <div class="help-drawer-head">
        <span class="help-drawer-title">Companion UI · Help</span>
        <span class="help-drawer-sub">served at /help</span>
        <button type="button" class="help-drawer-close"
                data-testid="workspace-help-close" aria-label="Close help"
                onclick="companionHelp.close()">&times;</button>
      </div>
      <iframe class="help-drawer-frame" id="workspace-help-frame"
              data-testid="workspace-help-frame" title="Companion UI help guide"
              data-src="/help" loading="lazy"></iframe>
    </aside>
  </div>
  <script>
  (function() {
    var host  = document.getElementById('workspace-help-host');
    var frame = document.getElementById('workspace-help-frame');
    var toggle = document.querySelector('[data-testid="workspace-help-toggle"]');
    if (!host || !frame) { return; }
    function setExpanded(state) {
      if (toggle) { toggle.setAttribute('aria-expanded', state ? 'true' : 'false'); }
    }
    function handleEscape(ev) {
      if (ev.key === 'Escape' && host.getAttribute('data-open') === 'true') {
        window.companionHelp.close();
      }
    }
    function installHelpFrameEscapeHandling() {
      try {
        var frameWindow = frame.contentWindow;
        var frameDocument = frameWindow ? frameWindow.document : null;
        if (!frameDocument || frameDocument.__companionHelpEscapeInstalled) { return; }
        frameDocument.addEventListener('keydown', handleEscape);
        frameDocument.__companionHelpEscapeInstalled = true;
      } catch (e) {
        // Same-origin is expected for /help; if that contract changes, the
        // parent document Escape handler still covers shell focus.
      }
    }
    frame.addEventListener('load', installHelpFrameEscapeHandling);
    window.companionHelp = {
      open: function() {
        // Lazy-load the guide on first open (server declares the content).
        if (!frame.getAttribute('src')) { frame.setAttribute('src', frame.dataset.src); }
        installHelpFrameEscapeHandling();
        host.setAttribute('data-open', 'true');
        setExpanded(true);
      },
      close: function() {
        host.setAttribute('data-open', 'false');
        setExpanded(false);
        if (toggle) { try { toggle.focus(); } catch (e) {} }
      },
      toggle: function() {
        if (host.getAttribute('data-open') === 'true') { this.close(); }
        else { this.open(); }
      }
    };
    document.addEventListener('keydown', handleEscape);
  }());
  </script>"""


def render_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: Optional[dict] = None,
    error: str = "",
    orientation: Optional[dict] = None,
    orientation_error: str = "",
    orientation_vault_browser: Optional[dict] = None,
    orientation_vault_browser_error: str = "",
    production_profile: bool = False,
    diagnostics: bool = False,
    ambient_refresh_enabled: bool = False,
    page_origin_hostname: str = "",
) -> str:
    """Render the workspace dev page as a Companion UI visual shell.

    Pure function — no network calls, no file I/O.
    All user-supplied values are HTML-escaped.

    This is the first visual-alignment pass (not production UI). It uses
    Yggdrasil design tokens and the workspace region contract from
    real_note_workspace_shell.py. Canvas body-edit and Panel execution
    are not implemented; the agent rail is a placeholder.

    Entry-state resolution (#1783) wraps — does not replace — the
    orientation/workspace branch below: the resolved state is declared on the
    shell root (`<body data-entry-state=…>`) and the UI never re-derives it.
    """
    entry_resolution = resolve_entry_state(
        note_path=note_path,
        note_loaded=fields is not None,
        error=error,
        orientation=orientation,
        orientation_error=orientation_error,
    )
    if orientation is not None and fields is None and not error:
        return _render_orientation_index_html(
            api_base_url=api_base_url,
            note_path=note_path,
            orientation=orientation,
            vault_browser=orientation_vault_browser,
            vault_browser_error=orientation_vault_browser_error,
            production_profile=production_profile,
            diagnostics=diagnostics,
            ambient_refresh_enabled=ambient_refresh_enabled,
            entry_resolution=entry_resolution,
        )

    content_section = ""
    if error:
        content_section = _render_error_section(
            error,
            entry_state=entry_resolution.state,
            page_origin_hostname=page_origin_hostname,
        )
    elif fields is not None:
        content_section = _render_note_section(fields)
    # When the runtime is unreachable the error banner already carries the only
    # truthful affordances (Retry, System map). The vault-setup form (open /
    # initialize / recent / settings flags) is a false affordance — the runtime
    # cannot process an open/init while it is down — so it is suppressed here to
    # match the designed "Vault unreachable" / "wrong device" entry state
    # (#2123 AC1, #2124; open-questions Q24). Server declares, UI renders: this
    # gates only on the server-declared error, it does not re-classify state.
    runtime_unreachable = _is_runtime_unreachable(error)
    vault_settings_panel_html = "" if runtime_unreachable else vault_settings_panel_markup()
    vault_settings_panel_js = "" if runtime_unreachable else vault_settings_panel_script()
    # Live co-authoring wiring is gated by the server-declared canvas flag,
    # matching _render_note_section's guard derivation. With no fields (error /
    # orientation) the canvas surface is absent, so the script is not emitted.
    canvas_enabled = bool(fields.get("guard_canvas_enabled", True)) if fields is not None else False
    # Residual ambient layer (#1784, SEP-02): after entry.resume the document
    # anchor opens in shell_active with the caret echo and marginalia dots
    # persisting (CONTINUITY_AND_DECAY.md §Ambient Persistence After Re-entry).
    # Dismissal never erases unresolved tension. Styles are inline so this
    # region stays self-contained next to the document column.
    residual_ambient_html = ""
    if entry_resolution.state == "shell_active" and fields is not None:
        residual_ambient_html = """
  <aside class="reentry-ambient" data-region="reentry-ambient" data-testid="reentry-ambient"
    data-unresolved-tension="preserved" aria-hidden="true"
    style="position:fixed;left:12px;bottom:20px;z-index:4;display:flex;flex-direction:column;align-items:center;gap:6px;pointer-events:none;">
    <span data-testid="reentry-caret-echo" style="display:block;width:2px;height:14px;background:var(--accent);opacity:0.6;"></span>
    <span data-testid="reentry-marginalia-dot" style="display:block;width:5px;height:5px;border-radius:50%;background:var(--accent);opacity:0.45;"></span>
    <span data-testid="reentry-marginalia-dot" style="display:block;width:5px;height:5px;border-radius:50%;background:var(--accent);opacity:0.30;"></span>
    <span data-testid="reentry-marginalia-dot" style="display:block;width:5px;height:5px;border-radius:50%;background:var(--accent);opacity:0.18;"></span>
  </aside>"""
    title_suffix = "PROD" if production_profile else "DEV"
    dev_chip = "" if production_profile else '<span class="dev-chip">DEV / not production</span>'
    production_static_link = (
        '<link rel="stylesheet" href="/static/companion-workspace.css">'
        if production_profile
        else ""
    )
    # System map overlay (#1787, SEP-05; spec §Resolved Q4): pull-based —
    # opened only by explicit `map.open` affordances (the topbar icon on the
    # shell; the calm affordance on the no_vault error page). On the active
    # workspace shell every routable surface is live; on the error page only
    # the Vault Browser truthfully remains reachable.
    map_available_routes: tuple[str, ...] = (
        (
            "anchor",
            "vault",
            "panel",
            "palette",
            "memory",
            "capture",
            "receipts",
            "settings",
        )
        if fields is not None
        else ()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion UI — Real-Note Workspace [{title_suffix}]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;1,400&family=JetBrains+Mono:wght@400;500&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
  {production_static_link}
  <style>
    /* Yggdrasil design tokens (subset inlined for offline resilience) */
    :root {{
      --bg-base:       #070b12;
      --bg-surface:    #0c1220;
      --bg-raised:     #111a2e;
      --bg-overlay:    #162038;
      --fg-1:          #dce8f0;
      --fg-2:          #7a9ab8;
      --fg-3:          #3d5570;
      --border:        #152030;
      --border-strong: #1e3050;
      --border-focus:  #00d4e8;
      --accent:        #d4a843;
      --accent-dim:    #80621a;
      --accent-muted:  #2a1e06;
      --cyan:          #00d4e8;
      --cyan-dim:      #007a8a;
      --cyan-muted:    #001e28;
      --vault:         #39e87d;
      --vault-dim:     #1a7840;
      --vault-muted:   #041a10;
      --agent:         #4a9eff;
      --agent-dim:     #1e5a9a;
      --agent-muted:   #051228;
      --amber:         #f09030;
      --amber-dim:     #805010;
      --amber-muted:   #1a0e02;
      --destructive:      #ff3d3d;
      --destructive-dim:  #8a1a1a;
      --destructive-muted:#160404;
      --au-canonical:  var(--vault);
      --au-projection: var(--cyan);
      --au-proposal:   var(--agent);
      --au-confirm:    var(--accent);
      --au-receipt:    #b98be0;
      --au-local:      #6b7a90;
      --au-blocked:    var(--destructive);
      --font-display:  'EB Garamond', Georgia, serif;
      --font-ui:       'Space Grotesk', system-ui, sans-serif;
      --font-mono:     'JetBrains Mono', 'Fira Code', ui-monospace, monospace;
      --text-xs:   0.6875rem;
      --text-sm:   0.8125rem;
      --text-base: 0.9375rem;
      --text-xl:   1.5rem;
      --text-2xl:  2rem;
      --radius-sm: 2px;
      --radius-md: 4px;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html {{ font-size: 16px; -webkit-font-smoothing: antialiased; }}
    body {{
      background: var(--bg-base);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-base);
      line-height: 1.55;
      /* §3.3 scroll ownership — the app shell is exactly one viewport tall and
         owns no page scroll; the central note surface owns the reading scroll. */
      height: 100dvh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}

    /* ---- Top bar ---- */
    .topbar {{
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 20px;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .topbar-api {{
      display: flex;
      align-items: center;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
      flex: 1;
      min-width: 0;
    }}
    .topbar-api .api-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      flex-shrink: 0;
    }}
    .topbar-api .api-url {{
      color: var(--fg-2);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    /* #1418 — dev/operator harness chrome is hidden in the default human
       workspace and only revealed in diagnostics mode (?diagnostics=1). The
       elements stay in the DOM for operator access + data-* compatibility. */
    body[data-diagnostics="false"] .topbar,
    body[data-diagnostics="false"] .dev-controls-disclosure,
    body[data-diagnostics="false"] .workspace-dev-ribbon,
    body[data-diagnostics="false"] .dev-chip {{
      display: none;
    }}
    .dev-chip {{
      display: inline-block;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.07em;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: var(--radius-sm);
      background: rgba(240,144,48,0.08);
      border: 1px solid rgba(240,144,48,0.35);
      color: #f09030;
      flex-shrink: 0;
    }}

    /* ---- Load form ---- */
    .load-bar {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 20px;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .load-bar label {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      flex-shrink: 0;
    }}
    .load-bar input[type=text] {{
      flex: 1;
      min-width: 0;
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      padding: 5px 10px;
      outline: none;
    }}
    .load-bar input[type=text]:focus {{
      border-color: var(--border-focus);
      box-shadow: 0 0 0 1px var(--border-focus);
    }}
    .load-bar button {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      padding: 5px 14px;
      cursor: pointer;
      flex-shrink: 0;
    }}
    .load-bar button:hover {{ border-color: var(--cyan); color: var(--cyan); }}

    /* ---- Dev controls disclosure (#1361) ---- */
    .dev-controls-disclosure {{ margin: 0; padding: 0; }}
    .dev-controls-disclosure > summary.dev-controls-summary {{
      display: inline-block;
      cursor: pointer;
      color: var(--fg-3);
      font-size: var(--text-xs);
      font-family: var(--font-mono);
      padding: 2px 8px;
      user-select: none;
    }}

    /* ---- Note body read-only affordance (#1361) ---- */
    .note-body-readonly-indicator {{
      display: inline-block;
      font-size: var(--text-xs);
      font-family: var(--font-mono);
      color: var(--fg-3);
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 1px 6px;
      margin-bottom: 8px;
      cursor: default;
    }}
    .note-body-readonly-reason {{
      font-size: var(--text-xs);
      color: var(--fg-2);
      margin-bottom: 8px;
    }}
    .note-body-readonly-reason[hidden] {{ display: none; }}

    /* ---- Frontmatter disclosure (#1361) ---- */
    .frontmatter-disclosure > summary.frontmatter-summary {{
      cursor: pointer;
      font-size: var(--text-xs);
      color: var(--fg-3);
      font-family: var(--font-mono);
      user-select: none;
      list-style: none;
    }}
    .frontmatter-disclosure > summary.frontmatter-summary::before {{
      content: "▸ ";
      font-size: 0.7em;
    }}
    .frontmatter-disclosure[open] > summary.frontmatter-summary::before {{
      content: "▾ ";
    }}

    /* ---- Vault browser calm provenance (#1361) ---- */
    .vault-browser-provenance-calm {{
      font-size: var(--text-xs);
      color: var(--fg-3);
      display: block;
      padding: 4px 10px 6px;
    }}
    .vault-browser-hidden-count {{
      font-size: var(--text-xs);
      color: var(--fg-3);
      padding: 2px 10px 4px;
      display: block;
    }}
    /* #1417 — raw kind/review/trust metadata must not show as visible row text.
       Keep the elements in the DOM (data-* compatibility) but hide them; the
       inspector/disclosure carries the detail. */
    .note-badge--nav-hidden {{ display: none; }}
    /* #1417 — the raw zone value (e.g. 'inbox', '⚙ System') is navigation noise;
       folder grouping already supplies path context. Hide it from row text. */
    .vault-browser-zone-label {{ display: none; }}

    /* ---- Error state ---- */
    .error-state {{
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin: 20px;
      padding: 12px 16px;
      background: var(--destructive-muted);
      border: 1px solid rgba(255,61,61,0.3);
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
    }}
    .error-label {{
      color: var(--destructive);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      font-size: var(--text-xs);
      flex-shrink: 0;
    }}
    .error-message {{ color: var(--fg-2); }}
    .error-message code {{ background: none; border: none; padding: 0; color: var(--fg-1); }}
    .note-not-found-state {{
      background: rgba(212,168,67,0.08);
      border-color: rgba(212,168,67,0.35);
    }}
    .note-not-found-state .error-label {{ color: var(--accent); }}

    /* ---- Workspace layout ---- */
    .workspace-layout {{
      display: flex;
      flex: 1;
      min-height: 0;
      overflow: hidden;
    }}
    /* Left-pane layout: vault browser left, note center, agent-rail right */
    .workspace-layout--three-col {{
      display: grid;
      grid-template-columns: 280px 1fr 320px;
      grid-template-rows: 1fr;
    }}
    .vault-browser-left-pane {{
      background: var(--bg-surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      min-height: 0;
      overflow-y: auto;
      padding: 12px 8px;
    }}
    /* §4 — single adaptive left context panel: mode switcher + mode regions. */
    .left-panel-mode-switcher {{
      align-items: center;
      border-bottom: 1px solid var(--border);
      display: flex;
      flex-shrink: 0;
      gap: 2px;
      margin-bottom: 8px;
      padding-bottom: 6px;
    }}
    .left-panel-mode-tab {{
      background: none;
      border: none;
      border-radius: var(--radius-sm);
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 3px 8px;
    }}
    .left-panel-mode-tab[aria-selected="true"] {{
      background: var(--bg-raised);
      color: var(--fg-1);
    }}
    .left-panel-collapse {{
      background: none;
      border: none;
      color: var(--fg-3);
      cursor: pointer;
      margin-left: auto;
      padding: 3px 6px;
    }}
    .left-panel-mode {{
      display: flex;
      flex: 1;
      flex-direction: column;
      min-height: 0;
    }}
    .left-panel-mode[hidden] {{ display: none; }}
    .left-panel-context-row {{
      display: flex;
      gap: 8px;
      justify-content: space-between;
      padding: 4px 2px;
    }}
    .left-panel-context .lpc-label {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .left-panel-context .lpc-value {{
      color: var(--fg-2);
      font-size: var(--text-xs);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .left-panel-context-empty {{
      color: var(--fg-3);
      font-size: var(--text-sm);
      margin-top: 8px;
    }}
    .left-panel-reopen {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: pointer;
      font-size: var(--text-xs);
      padding: 6px 10px;
    }}
    .left-panel-reopen[hidden] {{ display: none; }}
    /* §4 — the outline now lives in the left panel (outline mode), so the
       central reading layout is a single column. Double-class selector beats
       the 2-column .note-reading-layout rule from note_outline_css(). */
    .note-reading-layout.note-reading-layout--single {{
      grid-template-columns: minmax(0, 1fr);
    }}
    /* Collapsed mode maximizes reading: hide switcher + mode regions, keep the
       reopen affordance, and shrink the panel to a narrow rail. */
    .vault-browser-left-pane[data-left-panel-mode="collapsed"] {{
      align-items: center;
      overflow: visible;
      padding: 12px 6px;
    }}
    .vault-browser-left-pane[data-left-panel-mode="collapsed"] .left-panel-mode-switcher,
    .vault-browser-left-pane[data-left-panel-mode="collapsed"] .left-panel-mode {{
      display: none;
    }}
    .workspace-main {{
      flex: 1;
      min-width: 0;
      min-height: 0;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .workspace-header-strip {{
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
      color: var(--fg-3);
      flex-shrink: 0;
      height: 32px;
      min-height: 32px;
      overflow: visible;
      position: relative;
      white-space: nowrap;
      z-index: 20;
    }}
    .workspace-header-row {{
      align-items: center;
      display: flex;
      gap: 10px;
      height: 32px;
      padding: 0 14px;
      width: 100%;
    }}
    .workspace-wordmark {{
      color: color-mix(in srgb, var(--accent) 72%, var(--fg-3));
      flex-shrink: 0;
      font-family: var(--font-display);
      font-size: 16px;
      line-height: 1;
      text-decoration: none;
    }}
    .workspace-vault-chip,
    .workspace-runtime-pill,
    .workspace-freshness,
    .workspace-quick-open,
    .workspace-browse-vault,
    .workspace-dev-ribbon {{
      align-items: center;
      display: inline-flex;
      flex-shrink: 0;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 1;
    }}
    .workspace-vault-chip {{
      color: var(--fg-2);
      gap: 6px;
      text-decoration: none;
    }}
    .workspace-vault-dot {{
      background: var(--cyan);
      border-radius: 999px;
      display: inline-block;
      height: 6px;
      width: 6px;
    }}
    .workspace-vault-chip[data-state="unresolved"] .workspace-vault-dot {{
      background: var(--accent);
    }}
    .workspace-vault-chip[data-state="unreachable"] .workspace-vault-dot {{
      background: var(--destructive);
    }}
    .workspace-vault-chip[data-state="unreachable"] {{
      color: var(--destructive);
    }}
    .workspace-anchor-pill {{
      align-items: center;
      border: 0;
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      display: inline-flex;
      flex-shrink: 1;
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      line-height: 1;
      max-width: 220px;
      min-width: 0;
      overflow: hidden;
      padding: 2px 6px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .workspace-posture-pill {{
      align-items: center;
      color: var(--fg-3);
      display: inline-flex;
      flex-shrink: 0;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      line-height: 1;
      text-transform: uppercase;
    }}
    .workspace-surface-icons {{
      align-items: center;
      display: inline-flex;
      flex-shrink: 0;
      gap: 6px;
    }}
    .workspace-surface-icon {{
      align-items: center;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: pointer;
      display: inline-flex;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      height: 22px;
      justify-content: center;
      line-height: 1;
      width: 24px;
    }}
    .workspace-surface-icon:hover {{
      border-color: var(--border-strong);
      color: var(--fg-1);
    }}
    .workspace-runtime-status {{
      flex-shrink: 0;
      position: relative;
    }}
    .workspace-runtime-status summary {{
      list-style: none;
    }}
    .workspace-runtime-status summary::-webkit-details-marker {{
      display: none;
    }}
    .workspace-runtime-pill {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: pointer;
      gap: 6px;
      height: 22px;
      padding: 0 8px;
    }}
    .workspace-runtime-human-label {{
      color: var(--fg-3);
    }}
    .workspace-runtime-status-popover {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      box-shadow: 0 18px 40px rgba(0, 0, 0, 0.35);
      display: none;
      min-width: 360px;
      padding: 10px 12px;
      position: absolute;
      top: 28px;
      z-index: 30;
    }}
    .workspace-runtime-status[open] .workspace-runtime-status-popover {{
      display: grid;
      gap: 6px;
    }}
    .workspace-runtime-popover-row {{
      align-items: baseline;
      display: grid;
      gap: 10px;
      grid-template-columns: minmax(130px, 0.8fr) minmax(120px, 1fr);
    }}
    .workspace-runtime-popover-key {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .workspace-runtime-popover-row code {{
      background: none;
      border: none;
      color: var(--fg-2);
      font-size: var(--text-xs);
      overflow: hidden;
      padding: 0;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .workspace-freshness {{
      color: var(--fg-3);
    }}
    .workspace-header-spacer {{
      flex: 1 1 auto;
      min-width: 12px;
    }}
    .workspace-quick-open,
    .workspace-browse-vault {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      height: 24px;
      gap: 6px;
      padding: 0 8px;
    }}
    .workspace-quick-open {{
      cursor: default;
      opacity: 0.46;
      padding: 0 6px;
    }}
    .workspace-quick-open span {{
      display: none;
    }}
    .workspace-quick-open kbd {{
      background: transparent;
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .workspace-browse-vault {{
      cursor: pointer;
      font-family: var(--font-ui);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }}
    .workspace-browse-vault:hover {{
      border-color: var(--cyan);
      color: var(--cyan);
    }}
    .workspace-dev-ribbon {{
      background: rgba(240,144,48,0.08);
      border: 1px solid rgba(240,144,48,0.35);
      border-radius: var(--radius-sm);
      color: #f09030;
      height: 28px;
      letter-spacing: 0.07em;
      padding: 0 8px;
      text-transform: uppercase;
    }}
    .runtime-safety-strip {{
      align-items: center;
      background: rgba(17,26,46,0.65);
      border-bottom: 1px solid var(--border);
      color: var(--fg-2);
      display: flex;
      flex-wrap: wrap;
      gap: 6px 12px;
      padding: 8px 24px;
    }}
    .safety-item {{
      align-items: baseline;
      display: inline-flex;
      gap: 5px;
      min-width: 0;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .safety-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .safety-item code {{
      background: none;
      border: none;
      color: var(--fg-2);
      max-width: 18ch;
      overflow: hidden;
      padding: 0;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .safety-sep {{ color: var(--border-strong); }}

    /* ---- Shell error surfaces (#1341) ---- */
    .workspace-vault-unreachable-banner {{
      align-items: center;
      background: color-mix(in srgb, var(--destructive) 8%, var(--bg-surface));
      border-left: 2px solid var(--destructive);
      color: var(--fg-2);
      display: flex;
      flex-shrink: 0;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 12px;
      height: 32px;
      min-height: 32px;
      padding: 0 16px;
    }}
    .banner-retry-link {{
      color: var(--fg-2);
      text-decoration: underline;
      text-underline-offset: 2px;
    }}
    .workspace-read-only-pill {{
      align-items: center;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: default;
      display: inline-flex;
      float: right;
      font-family: var(--font-mono);
      font-size: 11px;
      height: 24px;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
      padding: 0 8px;
    }}
    .workspace-note-not-found {{
      align-items: flex-start;
      display: flex;
      flex-direction: column;
      gap: 10px;
      padding: 32px 24px;
    }}
    .workspace-note-not-found h1 {{
      color: var(--fg-1);
      font-family: var(--font-display);
      font-size: var(--text-xl);
      margin: 0;
    }}
    .workspace-note-not-found code {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
    }}
    .workspace-note-not-found p {{
      color: var(--fg-2);
      font-size: var(--text-sm);
      margin: 0;
    }}
    .not-found-actions {{
      display: flex;
      gap: 8px;
      margin-top: 4px;
    }}
    .not-found-browse,
    .not-found-last-note {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      height: 32px;
      padding: 0 14px;
    }}

    /* ---- Note header ---- */
    .note-header {{
      padding: 20px 24px 12px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .note-title {{
      font-family: var(--font-display);
      font-size: var(--text-2xl);
      font-weight: 400;
      line-height: 1.2;
      color: var(--fg-1);
      margin-bottom: 8px;
    }}
    .workspace-breadcrumb {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px 6px;
      font-family: var(--font-mono);
      font-size: 12px;
      color: var(--fg-3);
      margin-top: 4px;
      margin-bottom: 6px;
    }}
    .breadcrumb-path {{ color: var(--fg-3); }}
    .breadcrumb-sep {{ color: var(--border-strong); }}
    .breadcrumb-meta-item {{ color: var(--fg-3); }}
    .workspace-properties-disclosure {{ display: contents; }}
    .workspace-properties-disclosure summary {{
      display: inline;
      cursor: pointer;
      color: var(--fg-3);
      list-style: none;
      font-family: var(--font-mono);
      font-size: 12px;
    }}
    .workspace-properties-disclosure summary::-webkit-details-marker {{ display: none; }}
    .workspace-properties-disclosure[open] summary {{ color: var(--fg-2); }}
    .properties-disclosure-body {{
      position: absolute;
      z-index: 20;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      padding: 12px 14px;
      min-width: 280px;
      max-width: 480px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.18);
    }}
    .breadcrumb-identity-chips {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px 8px;
      margin-bottom: 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .note-provenance {{
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 4px 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-3);
    }}
    .prov-item {{ display: inline-flex; align-items: baseline; gap: 4px; }}
    .artifact-identity-pill, .content-hash-pill {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 2px 6px;
    }}
    .artifact-identity-pill[data-identity-state^="unresolved"] {{
      border-color: rgba(212,168,67,0.35);
    }}
    .identity-meta {{
      color: var(--fg-3);
      font-size: var(--text-xs);
    }}
    .identity-caution {{
      align-items: baseline;
      background: rgba(212,168,67,0.08);
      border: 1px solid rgba(212,168,67,0.35);
      border-radius: var(--radius-sm);
      color: var(--accent);
      display: inline-flex;
      gap: 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      margin-top: 6px;
      padding: 4px 7px;
    }}
    .identity-caution small {{
      color: var(--fg-3);
      font-size: var(--text-xs);
    }}
    .prov-label {{
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--fg-3);
    }}
    .prov-item code {{
      background: none;
      border: none;
      padding: 0;
      font-size: var(--text-xs);
      color: var(--fg-2);
    }}
    .prov-sep {{ color: var(--border-strong); }}

    /* ---- Read-only properties ---- */
    .vault-properties {{
      margin: 14px 24px 0;
      padding: 10px 12px;
      background: color-mix(in srgb, var(--bg-raised) 78%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-2);
    }}
    .vault-properties-header {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .vault-properties-label {{
      color: var(--fg-3);
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .vault-properties-mode {{
      color: var(--fg-3);
    }}
    .vault-properties-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px 14px;
      margin: 0;
    }}
    .vault-property {{
      display: inline-flex;
      align-items: baseline;
      gap: 6px;
      min-width: min(180px, 100%);
    }}
    .vault-property dt {{
      color: var(--fg-3);
      margin: 0;
    }}
    .vault-property dd {{
      display: inline-flex;
      flex-wrap: wrap;
      gap: 4px;
      margin: 0;
    }}
    .vault-property-tag, .vault-property-value {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 1px 7px;
      background: var(--bg);
      color: var(--fg-1);
    }}
    .vault-properties-invalid {{
      border-color: rgba(212,168,67,0.35);
    }}
    .vault-properties-diagnostics {{
      margin: 0;
      padding-left: 18px;
      color: var(--accent);
    }}

    /* ---- Note body ---- */
    /* §3.3 — the note body is the single primary scroll container. It owns the
       reading scroll (min-height:0 + overflow-y:auto) and reserves >=96px of
       bottom breathing room so the last heading/paragraph is never clipped. */
    .note-body {{
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      padding: 24px 24px 96px;
    }}
    .note-body-empty {{
      background: color-mix(in srgb, var(--bg-raised) 72%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      margin: 20px auto;
      max-width: var(--display-reading-width, 68ch);
      padding: 18px 22px;
    }}
    .note-body-empty h2 {{
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-lg);
      font-weight: 600;
      margin: 0 0 8px;
    }}
    .note-body-empty p {{
      margin: 0;
    }}
    .tts-readback-controls {{
      margin: 0 auto 8px;
      max-width: var(--display-reading-width, 68ch);
      padding: 0 32px;
    }}
    .tts-readback-summary {{
      color: var(--fg-3);
      cursor: pointer;
      display: inline-flex;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      list-style: none;
      padding: 2px 0;
    }}
    .tts-readback-summary::-webkit-details-marker {{
      display: none;
    }}
    .tts-readback-summary::before {{
      color: var(--fg-3);
      content: "▸";
      margin-right: 5px;
    }}
    .tts-readback-controls[open] .tts-readback-summary::before {{
      content: "▾";
    }}
    .tts-readback-panel {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding-top: 6px;
    }}
    .tts-readback-controls button,
    .note-edit-readback {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-1);
      cursor: pointer;
      font: inherit;
      font-size: var(--text-xs);
      min-height: 26px;
      padding: 2px 8px;
    }}
    .tts-readback-controls button:hover,
    .note-edit-readback:hover {{
      border-color: var(--accent);
    }}
    .tts-readback-controls button:disabled,
    .note-edit-readback:disabled {{
      cursor: not-allowed;
      opacity: 0.5;
    }}
    .tts-rate-control {{
      align-items: center;
      color: var(--fg-2);
      display: inline-flex;
      gap: 6px;
      font-size: var(--text-xs);
    }}
    .tts-rate-control select {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-1);
      font: inherit;
      min-height: 26px;
      padding: 2px 6px;
    }}
    .tts-readback-status {{
      color: var(--fg-3);
      font-size: var(--text-xs);
    }}
    .tts-plan-inspection {{
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      font-size: var(--text-xs);
      margin: 0 auto 12px;
      max-width: var(--display-reading-width, 68ch);
      padding: 8px 32px;
    }}
    .tts-plan-inspection[hidden] {{
      display: none;
    }}
    .tts-plan-text {{
      color: var(--fg-1);
      margin-bottom: 6px;
    }}
    .tts-plan-segments,
    .tts-plan-warnings {{
      margin: 4px 0;
      padding-left: 18px;
    }}
    .tts-warning {{
      color: var(--accent);
    }}
    .display-preferences {{
      align-items: center;
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      margin: 0 auto 12px;
      max-width: var(--display-reading-width, 68ch);
      padding: 0 32px;
    }}
    .display-preference-control,
    .display-preference-toggle {{
      align-items: center;
      color: var(--fg-2);
      display: inline-flex;
      gap: 6px;
      font-size: var(--text-xs);
    }}
    .display-preference-control select {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      color: var(--fg-1);
      font: inherit;
      min-height: 26px;
      padding: 2px 6px;
    }}
    .display-preference-toggle input {{
      accent-color: var(--accent);
    }}
    /* ---- Direct human note editor (Read <-> Edit) ---- */
    .note-edit-bar {{
      max-width: 68ch;
      margin: 0 auto 10px;
      padding: 0 32px;
    }}
    .note-edit-summary {{
      display: inline-flex;
      list-style: none;
    }}
    .note-edit-summary::-webkit-details-marker {{
      display: none;
    }}
    .note-edit-bar[open] .note-edit-summary {{
      margin-bottom: 8px;
    }}
    .note-edit-toggle, .note-edit-save, .note-edit-cancel {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm);
      color: var(--fg-1);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      min-height: 26px;
      padding: 2px 8px;
    }}
    .note-edit-toggle:hover, .note-edit-save:hover, .note-edit-cancel:hover {{
      border-color: var(--accent);
    }}
    .note-edit-save {{
      background: color-mix(in srgb, var(--accent) 18%, var(--bg-raised));
      font-weight: 600;
    }}
    .note-edit-actions {{ display: flex; align-items: center; gap: 8px; }}
    .note-edit-status {{ color: var(--fg-3); font-family: var(--font-mono); font-size: var(--text-xs); }}
    .note-edit-status.ok {{ color: var(--cyan); }}
    .note-edit-status.error {{ color: var(--destructive); }}
    .note-source-editor {{
      background: var(--bg-base);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      box-sizing: border-box;
      color: var(--fg-1);
      display: block;
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      line-height: 1.6;
      margin: 0 auto;
      max-width: 68ch;
      min-height: 60vh;
      padding: 24px 32px;
      resize: vertical;
      width: 100%;
    }}
    .note-source-editor[hidden] {{ display: none; }}
    .note-source-editor:focus {{ outline: 1px solid var(--border-focus); }}
    /* Design review §6.1 — body column is a reading surface, not a card.
       Background matches the page; no inset border; line-length capped at 68ch.
       §3.3/§7 — the reading column does not own a second nested scroll and is
       not height-clamped; it grows naturally inside the .note-body scroll. */
    .note-body-content {{
      background: var(--bg-base);
      border: none;
      border-radius: 0;
      margin: 0 auto;
      max-width: var(--display-reading-width, 68ch);
      min-height: 0;
      padding: 40px 32px 48px;
      font-family: var(--font-ui);
      font-size: var(--display-font-size, var(--text-base));
      color: var(--fg-1);
      /* §6.3 — paragraph rhythm */
      line-height: var(--display-line-height, 1.65);
      word-break: break-word;
    }}
    body.display-pref-focus .vault-browser-left-pane,
    body.display-pref-focus .agent-rail {{
      opacity: 0.54;
    }}
    /* Design review §6.2 — heading scale (sharp step-down between levels). */
    .vault-markdown-rendered h1 {{
      font-family: var(--font-display);
      font-size: 40px;
      line-height: 44px;
      font-weight: 400;
      letter-spacing: 0;
      color: var(--fg-1);
      margin: 0 0 32px;
    }}
    .vault-markdown-rendered h2 {{
      font-family: var(--font-ui);
      font-size: 22px;
      line-height: 28px;
      font-weight: 600;
      letter-spacing: 0;
      color: var(--fg-1);
      margin: 40px 0 12px;
      padding-bottom: 6px;
      border-bottom: 1px solid var(--border);
      max-width: 80%;
    }}
    .vault-markdown-rendered h3 {{
      font-family: var(--font-ui);
      font-size: 16px;
      line-height: 22px;
      font-weight: 600;
      color: var(--fg-1);
      margin: 28px 0 8px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .vault-markdown-rendered h3::before {{
      content: "";
      display: inline-block;
      flex: 0 0 auto;
      width: 4px;
      height: 14px;
      background: var(--accent-dim);
      border-radius: 1px;
    }}
    .vault-markdown-rendered h4 {{
      font-family: var(--font-mono);
      font-size: 12px;
      line-height: 16px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-2);
      margin: 20px 0 4px;
    }}
    .vault-markdown-rendered h5,
    .vault-markdown-rendered h6 {{
      font-family: var(--font-mono);
      font-size: 11px;
      line-height: 14px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--fg-3);
      margin: 16px 0 4px;
    }}
    /* §6.3 — block rhythm */
    .vault-markdown-rendered p,
    .vault-markdown-rendered ul,
    .vault-markdown-rendered ol,
    .vault-markdown-rendered blockquote,
    .vault-markdown-rendered table,
    .vault-markdown-rendered pre {{
      margin: 0 0 16px;
    }}
    .vault-markdown-rendered ul,
    .vault-markdown-rendered ol {{
      padding-left: 24px;
    }}
    .vault-markdown-rendered li + li {{
      margin-top: 4px;
    }}
    /* §6.5 — blockquote: rule + muted text, no fill. A blockquote is not a callout. */
    .vault-markdown-rendered blockquote {{
      border-left: 2px solid var(--border-strong);
      background: transparent;
      color: var(--fg-2);
      padding: 2px 0 2px 20px;
      margin: 0 0 16px;
    }}
    /* §6.5 — tables: header is a label band; rows separated by a single dashed rule;
       no row striping. */
    .vault-markdown-rendered table {{
      border-collapse: collapse;
      width: 100%;
    }}
    .vault-markdown-rendered th,
    .vault-markdown-rendered td {{
      border: none;
      padding: 12px 14px;
      text-align: left;
      vertical-align: top;
    }}
    .vault-markdown-rendered th {{
      background: var(--bg-base);
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      border-bottom: 1px solid var(--border);
    }}
    .vault-markdown-rendered td {{
      border-bottom: 1px dashed var(--border);
      color: var(--fg-1);
      font-size: var(--text-sm);
      line-height: 20px;
    }}
    .vault-markdown-rendered tr:last-child td {{
      border-bottom: none;
    }}
    /* §6.4 — inline code: present but quiet. */
    .vault-markdown-rendered code {{
      font-family: var(--font-mono);
      font-size: 0.875em;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      padding: 1px 5px;
      color: var(--fg-1);
    }}
    /* §6.5 — code block: surface card, no inline-code chrome inside it. */
    .vault-markdown-rendered pre {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      overflow-x: auto;
      padding: 16px 18px;
      font-family: var(--font-mono);
      font-size: 13px;
      line-height: 20px;
      color: var(--fg-1);
    }}
    .vault-markdown-rendered pre code {{
      background: transparent;
      border: none;
      padding: 0;
      font-size: inherit;
    }}
    /* §6.5 — horizontal rule */
    .vault-markdown-rendered hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 32px 0;
    }}
    /* §6.5 — task lists: ordinary checkboxes stay read-only; runtime-declared
       Panel options can request backend checkbox projection. */
    .vault-markdown-rendered ul.task-list {{
      list-style: none;
      padding-left: 4px;
    }}
    .vault-markdown-rendered li.task-list-item {{
      position: relative;
      padding-left: 24px;
      list-style: none;
    }}
    .vault-markdown-rendered li.task-list-item > input[type="checkbox"] {{
      appearance: none;
      -webkit-appearance: none;
      position: absolute;
      left: 0;
      top: 0.32em;
      width: 14px;
      height: 14px;
      margin: 0;
      border: 1.5px solid var(--fg-3);
      border-radius: 2px;
      background: transparent;
      cursor: default;
      vertical-align: baseline;
    }}
    .vault-markdown-rendered li.task-list-item > input[data-panel-checkbox="true"] {{
      cursor: pointer;
      border-color: var(--cyan);
    }}
    .vault-markdown-rendered .panel-decision-option-label {{
      font-weight: 600;
      color: var(--fg-1);
    }}
    .vault-markdown-rendered .panel-decision-surface {{
      margin: 8px 0 12px;
      padding: 10px 12px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--bg-surface);
    }}
    .vault-markdown-rendered .panel-decision-fields {{
      display: grid;
      gap: 8px;
      margin: 0;
    }}
    .vault-markdown-rendered .panel-decision-field {{
      display: grid;
      grid-template-columns: minmax(92px, 0.28fr) 1fr;
      gap: 8px;
      align-items: start;
    }}
    .vault-markdown-rendered .panel-decision-field dt {{
      margin: 0;
      color: var(--fg-2);
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .vault-markdown-rendered .panel-decision-field dd {{
      margin: 0;
      color: var(--fg-1);
    }}
    .vault-markdown-rendered .panel-local-choice {{
      margin-left: 8px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: transparent;
      color: var(--fg-1);
      font: inherit;
      font-size: 0.84rem;
      padding: 2px 8px;
      cursor: pointer;
    }}
    .vault-markdown-rendered .panel-local-choice:hover {{
      border-color: var(--fg-3);
      background: var(--bg-raised);
    }}
    .vault-markdown-rendered .panel-decision-identity {{
      margin: 8px 0 0;
      color: var(--fg-3);
      font-size: 0.78rem;
      line-height: 1.3;
    }}
    .vault-markdown-rendered .panel-checkbox-feedback {{
      display: block;
      margin-top: 4px;
      color: var(--destructive);
      font-size: 0.84rem;
      line-height: 1.25;
    }}
    .vault-markdown-rendered li.task-list-item > input[type="checkbox"]:checked {{
      background: var(--cyan);
      border-color: var(--cyan);
    }}
    .vault-markdown-rendered li.task-list-item > input[type="checkbox"]:checked::after {{
      content: "";
      position: absolute;
      left: 4px;
      top: 1px;
      width: 4px;
      height: 8px;
      border: solid var(--bg-base);
      border-width: 0 2px 2px 0;
      transform: rotate(45deg);
    }}
    /* #1410 — completed tasks get Obsidian-style completed treatment so the
       checked state is unambiguous beyond the checkbox alone. */
    .vault-markdown-rendered li.task-list-item[data-task-state="x"],
    .vault-markdown-rendered li.task-list-item[data-task-state="X"] {{
      color: var(--fg-3);
      text-decoration: line-through;
    }}
    {note_outline_css()}
    .vault-callout {{
      --callout-rgb: 0, 212, 232;
      --callout-color: rgb(var(--callout-rgb));
      background: rgba(var(--callout-rgb), 0.08);
      border: 1px solid rgba(var(--callout-rgb), 0.25);
      border-left: 4px solid var(--callout-color);
      border-radius: var(--radius-md);
      margin: 0 0 16px;
      padding: 12px 14px;
    }}
    .vault-callout--warning {{ --callout-rgb: 212, 168, 67; }}
    .vault-callout--danger,
    .vault-callout--failure,
    .vault-callout--bug {{ --callout-rgb: 255, 61, 61; }}
    .vault-callout--success,
    .vault-callout--tip {{ --callout-rgb: 98, 208, 123; }}
    .vault-callout--question,
    .vault-callout--example {{ --callout-rgb: 74, 158, 255; }}
    .vault-callout--quote {{ --callout-rgb: 122, 154, 184; }}
    .vault-callout-header {{
      align-items: center;
      color: var(--callout-color);
      display: flex;
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      font-weight: 600;
      gap: 8px;
      line-height: 1.35;
    }}
    .vault-callout > summary.vault-callout-header {{
      cursor: pointer;
      list-style: none;
    }}
    .vault-callout > summary.vault-callout-header::-webkit-details-marker {{
      display: none;
    }}
    .vault-callout-icon {{
      align-items: center;
      border: 1px solid rgba(var(--callout-rgb), 0.4);
      border-radius: 999px;
      display: inline-flex;
      flex: 0 0 auto;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      height: 20px;
      justify-content: center;
      line-height: 1;
      width: 20px;
    }}
    .vault-callout-body {{
      margin-top: 10px;
    }}
    .vault-callout-body > :last-child {{
      margin-bottom: 0;
    }}
    {link_preview_css()}
    .vault-wikilink {{
      color: var(--cyan);
      text-decoration: none;
    }}
    /* Design review §9 — unresolved wikilink: visible without being alarming. */
    .vault-markdown-rendered .vault-wikilink.vault-wikilink-diagnostic {{
      background: transparent;
      border: none;
      padding: 0;
      color: var(--fg-2);
      font-family: inherit;
      font-size: inherit;
      text-decoration: underline dashed rgba(255, 61, 61, 0.6);
      text-underline-offset: 3px;
      display: inline;
      cursor: help;
    }}
    .failed-embed {{
      align-items: flex-start;
      background: var(--bg-surface);
      border: 1px dashed var(--border-strong);
      border-radius: 2px;
      display: flex;
      gap: 16px;
      justify-content: space-between;
      margin: 0 0 16px;
      padding: 14px 16px;
    }}
    .failed-embed-main {{
      align-items: baseline;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      min-width: 0;
    }}
    .failed-embed-tag {{
      color: var(--amber);
      font-family: var(--font-mono);
      font-size: 11px;
      letter-spacing: 0;
      line-height: 1;
    }}
    .failed-embed-message {{
      color: var(--fg-2);
      font-size: var(--text-sm);
    }}
    .failed-embed .vault-mermaid-source {{
      flex: 0 0 auto;
      margin: 0;
    }}
    .failed-embed .vault-mermaid-source > summary {{
      color: var(--accent);
      cursor: pointer;
      font-size: var(--text-sm);
      list-style: none;
    }}
    .failed-embed .vault-mermaid-source > summary::-webkit-details-marker {{
      display: none;
    }}
    .failed-embed .vault-mermaid-source[open] {{
      flex-basis: 100%;
    }}
    .failed-embed .vault-mermaid-source-code {{
      margin: 12px 0 0;
    }}
    /* #1344 — Mermaid client-render placeholder + rendered SVG holder. The
       placeholder is a quiet source preview until the runtime swaps in SVG;
       theme colors come from Mermaid's built-in dark theme (no new tokens). */
    .vault-mermaid {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      margin: 0 0 16px;
      overflow-x: auto;
      padding: 14px 16px;
    }}
    .vault-mermaid-rendered {{
      margin: 0 0 16px;
      text-align: center;
    }}
    .vault-mermaid-rendered svg {{
      height: auto;
      max-width: 100%;
    }}
    .vault-asset-diagnostic.missing-image {{
      background: transparent;
      border: 0;
      color: var(--fg-2);
      display: block;
      font-family: inherit;
      margin: 0 0 16px;
      padding: 0;
    }}
    .missing-image-box {{
      align-items: center;
      background: var(--bg-surface);
      border: 1px dashed var(--border-strong);
      border-radius: 4px;
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: 8px;
      height: 120px;
      justify-content: center;
      max-width: 100%;
      width: 100%;
    }}
    .missing-image-icon {{
      border: 1px solid var(--fg-3);
      border-radius: 2px;
      box-sizing: border-box;
      height: 20px;
      position: relative;
      width: 20px;
    }}
    .missing-image-icon::after {{
      border-bottom: 1px solid var(--fg-3);
      border-left: 1px solid var(--fg-3);
      bottom: 4px;
      content: "";
      height: 6px;
      left: 4px;
      position: absolute;
      transform: rotate(-45deg);
      width: 10px;
    }}
    .missing-image-caption {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .missing-image-alt {{
      color: var(--fg-2);
      font-size: var(--text-sm);
      margin-top: 6px;
    }}
    .vault-asset-diagnostic,
    .unsupported-block-diagnostic,
    .vault-diagnostics {{
      background: rgba(212,168,67,0.12);
      border: 1px solid rgba(212,168,67,0.35);
      border-radius: var(--radius-sm);
      color: var(--accent);
      display: inline-block;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      padding: 4px 7px;
    }}
    .unsupported-block-diagnostic,
    .vault-diagnostics {{
      display: block;
      margin: 0 0 16px;
    }}
    .vault-image {{
      border-radius: var(--radius-sm);
      display: block;
      height: auto;
      max-width: 100%;
    }}
    .suggested-insertion {{
      background: var(--amber-muted);
      border-left: 3px solid var(--amber);
      color: var(--fg-1);
      display: block;
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      margin-top: 12px;
      padding: 10px 12px;
      text-decoration: none;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .suggested-insertion-label {{
      color: var(--amber);
      display: block;
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    /* ---- Agent rail ---- */
    /* §§8–9 — compact posture chip + collapsed idle details. */
    .rail-posture {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      padding: 6px 10px;
    }}
    .rail-posture[data-rail-posture="active"] {{ color: var(--fg-1); }}
    .rail-idle-details {{
      border-top: 1px solid var(--border);
      margin-top: 4px;
    }}
    /* #1419 — deterministic collapse: hide the non-actionable cards when the
       details is closed, independent of UA details behavior. */
    .rail-idle-details:not([open]) > :not(summary) {{
      display: none;
    }}
    .rail-idle-summary {{
      color: var(--fg-3);
      cursor: pointer;
      font-size: var(--text-xs);
      list-style: none;
      padding: 6px 10px;
    }}
    .rail-idle-summary::-webkit-details-marker {{ display: none; }}
    .agent-rail {{
      width: 280px;
      flex-shrink: 0;
      background: var(--bg-surface);
      border-left: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .rail-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }}
    .rail-label {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--fg-3);
    }}
    .rail-badge {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      padding: 1px 7px;
      border-radius: var(--radius-sm);
      background: var(--agent-muted);
      border: 1px solid var(--agent-dim);
      color: var(--au-proposal);
      letter-spacing: 0.04em;
    }}
    .rail-placeholder-body {{
      flex: 1;
      padding: 16px;
      font-size: var(--text-sm);
      color: var(--fg-3);
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .rail-state-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
    }}
    .rail-state-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .rail-state-value, .rail-state-count {{
      color: var(--fg-2);
    }}
    /* ---- Commitment surface (read-only): Next (warm) / Review (cool) ---- */
    .commitments-mode {{ display: flex; flex-direction: column; gap: 12px; }}
    .commitment-group {{ display: flex; flex-direction: column; gap: 6px; }}
    .commitment-group-head {{
      display: flex; align-items: baseline; gap: 6px;
      font-family: var(--font-mono); font-size: 10px;
      letter-spacing: 0.08em; text-transform: uppercase;
    }}
    .commitment-group-label {{ white-space: nowrap; }}
    .commitment-group.g-next .commitment-group-label {{ color: var(--accent); }}
    .commitment-group.g-review .commitment-group-label {{ color: var(--fg-2); }}
    .commitment-group-sub {{
      color: var(--fg-3); white-space: nowrap; overflow: hidden;
      text-overflow: ellipsis; min-width: 0;
    }}
    .commitment-group-count {{
      margin-left: auto; color: var(--fg-3);
      border: 1px solid var(--border-strong); border-radius: var(--radius-sm);
      padding: 0 6px;
    }}
    /* Review sits in a faintly recessed well — a distinct mode of attention. */
    .commitment-group.g-review {{
      background: rgba(122,154,184,0.035);
      border: 1px solid var(--border); border-radius: var(--radius-sm);
      padding: 8px; margin: 0 -2px;
    }}
    .commitment-group-empty {{
      font-family: var(--font-mono); font-size: 10px; color: var(--fg-3);
      letter-spacing: 0.06em; padding: 2px 0 2px 10px;
      border-left: 2px solid var(--border);
    }}
    .commitment-item {{
      padding: 7px 9px; border-radius: 2px;
      border-left: 2px solid var(--border-strong); background: transparent;
    }}
    .commitment-item-top {{ display: flex; align-items: baseline; gap: 8px; }}
    .commitment-summary {{
      flex: 1; font-size: var(--text-sm); color: var(--fg-1); line-height: 1.4;
    }}
    .commitment-kind-tag {{
      flex: none; margin-top: 1px;
      font-family: var(--font-mono); font-size: 9px; letter-spacing: 0.06em;
      text-transform: uppercase; padding: 1px 5px; border-radius: var(--radius-sm);
      border: 1px solid var(--border-strong); color: var(--fg-3); white-space: nowrap;
    }}
    .commitment-target {{
      font-family: var(--font-mono); font-size: 10px; color: var(--fg-3);
      letter-spacing: 0.06em; margin-top: 4px; display: flex; align-items: center; gap: 5px;
    }}
    .commitment-arrow, .commitment-cycle {{ color: var(--fg-3); }}
    .commitment-cycle {{ font-family: var(--font-mono); font-size: 11px; margin-right: 5px; }}
    .commitment-prov {{ font-size: 11px; margin-top: 3px; line-height: 1.4; font-style: italic; }}
    /* next_action — warm, clearest (still calm) */
    .commitment-item.k-next {{ border-left-color: var(--accent); }}
    .commitment-item.k-next .commitment-summary {{ color: var(--fg-1); font-weight: 500; }}
    .commitment-item.k-next .commitment-kind-tag {{
      color: var(--accent); border-color: var(--accent-dim); background: var(--accent-muted);
    }}
    /* waiting — tracked-but-blocked: dashed, dimmer, amber */
    .commitment-item.k-wait {{ border-left: 2px dashed var(--amber-dim); opacity: 0.92; }}
    .commitment-item.k-wait .commitment-summary {{ color: var(--fg-2); font-weight: 400; }}
    .commitment-item.k-wait .commitment-kind-tag {{
      color: var(--amber); border-color: var(--amber-dim); background: var(--amber-muted);
    }}
    .commitment-item.k-wait .commitment-prov {{ color: var(--amber); }}
    /* review_return — cool, cyclical, metacognitive */
    .commitment-item.k-review {{ border-left-color: var(--fg-3); }}
    .commitment-item.k-review .commitment-summary {{ color: var(--fg-1); font-weight: 400; }}
    .commitment-item.k-review .commitment-kind-tag {{ color: var(--fg-2); border-color: var(--border-strong); }}
    .commitment-item.k-review .commitment-prov {{ color: var(--fg-3); }}
    /* empty-but-healthy — affirmative vault-green zero */
    .commitments-empty {{ display: flex; align-items: center; gap: 8px; padding: 8px 0; }}
    .commitments-empty-dot {{
      width: 6px; height: 6px; border-radius: 50%; background: var(--vault); flex: none;
    }}
    .commitments-empty-msg {{ font-size: var(--text-sm); color: var(--fg-2); }}
    /* freshness / provenance footer */
    .commitments-foot {{
      font-family: var(--font-mono); font-size: 10px; color: var(--fg-3);
      letter-spacing: 0.06em; margin-top: 4px; padding-top: 8px;
      border-top: 1px solid var(--border);
    }}
    .commitments-foot-ok {{ color: var(--vault); }}
    /* degraded / not-shown — amber, unmistakably NOT the green empty state */
    .commitments-mode[data-commitment-state="degraded"] .commitments-notice,
    .commitments-mode[data-commitment-state="not-shown"] .commitments-notice {{
      border: 1px solid var(--amber-dim); background: var(--amber-muted);
      border-radius: var(--radius-sm); padding: 8px;
      font-size: var(--text-sm); color: var(--fg-2); line-height: 1.4;
    }}
    /* ---- Resurface surface (read-only): Claude-Design visual treatment.
       Source (annotated): design handoff resurface-implementation/resurface.css ---- */
    .resurface-mode {{
      display: flex;
      flex-direction: column;
      gap: 9px;
      padding: 14px 14px 16px;
      font-family: var(--font-ui);
      color: var(--fg-2);
    }}

    .resurface-mode .rail-state-row {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      padding-bottom: 1px;
    }}
    .resurface-mode .rail-state-label {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--fg-2);
    }}
    .resurface-mode .rail-state-value {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.03em;
      color: var(--fg-3);
    }}

    .resurface-candidate {{
      position: relative;
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 12px 13px;
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      transition: border-color 150ms ease, background-color 150ms ease;
    }}
    .resurface-candidate:hover {{
      border-color: var(--border-strong);
      background: var(--bg-surface);
    }}

    .resurface-title {{
      font-size: var(--text-sm);
      line-height: 1.35;
      font-weight: 500;
      letter-spacing: 0.004em;
      color: var(--fg-1);
    }}

    .resurface-why {{
      position: relative;
      padding-left: 16px;
      font-size: var(--text-sm);
      line-height: 1.4;
      color: var(--fg-2);
    }}
    .resurface-why::before {{
      content: "◇"; 
      position: absolute;
      left: 0;
      top: 0.06em;
      font-size: 11px;
      line-height: 1.4;
      color: var(--cyan-dim);
    }}

    .resurface-relation {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 1.45;
      color: var(--fg-3);
    }}

    .resurface-source {{
      display: inline-flex;
      align-items: baseline;
      gap: 5px;
      align-self: flex-start;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      color: var(--fg-2);
      text-decoration: none;
      transition: color 150ms ease;
    }}
    .resurface-source::before {{
      content: "→"; 
      color: var(--fg-3);
      transition: color 150ms ease;
    }}
    .resurface-source:hover,
    .resurface-source:hover::before {{
      color: var(--cyan);
    }}
    .resurface-source:focus-visible {{
      outline: 2px solid var(--border-focus);
      outline-offset: 2px;
      border-radius: var(--radius-sm);
    }}

    .resurface-signals {{
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      margin-top: 1px;
    }}
    .resurface-signal {{
      font-family: var(--font-mono);
      font-size: 10px;
      line-height: 1;
      letter-spacing: 0.02em;
      color: var(--fg-3);
      padding: 3px 7px;
      background: color-mix(in srgb, var(--bg-raised) 55%, transparent);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
    }}

    .resurface-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      margin-top: 4px;
      opacity: 0.5;
      transition: opacity 150ms ease;
    }}
    .resurface-candidate:hover .resurface-actions,
    .resurface-candidate:focus-within .resurface-actions {{
      opacity: 1;
    }}
    .resurface-action {{
      font-family: var(--font-mono);
      font-size: 10px;
      line-height: 1.2;
      letter-spacing: 0.02em;
      text-align: left;
      color: var(--fg-3);
      background: transparent;
      border: 1px solid transparent;
      border-radius: var(--radius-sm);
      padding: 4px 7px;
      cursor: pointer;
      transition: color 150ms ease, border-color 150ms ease, background-color 150ms ease;
    }}
    .resurface-action:not([disabled]):not([aria-disabled="true"]):hover {{
      color: var(--fg-1);
      border-color: var(--border-strong);
      background: var(--bg-raised);
    }}
    .resurface-action:focus-visible {{
      outline: 2px solid var(--border-focus);
      outline-offset: 1px;
    }}

    .resurface-action[disabled],
    .resurface-action[aria-disabled="true"] {{
      color: var(--fg-3);
      opacity: 0.75;
      cursor: default;
    }}

    .resurface-candidate[data-pinned="true"] {{
      background: var(--bg-surface);
      border-color: color-mix(in srgb, var(--cyan-dim) 45%, var(--border));
    }}
    .resurface-candidate[data-pinned="true"] .resurface-title {{
      padding-right: 46px;
    }}
    .resurface-candidate[data-pinned="true"]::after {{
      content: "pinned";
      position: absolute;
      top: 11px;
      right: 12px;
      font-family: var(--font-mono);
      font-size: 9px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--cyan);
      opacity: 0.85;
    }}

    .resurface-empty[data-testid="resurface-empty-state"] {{
      position: relative;
      padding: 12px 13px 12px 30px;
      font-size: var(--text-sm);
      line-height: 1.5;
      color: var(--fg-2);
      background: color-mix(in srgb, var(--vault-muted) 55%, var(--bg-base));
      border: 1px solid color-mix(in srgb, var(--vault-dim) 32%, var(--border));
      border-radius: var(--radius-md);
    }}
    .resurface-empty[data-testid="resurface-empty-state"]::before {{
      content: "";
      position: absolute;
      left: 13px;
      top: 1.05em;
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--vault);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--vault) 16%, transparent);
    }}

    .resurface-mode[data-affordance-status="unavailable"] .rail-state-value {{
      color: var(--amber);
    }}
    .resurface-empty[data-testid="resurface-degraded-state"] {{
      position: relative;
      padding: 11px 13px 11px 31px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 1.55;
      color: var(--fg-2);
      background: var(--amber-muted);
      border: 1px solid color-mix(in srgb, var(--amber-dim) 55%, var(--border));
      border-left: 2px solid var(--amber);
      border-radius: var(--radius-md);
    }}
    .resurface-empty[data-testid="resurface-degraded-state"]::before {{
      content: "⚠"; 
      position: absolute;
      left: 11px;
      top: 0.72em;
      font-size: 12px;
      line-height: 1;
      color: var(--amber);
    }}

    @media (prefers-reduced-motion: reduce) {{
      .resurface-candidate,
      .resurface-actions,
      .resurface-action,
      .resurface-source,
      .resurface-source::before {{
        transition: none;
      }}
    }}

    .rail-alert {{
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
      padding: 8px 10px;
    }}
    .rail-alert-blocked {{
      background: var(--destructive-muted);
      border: 1px solid var(--destructive-dim);
      color: var(--au-blocked);
    }}
    .rail-alert-muted {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      color: var(--fg-2);
    }}
    .panel-message {{
      border-left: 2px solid var(--au-proposal);
      color: var(--fg-2);
      font-size: var(--text-sm);
      padding-left: 10px;
    }}
    .canvas-controls {{
      display: grid;
      gap: 6px;
      grid-template-columns: 1fr 1fr;
    }}
    .canvas-controls button {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
      padding: 5px 8px;
      text-transform: uppercase;
    }}
    .canvas-controls button:disabled {{
      color: var(--fg-3);
      cursor: not-allowed;
      opacity: 0.55;
    }}
    .canvas-presence {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      grid-column: 1 / -1;
    }}
    .canvas-body-edit-composer, .canvas-body-edit-unavailable {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: 7px;
      grid-column: 1 / -1;
      padding: 10px;
    }}
    .canvas-body-edit-composer label, .canvas-undo-state {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .canvas-body-edit-composer textarea {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      min-height: 108px;
      padding: 8px 10px;
      resize: vertical;
      width: 100%;
    }}
    .canvas-body-edit-preview, .canvas-body-edit-unavailable {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .canvas-body-edit-actions {{
      display: flex;
      justify-content: flex-end;
    }}
    .canvas-undo-state {{
      grid-column: 1 / -1;
      letter-spacing: 0;
      text-transform: none;
    }}
    .canvas-recovery-conflict {{
      background: var(--destructive-muted);
      border: 1px solid var(--destructive-dim);
      border-radius: var(--radius-md);
      color: var(--au-blocked);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 5px;
      grid-column: 1 / -1;
      padding: 8px 10px;
    }}
    .canvas-recovery-conflict button {{
      background: var(--bg-raised);
      border: 1px solid rgba(255,61,61,0.35);
      color: var(--fg-1);
      width: 100%;
    }}
    .canvas-provenance {{
      color: var(--fg-3);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 2px;
      grid-column: 1 / -1;
      min-width: 0;
    }}
    .canvas-provenance code {{
      color: var(--fg-2);
      overflow-wrap: anywhere;
    }}
    .canvas-provenance-label {{
      color: var(--fg-3);
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }}
    .suggestion-flow {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 10px;
    }}
    .suggestion-composer-state, .suggestion-transition {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .suggestion-transitions {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .suggestion-card {{
      background: var(--bg-raised);
      border: 1px solid var(--agent-dim);
      border-left: 3px solid var(--au-proposal);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 10px;
    }}
    .suggestion-card[data-variant="blocked"] {{
      background: var(--destructive-muted);
      border-color: var(--destructive-dim);
      border-left-color: var(--au-blocked);
    }}
    .suggestion-card-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
    }}
    .suggestion-card-notice {{
      color: var(--au-proposal);
    }}
    .suggestion-card-denial {{
      color: var(--amber);
    }}
    .suggestion-card-preview, .suggestion-card-notice, .suggestion-card-denial {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .suggestion-card-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .suggestion-action {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    .suggestion-action:hover, .panel-proposal-action:hover, .panel-action-discard:hover {{
      border-color: var(--cyan);
      color: var(--cyan);
    }}
    .shortcut-map {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 8px 10px;
    }}
    .shortcut-hint {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      min-height: 20px;
    }}
    .portrait-sheet {{
      display: none;
    }}
    .find-mode, .find-candidate {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding: 10px;
    }}
    .find-candidate-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
    }}
    .find-candidate-snippet, .find-candidate-why, .find-candidate-meta {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .find-candidate-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .find-panel-handoff {{
      align-self: flex-start;
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    /* §7.5 Responsive breakpoints */
    /* Default (≥1300px): all three columns visible — no overrides needed */

    /* Hide responsive-only elements at full width */
    .workspace-panel-peek, .workspace-outline-ribbon, .workspace-sheet-triggers {{
      display: none;
    }}

    /* 1100–1299px: Panel collapses to 32px peek tab on right edge */
    @media (min-width: 1100px) and (max-width: 1299px) {{
      .agent-rail[data-layout-desktop="side-rail"] {{
        display: none;
      }}
      .workspace-panel-peek {{
        align-items: center;
        background: var(--bg-raised);
        border-left: 1px solid var(--border);
        bottom: 0;
        display: flex;
        flex-direction: column;
        justify-content: center;
        position: fixed;
        right: 0;
        top: 0;
        width: 32px;
        z-index: 10;
      }}
      .peek-badge {{
        background: var(--agent);
        border-radius: 9px;
        color: white;
        font-family: var(--font-mono);
        font-size: 10px;
        min-width: 16px;
        padding: 1px 4px;
        text-align: center;
      }}
    }}

    /* 800–1099px: Outline collapses to 36px ribbon */
    @media (min-width: 800px) and (max-width: 1099px) {{
      .note-outline {{
        display: none;
      }}
      .workspace-outline-ribbon {{
        align-items: center;
        background: var(--bg-raised);
        border-bottom: 1px solid var(--border);
        cursor: pointer;
        display: flex;
        font-family: var(--font-mono);
        font-size: var(--text-xs);
        height: 36px;
        padding: 0 12px;
        width: 100%;
      }}
    }}

    /* <800px: single column, sheet trigger buttons visible */
    @media (max-width: 799px) {{
      .workspace-sheet-triggers {{
        display: flex;
        gap: 8px;
        padding: 6px 12px;
      }}
      .workspace-outline-sheet-trigger,
      .workspace-panel-sheet-trigger {{
        background: var(--bg-raised);
        border: 1px solid var(--border);
        border-radius: var(--radius-md);
        cursor: pointer;
        font-family: var(--font-mono);
        font-size: var(--text-xs);
        padding: 4px 10px;
      }}
      .workspace-layout--three-col {{
        grid-template-columns: 1fr;
      }}
      .vault-browser-left-pane, .agent-rail {{
        display: none;
      }}
      .note-outline {{
        display: none;
      }}
      .workspace-header-strip {{
        flex-wrap: wrap;
        height: auto;
      }}
    }}

    @media (max-width: 899px) {{
      .workspace-shell {{
        padding-bottom: 60px;
      }}
      .agent-rail {{
        display: none;
      }}
      /* Collapse three-col grid to single-column on narrow viewports.
         The 280px left pane and 320px agent-rail would otherwise crush the note
         center column behind overflow:hidden (Codex P1 review finding). */
      .workspace-layout--three-col {{
        grid-template-columns: 1fr;
      }}
      .vault-browser-left-pane {{
        display: none;
      }}
      .portrait-sheet {{
        background: var(--bg-surface);
        border-top: 1px solid var(--border);
        bottom: 0;
        display: block;
        left: 0;
        min-height: 44px;
        position: fixed;
        right: 0;
        z-index: 20;
      }}
      .portrait-sheet[data-current-snap="peek"] {{
        height: 60px;
      }}
      .portrait-sheet[data-current-snap="half"] {{
        height: 50vh;
      }}
      .portrait-sheet[data-current-snap="full"] {{
        height: calc(100vh - 64px);
      }}
      .portrait-sheet[data-current-snap="closed"] {{
        display: none;
      }}
    }}
    @media (min-width: 900px) {{
      .agent-rail[data-layout-desktop="side-rail"] {{
        display: flex;
      }}
    }}
    /* §8 Panel section state model */
    .panel-section[data-section-state="idle"] {{
      padding: 4px 0;
    }}
    .panel-section[data-section-state="idle"] .panel-section-title {{
      color: var(--fg-2);
      font-family: var(--font-mono);
      font-size: 13px;
    }}
    .panel-section[data-section-state="active"] {{
      background: var(--bg-raised);
      border: 1px solid var(--agent-dim);
      border-left: 2px solid var(--au-proposal);
      border-radius: 4px;
      padding: 10px;
    }}
    .panel-section-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
      font-style: normal;
      font-family: var(--font-mono);
      letter-spacing: 0.08em;
      text-transform: uppercase;
      font-size: 11px;
      color: var(--fg-3);
    }}
    .panel-section[data-section-state="active"] .panel-section-title {{
      color: var(--au-proposal);
    }}
    .panel-section-provenance {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .panel-action-row {{
      display: flex;
      gap: 6px;
      justify-content: flex-end;
      margin-top: 4px;
    }}
    .panel-action-apply {{
      background: transparent;
      border: 1px solid var(--cyan);
      border-radius: var(--radius-md);
      color: var(--cyan);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: 12px;
      height: 28px;
      padding: 0 10px;
    }}
    .panel-action-discard {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: 12px;
      height: 28px;
      padding: 0 10px;
    }}
    .panel-action-defer {{
      background: transparent;
      border: none;
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: 12px;
      height: 28px;
      padding: 0 6px;
    }}
    /* Reorient recall disclosure */
    .reorient-recall-disclosure {{ display: inline; }}
    .reorient-recall-trigger {{
      display: inline;
      cursor: pointer;
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      list-style: none;
    }}
    .reorient-recall-trigger::-webkit-details-marker {{ display: none; }}
    .reorient-recall-body {{ margin-top: 8px; }}
    .panel-proposal-row {{
      background: var(--bg-raised);
      border: 1px solid var(--agent-dim);
      border-left: 3px solid var(--au-proposal);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding: 10px;
    }}
    .panel-proposal-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
      font-style: normal;
    }}
    .panel-proposal-meta, .panel-proposal-evidence, .panel-proposal-affordances {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
    }}
    .panel-proposal-action {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 4px 7px;
      text-transform: uppercase;
    }}
    .panel-confirm-response {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      gap: 5px;
      padding: 10px;
    }}
    .panel-confirm-receipt {{ color: var(--au-receipt); }}
    .panel-confirm-blocked {{ color: var(--au-blocked); }}
    /* Body edit panel */
    /* #1416 — the composer is shrink-locked and height-bounded so it cannot
       squeeze the central note reading surface in the fixed-height shell
       (#1397). Collapsed by default it is just the summary row; expanded it is
       capped at 42vh and scrolls internally instead of growing the column. */
    .body-edit-panel {{
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
      gap: 8px;
      margin-top: 12px;
      max-height: 42vh;
      overflow-y: auto;
      padding: 12px;
    }}
    .body-edit-summary {{
      align-items: baseline;
      cursor: pointer;
      display: flex;
      gap: 10px;
      list-style-position: inside;
    }}
    /* Deterministic collapse — some rendering engines do not apply the UA
       details:not([open]) rule, so hide the body explicitly when collapsed so
       the composer contributes only its summary row (#1416). */
    .body-edit-panel:not([open]) > :not(summary) {{
      display: none;
    }}
    .body-edit-body {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-top: 10px;
    }}
    .body-edit-disabled {{
      border-color: var(--border-strong);
      color: var(--fg-2);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      flex-direction: row;
      align-items: center;
      gap: 12px;
    }}
    .body-edit-disabled .absent-label {{
      font-weight: 600;
      white-space: nowrap;
    }}
    .body-edit-disabled .absent-reason {{
      color: var(--fg-3);
      font-size: var(--text-xs);
    }}
    .body-edit-header {{ display: flex; flex-direction: column; gap: 2px; }}
    .body-edit-label {{ color: var(--fg-1); font-family: var(--font-ui); font-size: var(--text-sm); font-weight: 600; }}
    .body-edit-note {{ color: var(--fg-3); font-family: var(--font-mono); font-size: var(--text-xs); }}
    .body-edit-codemirror {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      max-height: 28vh;
      min-height: 160px;
      overflow: auto;
      width: 100%;
    }}
    .body-edit-codemirror .cm-editor {{
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
    }}
    .body-edit-codemirror .cm-focused {{ outline: 1px solid var(--border-focus); }}
    .body-edit-actions {{ display: flex; gap: 8px; }}
    .body-edit-submit {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 5px 12px;
    }}
    .body-edit-reset {{
      background: transparent;
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      cursor: pointer;
      font-family: var(--font-ui);
      font-size: var(--text-xs);
      padding: 5px 12px;
    }}
    .body-edit-status {{
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      min-height: 1em;
    }}
    .body-edit-status.ok {{ color: var(--cyan); }}
    .body-edit-status.error {{ color: var(--destructive); }}
    /* Shared overlay host (#1785, SEP-03) — the single overlay layer later
       surfaces mount on. The scrim sits below host occupants that bring
       their own full-screen chrome (e.g. the vault modal at z-index 1000). */
    .overlay-host-scrim {{
      background: rgba(7, 11, 18, 0.55);
      display: none;
      inset: 0;
      position: fixed;
      z-index: 900;
    }}
    .overlay-host-scrim[data-active="true"] {{
      display: block;
    }}
    .overlay-host-mount {{
      display: none;
      inset: 0;
      pointer-events: none;
      position: fixed;
      z-index: 950;
    }}

    /* Vault note browser overlay */
    .vault-browser-overlay {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(7, 11, 18, 0.85);
      z-index: 1000;
      align-items: flex-start;
      justify-content: center;
      padding: 40px 16px;
    }}
    .vault-browser-overlay.open {{ display: flex; }}
    .vault-browser-panel {{
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-lg);
      display: flex;
      flex-direction: column;
      gap: 12px;
      max-height: 80vh;
      max-width: 640px;
      overflow: hidden;
      padding: 20px;
      width: 100%;
    }}
    .vault-browser-header {{
      align-items: center;
      display: flex;
      gap: 10px;
      justify-content: space-between;
    }}
    .vault-browser-title {{
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
      font-weight: 600;
    }}
    .vault-browser-identity {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .vault-browser-close {{
      background: transparent;
      border: none;
      color: var(--fg-2);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
      padding: 0 4px;
    }}
    .vault-browser-search {{
      background: var(--bg-raised);
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      color: var(--fg-1);
      font-family: var(--font-mono);
      font-size: var(--text-sm);
      padding: 8px 12px;
      width: 100%;
    }}
    .vault-browser-list {{
      flex: 1;
      list-style: none;
      margin: 0;
      overflow-y: auto;
      padding: 0;
    }}
    /* #1417 — Filters tucked behind a collapsed disclosure; chips get light
       chip chrome so the expanded view reads as controls, not a metadata dump. */
    .vault-browser-filters-disclosure {{
      border-bottom: 1px solid var(--border);
      margin-bottom: 6px;
      padding-bottom: 6px;
    }}
    .vault-browser-filters-summary {{
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
      list-style: none;
      padding: 2px 2px;
    }}
    .vault-browser-filters-summary::-webkit-details-marker {{ display: none; }}
    .vault-browser-filters {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding-top: 6px;
    }}
    /* Deterministic collapse: do not rely on UA details behavior so the facets
       are hidden from the default Browse view in every engine. */
    .vault-browser-filters-disclosure:not([open]) > .vault-browser-filters {{
      display: none;
    }}
    .filter-chip {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--fg-2);
      font-size: var(--text-xs);
      padding: 2px 8px;
    }}
    .filter-chip[data-active="true"] {{
      border-color: var(--border-focus);
      color: var(--fg-1);
    }}
    /* §6 — density: folder group headers + compact, truncating rows. */
    /* #1425/#1427 — Obsidian-style collapsible folder tree. The folder summaries
       and note rows share the exact graphical profile of the Outline list
       (font-display 13px/18px, 2px left rail, accent for the active item) so the
       single left panel reads as one consistent family across its modes. */
    .vault-tree, .vault-tree ul {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .vault-tree {{
      display: flex;
      flex-direction: column;
      gap: 3px;
    }}
    .vault-tree-children {{
      display: flex;
      flex-direction: column;
      gap: 3px;
      padding-left: 12px;
    }}
    .vault-tree-folder {{ list-style: none; min-width: 0; }}
    .vault-tree-folder-details > summary {{ list-style: none; }}
    .vault-tree-folder-details > summary::-webkit-details-marker {{ display: none; }}
    .vault-tree-folder-summary {{
      align-items: center;
      border-left: 2px solid transparent;
      border-radius: var(--radius-sm);
      box-sizing: border-box;
      color: var(--fg-2);
      cursor: pointer;
      display: flex;
      font-family: var(--font-display);
      font-size: 13px;
      gap: 4px;
      line-height: 18px;
      overflow: hidden;
      padding: 5px 6px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .vault-tree-folder-summary::before {{
      color: var(--fg-3);
      content: "\\203A";
      display: inline-block;
      flex-shrink: 0;
      transition: transform 0.12s ease;
      width: 10px;
    }}
    .vault-tree-folder-details[open] > .vault-tree-folder-summary::before {{
      transform: rotate(90deg);
    }}
    /* #1427 — subtle full-width background highlight on hover/focus (Obsidian /
       Claude Code style), not a heavy outline box or browser focus ring. */
    .vault-tree-folder-details > summary:focus {{ outline: none; }}
    .vault-tree-folder-summary:hover,
    .vault-tree-folder-details > summary:focus-visible > .vault-tree-folder-summary,
    .vault-tree-folder-details > summary:focus-visible {{
      background: var(--bg-raised);
      color: var(--fg-1);
    }}
    /* Tree note rows mirror .note-outline-link exactly. */
    .vault-tree .vault-browser-row {{
      align-items: center;
      box-sizing: border-box;
      display: grid;
      gap: 4px;
      grid-template-columns: 18px minmax(0, 1fr);
      list-style: none;
      min-width: 0;
    }}
    .vault-browser-selection-summary {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      line-height: 18px;
      min-height: 18px;
      padding: 2px 2px 6px;
    }}
    .vault-browser-selection-toggle {{
      appearance: auto;
      cursor: pointer;
      height: 14px;
      margin: 0;
      width: 14px;
    }}
    .vault-browser-row[data-selected="true"] > .vault-browser-selection-toggle {{
      accent-color: var(--accent);
    }}
    .vault-tree .vault-browser-row[data-selected="true"] {{
      background: var(--bg-raised);
      border-radius: var(--radius-sm);
    }}
    .vault-tree .vault-browser-row-title {{
      border-left: 2px solid transparent;
      border-radius: var(--radius-sm);
      box-sizing: border-box;
      color: var(--fg-2);
      display: block;
      font-family: var(--font-display);
      font-size: 13px;
      line-height: 18px;
      overflow: hidden;
      padding: 5px 6px;
      text-decoration: none;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .vault-tree .vault-browser-row-title:hover,
    .vault-tree .vault-browser-row-title:focus-visible {{
      background: var(--bg-raised);
      color: var(--fg-1);
      outline: none;
    }}
    /* Active note: a subtle full-width background block + the Outline accent
       rail/text, so it reads as the current selection (Obsidian/Claude Code). */
    .vault-tree .vault-browser-row[data-active="true"] {{
      background: var(--bg-raised);
      border-radius: var(--radius-sm);
    }}
    .vault-tree .vault-browser-row[data-active="true"] > .vault-browser-row-title {{
      border-left-color: var(--accent);
      color: var(--accent);
    }}
    .vault-tree .vault-browser-row-path {{ display: none; }}
    /* #1427 — inspector behind a collapsed disclosure; deterministic collapse. */
    .vault-browser-inspector-disclosure {{
      border-top: 1px solid var(--border);
      margin-top: 8px;
      padding-top: 6px;
    }}
    .vault-browser-inspector-summary {{
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      list-style: none;
      padding: 2px 2px;
      text-transform: uppercase;
    }}
    .vault-browser-inspector-summary::-webkit-details-marker {{ display: none; }}
    .vault-browser-inspector-disclosure:not([open]) > :not(summary) {{
      display: none;
    }}
    /* #1427 — readable label/value spacing in the inspector (was "kindnote"). */
    .inspector-field {{
      display: flex;
      gap: 6px;
      justify-content: space-between;
      padding: 2px 0;
    }}
    .inspector-field > .inspector-label {{
      color: var(--fg-3);
      flex-shrink: 0;
    }}
    .receipt-row {{
      background: color-mix(in srgb, var(--au-receipt) 6%, transparent);
      border: 1px solid color-mix(in srgb, var(--au-receipt) 55%, transparent);
      border-radius: var(--radius-sm);
      color: var(--fg-2);
      cursor: pointer;
      display: grid;
      gap: 4px;
      grid-template-columns: minmax(0, 1fr) auto;
      margin: 2px 0;
      padding: 5px 7px;
    }}
    .receipt-row:focus-visible {{
      border-radius: var(--radius-sm);
      outline: 2px solid var(--cyan);
      outline-offset: 2px;
    }}
    .receipt-detail {{
      border-left: 1px solid var(--border);
      display: grid;
      gap: 2px 8px;
      grid-template-columns: max-content minmax(0, 1fr);
      margin: 2px 0 6px;
      padding-left: 8px;
    }}
    .receipt-detail[hidden] {{ display: none; }}
    .receipt-detail-label {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .receipt-detail-value {{
      margin: 0;
      min-width: 0;
      overflow-wrap: anywhere;
    }}
    .vault-related-results {{
      display: grid;
      gap: 6px;
      margin-top: 6px;
    }}
    .vault-related-result {{
      border-left: 1px solid var(--border);
      display: grid;
      gap: 2px;
      padding-left: 8px;
    }}
    .vault-related-title {{
      color: var(--fg-1);
      font-weight: 600;
    }}
    .vault-related-path,
    .vault-related-score,
    .vault-related-signal {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      overflow-wrap: anywhere;
    }}
    .vault-related-signals {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }}
    /* #1425 — de-emphasize browse header chrome; the tree is the surface. The
       "Browse vault notes" toggle matches the Outline heading label. */
    .vault-browser-meta,
    .vault-browser-state {{ display: none; }}
    .vault-browser > summary[data-testid="workspace-vault-browser-toggle"] {{
      color: var(--fg-3);
      cursor: pointer;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.08em;
      list-style: none;
      margin-bottom: 10px;
      text-transform: uppercase;
    }}
    .vault-browser > summary[data-testid="workspace-vault-browser-toggle"]::-webkit-details-marker {{
      display: none;
    }}
    .vault-browser-group {{
      list-style: none;
      padding: 8px 4px 2px;
      position: sticky;
      top: 0;
      background: var(--bg-surface);
      z-index: 1;
    }}
    .vault-browser-group-label {{
      color: var(--fg-3);
      display: block;
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      letter-spacing: 0.04em;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .vault-browser-row-title {{
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .vault-browser-row-path {{
      color: var(--fg-3);
      direction: rtl;
      display: block;
      font-size: var(--text-xs);
      overflow: hidden;
      text-align: left;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}
    .vault-browser-item {{
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 8px 4px;
    }}
    .vault-browser-item:hover {{ background: var(--bg-raised); }}
    .vault-browser-item-title {{
      color: var(--fg-1);
      font-family: var(--font-ui);
      font-size: var(--text-sm);
    }}
    .vault-browser-item-path {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
    }}
    .vault-browser-status {{
      color: var(--fg-3);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      text-align: center;
    }}
  </style>
</head>
<body data-diagnostics="{'true' if diagnostics else 'false'}" data-posture-emphasis="{DEFAULT_POSTURE_EMPHASIS}" {entry_state_attributes(entry_resolution)}>
  {_render_help_toggle()}
  <div class="topbar">
    <div class="topbar-api">
      <span class="api-label">Server-side runtime</span>
      <span class="api-url" title="Companion UI proxies browser actions through same-origin routes">same-origin bridge</span>
    </div>
    {dev_chip}
  </div>
  <details class="dev-controls-disclosure" data-testid="workspace-dev-controls" open>
    <summary class="dev-controls-summary" data-testid="workspace-dev-controls-toggle">dev controls</summary>
    <div class="load-bar">
      <form method="GET" action="/" style="display:flex;align-items:center;gap:8px;width:100%">
        <label for="note_path">note_path</label>
        <input
          type="text"
          id="note_path"
          name="note_path"
          value="{_e(note_path)}"
          placeholder="Some/Note.md"
          autocomplete="off">
        <button type="submit">Load</button>
        <button type="button"
          id="vault-browse-btn"
          data-testid="vault-browse-button"
          data-browse-target="vault-browser-pane"
          onclick="vaultBrowser.focus()">Browse vault</button>
      </form>
    </div>
  </details>
  {content_section}
  {residual_ambient_html}

  <!-- Vault note browser overlay — narrow responsive fallback only (§5.3).
       On desktop, Browse Vault focuses the canonical left-pane browse surface
       instead of opening this modal. -->
  <div class="vault-browser-overlay" id="vault-browser-overlay"
       data-testid="vault-browser-overlay" data-browser-role="responsive-fallback"
       role="dialog" aria-modal="true">
    <div class="vault-browser-panel">
      <div class="vault-browser-header">
        <span class="vault-browser-title">Browse vault</span>
        <span class="vault-browser-identity" id="vault-browser-identity"
              data-testid="vault-browser-identity"></span>
        {guidance_toggle_markup('vault')}
        <button class="vault-browser-close" onclick="vaultBrowser.close()"
                data-testid="vault-browser-close" aria-label="Close">&times;</button>
      </div>
      {guidance_callout_markup('vault')}
      <input type="text" class="vault-browser-search" id="vault-browser-search"
             data-testid="vault-browser-search"
             placeholder="Search by title or path…"
             autocomplete="off">
      <ul class="vault-browser-list" id="vault-browser-list"
          data-testid="vault-browser-list"></ul>
      <div class="vault-browser-status" id="vault-browser-status"
           data-testid="vault-browser-status"></div>
    </div>
  </div>
  {overlay_host_markup(anchor_note_path=note_path)}
  {capture_modal_markup()}
  {panel_palette_markup(fields)}
  {memory_review_drawer_markup()}
  {receipts_history_modal_markup()}
  {settings_drawer_markup(fields)}
  {vault_settings_panel_html}
  {system_map_overlay_markup(
    available_routes=map_available_routes,
    orientation_freshness=str((fields or {}).get("orientation_freshness") or ""),
    orientation_as_of=str((fields or {}).get("orientation_as_of") or ""),
    orientation_trace_id=str((fields or {}).get("orientation_trace_id") or ""),
    open_loops_count=int((fields or {}).get("orientation_open_loops_count") or 0),
  )}
  {guidance_layer_style()}

  {note_outline_script()}

  <script>
  (function() {{
    var overlay = document.getElementById('vault-browser-overlay');
    var list    = document.getElementById('vault-browser-list');
    var status  = document.getElementById('vault-browser-status');
    var search  = document.getElementById('vault-browser-search');
    var identity = document.getElementById('vault-browser-identity');
    var debounceTimer = null;

    function setStatus(msg) {{ status.textContent = msg; }}

    function renderNotes(notes, vaultIdentity) {{
      list.innerHTML = '';
      if (vaultIdentity && vaultIdentity.vault_name && vaultIdentity.channel) {{
        identity.textContent = vaultIdentity.vault_name + ' / ' + vaultIdentity.channel;
      }}
      if (!notes || notes.length === 0) {{
        setStatus('No notes found.');
        return;
      }}
      setStatus(notes.length + ' note' + (notes.length === 1 ? '' : 's'));
      notes.forEach(function(note) {{
        var li = document.createElement('li');
        li.className = 'vault-browser-item';
        li.setAttribute('data-note-path', note.path);
        li.innerHTML = '<span class="vault-browser-item-title">' +
          _esc(note.title) + '</span><span class="vault-browser-item-path">' +
          _esc(note.path) + '</span>';
        li.addEventListener('click', function() {{
          vaultBrowser.selectNote(note.path);
        }});
        list.appendChild(li);
      }});
    }}

    function _esc(s) {{
      return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
    }}

    function fetchNotes(q) {{
      setStatus('Loading…');
      list.innerHTML = '';
      var url = '/api/companion/vault/notes' + (q ? '?q=' + encodeURIComponent(q) : '');
      fetch(url)
        .then(function(r) {{
          if (!r.ok) throw new Error('API error ' + r.status);
          return r.json();
        }})
        .then(function(data) {{
          renderNotes(data.notes, data.vault_identity);
        }})
        .catch(function(err) {{
          setStatus('Error: ' + err.message);
        }});
    }}

    window.vaultBrowser = {{
      focus: function() {{
        // §5.2/§5.3 — on desktop the canonical browser is the left context
        // pane; focus it in place. Only fall back to the modal overlay on
        // narrow viewports where the persistent left pane is not available.
        var leftPane = document.getElementById('vault-browser-left-pane');
        var hasInlinePane = leftPane &&
          window.matchMedia('(min-width: 860px)').matches &&
          window.getComputedStyle(leftPane).display !== 'none';
        if (hasInlinePane) {{
          // §4.1/§5.2 — activate browse mode in the single left context panel.
          if (window.leftPanel) window.leftPanel.setMode('browse');
          leftPane.setAttribute('data-browse-focused', 'true');
          leftPane.scrollIntoView({{ block: 'nearest', inline: 'nearest' }});
          var paneSearch = leftPane.querySelector('input, a, button');
          if (paneSearch) paneSearch.focus();
          return;
        }}
        vaultBrowser.open();
      }},
      open: function() {{
        overlay.classList.add('open');
        search.value = '';
        fetchNotes('');
        search.focus();
      }},
      close: function() {{
        overlay.classList.remove('open');
      }},
      selectNote: function(path) {{
        vaultBrowser.close();
        var input = document.getElementById('note_path');
        if (input) {{ input.value = path; input.form.submit(); }}
      }}
    }};

    search.addEventListener('input', function() {{
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function() {{
        fetchNotes(search.value.trim());
      }}, 300);
    }});

    overlay.addEventListener('click', function(e) {{
      if (e.target === overlay) vaultBrowser.close();
    }});

    // Esc handling for this modal is owned by the shared overlay host
    // (#1785, SEP-03): the narrow-mode vault browser is a host occupant and
    // the host dismisses the topmost overlay back to the document anchor.
  }})();
  </script>
  {overlay_host_script()}
  {capture_modal_script()}
  {panel_palette_script()}
  {memory_review_drawer_script()}
  {receipts_history_script()}
  {system_map_overlay_script()}
  {guidance_layer_script()}

  <script>
  (function() {{
    // §4 — single adaptive left context panel controller. Exactly one mode is
    // visible at a time; collapsed maximizes the reading surface and keeps a
    // visible reopen affordance that restores the last non-collapsed mode.
    function nav() {{ return document.getElementById('vault-browser-left-pane'); }}

    window.leftPanel = {{
      setMode: function(mode) {{
        var n = nav();
        if (!n) return;
        var current = n.getAttribute('data-left-panel-mode');
        if (current && current !== 'collapsed') {{
          n.setAttribute('data-left-panel-last-mode', current);
        }}
        n.setAttribute('data-left-panel-mode', mode);
        var regions = n.querySelectorAll('[data-left-panel-mode-region]');
        Array.prototype.forEach.call(regions, function(r) {{
          if (mode !== 'collapsed' && r.getAttribute('data-mode') === mode) {{
            r.removeAttribute('hidden');
          }} else {{
            r.setAttribute('hidden', '');
          }}
        }});
        var tabs = n.querySelectorAll('[role="tab"]');
        Array.prototype.forEach.call(tabs, function(t) {{
          t.setAttribute('aria-selected',
            t.getAttribute('data-mode') === mode ? 'true' : 'false');
        }});
        var reopen = n.querySelector('[data-testid="workspace-left-panel-reopen"]');
        if (reopen) {{
          if (mode === 'collapsed') reopen.removeAttribute('hidden');
          else reopen.setAttribute('hidden', '');
        }}
      }},
      collapse: function() {{ window.leftPanel.setMode('collapsed'); }},
      reopen: function() {{
        var n = nav();
        var last = (n && n.getAttribute('data-left-panel-last-mode')) || 'browse';
        window.leftPanel.setMode(last);
      }}
    }};
  }})();
  </script>

  <script>
  (function() {{
    window.bodyEditor = {{
      submit: function() {{
        var container = document.getElementById('body-edit-codemirror');
        var statusEl = document.getElementById('body-edit-status');
        if (!container || !statusEl) return;
        var notePath = container.getAttribute('data-note-path');
        if (!window._cmView) {{
          statusEl.className = 'body-edit-status error';
          statusEl.textContent = 'Editor not ready. Wait for the page to finish loading.';
          return;
        }}
        var newBody = window._cmView.state.doc.toString();
        statusEl.className = 'body-edit-status';
        statusEl.textContent = 'Submitting…';
        fetch('/api/companion/workspace/body', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{note_path: notePath, new_body: newBody}})
        }})
        .then(function(r) {{ return r.json().then(function(d) {{ return {{ok: r.ok, data: d}}; }}); }})
        .then(function(res) {{
          if (res.ok) {{
            statusEl.className = 'body-edit-status ok';
            statusEl.textContent = 'Updated. hash=' + res.data.content_hash;
          }} else {{
            var detail = res.data.detail || res.data;
            var msg = detail.message || detail.error || JSON.stringify(detail);
            statusEl.className = 'body-edit-status error';
            statusEl.textContent = 'Error: ' + msg;
          }}
        }})
        .catch(function(err) {{
          statusEl.className = 'body-edit-status error';
          statusEl.textContent = 'Network error: ' + err.message;
        }});
      }},
      reset: function() {{
        var container = document.getElementById('body-edit-codemirror');
        var statusEl = document.getElementById('body-edit-status');
        if (window._cmView && container) {{
          var orig = container.getAttribute('data-raw-body') || '';
          window._cmView.dispatch({{
            changes: {{from: 0, to: window._cmView.state.doc.length, insert: orig}}
          }});
        }}
        if (statusEl) {{ statusEl.className = 'body-edit-status'; statusEl.textContent = ''; }}
      }}
    }};
  }})();
  </script>
  <script type="module">
  import {{EditorView, basicSetup}} from 'https://esm.sh/codemirror@6.0.1';
  import {{markdown, markdownLanguage}} from 'https://esm.sh/@codemirror/lang-markdown@6.2.5';
  import {{oneDark}} from 'https://esm.sh/@codemirror/theme-one-dark@6.1.2';
  var container = document.getElementById('body-edit-codemirror');
  if (container) {{
    var rawBody = container.dataset.rawBody || '';
    window._cmView = new EditorView({{
      doc: rawBody,
      extensions: [basicSetup, markdown({{base: markdownLanguage}}), oneDark],
      parent: container,
    }});
    // #1416 — the composer is a collapsed <details> by default, so CodeMirror
    // mounts with zero measured size. Re-measure when the user opens it.
    var panel = container.closest('details.body-edit-panel');
    if (panel) {{
      panel.addEventListener('toggle', function() {{
        if (panel.open && window._cmView) {{ window._cmView.requestMeasure(); }}
      }});
    }}
  }}
  </script>
  <script>
  function vaultBrowserToggleReceiptDetail(row) {{
    if (!row || !row.getAttribute) return;
    var detailId = row.getAttribute('data-detail-id');
    var detail = detailId ? document.getElementById(detailId) : null;
    if (!detail) return;
    var expanded = row.getAttribute('aria-expanded') === 'true';
    row.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    row.setAttribute('data-expanded', expanded ? 'false' : 'true');
    detail.hidden = expanded;
    detail.setAttribute('aria-hidden', expanded ? 'true' : 'false');
    detail.setAttribute('data-expanded', expanded ? 'false' : 'true');
  }}

  function vaultBrowserEscape(value) {{
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }}

  function renderVaultBrowserFindRelatedResults(data) {{
    var container = document.querySelector('[data-testid="vault-browser-find-related-results"]');
    if (!container) return;
    var results = data && Array.isArray(data.results) ? data.results : [];
    container.setAttribute('data-mode', 'read_only');
    container.setAttribute('data-state', results.length ? 'ready' : 'empty');
    if (!results.length) {{
      container.innerHTML = '<span class="vault-related-empty">No related artifacts found.</span>';
      return;
    }}
    container.innerHTML = results.map(function(result) {{
      var signals = Array.isArray(result.ranking_signals) ? result.ranking_signals : [];
      var signalHtml = signals.map(function(signal) {{
        return '<span class="vault-related-signal" ' +
          'data-testid="vault-browser-find-related-signal" ' +
          'data-signal="' + vaultBrowserEscape(signal.signal) + '" ' +
          'data-weight="' + vaultBrowserEscape(signal.weight) + '" ' +
          'data-provenance="' + vaultBrowserEscape(signal.provenance) + '">' +
          vaultBrowserEscape(signal.signal) + ': ' + vaultBrowserEscape(signal.value) +
          '</span>';
      }}).join('');
      return '<article class="vault-related-result" ' +
        'data-testid="vault-browser-find-related-result" ' +
        'data-mode="read_only" ' +
        'data-note-path="' + vaultBrowserEscape(result.note_path) + '" ' +
        'data-ranking-score="' + vaultBrowserEscape(result.ranking_score || 0) + '">' +
        '<span class="vault-related-title">' + vaultBrowserEscape(result.title || 'Related artifact') + '</span>' +
        '<code class="vault-related-path">' + vaultBrowserEscape(result.note_path || '') + '</code>' +
        '<span class="vault-related-score" data-testid="vault-browser-find-related-score">' +
        vaultBrowserEscape(result.ranking_score || 0) + '</span>' +
        '<span class="vault-related-signals">' + signalHtml + '</span>' +
        '</article>';
    }}).join('');
  }}

  function vaultBrowserFindRelated(action) {{
    if (!action || !action.dataset) return;
    var params = new URLSearchParams();
    if (action.dataset.notePath) params.set('note_path', action.dataset.notePath);
    if (action.dataset.artifactUuid) params.set('artifact_uuid', action.dataset.artifactUuid);
    if (!params.toString()) return;
    var endpoint = action.dataset.apiPath || '/api/companion/vault-related';
    var url = endpoint + '?' + params.toString();
    fetch(url, {{method: 'GET'}})
      .then(function(response) {{
        if (!response.ok) throw new Error('Find request failed: ' + response.status);
        return response.json();
      }})
      .then(function(data) {{
        renderVaultBrowserFindRelatedResults(data);
      }})
      .catch(function(error) {{
        var container = document.querySelector('[data-testid="vault-browser-find-related-results"]');
        if (!container) return;
        container.setAttribute('data-mode', 'read_only');
        container.setAttribute('data-state', 'error');
        container.textContent = error.message;
      }});
  }}

  function vaultBrowserQueueReview(action) {{
    if (!action || !action.dataset) return;
    if (action.getAttribute('data-submitting') === 'true') return;
    var payload = {{}};
    if (action.dataset.notePath) payload.note_path = action.dataset.notePath;
    if (action.dataset.artifactUuid) payload.artifact_uuid = action.dataset.artifactUuid;
    if (!payload.note_path && !payload.artifact_uuid) return;
    var endpoint = action.dataset.apiPath || '/api/companion/vault-browser/actions/queue-review';
    action.setAttribute('data-submitting', 'true');
    action.setAttribute('data-affordance-status', 'pending');
    fetch(endpoint, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }})
      .then(function(response) {{
        return response.json().then(function(data) {{
          return {{ok: response.ok, status: response.status, data: data}};
        }});
      }})
      .then(function(result) {{
        if (!result.ok) {{
          var detail = result.data && result.data.detail ? result.data.detail : {{}};
          var message = detail.message || detail.error || 'queue_review staging failed';
          throw new Error(message);
        }}
        // A 200 vault_selection_required payload is the no-vault / missing-vault
        // picker state, NOT a staged review. Route the human to the vault picker
        // instead of masquerading it as a pending_intent receipt (#2184).
        if (result.data && result.data.state === 'vault_selection_required') {{
          action.removeAttribute('data-submitting');
          action.setAttribute('data-affordance-status', 'vault_selection_required');
          action.setAttribute('data-pending-state', 'vault_selection_required');
          action.setAttribute('data-vault-selection-required', 'true');
          // Re-resolve the entry state so the vault picker surfaces.
          window.location.reload();
          return;
        }}
        action.removeAttribute('data-submitting');
        action.setAttribute('data-affordance-status', 'pending_intent');
        action.setAttribute('data-intent-id', result.data.intent_id || '');
        action.setAttribute('data-proposal-id', result.data.proposal_id || '');
        action.setAttribute('data-pending-state', result.data.state || 'pending_intent');
        action.setAttribute(
          'data-receipt-state',
          result.data.receipt_state || 'pending_intent_not_durable_receipt'
        );
      }})
      .catch(function(error) {{
        action.removeAttribute('data-submitting');
        action.setAttribute('data-affordance-status', 'blocked');
        action.setAttribute('data-blocked', 'true');
        action.setAttribute('data-blocked-reason', error.message);
      }});
  }}

  function vaultBrowserSelectionControls() {{
    return Array.prototype.slice.call(
      document.querySelectorAll('[data-testid="workspace-vault-browser-selection-toggle"]')
    );
  }}

  function vaultBrowserUpdateSelectionSummary() {{
    var controls = vaultBrowserSelectionControls();
    var selected = controls.filter(function(control) {{ return control.checked; }});
    var summary = document.querySelector('[data-testid="workspace-vault-browser-selection-summary"]');
    if (!summary) return;
    summary.dataset.selectedCount = String(selected.length);
    summary.textContent = selected.length === 1 ? '1 selected' : selected.length + ' selected';
  }}

  function vaultBrowserToggleSelection(event, control) {{
    if (event) {{ event.stopPropagation(); }}
    if (!control) return;
    var row = control.closest('[data-testid="workspace-vault-browser-note-row"]');
    var selected = !!control.checked;
    control.dataset.selected = selected ? 'true' : 'false';
    if (row) {{
      row.dataset.selected = selected ? 'true' : 'false';
    }}
    vaultBrowserUpdateSelectionSummary();
  }}

  document.addEventListener('DOMContentLoaded', vaultBrowserUpdateSelectionSummary);

  function vbToggleFilter(el) {{
    var key = el.dataset.key;
    var val = el.dataset.value;
    var url = new URL(window.location.href);
    var params = url.searchParams;
    var existing = params.getAll(key);
    params.delete(key);
    if (existing.indexOf(val) === -1) {{ params.append(key, val); }}
    existing.filter(function(v) {{ return v !== val; }}).forEach(function(v) {{ params.append(key, v); }});
    window.location.href = url.toString();
  }}
  </script>
  <script>
  (function() {{
    function idempotencyKey() {{
      if (window.crypto && typeof window.crypto.randomUUID === 'function') {{
        return window.crypto.randomUUID();
      }}
      return 'panel-checkbox-' + Date.now() + '-' + Math.random().toString(16).slice(2);
    }}
    function refreshWorkspace(notePath) {{
      var url = '/api/companion/workspace?note_path=' + encodeURIComponent(notePath || '');
      return fetch(url, {{method: 'GET'}}).catch(function() {{ return null; }});
    }}
    function panelProjectionSucceeded(data) {{
      return data && ['projected', 'executed', 'already_projected'].indexOf(data.status) !== -1;
    }}
    function panelProjectionMessage(data, fallback) {{
      if (!data) return fallback;
      if (data.block_reason) return data.block_reason;
      if (data.status === 'blocked') return 'Panel action blocked by runtime guard.';
      if (data.status === 'failed') return 'Panel action failed before execution completed.';
      if (data.status === 'stale') return 'Panel action is stale. Refresh the note and try again.';
      if (data.status === 'not_found') return 'Panel action is no longer available.';
      if (data.status === 'not_selectable') return 'Panel action is not selectable.';
      return fallback;
    }}
    function setPanelCheckboxFeedback(target, message) {{
      var item = target.closest ? target.closest('li.task-list-item') : null;
      if (!item) return;
      var feedback = item.querySelector('.panel-checkbox-feedback');
      if (!feedback) {{
        feedback = document.createElement('span');
        feedback.className = 'panel-checkbox-feedback';
        feedback.setAttribute('role', 'status');
        item.appendChild(feedback);
      }}
      feedback.textContent = message || '';
    }}
    function clearPanelCheckboxFeedback(target) {{
      var item = target.closest ? target.closest('li.task-list-item') : null;
      if (!item) return;
      var feedback = item.querySelector('.panel-checkbox-feedback');
      if (feedback) feedback.remove();
    }}
    document.addEventListener('click', function(event) {{
      var target = event.target && event.target.closest
        ? event.target.closest('button[data-panel-local-choice]')
        : null;
      if (!target) return;
      event.preventDefault();
      var item = target.closest ? target.closest('li.task-list-item') : null;
      if (!item) return;
      var feedback = item.querySelector('.panel-checkbox-feedback');
      if (!feedback) return;
      var choice = target.getAttribute('data-panel-local-choice') || 'choice';
      feedback.setAttribute('data-panel-status', 'local-only');
      feedback.textContent = choice.charAt(0).toUpperCase() + choice.slice(1)
        + ' is local only in this slice; no durable change was written.';
    }});
    document.addEventListener('click', function(event) {{
      var target = event.target && event.target.closest
        ? event.target.closest('input[data-panel-checkbox="true"]')
        : null;
      if (!target) return;
      event.preventDefault();
      if (target.getAttribute('data-panel-submitting') === 'true') return;
      var payload = {{
        artifact_id: target.getAttribute('data-artifact-id') || '',
        note_path: target.getAttribute('data-note-path') || '',
        panel_id: target.getAttribute('data-panel-id') || '',
        option_id: target.getAttribute('data-option-id') || '',
        expected_content_hash: target.getAttribute('data-content-hash') || '',
        expected_source_hash: target.getAttribute('data-source-hash') || '',
        idempotency_key: idempotencyKey()
      }};
      target.setAttribute('data-panel-submitting', 'true');
      target.disabled = true;
      clearPanelCheckboxFeedback(target);
      fetch('/api/panel/checkbox-projection', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify(payload)
      }}).then(function(response) {{
        return response.json().then(function(data) {{
          return {{ok: response.ok, status: response.status, data: data}};
        }});
      }}).then(function(result) {{
        if (!result.ok || !panelProjectionSucceeded(result.data)) {{
          target.disabled = false;
          target.removeAttribute('data-panel-submitting');
          target.checked = false;
          setPanelCheckboxFeedback(target, panelProjectionMessage(result.data, 'Panel checkbox projection failed.'));
          try {{ console.error('panel checkbox projection failed', result.status, result.data); }} catch (e) {{}}
          return;
        }}
        target.checked = true;
        refreshWorkspace(payload.note_path).finally(function() {{
          window.location.reload();
        }});
      }}).catch(function(error) {{
        target.disabled = false;
        target.removeAttribute('data-panel-submitting');
        target.checked = false;
        try {{ console.error('panel checkbox projection network error', error); }} catch (e) {{}}
      }});
    }});
  }})();
  </script>
  {_mermaid_runtime_script()}
  {_display_preferences_script()}
  {_note_readback_script()}
  {_note_editor_script()}
  {settings_drawer_script()}
  {vault_settings_panel_js}
  {_canvas_coauthor_script(canvas_enabled)}
  {_render_help_drawer()}
  {_render_operator_drawer()}
</body>
</html>"""


def handle_get(
    *,
    query_string: str,
    client: WorkspaceHttpClient,
    api_base_url: str,
    production_profile: bool = False,
    page_origin_host: str = "",
) -> str:
    """Parse query string, optionally load a note, and return full page HTML.

    Pure except for one WorkspaceHttpClient read: artifact workspace when
    note_path is present, otherwise workspace orientation for re-entry.
    """
    params = parse_qs(query_string)
    note_path = params.get("note_path", [""])[0].strip()
    _filter_keys = ("kind", "zone", "review_state", "trust")
    active_filters = {k: params[k] for k in _filter_keys if params.get(k)}
    cursor = params.get("cursor", [""])[0].strip()
    try:
        browser_limit = int(params.get("limit", ["250"])[0])
    except (TypeError, ValueError):
        browser_limit = 250
    # #1418 — diagnostics/operator chrome is opt-in via an explicit route.
    diagnostics = params.get("diagnostics", ["0"])[0].strip().lower() in {"1", "true", "yes", "on"}
    fields: Optional[dict] = None
    orientation: Optional[dict] = None
    orientation_vault_browser: Optional[dict] = None
    orientation_vault_browser_error = ""
    orientation_error = ""
    error = ""

    if note_path:
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(
            NoteLoadIntent(
                note_path=note_path,
                active_filters=active_filters,
                vault_browser_cursor=cursor,
                vault_browser_limit=browser_limit,
            )
        )
        if state.is_loaded:
            fields = page.render_fields()
        else:
            error = state.error or "Unknown error"
    else:
        try:
            orientation = client.get("/api/companion/orientation", params={})
        except WorkspaceClientError as exc:
            orientation_error = str(exc)
        try:
            browser_params: dict = {
                "q": params.get("q", [""])[0].strip(),
                "limit": browser_limit,
            }
            if cursor:
                browser_params["cursor"] = cursor
            browser_params.update(active_filters)
            orientation_vault_browser = client.get(
                "/api/companion/vault-browser",
                params=browser_params,
            )
        except (WorkspaceClientError, AssertionError) as exc:
            orientation_vault_browser_error = str(exc)
        if orientation is None and orientation_vault_browser is not None:
            orientation = _orientation_unavailable_frame(orientation_error)
        elif orientation is None:
            error = orientation_error or orientation_vault_browser_error

    return render_index_html(
        api_base_url=api_base_url,
        note_path=note_path,
        fields=fields,
        error=error,
        orientation=orientation,
        orientation_error=orientation_error,
        orientation_vault_browser=orientation_vault_browser,
        orientation_vault_browser_error=orientation_vault_browser_error,
        production_profile=production_profile,
        diagnostics=diagnostics,
        ambient_refresh_enabled=orientation_ambient_refresh_enabled(),
        page_origin_hostname=page_origin_host,
    )


def make_handler(
    *,
    client: WorkspaceHttpClient,
    api_base_url: str,
    production_profile: bool = False,
    static_assets: dict[str, tuple[str, bytes]] | None = None,
) -> type:
    """Return a configured BaseHTTPRequestHandler subclass.

    The returned class closes over client and api_base_url as class attributes
    so each request instance can reach them without global state.
    """

    class _Handler(BaseHTTPRequestHandler):
        _client = client
        _api_base_url = api_base_url
        _production_profile = production_profile
        _static_assets = static_assets or {}

        def _send_json(self, status_code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _proxy_error(self, exc: WorkspaceClientError) -> None:
            if isinstance(exc, WorkspaceClientHTTPError):
                # Forward the runtime's JSON error body verbatim when it is JSON
                # (preserving the original status code) so structured handoff
                # references survive to the page — e.g. the canvas co-authoring
                # 409 body {"status":"routed_to_panel","intent_id":...} the
                # served page renders as the view-in-Panel affordance (#1733).
                # Non-JSON details fall back to the wrapped diagnostic shape.
                try:
                    runtime_body = json.loads(exc.detail)
                except (json.JSONDecodeError, TypeError):
                    runtime_body = None
                if isinstance(runtime_body, dict):
                    self._send_json(exc.status_code, runtime_body)
                    return
                self._send_json(
                    exc.status_code,
                    {
                        "error": "runtime_api_error",
                        "message": exc.detail,
                        "status_code": exc.status_code,
                    },
                )
                return
            self._send_json(
                502,
                {
                    "error": "runtime_unavailable",
                    "message": str(exc),
                    "next_step": "Verify the Companion runtime API is running on the server host.",
                },
            )

        def _proxy_audio(self, path: str) -> None:
            if re.fullmatch(r"/api/companion/tts/audio/[a-f0-9]{64}\.wav", path) is None:
                self._send_json(404, {"error": "not_found", "message": "Unknown Companion UI route"})
                return
            try:
                response = httpx.get(self._api_base_url.rstrip("/") + path, timeout=10.0)
            except httpx.RequestError as exc:
                self._send_json(
                    502,
                    {
                        "error": "runtime_unavailable",
                        "message": str(exc),
                        "next_step": "Verify the Companion runtime API is running on the server host.",
                    },
                )
                return
            self.send_response(response.status_code)
            self.send_header("Content-Type", response.headers.get("Content-Type", "audio/wav"))
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/help":
                body = load_help_guide_html().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/help-assets/"):
                asset = load_help_asset(parsed.path[len("/help-assets/"):])
                if asset is None:
                    self._send_json(404, {"error": "not_found", "message": "Unknown help asset"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(asset)))
                self.end_headers()
                self.wfile.write(asset)
                return
            if parsed.path in self._static_assets:
                content_type, body = self._static_assets[parsed.path]
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/companion/orientation":
                try:
                    data = self._client.get("/api/companion/orientation", params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/companion/workspace":
                params = parse_qs(parsed.query)
                note_param = params.get("note_path", [""])[0]
                try:
                    data = self._client.get(
                        "/api/companion/workspace",
                        params={"note_path": note_param},
                    )
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/companion/vault/notes":
                params = parse_qs(parsed.query)
                q = params.get("q", [""])[0]
                try:
                    data = self._client.get(
                        "/api/companion/vault/notes",
                        params={"q": q} if q else {},
                    )
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == VAULT_SETTINGS_ENDPOINT:
                try:
                    data = self._client.get(VAULT_SETTINGS_ENDPOINT, params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == VAULT_SETTINGS_FRAGMENT_ROUTE:
                # Vault settings panel fragment (#2016): server-rendered from
                # the runtime settings projection so the panel reflects the
                # fetched vault context on load and after actions instead of
                # discarding it. An unreachable runtime renders the calm
                # no-vault default — no fabricated vault state.
                try:
                    data = self._client.get(VAULT_SETTINGS_ENDPOINT, params={})
                except WorkspaceClientError:
                    data = {}
                body = vault_settings_panel_fragment(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/companion/vault-related":
                params = {
                    key: values[0]
                    for key, values in parse_qs(parsed.query).items()
                    if values and values[0]
                }
                try:
                    data = self._client.get("/api/companion/vault-related", params=params)
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/companion/tts/status":
                try:
                    data = self._client.get("/api/companion/tts/status", params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path.startswith("/api/companion/tts/audio/"):
                self._proxy_audio(parsed.path)
                return
            if parsed.path == MEMORY_REVIEW_FRAGMENT_ROUTE:
                # Memory review drawer queue fragment (#1793, SEP-09b):
                # server-rendered from the #1792 read endpoint (the /operator
                # overlay precedent). An unreachable runtime renders a calm
                # unavailable state — never invented candidates.
                try:
                    data = self._client.get(MEMORY_REVIEW_QUEUE_ENDPOINT, params={})
                except WorkspaceClientError as exc:
                    fragment = memory_review_unavailable_fragment(str(exc))
                else:
                    fragment = memory_review_queue_fragment(data)
                body = fragment.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == RECEIPTS_HISTORY_FRAGMENT_ROUTE:
                # Receipts history fragment (#1794, SEP-10): server-rendered
                # read-only from the existing vault-browser receipts
                # projection. An unreachable runtime renders a calm
                # unavailable state — receipts are never invented by the UI.
                try:
                    data = self._client.get(RECEIPTS_PROJECTION_ENDPOINT, params={})
                except WorkspaceClientError as exc:
                    fragment = receipts_history_unavailable_fragment(str(exc))
                else:
                    fragment = receipts_history_fragment(data)
                body = fragment.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            # --- Operator diagnostics proxy (same-origin, issue #1758) ---
            # Browser calls /api/operator/* same-origin; this server proxies
            # to COMPANION_API_BASE_URL /api/* so browsers never need the
            # runtime port directly (LOCAL_ACCESS_MODEL.md).
            if parsed.path == "/operator":
                # Serve the operator overlay HTML fragment (lazy-loaded by drawer).
                # Proxy all four read endpoints first; degrade gracefully on error.
                def _op_get(runtime_path: str, params: dict | None = None) -> tuple[dict | None, str]:
                    try:
                        return self._client.get(runtime_path, params=params or {}), ""
                    except WorkspaceClientError as exc:
                        return None, str(exc)

                status_payload, status_error = _op_get("/api/status")
                health_payload, health_error = _op_get("/api/health")
                settings_payload, settings_error = _op_get("/api/settings/validate")
                events_qp = parse_qs(parsed.query)
                events_params: dict = {}
                if events_qp.get("limit"):
                    events_params["limit"] = events_qp["limit"][0]
                if events_qp.get("event_prefix"):
                    events_params["event_prefix"] = events_qp["event_prefix"][0]
                events_payload, events_error = _op_get("/api/events/tail", events_params)
                body = render_operator_overlay_html(
                    status_payload=status_payload,
                    health_payload=health_payload,
                    settings_payload=settings_payload,
                    events_payload=events_payload,
                    status_error=status_error,
                    health_error=health_error,
                    settings_error=settings_error,
                    events_error=events_error,
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/operator/status":
                try:
                    data = self._client.get("/api/status", params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/operator/health":
                try:
                    data = self._client.get("/api/health", params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/operator/settings/validate":
                try:
                    data = self._client.get("/api/settings/validate", params={})
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            if parsed.path == "/api/operator/events/tail":
                qp = parse_qs(parsed.query)
                tail_params: dict = {}
                if qp.get("limit"):
                    tail_params["limit"] = qp["limit"][0]
                if qp.get("event_prefix"):
                    tail_params["event_prefix"] = qp["event_prefix"][0]
                try:
                    data = self._client.get("/api/events/tail", params=tail_params)
                except WorkspaceClientError as exc:
                    self._proxy_error(exc)
                    return
                self._send_json(200, data)
                return
            body = handle_get(
                query_string=parsed.query,
                client=self._client,
                api_base_url=self._api_base_url,
                production_profile=self._production_profile,
                # Page origin (the Host the browser used) drives the #2124
                # remote-vs-local disambiguation — a client/page fact, not a
                # runtime signal.
                page_origin_host=self.headers.get("Host", ""),
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        # GET paths the page server proxies through to the runtime API.
        _GET_PROXY_PATHS = frozenset(
            {
                "/api/companion/orientation",
                "/api/companion/workspace",
                "/api/companion/vault/notes",
                VAULT_SETTINGS_ENDPOINT,
                "/api/companion/vault-related",
                "/api/companion/tts/status",
                "/api/operator/status",
                "/api/operator/health",
                "/api/operator/settings/validate",
                "/api/operator/events/tail",
            }
        )
        _GET_PROXY_PATTERNS = (
            re.compile(r"^/api/companion/tts/audio/[a-f0-9]{64}\.wav$"),
        )

        @classmethod
        def _get_path_allowed(cls, path: str) -> bool:
            if path in cls._GET_PROXY_PATHS:
                return True
            return any(pattern.fullmatch(path) for pattern in cls._GET_PROXY_PATTERNS)

        # POST paths the page server proxies through to the runtime API
        # (same-origin model; the browser never talks to the runtime directly).
        _POST_PROXY_PATHS = frozenset(
            {
                "/api/companion/workspace/body",
                "/api/companion/workspace/update",
                "/api/companion/capture",
                "/api/companion/note/save",  # direct human note edit
                "/api/companion/tts/plan",
                "/api/companion/tts/synthesize",
                "/api/companion/vault-browser/actions/queue-review",
                VAULT_SELECT_ENDPOINT,
                VAULT_INITIALIZE_ENDPOINT,
                VAULT_RELOAD_ENDPOINT,
                VAULT_SETTINGS_ENDPOINT,
                "/api/canvas/sessions",
                "/api/panel/confirm",
                "/api/panel/checkbox-projection",
                "/api/operator/ask",  # operator diagnostics Ask (#1758)
            }
        )

        # Dynamic POST proxy paths (session id in the path). The live canvas
        # co-authoring loop (#1733) posts the user's intent here; the runtime
        # composes/applies the body or routes a governance-bearing intent to the
        # Panel via HTTP 409. The 409/503 JSON body must be forwarded verbatim so
        # the served page can render the view-in-Panel handoff (intent_id) and
        # the provider-unavailable notice — server declares, UI renders.
        _POST_PROXY_PATTERNS = (
            re.compile(r"^/api/canvas/sessions/[^/]+/coauthor$"),
            re.compile(r"^/api/canvas/sessions/[^/]+/edits$"),
            # Governed memory review decisions (#1793 -> #1792 endpoints).
            # Runtime refusals (409, e.g. the accept dry-run) are forwarded
            # verbatim by _proxy_error so the drawer renders calm with the
            # candidate still pending.
            re.compile(r"^/api/companion/memory/review-queue/[^/]+/decision$"),
        )

        def _post_path_allowed(self, path: str) -> bool:
            if path in self._POST_PROXY_PATHS:
                return True
            return any(pattern.fullmatch(path) for pattern in self._POST_PROXY_PATTERNS)

        _DELETE_PROXY_PATTERNS = (
            re.compile(r"^/api/canvas/sessions/[^/]+$"),
            re.compile(r"^/api/canvas/sessions/[^/]+/edits/last$"),
        )

        @classmethod
        def _delete_path_allowed(cls, path: str) -> bool:
            return any(pattern.fullmatch(path) for pattern in cls._DELETE_PROXY_PATTERNS)

        @classmethod
        def route_allowed(cls, method: str, path: str) -> bool:
            method = method.upper()
            if method == "GET":
                return cls._get_path_allowed(path)
            if method == "POST":
                if path in cls._POST_PROXY_PATHS:
                    return True
                return any(pattern.fullmatch(path) for pattern in cls._POST_PROXY_PATTERNS)
            if method == "DELETE":
                return cls._delete_path_allowed(path)
            return False

        # Operator POST paths that rewrite to a different runtime path.
        # key = companion-UI path, value = runtime API path.
        _POST_PATH_REWRITES: dict[str, str] = {
            "/api/operator/ask": "/api/ask",
        }

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if not self._post_path_allowed(parsed.path):
                self._send_json(404, {"error": "not_found", "message": "Unknown Companion UI route"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or "0")
            except ValueError:
                length = 0
            raw_body = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw_body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "invalid_json", "message": "Request body must be JSON"})
                return
            runtime_path = self._POST_PATH_REWRITES.get(parsed.path, parsed.path)
            try:
                data = self._client.post(runtime_path, json=payload)
            except WorkspaceClientError as exc:
                self._proxy_error(exc)
                return
            self._send_json(200, data)

        def do_DELETE(self) -> None:
            parsed = urlparse(self.path)
            if not self._delete_path_allowed(parsed.path):
                self._send_json(404, {"error": "not_found", "message": "Unknown Companion UI route"})
                return
            try:
                data = self._client.delete(parsed.path, params={})
            except WorkspaceClientError as exc:
                self._proxy_error(exc)
                return
            self._send_json(200, data)

        def log_message(self, fmt: str, *args: object) -> None:
            pass  # suppress per-request log noise; startup banner handles visibility

    return _Handler


def main() -> None:
    """Entry point: read env config, bind server, serve until KeyboardInterrupt."""
    config = load_config()
    client = WorkspaceHttpClient(
        base_url=config["api_base_url"],
        timeout=config["api_timeout_seconds"],
    )
    handler = make_handler(client=client, api_base_url=config["api_base_url"])
    server = CompanionThreadingHTTPServer((config["host"], config["port"]), handler)
    print(
        "[companion-ui] DEV/STAGING ONLY — real-note workspace dev server",
        flush=True,
    )
    print(
        f"[companion-ui] Listening:    http://{config['host']}:{config['port']}/",
        flush=True,
    )
    print(
        f"[companion-ui] Runtime API:  {config['api_base_url']}",
        flush=True,
    )
    print(
        f"[companion-ui] API timeout:  {config['api_timeout_seconds']}s",
        flush=True,
    )
    print(
        "[companion-ui] Stop with Ctrl-C",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
