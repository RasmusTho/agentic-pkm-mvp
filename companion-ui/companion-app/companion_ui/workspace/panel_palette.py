"""⌘K Panel command palette — a presentation of the Panel rail (#1786, SEP-04).

Implements ``docs/SYSTEM_ENTRY_POINT/PANEL_COMMAND_PALETTE.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Surface composition (NORMATIVE table), §Intent vocabulary, §Overlay-grammar
rule) and ``companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md``.

The palette is **a presentation of Panel, not new authority**:

- it renders the **same server-declared proposal objects** as the rail, keyed
  by ``data-proposal-id`` (identity is never inferred from rendered position);
- every action declares the rail's transport — ``POST /api/panel/confirm`` —
  and the in-page controller performs **no I/O of its own**: a palette action
  re-dispatches to the rail's identical declared button, so the governed
  confirm flow, receipts, and blocked semantics stay exactly where they live;
- a WriteGuard-denied proposal presents as the calm guard-held state per
  ``companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md`` (gate, reason, intent
  preserved — never a generic red toast);
- it is visually and behaviorally distinct from chat: a callout states
  Panel ≠ Chat, there is no conversational input surface and no free-text
  generation — the single input only filters declared proposals (the exact
  input grammar is deferred, package Q12);
- it mounts on the shared overlay host (#1785) as the ``cmd`` occupant and
  dismisses to the document anchor via the host (Esc / scrim).

Like ``overlay_host.py``, the model functions here are pure — no network
calls, no file I/O — and the markup/script emitters return strings for
``render_index_html`` to embed.
"""

from __future__ import annotations

import html as _html
from typing import Any, Optional

from companion_ui.workspace.calm_degraded import humanise_token
from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,
)

# The overlay-host id the palette occupies (SYSTEM_ENTRY_POINT_SPEC.md
# §Allowed transitions: `overlay(cmd|…)`; §Keyboard map: ⌘K → `cmd.open`).
PALETTE_OVERLAY_ID: str = "cmd"

# Mirrors the rail's action vocabulary exactly (overlay-grammar continuity
# rule: the same proposal object shows identical status and actions in the
# rail and in the palette). Order and labels match
# `serve_dev_page._render_panel_proposal_rows`.
_ACTION_ORDER: tuple[str, ...] = ("confirm", "reject", "correct")
_ACTION_LABELS: dict[str, str] = {
    "confirm": "Apply",
    "reject": "Discard",
    "correct": "Defer",
}

# The one governed entry/shell intent the palette emits (spec §Intent
# vocabulary: `panel.confirm` — surface "Panel (rail or palette)").
_CONFIRM_INTENT: str = "panel.confirm"


def _e(value: Any) -> str:
    return _html.escape(str(value), quote=True)


def palette_row_model(
    proposal: dict[str, Any],
    *,
    writeguard_blocked: bool,
) -> dict[str, Any]:
    """Pure row model for one server-declared Panel proposal.

    Derives exactly what the rail derives — availability from the declared
    status plus the WriteGuard state, enabled actions from the declared
    affordances — and nothing else. Identity stays the declared
    ``proposal_id``; no positional or palette-local identity is introduced.
    """
    evidence = proposal.get("evidence") or {}
    affordances = proposal.get("affordances") or {}
    status = str(proposal.get("status") or "staged")
    available = status in {"staged", "corrected"} and not writeguard_blocked
    actions: tuple[str, ...] = (
        tuple(label for label in _ACTION_ORDER if affordances.get(label))
        if available
        else ()
    )
    proposal_id = str(proposal.get("proposal_id") or "")
    description = str(proposal.get("description") or "")
    action_class = str(evidence.get("action_class") or "")
    return {
        "proposal_id": proposal_id,
        "artifact_id": str(proposal.get("artifact_id") or ""),
        "description": description,
        "action_class": action_class,
        "status": status,
        "available": available,
        "guard_held": writeguard_blocked,
        "actions": actions,
        # Filter haystack (simple substring grammar; package Q12 deferred).
        # Include the humanised action-class label so typing the *visible* text
        # (e.g. "Move note") matches the row even when the description does not
        # already contain it (CUIDR-01: the user filters on what they see).
        "filter_text": " ".join(
            part
            for part in (
                description,
                action_class,
                humanise_token(action_class),
                proposal_id,
            )
            if part
        ).lower(),
    }


def filter_palette_rows(
    rows: list[dict[str, Any]],
    query: str,
) -> list[dict[str, Any]]:
    """Filter palette row models by a simple case-insensitive substring.

    A blank query selects every declared proposal. Filtering only selects
    among rows — identity stays keyed by ``proposal_id`` regardless of input
    order or rendered position (exact input grammar deferred — package Q12).
    """
    needle = str(query or "").strip().lower()
    if not needle:
        return list(rows)
    return [
        row
        for row in rows
        if needle in str(row.get("filter_text") or "").lower()
    ]


