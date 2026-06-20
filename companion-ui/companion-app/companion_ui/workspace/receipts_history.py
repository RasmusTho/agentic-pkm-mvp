"""Receipts history surface — read-only receipts modal (#1794, SEP-10).

Implements ``docs/SYSTEM_ENTRY_POINT/RECEIPTS_HISTORY_SURFACE.md`` against the
normative contracts in ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md``
(§Surface composition — Receipts/history row: Receipt class, read-only, top
modal via ``receipts.open``; §Authority boundaries — "Receipts are never
invented by the UI") and ``companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md``
(a held boundary is a success of the governance model, not a failure of the
app).

Give governed outcomes a place to live beyond a transient toast:

- The modal mounts on the shared overlay host (#1785) as the declared
  ``receipts`` occupant — a top modal opened from the topbar surface icon
  (``receipts.open``), dismissing through the host back to the document
  anchor with no route reset and no data loss.
- It renders a bounded recent list of **existing runtime-produced receipt
  projections**: the per-note ``receipts`` rows the runtime already serves on
  ``GET /api/companion/vault-browser`` (projected from governed outbox
  records and promotion receipts by ``app/receipts/artifact_receipts.py``).
  Outcome, id, target path, and timestamp render verbatim — the runtime's
  words, never re-classified, never re-derived.
- Strictly read-only: the surface performs reads only. There is no receipt
  creation, no mutation affordance, no aggregation the runtime does not
  declare, and no receipt is ever invented, edited, or re-derived. A surface
  with any write affordance would instantly be a new control surface, which
  the composition forbids.
- Blocked receipts render with their guard posture: history shows held
  boundaries as held boundaries (calm, named, nothing mutated), visually
  distinct from generic failures.

Like ``overlay_host.py`` and ``memory_review_drawer.py``, the pure
projections in this module are the contract the in-page controller
(:func:`receipts_history_script`) mirrors; tests assert both. Nothing here
performs I/O — the page server proxies the existing runtime read same-origin
and serves the server-rendered fragment at
:data:`RECEIPTS_HISTORY_FRAGMENT_ROUTE`.
"""

from __future__ import annotations

import html as _html
from typing import Any

from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,
)

# The overlay-host id this surface occupies (declared in
# overlay_host.DECLARED_OVERLAYS; shipped via SHIPPED_OVERLAY_OCCUPANTS).
RECEIPTS_OVERLAY_ID = "receipts"

# The existing runtime read serving the receipts projection: the vault
# browser response carries ``notes[].receipts`` rows projected read-only from
# governed outbox records (app/receipts/artifact_receipts.py). This surface
# adds no new receipt source and no new endpoint.
RECEIPTS_PROJECTION_ENDPOINT = "/api/companion/vault-browser"

# Page-server route serving the server-rendered history fragment (the
# /memory-review precedent): the modal lazily fetches HTML the server
# composed from the runtime payload, so rendering stays a pure, testable
# Python function.
RECEIPTS_HISTORY_FRAGMENT_ROUTE = "/receipts-history"

# Bounded recent list (issue #1794 constraint): retention, export, and
# filtering are out of scope; the surface never grows past this bound.
RECEIPTS_HISTORY_MAX_ROWS = 50

# Runtime-declared receipt states presented with guard posture
# (BLOCKED_AND_STALE_STATE_SPEC.md): the mapping consumes only the runtime's
# own ``state`` word — the UI never re-classifies an outcome into "blocked".
GUARD_HELD_RECEIPT_STATES: tuple[str, ...] = ("blocked",)


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _row_from_receipt(receipt: dict, *, note_path: str) -> dict[str, Any]:
    """One history row, verbatim from a runtime receipt projection row.

    Every rendered field is the runtime's own value. ``guard_held`` is the
    one presentation flag, mapped only from the runtime-declared ``state``
    per :data:`GUARD_HELD_RECEIPT_STATES`.
    """
    state = str(receipt.get("state") or "")
    target = str(
        receipt.get("artifact_path")
        or receipt.get("path")
        or note_path
        or ""
    )
    return {
        "receipt_id": str(receipt.get("receipt_id") or ""),
        "status": str(receipt.get("status") or state or ""),
        "state": state,
        "guard_held": state in GUARD_HELD_RECEIPT_STATES,
        "target": target,
        "timestamp": str(receipt.get("timestamp") or ""),
        "action_type": str(receipt.get("action_type") or ""),
        "trace_id": str(receipt.get("trace_id") or ""),
    }


