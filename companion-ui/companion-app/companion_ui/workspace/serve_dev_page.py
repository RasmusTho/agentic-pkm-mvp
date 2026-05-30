"""Minimal browser dev server for the real-note workspace page (#1103).

DEV/STAGING ONLY — not for production use.

Does not implement auth, TLS, reverse proxy, or public exposure.
Calls the configured runtime API through WorkspaceHttpClient
(GET /api/companion/workspace). Does not read vault files directly.
Vault binding is determined by the runtime environment, not by this server.

Environment variables:
    HOST                   Bind address         (default: 127.0.0.1)
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

Local dev:
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=127.0.0.1 PORT=8111 \\
        python -m companion_ui.workspace.serve_dev_page

LAN/Tailscale (explicit operator action required — not the default):
    cd companion-ui/companion-app
    COMPANION_API_BASE_URL=http://127.0.0.1:18001 HOST=0.0.0.0 PORT=8111 \\
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
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

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
from companion_ui.workspace.real_note_workspace_dev_page import (
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.workspace_http_client import WorkspaceHttpClient
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientError,
    WorkspaceClientHTTPError,
)

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8111
_DEFAULT_API_BASE_URL = "http://127.0.0.1:18001"


def load_config() -> dict:
    """Load server configuration from environment variables.

    Returns a dict with keys: host, port, api_base_url.
    Defaults: HOST=127.0.0.1, PORT=8111, COMPANION_API_BASE_URL=http://127.0.0.1:18001.
    """
    return {
        "host": os.environ.get("HOST", _DEFAULT_HOST),
        "port": int(os.environ.get("PORT", str(_DEFAULT_PORT))),
        "api_base_url": os.environ.get("COMPANION_API_BASE_URL", _DEFAULT_API_BASE_URL),
    }


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
    # Path segments — keep raw slashes as separators for readability
    path_segments = note_path.replace("&amp;", "&").split("/")
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

    raw_path = note_path.replace("&amp;", "&")
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
    return f"""
      <header
        class="workspace-header-strip primary-posture posture-tone-{posture}"
        data-testid="workspace-primary-posture"
        data-posture="{posture}"
        data-region="workspace-header">
        <div class="workspace-header-row" data-testid="workspace-header-row">
          <a class="workspace-wordmark" data-testid="workspace-wordmark" href="/" aria-label="Return to vault root">Yggdrasil</a>
          <a class="workspace-vault-chip" data-testid="workspace-vault-chip" data-state="{vault_state}" data-vault-provenance="{_e(vault_provenance)}" href="{browse_target}">
            <span class="workspace-vault-dot" aria-hidden="true"></span>
            <span>{vault_name} · vault {vault_state}</span>
          </a>
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
          <button class="workspace-quick-open" data-testid="workspace-quick-open" type="button" aria-disabled="true" title="Quick-open is visual only in this slice">
            <kbd>/</kbd><span>⌘K</span>
          </button>
          <button class="workspace-browse-vault" data-testid="workspace-browse-vault" type="button" data-browse-target="vault-browser-pane" onclick="vaultBrowser.focus()">Browse vault</button>
          {dev_ribbon}
        </div>
      </header>"""


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


def _render_body_edit_panel(update_flow_available: bool, note_path: str, raw_body: str = "") -> str:
    if not update_flow_available:
        return (
            '<section class="body-edit-panel body-edit-disabled workspace-action-absent" '
            'data-testid="workspace-action-absent" '
            'data-action="body-edit" '
            'data-reason="update_flow_disabled" '
            'data-update-flow="disabled">'
            '<span class="absent-label" data-testid="workspace-body-edit-panel">'
            "&#9998; Read only</span>"
            '<span class="absent-reason">'
            "This note is open for reading. Editing is not enabled in this workspace."
            "</span>"
            "</section>"
        )
    return f"""<div class="body-edit-panel" data-testid="workspace-body-edit-panel"
         data-update-flow="available">
  <div class="body-edit-header">
    <span class="body-edit-label">Edit note body</span>
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
</div>"""


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


def _render_note_section(fields: dict) -> str:
    """Render the workspace shell from render_fields() output.

    Uses Yggdrasil design tokens. Stable data-testid / data-region attributes
    match the region constants in real_note_workspace_shell.py for future
    Canvas/Panel integration.
    """
    title = _e(fields.get("title", ""))
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
    rendered_body = render_vault_markdown(raw_body, note_path=raw_note_path)
    body = rendered_body.html
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
            "Artifact identity unresolved; runtime may block governed actions until identity is resolved."
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
    read_only_pill_html = _render_read_only_pill() if not canvas_enabled else ""
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
          data-read-only="true">
          <div class="note-body-readonly-indicator"
            data-testid="workspace-note-body-readonly-indicator"
            data-read-only="true">read-only</div>
          <div class="note-body-readonly-reason"
            data-testid="workspace-note-body-readonly-reason"
            aria-live="polite"
            hidden>
            Editing is currently disabled by runtime configuration.&#160;<a
              href="#workspace-runtime-telemetry"
              data-testid="workspace-note-body-readonly-why">Why?</a>
          </div>
          {read_only_pill_html}
          <div class="note-body-content">{body}</div>
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
      <div class="rail-placeholder-body">
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
        {act_mode_html}
        {guard_html}
        {persistence_html}
        {panel_rail}
        {rail_empty_state_html}
      </div>
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

    return f"""
        <section
          class="active-note-body-update-flow"
          data-testid="workspace-active-note-body-update-flow"
          data-flow-state="enabled">
          <label for="active_note_body_update_input">Active note body update</label>
          <textarea
            id="active_note_body_update_input"
            data-testid="workspace-active-note-body-update-input"
            aria-label="Active note body update input"></textarea>
          <button
            type="button"
            data-testid="workspace-active-note-body-update-submit"
            data-api-method="POST"
            data-api-path="/api/companion/workspace/update"
            data-note-path="{_e(note_path)}"
            data-content-hash="{_e(content_hash)}">Update body</button>
          {status_html}
        </section>"""


def _render_artifact_inspector(
    note: dict,
    *,
    vault_name: str,
    vault_channel: str,
) -> str:
    """Render a read-only artifact inspector panel for the selected note.

    Tabs/sections: Metadata, Health, Provenance, Links placeholder, Receipts placeholder.
    Inspector is read-only; no edit controls rendered. Client uses normalized server
    payload only — no frontmatter parsing here (#1255).
    """
    title = _e(str(note.get("title") or ""))
    path = _e(str(note.get("note_path") or ""))
    kind_val = note.get("kind")
    zone_val = note.get("zone")
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
        _field_row("workspace-vault-browser-inspector-zone", "zone", zone_val),
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

    links_placeholder = (
        '<div data-testid="workspace-vault-browser-inspector-links-placeholder" '
        'class="inspector-placeholder" data-affordance-status="unavailable">'
        'Links: not connected yet.'
        '</div>'
    )
    actions_html = _render_vault_actions(note)
    receipts_html = _render_inspector_receipts(note)
    posture_html = _render_inspector_review_posture(note)

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
        f'{actions_html}'
        f'{links_placeholder}'
        f'{receipts_html}'
        f'</section>'
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
    for receipt in receipts:
        receipt_id = str(receipt.get("receipt_id") or "")
        state = str(receipt.get("state") or "unknown")
        action_type = str(receipt.get("action_type") or "")
        trace_id = str(receipt.get("trace_id") or "")
        receipt_state = state if state in _RECEIPT_STATES else "unknown"
        rows.append(
            f'<div class="receipt-row" '
            f'data-testid="vault-browser-receipt-row" '
            f'data-receipt-state="{_e(receipt_state)}">'
            f'<span data-testid="vault-browser-receipt-id" class="receipt-id">{_e(receipt_id)}</span>'
            f'<span data-testid="vault-browser-receipt-state" class="receipt-state">{_e(state)}</span>'
            f'<span data-testid="vault-browser-receipt-action-type" class="receipt-action">{_e(action_type)}</span>'
            + (
                f'<span data-testid="vault-browser-receipt-trace-id" class="receipt-trace">{_e(trace_id)}</span>'
                if trace_id else ""
            )
            + '</div>'
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
            disabled=True,
            disabled_reason="Find not connected for this artifact.",
        ),
        _action(
            "vault-action-queue-review",
            "Queue for review",
            "governance_write",
            blocked=True,
            blocked_reason="Review queue not connected. Governed writes require a receipt.",
            requires_receipt=True,
            requires_confirmation=True,
        ),
    ]
    return (
        '<div class="vault-action-strip" '
        'data-testid="workspace-vault-browser-inspector-actions">'
        + "".join(actions)
        + "</div>"
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
    return (
        '<div class="vault-browser-filters" data-testid="workspace-vault-browser-filters">'
        + "".join(chips_html)
        + "</div>"
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

    rows: list[str] = []
    for note in notes:
        path = str(note.get("note_path") or "").strip()
        if not path:
            continue
        title = _e(note.get("title") or path)
        zone = _e(note.get("zone") or "root")
        href = "/?note_path=" + quote(path, safe="/")
        active = "true" if path == note_path else "false"

        # Per-note metadata badges: hidden from the nav list by default (daily-use
        # visibility pass). The inspector panel shows the full metadata. These
        # elements retain their data-testid for test compatibility but are visually
        # hidden so the nav list stays calm and navigation-focused.
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
            health_badge = (
                f'<span class="note-badge note-badge--health note-badge--health-invalid" '
                f'data-testid="workspace-vault-browser-note-health" '
                f'data-missing-fields="{_e(missing_label)}">missing: {_e(missing_label)}</span>'
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

        rows.append(
            f"""
          <li class="vault-browser-row{row_extra_class}" data-testid="workspace-vault-browser-note-row" data-active="{active}"{row_kind_attr}{row_companion_attr}{row_nav_attr}{row_hidden_attr}>
            <a href="{href}" data-testid="workspace-vault-browser-note-link">{title}</a>
            <code data-testid="workspace-vault-browser-note-path">{_e(path)}</code>
            <span data-testid="workspace-vault-browser-note-zone" class="vault-browser-zone-label">{zone}</span>
            {badges_html}
          </li>"""
        )

    list_html = (
        '<ul class="vault-browser-list" data-testid="workspace-vault-browser-list">'
        + "".join(rows)
        + "</ul>"
        if rows
        else ""
    )
    read_only_text = "read-only" if read_only else "mutating"
    # Calm provenance label for daily-use visibility; raw value in data attribute.
    calm_provenance = "read-only fallback · filesystem index" if read_only else "filesystem index"
    filters_html = _render_filter_chips(notes, active_filters or {})
    selected_note = next((n for n in notes if str(n.get("note_path") or "").strip() == note_path), None)
    inspector_html = (
        _render_artifact_inspector(selected_note, vault_name=vault_name, vault_channel=vault_channel)
        if selected_note is not None
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
          {list_html}
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
    visible = "true" if sheet.get("is_visible") else "false"
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
      aria-hidden="{visible == "false"}">
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
        return f"""
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
    recovery_api_path = f"/api/canvas/sessions/{session_id}/recovery/ack" if session_id else ""
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
              data-api-method="LOCAL"
              data-api-path="{recovery_api_path}">Acknowledge</button>
          </div>"""
    return f"""
        <div class="canvas-controls" data-testid="workspace-canvas-session-controls">
          {start_html}
          {close_html}
          {edit_button_html}
          {undo_button_html}
          {unavailable_html}
          <span class="canvas-presence" data-testid="workspace-canvas-user-present" data-user-present="{'true' if user_present else 'false'}">{present_text}</span>
          {composer_html}
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


def _render_error_section(error: str) -> str:
    """Render a visible error state using Yggdrasil destructive tokens."""
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
    runtime_unavailable = any(
        marker in error.lower()
        for marker in ("connection refused", "timed out", "timeout", "network")
    )
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
    <span class="error-message"><code>{_e(error)}</code></span>
  </div>"""


def render_index_html(
    *,
    api_base_url: str,
    note_path: str = "",
    fields: Optional[dict] = None,
    error: str = "",
    production_profile: bool = False,
) -> str:
    """Render the workspace dev page as a Companion UI visual shell.

    Pure function — no network calls, no file I/O.
    All user-supplied values are HTML-escaped.

    This is the first visual-alignment pass (not production UI). It uses
    Yggdrasil design tokens and the workspace region contract from
    real_note_workspace_shell.py. Canvas body-edit and Panel execution
    are not implemented; the agent rail is a placeholder.
    """
    content_section = ""
    if error:
        content_section = _render_error_section(error)
    elif fields is not None:
        content_section = _render_note_section(fields)
    title_suffix = "PROD" if production_profile else "DEV"
    dev_chip = "" if production_profile else '<span class="dev-chip">DEV / not production</span>'
    production_static_link = (
        '<link rel="stylesheet" href="/static/companion-workspace.css">'
        if production_profile
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Companion UI — Real-Note Workspace [{title_suffix}]</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:ital,wght@0,400;0,500;1,400&family=Space+Grotesk:wght@300;400;500;600&display=swap" rel="stylesheet">
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
      --cyan:          #00d4e8;
      --cyan-muted:    #001e28;
      --agent:         #4a9eff;
      --agent-muted:   #051228;
      --destructive:      #ff3d3d;
      --destructive-muted:#160404;
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
      background-image:
        linear-gradient(rgba(0,212,232,0.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(0,212,232,0.022) 1px, transparent 1px);
      background-size: 48px 48px;
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
    .note-badge--nav-hidden {{ opacity: 0.45; }}

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
    }}
    .workspace-quick-open kbd {{
      background: transparent;
      color: var(--fg-2);
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
      background: rgba(212,168,67,0.08);
      border: 1px solid rgba(212,168,67,0.35);
      border-radius: var(--radius-md);
      color: var(--accent);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      margin-top: 10px;
      padding: 8px 10px;
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
    /* Design review §6.1 — body column is a reading surface, not a card.
       Background matches the page; no inset border; line-length capped at 68ch.
       §3.3/§7 — the reading column does not own a second nested scroll and is
       not height-clamped; it grows naturally inside the .note-body scroll. */
    .note-body-content {{
      background: var(--bg-base);
      border: none;
      border-radius: 0;
      margin: 0 auto;
      max-width: 68ch;
      min-height: 0;
      padding: 40px 32px 48px;
      font-family: var(--font-ui);
      font-size: var(--text-base);
      color: var(--fg-1);
      /* §6.3 — paragraph rhythm */
      line-height: 1.65;
      word-break: break-word;
    }}
    /* Design review §6.2 — heading scale (sharp step-down between levels). */
    .vault-markdown-rendered h1 {{
      font-family: var(--font-display);
      font-size: 40px;
      line-height: 44px;
      font-weight: 400;
      letter-spacing: -0.02em;
      color: var(--fg-1);
      margin: 0 0 32px;
    }}
    .vault-markdown-rendered h2 {{
      font-family: var(--font-ui);
      font-size: 22px;
      line-height: 28px;
      font-weight: 600;
      letter-spacing: -0.005em;
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
    /* §6.5 — task lists: custom checkboxes; read-only is the truth in v0. */
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
    .vault-markdown-rendered li.task-list-item > input[type="checkbox"]:checked {{
      background: var(--accent-dim);
      border-color: var(--accent);
    }}
    .vault-markdown-rendered li.task-list-item > input[type="checkbox"]:checked::after {{
      content: "";
      position: absolute;
      left: 3px;
      top: 0px;
      width: 4px;
      height: 8px;
      border: solid var(--bg-base);
      border-width: 0 1.5px 1.5px 0;
      transform: rotate(45deg);
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
      background: rgba(212,168,67,0.08);
      border-left: 3px solid var(--accent);
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
      color: var(--accent);
      display: block;
      font-size: var(--text-xs);
      letter-spacing: 0.06em;
      margin-bottom: 4px;
      text-transform: uppercase;
    }}

    /* ---- Agent rail ---- */
    .agent-rail {{
      width: 280px;
      flex-shrink: 0;
      background: var(--bg-surface);
      border-left: 1px solid var(--border);
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
      border: 1px solid rgba(74,158,255,0.2);
      color: var(--agent);
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
    .rail-alert {{
      border-radius: var(--radius-md);
      font-family: var(--font-mono);
      font-size: var(--text-xs);
      font-style: normal;
      padding: 8px 10px;
    }}
    .rail-alert-blocked {{
      background: var(--destructive-muted);
      border: 1px solid rgba(255,61,61,0.3);
      color: var(--destructive);
    }}
    .rail-alert-muted {{
      background: var(--bg-raised);
      border: 1px solid var(--border);
      color: var(--fg-2);
    }}
    .panel-message {{
      border-left: 2px solid var(--accent);
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
      border: 1px solid rgba(255,61,61,0.3);
      border-radius: var(--radius-md);
      color: var(--destructive);
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
      border: 1px solid var(--border);
      border-radius: var(--radius-md);
      color: var(--fg-2);
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 10px;
    }}
    .suggestion-card[data-variant="blocked"] {{
      border-color: rgba(255,61,61,0.3);
    }}
    .suggestion-card-title {{
      color: var(--fg-1);
      font-size: var(--text-sm);
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
      border: 1px solid var(--border);
      border-left: 2px solid var(--agent);
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
      color: var(--agent);
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
      background: var(--accent);
      border: none;
      border-radius: var(--radius-md);
      color: white;
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
      border: 1px solid var(--border);
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
    .panel-confirm-receipt {{ color: var(--fg-1); }}
    .panel-confirm-blocked {{ color: var(--destructive); }}
    /* Body edit panel */
    .body-edit-panel {{
      border: 1px solid var(--border-strong);
      border-radius: var(--radius-md);
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-top: 12px;
      padding: 12px;
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
      min-height: 200px;
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
<body>
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
        <button class="vault-browser-close" onclick="vaultBrowser.close()"
                data-testid="vault-browser-close" aria-label="Close">&times;</button>
      </div>
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

    document.addEventListener('keydown', function(e) {{
      if (e.key === 'Escape') vaultBrowser.close();
    }});
  }})();
  </script>

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
  }}
  </script>
  <script>
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
</body>
</html>"""


def handle_get(
    *,
    query_string: str,
    client: WorkspaceHttpClient,
    api_base_url: str,
    production_profile: bool = False,
) -> str:
    """Parse query string, optionally load a note, and return full page HTML.

    Pure except for the WorkspaceHttpClient network call when note_path is present.
    """
    params = parse_qs(query_string)
    note_path = params.get("note_path", [""])[0].strip()
    _filter_keys = ("kind", "zone", "review_state", "trust")
    active_filters = {k: params[k] for k in _filter_keys if params.get(k)}
    fields: Optional[dict] = None
    error = ""

    if note_path:
        page = RealNoteWorkspaceDevPage(client)
        state = page.load(NoteLoadIntent(note_path=note_path, active_filters=active_filters))
        if state.is_loaded:
            fields = page.render_fields()
        else:
            error = state.error or "Unknown error"

    return render_index_html(
        api_base_url=api_base_url,
        note_path=note_path,
        fields=fields,
        error=error,
        production_profile=production_profile,
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

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in self._static_assets:
                content_type, body = self._static_assets[parsed.path]
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
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
            body = handle_get(
                query_string=parsed.query,
                client=self._client,
                api_base_url=self._api_base_url,
                production_profile=self._production_profile,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/api/companion/workspace/body":
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
            try:
                data = self._client.post("/api/companion/workspace/body", json=payload)
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
    client = WorkspaceHttpClient(base_url=config["api_base_url"])
    handler = make_handler(client=client, api_base_url=config["api_base_url"])
    server = HTTPServer((config["host"], config["port"]), handler)
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