def _row_actions_html(row: dict[str, Any]) -> str:
    proposal_id = _e(row["proposal_id"])
    artifact_id = _e(row["artifact_id"])
    if row["guard_held"]:
        # Calm guard-held affordance (BLOCKED_AND_STALE_STATE_SPEC.md
        # §Blocked — WriteGuard / policy): named gate, intent preserved,
        # nothing mutated — never a dead button, never an alarm.
        return (
            '<span class="palette-proposal-held" '
            'data-testid="palette-proposal-held" '
            'data-guard-held="true" '
            'data-guard-gate="writeguard" '
            f'data-proposal-id="{proposal_id}">'
            "guard-held — intent preserved; nothing was mutated</span>"
        )
    if not row["available"]:
        return (
            '<span class="palette-proposal-unavailable" '
            'data-testid="palette-proposal-unavailable" '
            'data-affordance-status="unavailable" '
            f'data-proposal-id="{proposal_id}">'
            f"{_e(row['status'])} proposal unavailable</span>"
        )
    buttons: list[str] = []
    for label in row["actions"]:
        # `panel.confirm` is the declared governed intent (spec §Intent
        # vocabulary). `reject` uses the same ConfirmRequest transport as the
        # rail; `correct` remains visible but presentation-only until a
        # correction payload exists.
        if label == "correct":
            buttons.append(
                '<button type="button" class="palette-proposal-action" '
                'data-testid="palette-proposal-action" '
                f'data-panel-action="{_e(label)}" '
                f'data-proposal-id="{proposal_id}" '
                f'data-artifact-id="{artifact_id}" '
                'data-runtime-backed="false" '
                'data-affordance-status="presentation-only" '
                'disabled aria-disabled="true">'
                f"{_ACTION_LABELS[label]}</button>"
            )
            continue
        intent_attr = (
            f'data-intent="{_CONFIRM_INTENT}" ' if label == "confirm" else ""
        )
        buttons.append(
            '<button type="button" class="palette-proposal-action" '
            'data-testid="palette-proposal-action" '
            f'data-panel-action="{_e(label)}" '
            f"{intent_attr}"
            f'data-proposal-id="{proposal_id}" '
            f'data-artifact-id="{artifact_id}" '
            'data-runtime-backed="true" '
            'data-api-method="POST" '
            'data-api-path="/api/panel/confirm">'
            f"{_ACTION_LABELS[label]}</button>"
        )
    return "".join(buttons)


def _rows_html(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<li class="palette-empty" data-testid="palette-empty">'
            "No staged proposals — the Panel rail is idle.</li>"
        )
    items: list[str] = []
    for row in rows:
        items.append(
            '<li class="palette-proposal-row" '
            'data-testid="palette-proposal-row" '
            f'data-proposal-id="{_e(row["proposal_id"])}" '
            f'data-artifact-id="{_e(row["artifact_id"])}" '
            f'data-proposal-status="{_e(row["status"])}" '
            f'data-action-class="{_e(row["action_class"])}" '
            f'data-filter-text="{_e(row["filter_text"])}">'
            f'<span class="palette-row-desc">{_e(row["description"])}</span>'
            '<span class="palette-row-class" '
            f'data-testid="palette-proposal-class">{_e(humanise_token(row["action_class"]))}</span>'
            '<span class="palette-row-status" '
            f'data-testid="palette-proposal-status">{_e(row["status"])}</span>'
            f'<span class="palette-row-actions">{_row_actions_html(row)}</span>'
            "</li>"
        )
    return "".join(items)


def _blocked_html(response: dict[str, Any]) -> str:
    """The calm guard-held blocked state for a denied confirmation.

    Same server-declared block data the rail surfaces, presented per
    BLOCKED_AND_STALE_STATE_SPEC.md: gate named, reason shown, intent
    preserved — distinct from a generic failure treatment.
    """
    block_reason = response.get("block_reason") or {}
    if str(response.get("status") or "") != "blocked" or not block_reason:
        return ""
    gate = str(block_reason.get("gate") or "unknown")
    message = str(block_reason.get("message") or "")
    # Mirror the rail's same-turn message normalization exactly.
    if gate == "same-turn" or "same-turn" in message.lower():
        message = (
            "Same-turn confirmation is not allowed. "
            "The proposal must be confirmed in a later interaction."
        )
    return (
        '<div class="palette-blocked" data-testid="palette-blocked" '
        'data-guard-held="true" '
        f'data-guard-gate="{_e(gate)}" '
        f'data-proposal-id="{_e(response.get("proposal_id") or "")}">'
        f'<span data-testid="palette-blocked-gate">{_e(gate)}</span>'
        f'<span data-testid="palette-blocked-message">{_e(message)}</span>'
        '<span data-testid="palette-blocked-intent">'
        "Intent preserved — nothing was mutated; the proposal stays held."
        "</span></div>"
    )