def _coerce_count(value: object) -> int:
    """Coerce an orientation count value to int; 0 on absent/invalid."""
    if value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def governance_counts_view(governance: object) -> dict[str, Any] | None:
    """Pure projection of an orientation payload governance object into display counts.

    Returns ``None`` when the governance object is absent or all counts are
    zero — the caller must omit the counts row entirely in that case (no
    zero-state).

    This is a read-only projection (#2246, TELEMETRY_RELOCATION-02): no
    mutation affordance, no confirm/reject/execute, no count derived beyond
    what the orientation payload supplies.

    The orientation payload's ``governance`` object is expected to supply:
    - ``pending_proposal_count`` (int or str)
    - ``pending_receipt_count`` (int or str)
    - ``latest_receipt_outcome`` (str)
    """
    data: dict[str, Any] = {}
    if isinstance(governance, dict):
        data = governance
    elif governance is not None:
        return None

    proposals = _coerce_count(data.get("pending_proposal_count"))
    receipts = _coerce_count(data.get("pending_receipt_count"))
    outcome_raw = str(data.get("latest_receipt_outcome") or "")
    outcome = outcome_raw if outcome_raw and outcome_raw not in ("none", "unknown", "") else None

    # No zero-state: omit when all meaningful values are absent or zero.
    if proposals == 0 and receipts == 0 and outcome is None:
        return None

    return {
        "proposals": proposals,
        "receipts": receipts,
        "outcome": outcome,
    }


def governance_counts_row_html(governance: object) -> str:
    """Server-rendered read-only governance counts row for the receipts modal head.

    Returns an empty string when ``governance_counts_view`` returns ``None``
    (absent or all-zero — no zero-state rendered).

    The row carries ``data-region="governance-counts"`` and
    ``data-authority="read-only-projection"`` as the cross-task invariant
    (#2246). No mutation affordance is present.
    """
    counts = governance_counts_view(governance)
    if counts is None:
        return ""
    proposals = counts["proposals"]
    receipts = counts["receipts"]
    outcome = counts["outcome"]

    outcome_html = ""
    if outcome is not None:
        outcome_html = (
            '<span class="governance-counts-item">'
            f'<span class="governance-counts-value">{_e(outcome)}</span>'
            '<span class="governance-counts-label">latest outcome</span></span>'
        )
    return (
        '<div class="governance-counts-row" '
        'data-testid="governance-counts-row" '
        'data-region="governance-counts" '
        'data-authority="read-only-projection" '
        'data-read-only="true">'
        '<span class="governance-counts-item">'
        f'<span class="governance-counts-value">{_e(proposals)}</span>'
        '<span class="governance-counts-label">pending proposals</span></span>'
        '<span class="governance-counts-item">'
        f'<span class="governance-counts-value">{_e(receipts)}</span>'
        '<span class="governance-counts-label">pending receipts</span></span>'
        f"{outcome_html}"
        "</div>"
    )