def _receipt_html(response: dict[str, Any]) -> str:
    """The runtime receipt, surfaced exactly as the rail surfaces it.

    Same server-declared receipt object, same field fallbacks as
    `serve_dev_page._render_panel_confirm_response` — rendered only when the
    runtime declared one (no receipt invention).
    """
    status = str(response.get("status") or "")
    receipt = response.get("receipt") or {}
    if status not in {"executed", "logged"} or not receipt:
        return ""
    outcome = receipt.get("outcome") or response.get("outcome") or status
    message = receipt.get("message") or receipt.get("action_taken") or status
    timestamp = (
        receipt.get("timestamp")
        or response.get("timestamp")
        or "timestamp unavailable"
    )
    return (
        '<div class="palette-receipt" data-testid="palette-receipt" '
        'data-receipt-persistence="durable-runtime-projection" '
        f'data-proposal-id="{_e(response.get("proposal_id") or "")}">'
        f'<span data-testid="palette-receipt-outcome">{_e(outcome)}</span>'
        f'<span data-testid="palette-receipt-message">{_e(message)}</span>'
        f'<span data-testid="palette-receipt-timestamp">{_e(timestamp)}</span>'
        "</div>"
    )


# Scoped styles travel with the occupant so the palette is one self-contained
# region (single host-layer slice; the shell stylesheet is untouched). The
# palette sits above the host scrim (z-index 900) alongside the vault modal
# (z-index 1000).
_PALETTE_CSS = """
    .panel-palette {
      display: none;
      position: fixed;
      top: 12vh;
      left: 50%;
      transform: translateX(-50%);
      width: min(560px, calc(100vw - 32px));
      max-height: 70vh;
      overflow: auto;
      z-index: 1000;
      background: var(--bg-overlay);
      border: 1px solid var(--border-strong);
      border-radius: 10px;
      padding: 14px;
      font-family: 'Space Grotesk', sans-serif;
    }
    .panel-palette[data-open="true"] { display: flex; flex-direction: column; gap: 10px; }
    .palette-not-chat {
      margin: 0;
      font-size: 0.78rem;
      color: var(--fg-2);
      border-left: 2px solid var(--accent-dim);
      padding-left: 8px;
    }
    .palette-filter {
      width: 100%;
      box-sizing: border-box;
      background: var(--bg-raised);
      color: var(--fg-1);
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      padding: 8px 10px;
      font-family: inherit;
    }
    .palette-filter:focus { outline: none; border-color: var(--border-focus); }
    .palette-proposal-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .palette-proposal-row {
      display: flex;
      flex-wrap: wrap;
      align-items: baseline;
      gap: 8px;
      background: var(--bg-raised);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 8px 10px;
    }
    .palette-proposal-row[data-filter-hit="false"] { display: none; }
    .palette-row-desc { color: var(--fg-1); flex: 1 1 100%; }
    .palette-row-class, .palette-row-status {
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.7rem;
      color: var(--fg-2);
    }
    .palette-row-actions { display: flex; gap: 6px; margin-left: auto; }
    .palette-proposal-action {
      background: var(--bg-overlay);
      color: var(--fg-1);
      border: 1px solid var(--border-strong);
      border-radius: 6px;
      padding: 3px 10px;
      font-family: inherit;
      font-size: 0.75rem;
      cursor: pointer;
    }
    .palette-proposal-action:hover { border-color: var(--border-focus); }
    .palette-proposal-held, .palette-proposal-unavailable {
      font-size: 0.72rem;
      color: var(--fg-2);
    }
    .palette-blocked {
      display: flex;
      flex-direction: column;
      gap: 4px;
      border: 1px solid var(--amber-dim);
      border-radius: 8px;
      background: var(--amber-muted);
      color: var(--fg-1);
      padding: 8px 10px;
      font-size: 0.78rem;
    }
    .palette-receipt {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      border: 1px solid var(--vault-dim);
      border-radius: 8px;
      background: var(--vault-muted);
      color: var(--fg-1);
      padding: 8px 10px;
      font-size: 0.78rem;
    }
    .palette-empty { color: var(--fg-2); font-size: 0.78rem; list-style: none; }
    .palette-head { display: flex; justify-content: space-between; align-items: center; }
    .palette-title {
      color: var(--fg-2);
      font-size: 0.72rem;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
"""