def receipts_history_view(
    payload: dict, *, max_rows: int = RECEIPTS_HISTORY_MAX_ROWS
) -> dict[str, Any]:
    """Pure projection of the vault-browser payload into the history view.

    Mirrors the shipped inspector receipt-state semantics
    (``serve_dev_page._render_inspector_receipts``):

    - a note without a ``receipts`` key (or ``None``) declares no receipt
      source — it contributes nothing and proves nothing;
    - ``source_available`` is true only when at least one note declares the
      receipts key, so "no receipts found" is never conflated with "receipt
      source not connected";
    - rows are the runtime's receipt rows verbatim, shown once per
      runtime-declared ``receipt_id`` (the runtime may attach the same
      receipt to several notes), ordered most-recent-first by the
      runtime-declared timestamp, and bounded to ``max_rows``.

    No aggregation the runtime does not declare: no counts are derived beyond
    the rendered list length, no outcomes are merged, nothing is invented.
    """
    data = payload if isinstance(payload, dict) else {}
    notes = [n for n in (data.get("notes") or []) if isinstance(n, dict)]
    source_available = False
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for note in notes:
        receipts_raw = note.get("receipts", None)
        if receipts_raw is None:
            continue
        source_available = True
        note_path = str(note.get("note_path") or "")
        for receipt in receipts_raw or []:
            if not isinstance(receipt, dict):
                continue
            row = _row_from_receipt(receipt, note_path=note_path)
            receipt_id = row["receipt_id"]
            if receipt_id and receipt_id in seen_ids:
                continue
            if receipt_id:
                seen_ids.add(receipt_id)
            rows.append(row)
    rows.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
    truncated = len(rows) > max_rows
    return {
        "source_available": source_available,
        "rows": rows[:max_rows],
        "truncated": truncated,
    }


def _row_html(row: dict[str, Any]) -> str:
    guard_held = "true" if row["guard_held"] else "false"
    guard_note = ""
    if row["guard_held"]:
        # Guard posture (BLOCKED_AND_STALE_STATE_SPEC.md): the held boundary
        # is named calmly — intent-preserving, nothing mutated — and is
        # visually distinct from a generic failure. History only shows the
        # held boundary; resolve/retry affordances live with the Panel, not
        # here (read-only surface).
        guard_note = (
            '<span class="receipts-history-guard-note" '
            'data-testid="receipts-history-guard-note" data-tone="calm">'
            "guard-held — boundary held; nothing was mutated</span>"
        )
    return (
        '<li class="receipts-history-row" data-testid="receipts-history-row" '
        f'data-receipt-id="{_e(row["receipt_id"])}" '
        f'data-receipt-status="{_e(row["status"])}" '
        f'data-receipt-state="{_e(row["state"])}" '
        f'data-guard-held="{guard_held}">'
        '<span class="receipts-history-outcome" '
        f'data-testid="receipts-history-outcome">{_e(row["status"])}</span>'
        '<span class="receipts-history-target" '
        f'data-testid="receipts-history-target">{_e(row["target"])}</span>'
        '<span class="receipts-history-timestamp" '
        f'data-testid="receipts-history-timestamp">{_e(row["timestamp"])}</span>'
        '<span class="receipts-history-id" '
        f'data-testid="receipts-history-id">{_e(row["receipt_id"])}</span>'
        f"{guard_note}</li>"
    )


def receipts_history_fragment(payload: dict) -> str:
    """Server-rendered history fragment from the existing runtime projection.

    Pure render of runtime-declared receipt rows — outcome, id, target, and
    timestamp exactly as supplied. Served at
    :data:`RECEIPTS_HISTORY_FRAGMENT_ROUTE` and injected into the modal body
    by the controller. Three honest states, mirroring the shipped inspector
    semantics: rows, empty (source connected, none found), and source not
    connected.
    """
    view = receipts_history_view(payload)
    if not view["source_available"]:
        body = (
            '<p class="receipts-history-unavailable" '
            'data-testid="receipts-history-unavailable" data-tone="calm">'
            "Receipt source not connected — no receipt data is "
            "available. Nothing was decided and nothing was lost.</p>"
        )
    elif not view["rows"]:
        body = (
            '<p class="receipts-history-empty" '
            'data-testid="receipts-history-empty">'
            "No receipts have been recorded yet. Governed outcomes will "
            "appear here when the runtime produces them.</p>"
        )
    else:
        body = (
            '<ol class="receipts-history-list" '
            'data-testid="receipts-history-list">'
            + "".join(_row_html(row) for row in view["rows"])
            + "</ol>"
        )
    truncated = "true" if view["truncated"] else "false"
    return (
        '<div class="receipts-history-fragment" '
        'data-testid="receipts-history-fragment" '
        'data-source="vault-browser.receipts" '
        f'data-row-count="{len(view["rows"])}" '
        f'data-truncated="{truncated}">'
        f"{body}</div>"
    )