def panel_palette_markup(fields: Optional[dict[str, Any]]) -> str:
    """The palette occupant markup for the shared overlay host.

    Pure presentation of the same ``fields`` the rail renders from: the
    server-declared proposal set, the WriteGuard state, and the last declared
    Panel response (receipt or block). With no loaded note there is no Panel
    lane to present, so no surface is emitted (the host keeps ``⌘K`` a
    graceful no-op rather than inventing an empty surface).
    """
    if fields is None:
        return ""
    writeguard_blocked = (
        str(fields.get("guard_writeguard_status", "ok")).lower() == "blocked"
    )
    rows = [
        palette_row_model(proposal, writeguard_blocked=writeguard_blocked)
        for proposal in (fields.get("panel_proposals") or [])
    ]
    response = fields.get("panel_last_response") or {}
    return f"""
  <!-- panel-palette (#1786, SEP-04) -->
  <style>{_PALETTE_CSS}</style>
  <div class="panel-palette" id="panel-palette"
       data-testid="panel-palette" data-region="panel-palette"
       data-overlay-id="{PALETTE_OVERLAY_ID}"
       data-authority-surface="panel"
       data-presentation-of="panel-rail"
       data-open="false"
       role="dialog" aria-modal="true" aria-label="Panel command palette">
    <div class="palette-head" data-testid="palette-head">
      <span class="palette-title">Panel</span>
      {guidance_toggle_markup('cmd')}
    </div>
    {guidance_callout_markup('cmd')}
    <p class="palette-not-chat" data-testid="palette-not-chat-callout">Panel ≠ Chat — a faster presentation of the same governed Panel proposals; no free-text generation, no conversation.</p>
    <input type="search" class="palette-filter" id="palette-filter-input"
           data-testid="palette-filter-input" data-input-role="filter"
           placeholder="Filter declared proposals…" autocomplete="off"
           aria-label="Filter declared proposals">
    <ul class="palette-proposal-list" data-testid="palette-proposal-list">{_rows_html(rows)}</ul>
    {_blocked_html(response)}{_receipt_html(response)}
  </div>
  <!-- /panel-palette -->"""


def panel_palette_script() -> str:
    """The in-page palette controller.

    Registers the palette as the host's ``cmd`` occupant (open via ``⌘K`` /
    ``cmd.open``; Esc and the scrim dismiss to the anchor through the host).
    Filtering only hides rows (identity stays on ``data-proposal-id``). Action
    clicks post the same proposal/action payload as the Panel confirm path.
    Correct is rendered as a presentation-only affordance here because the
    runtime ConfirmRequest does not accept ``action: "correct"``.
    """
    return """
  <script>
  /* panel-palette-controller */
  (function() {
    var root = document.getElementById('panel-palette');
    if (!root || !window.overlayHost) { return; }
    var input = document.getElementById('palette-filter-input');
    function applyFilter() {
      var needle = input ? String(input.value || '').trim().toLowerCase() : '';
      var rows = root.querySelectorAll('[data-testid="palette-proposal-row"]');
      rows.forEach(function(row) {
        var hay = String(row.getAttribute('data-filter-text') || '').toLowerCase();
        var hit = !needle || hay.includes(needle);
        row.setAttribute('data-filter-hit', hit ? 'true' : 'false');
      });
    }
    function setOpen(open) {
      root.setAttribute('data-open', open ? 'true' : 'false');
      if (open) {
        if (input) { input.value = ''; }
        applyFilter();
        if (input) { input.focus(); }
      }
    }
    if (input) { input.addEventListener('input', applyFilter); }
    function panelPayload(btn) {
      var action = btn.getAttribute('data-panel-action') || 'confirm';
      return {
        proposal_id: btn.getAttribute('data-proposal-id') || '',
        artifact_id: btn.getAttribute('data-artifact-id') || '',
        action: action,
        idempotency_key: 'palette:' + (btn.getAttribute('data-proposal-id') || '')
          + ':' + action
          + ':' + Date.now()
      };
    }
    function postPanelAction(btn) {
      var path = btn.getAttribute('data-api-path') || '/api/panel/confirm';
      return fetch(path, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(panelPayload(btn))
      });
    }
    root.addEventListener('click', function(e) {
      var btn = e.target && e.target.closest
        ? e.target.closest('[data-testid="palette-proposal-action"]')
        : null;
      if (!btn) { return; }
      if (btn.getAttribute('data-runtime-backed') !== 'true') { return; }
      postPanelAction(btn);
    });
    // The host owns mount/dismiss (Esc / scrim -> document anchor).
    window.overlayHost.register('cmd', {
      open: function() { setOpen(true); },
      close: function() { setOpen(false); }
    });
  })();
  /* /panel-palette-controller */
  </script>"""