def receipts_history_unavailable_fragment(detail: str = "") -> str:
    """Calm unavailable state: the runtime could not be read; nothing shown.

    Receipts are never invented to fill the gap — an unreachable runtime
    renders as exactly that.
    """
    detail_html = (
        f'<code class="receipts-history-unavailable-detail">{_e(detail)}</code>'
        if detail
        else ""
    )
    return (
        '<div class="receipts-history-fragment" '
        'data-testid="receipts-history-fragment" '
        'data-source="vault-browser.receipts" data-row-count="unknown">'
        '<p class="receipts-history-unavailable" '
        'data-testid="receipts-history-unavailable" data-tone="calm">'
        "Receipt history unavailable — the runtime could not be "
        "reached. Nothing was decided and nothing was lost.</p>"
        f"{detail_html}</div>"
    )


def receipts_history_modal_markup() -> str:
    """The top-modal shell mounted on the shared overlay host.

    Hidden until the host mounts the ``receipts`` occupant
    (``receipts.open``). Strictly read-only by construction: the only control
    on the surface is the dismiss-to-anchor close button; rows are display
    only. Styles are scoped here so the modal is self-contained. Blocked rows
    style through the guard-held attribute in the amber/staged family — never
    a destructive alarm treatment.
    """
    return """
  <!-- Receipts history modal (#1794, SEP-10) — read-only history over the
       existing runtime receipt projections. Receipts are never invented,
       edited, or re-derived by the UI; blocked rows render as calm held
       boundaries, not errors. -->
  <style>
    .receipts-history-modal {
      align-items: flex-start;
      display: flex;
      inset: 0;
      justify-content: center;
      padding: 56px 16px 0;
      pointer-events: none;
      position: fixed;
      z-index: 1010;
    }
    .receipts-history-modal[hidden] { display: none; }
    .receipts-history-panel {
      background: var(--bg-surface, #0c1220);
      border: 1px solid var(--border-strong, #1e3050);
      border-radius: var(--radius-lg, 10px);
      box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-height: 72vh;
      max-width: 640px;
      overflow: hidden;
      padding: 18px 20px;
      pointer-events: auto;
      width: 100%;
    }
    .receipts-history-head {
      align-items: center;
      display: flex;
      justify-content: space-between;
    }
    .receipts-history-title {
      color: var(--fg-1, #dce8f0);
      font-family: var(--font-ui, sans-serif);
      font-size: var(--text-sm, 13px);
      font-weight: 600;
    }
    .receipts-history-close {
      background: transparent;
      border: none;
      color: var(--fg-2, #7a9ab8);
      cursor: pointer;
      font-size: 1.2rem;
      line-height: 1;
      padding: 0 4px;
    }
    .receipts-history-readonly {
      color: var(--fg-3, #3d5570);
      font-family: var(--font-mono, monospace);
      font-size: var(--text-xs, 11px);
    }
    .receipts-history-body { overflow-y: auto; }
    .receipts-history-list {
      display: flex;
      flex-direction: column;
      gap: 6px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    .receipts-history-row {
      border: 1px solid var(--border, #152030);
      border-radius: 8px;
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: 8px 10px;
    }
    .receipts-history-outcome {
      color: var(--fg-1, #dce8f0);
      font-family: var(--font-mono, monospace);
      font-size: var(--text-xs, 11px);
      text-transform: lowercase;
    }
    .receipts-history-target {
      color: var(--fg-2, #7a9ab8);
      font-family: var(--font-ui, sans-serif);
      font-size: var(--text-sm, 13px);
      word-break: break-all;
    }
    .receipts-history-timestamp,
    .receipts-history-id {
      color: var(--fg-3, #3d5570);
      font-family: var(--font-mono, monospace);
      font-size: var(--text-xs, 11px);
      word-break: break-all;
    }
    /* Guard posture: held boundary in the amber/staged family — calm,
       named, and visually distinct from any failure treatment. */
    .receipts-history-row[data-guard-held="true"] {
      border-color: var(--amber-dim, #805010);
      border-left: 3px solid var(--amber, #f09030);
    }
    .receipts-history-row[data-guard-held="true"] .receipts-history-outcome {
      color: var(--amber, #f09030);
    }
    .receipts-history-guard-note {
      color: var(--amber, #f09030);
      font-family: var(--font-ui, sans-serif);
      font-size: var(--text-xs, 11px);
    }
    .receipts-history-empty,
    .receipts-history-unavailable,
    .receipts-history-loading {
      color: var(--fg-2, #7a9ab8);
      font-size: 13px;
    }
  </style>
  <div class="receipts-history-modal" id="receipts-history-modal"
       data-testid="receipts-history-modal" data-region="receipts-history"
       data-overlay-id="receipts" data-authority="receipt"
       data-read-only="true" role="dialog" aria-modal="true"
       aria-label="Receipts history" hidden>
    <div class="receipts-history-panel">
      <div class="receipts-history-head">
        <span class="receipts-history-title">Receipts</span>
        <span class="receipts-history-readonly"
              data-testid="receipts-history-readonly">read-only</span>
        """ + guidance_toggle_markup("receipts") + """
        <button type="button" class="receipts-history-close"
                data-testid="receipts-history-close"
                data-intent="overlay.dismiss"
                aria-label="Close and return to the document"
                onclick="overlayHost.dismiss()">&times;</button>
      </div>
      """ + guidance_callout_markup("receipts") + """
      <div class="receipts-history-body" id="receipts-history-body"
           data-testid="receipts-history-body" data-loaded="false">
        <p class="receipts-history-loading">Loading receipt history…</p>
      </div>
    </div>
  </div>
  <!-- /receipts-history-modal -->"""


def receipts_history_script() -> str:
    """The in-page controller mirroring the pure projections above.

    Must be emitted after :func:`overlay_host.overlay_host_script`: the modal
    registers as the host's ``receipts`` occupant so mount/dismiss (Esc,
    scrim, close button, ``receipts.open`` affordances) is host-owned in one
    place. The controller only ever GETs the server-rendered fragment — it
    carries no mutation transport, no outcome vocabulary, and no
    classification of any kind. It never navigates and never touches the
    document column.
    """
    return f"""
  <script>
  /* receipts-history-controller */
  (function() {{
    var modal = document.getElementById('receipts-history-modal');
    if (!modal || !window.overlayHost) {{ return; }}
    var body = document.getElementById('receipts-history-body');
    function load() {{
      body.setAttribute('data-loaded', 'false');
      fetch('{RECEIPTS_HISTORY_FRAGMENT_ROUTE}', {{method: 'GET'}})
        .then(function(r) {{
          if (!r.ok) {{ throw new Error(String(r.status)); }}
          return r.text();
        }})
        .then(function(html) {{
          body.innerHTML = html;
          body.setAttribute('data-loaded', 'true');
        }})
        .catch(function() {{
          body.innerHTML = '<p class="receipts-history-unavailable" ' +
            'data-testid="receipts-history-unavailable" data-tone="calm">' +
            'Receipt history unavailable \\u2014 the runtime could not be ' +
            'reached. Nothing was decided and nothing was lost.</p>';
          body.setAttribute('data-loaded', 'unavailable');
        }});
    }}
    // Host occupant: the host owns mount/dismiss (Esc / scrim / close ->
    // the document anchor; no route reset, no data loss).
    window.overlayHost.register('receipts', {{
      open: function() {{ modal.removeAttribute('hidden'); load(); }},
      close: function() {{ modal.setAttribute('hidden', ''); }}
    }});
    window.receiptsHistory = {{
      open: function() {{ window.overlayHost.mount('receipts'); }},
      close: function() {{ window.overlayHost.dismiss(); }}
    }};
  }})();
  /* /receipts-history-controller */
  </script>"""


__all__ = [
    "GUARD_HELD_RECEIPT_STATES",
    "RECEIPTS_HISTORY_FRAGMENT_ROUTE",
    "RECEIPTS_HISTORY_MAX_ROWS",
    "RECEIPTS_OVERLAY_ID",
    "RECEIPTS_PROJECTION_ENDPOINT",
    "governance_counts_row_html",
    "governance_counts_view",
    "receipts_history_fragment",
    "receipts_history_modal_markup",
    "receipts_history_script",
    "receipts_history_unavailable_fragment",
    "receipts_history_view",
]
