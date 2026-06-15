"""Memory candidate review drawer — right-drawer review UI (#1793, SEP-09b).

Implements issue (b) of ``docs/SYSTEM_ENTRY_POINT/MEMORY_REVIEW_DRAWER.md``
against the normative contracts in
``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`` (§Intent vocabulary
``memory.*``, §Surface composition, §Design-vs-owner-doc correction — memory
review outcomes) and ``docs/adr/ADR-0009-orientation-memory-candidate-intent.md``.

The drawer is the only admissible place where candidate → memory promotion is
decided — and it decides nothing itself:

- It renders the pending review queue the runtime serves
  (``GET /api/companion/memory/review-queue``, #1792): why-now, provenance,
  and the server-declared authority posture, headed by the normative
  "Unreviewed memory is not semantic authority" callout.
- Accept / Reject / Revise are governed review outcomes: each posts to the
  #1792 decision endpoint and renders the runtime-declared outcome and the
  runtime-produced receipt verbatim. The UI never classifies
  candidate-worthiness locally, never invents a receipt, and never renders a
  candidate as accepted memory before the runtime says so — a governed
  refusal (409, e.g. the accept dry-run) renders calm with the candidate
  still pending.
- Defer is non-terminal queue bookkeeping: the candidate stays pending, no
  semantic transition occurs, and no receipt exists or is rendered.

The drawer mounts on the shared overlay host (#1785) as the declared
``memory`` occupant: ``memory.open`` mounts it (topbar surface icon and the
re-entry card's unresolved-inspect affordance), and dismissal routes through
the host back to the document anchor — no route reset, no data loss.

Like ``overlay_host.py``, the pure projections in this module are the
contract the in-page controller (:func:`memory_review_drawer_script`)
mirrors; tests assert both. Nothing here performs I/O — the page server
proxies the runtime endpoints same-origin and serves the server-rendered
queue fragment at :data:`MEMORY_REVIEW_FRAGMENT_ROUTE`.
"""

from __future__ import annotations

import html as _html
from urllib.parse import quote

from companion_ui.workspace.guidance_layer import (
    guidance_callout_markup,
    guidance_toggle_markup,
)

# The normative callout (SYSTEM_ENTRY_POINT_SPEC.md; ADR-0009). The runtime
# declares the same phrase on the queue payload (`review_callout`); the static
# drawer copy is the same normative sentence, not a UI classification.
MEMORY_REVIEW_CALLOUT = "Unreviewed memory is not semantic authority."

# Runtime endpoints shipped by #1792 (SEP-09a) and proxied same-origin by the
# page server (LOCAL_ACCESS_MODEL.md: browsers never need the runtime port).
MEMORY_REVIEW_QUEUE_ENDPOINT = "/api/companion/memory/review-queue"

# Page-server route serving the server-rendered queue fragment (the /operator
# overlay precedent): the drawer lazily fetches HTML the server composed from
# the runtime payload, so rendering stays a pure, testable Python function.
MEMORY_REVIEW_FRAGMENT_ROUTE = "/memory-review"

# The spec's four memory-review actions (§Intent vocabulary, §Design-vs-owner-
# doc correction): accept/reject/revise are governed, receipt-bearing review
# outcomes through the #1792 decision endpoint; defer is the one non-terminal
# action — queue bookkeeping with no semantic transition and no receipt.
REVIEW_ACTIONS: tuple[str, ...] = ("accept", "reject", "revise", "defer")
GOVERNED_REVIEW_ACTIONS: tuple[str, ...] = ("accept", "reject", "revise")
NON_TERMINAL_REVIEW_ACTIONS: tuple[str, ...] = ("defer",)
REVIEW_ACTION_INTENTS: dict[str, str] = {
    "accept": "memory.accept",
    "reject": "memory.reject",
    "revise": "memory.revise",
    "defer": "memory.defer",
}

# Decided statuses the runtime contract declares for governed outcomes
# (MemoryReviewDecisionResponse.status minus the non-terminal "deferred").
# The controller reads this vocabulary from the drawer markup — generated
# from this constant — so the script itself carries no outcome literals.
GOVERNED_DECIDED_STATUSES: tuple[str, ...] = ("accepted", "rejected", "revised")

# Reviewer identity sent with every decision. The runtime refuses blank
# reviewers (accountable review semantics); this is the single-user
# Companion UI surface identity, recorded verbatim on the runtime receipt.
MEMORY_REVIEW_REVIEWER = "companion-ui:reviewer"


def decision_endpoint_path(candidate_id: str) -> str:
    """The #1792 decision endpoint path for one candidate, safely quoted."""
    return f"{MEMORY_REVIEW_QUEUE_ENDPOINT}/{quote(candidate_id, safe='')}/decision"


def decision_outcome_view(
    *, action: str, status_code: int, payload: dict | None
) -> dict:
    """Pure projection of a runtime decision response into the render state.

    The in-page controller mirrors this exactly; tests assert both. The
    invariants are the issue's constraints:

    - the rendered outcome comes from the runtime payload's declared
      ``status`` — never from the action the UI requested;
    - a receipt renders only when the runtime produced one; defer is
      non-terminal and receipt-free, so no receipt is rendered for it even if
      a malformed payload smuggles one in;
    - a governed refusal (409 — the boundary refusing the decision, e.g. the
      accept dry-run) renders calm: the candidate is still pending, nothing
      was promoted, nothing is invented;
    - when the runtime declares nothing usable, the candidate is treated as
      still pending — acceptance is never assumed.
    """
    if action not in REVIEW_ACTIONS:
        raise ValueError(
            f"undeclared review action {action!r}; declared: {REVIEW_ACTIONS}"
        )
    data = payload if isinstance(payload, dict) else {}
    if status_code == 409:
        detail = data.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return {
            "kind": "refused",
            "tone": "calm",
            "status": "pending",
            "candidate_pending": True,
            "receipt": None,
            "revision_candidate_id": None,
            "message": str(
                detail.get("message")
                or "The runtime declined to record this decision. The candidate "
                "is still pending review; nothing was decided."
            ),
        }
    if status_code != 200:
        return {
            "kind": "unavailable",
            "tone": "calm",
            "status": "pending",
            "candidate_pending": True,
            "receipt": None,
            "revision_candidate_id": None,
            "message": "The runtime could not be reached. No decision was "
            "recorded; the candidate is still pending review.",
        }
    status = data.get("status")
    if status == "deferred":
        return {
            "kind": "deferred",
            "tone": "calm",
            "status": "deferred",
            "candidate_pending": True,
            # Non-terminal: no receipt exists and none is rendered or invented.
            "receipt": None,
            "revision_candidate_id": None,
            "message": str(
                data.get("detail")
                or "Deferred — the candidate stays pending; no review decision "
                "was recorded and no receipt exists."
            ),
        }
    if status not in GOVERNED_DECIDED_STATUSES:
        return {
            "kind": "unconfirmed",
            "tone": "calm",
            "status": "pending",
            "candidate_pending": True,
            "receipt": None,
            "revision_candidate_id": None,
            "message": "The runtime did not declare a review outcome. The "
            "candidate is treated as still pending review.",
        }
    receipt = data.get("receipt")
    return {
        "kind": "governed_outcome",
        "tone": "calm",
        "status": status,  # the runtime's word, never the requested action
        "candidate_pending": bool(data.get("candidate_pending", False)),
        "receipt": receipt if isinstance(receipt, dict) else None,
        "revision_candidate_id": data.get("revision_candidate_id") or None,
        "message": "",
    }


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _candidate_provenance(candidate: dict) -> str:
    """Provenance lines exactly as the runtime declared them."""
    rows: list[tuple[str, str]] = []
    for ref in candidate.get("source_refs") or []:
        rows.append(("source", str(ref)))
    for key, label in (
        ("derived_from", "derived from"),
        ("generated_by", "generated by"),
        ("revision_of", "revision of"),
    ):
        value = candidate.get(key)
        if value:
            rows.append((label, str(value)))
    if not rows:
        rows.append(("provenance", "none declared by the runtime"))
    items = "".join(
        f'<div class="memory-provenance-row">'
        f'<span class="memory-provenance-label">{_e(label)}</span>'
        f"<code>{_e(value)}</code></div>"
        for label, value in rows
    )
    return (
        f'<div class="memory-candidate-provenance" '
        f'data-testid="memory-candidate-provenance">{items}</div>'
    )


def _candidate_actions() -> str:
    """The four declared actions; governed-vs-non-terminal marked explicitly."""
    buttons = []
    for action in REVIEW_ACTIONS:
        governed = "true" if action in GOVERNED_REVIEW_ACTIONS else "false"
        non_terminal = (
            ' data-non-terminal="true"'
            if action in NON_TERMINAL_REVIEW_ACTIONS
            else ""
        )
        buttons.append(
            f'<button type="button" class="memory-review-action" '
            f'data-testid="memory-action-{action}" data-action="{action}" '
            f'data-intent="{REVIEW_ACTION_INTENTS[action]}" '
            f'data-governed="{governed}"{non_terminal}>'
            f"{action.capitalize()}</button>"
        )
    return (
        f'<div class="memory-review-actions" data-testid="memory-review-actions">'
        f'{"".join(buttons)}</div>'
    )


def _candidate_row(candidate: dict) -> str:
    posture = candidate.get("authority_posture")
    posture = posture if isinstance(posture, dict) else {}
    authority = _e(posture.get("authority") or "non_authoritative")
    authority_role = _e(posture.get("authority_role") or "candidate")
    review_posture = _e(posture.get("review_posture") or "")
    semantic = "true" if posture.get("semantic_authority") else "false"
    inferred = "true" if candidate.get("inferred") else "false"
    inferred_label = "inferred" if candidate.get("inferred") else "asserted"
    return f"""
      <article class="memory-review-candidate" data-testid="memory-review-candidate"
        data-candidate-id="{_e(candidate.get("candidate_id"))}"
        data-review-state="pending"
        data-authority="{authority}" data-authority-role="{authority_role}"
        data-semantic-authority="{semantic}" data-inferred="{inferred}">
        <header class="memory-candidate-head">
          <span class="memory-candidate-title">{_e(candidate.get("title"))}</span>
          <span class="memory-candidate-authority-tag"
            data-testid="memory-candidate-authority-tag">
            {authority_role} · {review_posture} · {inferred_label} ·
            {_e(candidate.get("proposed_memory_type"))}</span>
        </header>
        <p class="memory-candidate-why-now" data-testid="memory-candidate-why-now">{_e(candidate.get("why_now"))}</p>
        {_candidate_provenance(candidate)}
        {_candidate_actions()}
        <div class="memory-decision-outcome" data-testid="memory-decision-outcome"
          data-outcome-state="none" aria-live="polite"></div>
      </article>"""


def materialized_memory_surface(memory: dict) -> str:
    """Render a materialized memory artifact with provenance and posture.

    Pure projection: the UI displays runtime/vault-declared metadata and does
    not classify authority or candidate-worthiness locally.
    """

    labels = [str(label) for label in memory.get("labels") or []]
    source_refs = [str(ref) for ref in memory.get("source_refs") or []]
    provenance_rows: list[tuple[str, str]] = [
        ("artifact", str(memory.get("artifact_path") or "")),
        ("candidate", str(memory.get("promoted_from_candidate_id") or "")),
        ("decided by", str(memory.get("decided_by") or "")),
        ("decided at", str(memory.get("decided_at") or "")),
    ]
    for ref in source_refs:
        provenance_rows.append(("source", ref))
    if memory.get("derived_from"):
        provenance_rows.append(("derived from", str(memory.get("derived_from"))))
    if memory.get("generated_by"):
        provenance_rows.append(("generated by", str(memory.get("generated_by"))))
    rows = "".join(
        f'<div class="materialized-memory-provenance-row">'
        f'<span>{_e(label)}</span><code>{_e(value)}</code></div>'
        for label, value in provenance_rows
        if value
    )
    label_items = "".join(
        f'<span class="materialized-memory-label">{_e(label)}</span>'
        for label in labels
    )
    agent_promoted = "true" if memory.get("agent_promoted") else "false"
    return f"""
    <article class="materialized-memory-surface"
      data-testid="materialized-memory-surface"
      data-agent-promoted="{agent_promoted}"
      data-artifact-class="{_e(memory.get("artifact_class") or "agentic_memory")}"
      data-human-authored="false">
      <header>
        <span class="materialized-memory-kicker">Agent-promoted memory</span>
        <h3>{_e(memory.get("title") or "Materialized memory")}</h3>
      </header>
      <div class="materialized-memory-labels" data-testid="materialized-memory-labels">
        {label_items}
      </div>
      <div class="materialized-memory-provenance" data-testid="materialized-memory-provenance">
        {rows}
      </div>
    </article>"""


def recall_provenance_surface(recall: dict) -> str:
    """Render recall provenance and authority posture from a recall receipt.

    Recall authority is the runtime's declaration, never the UI's. Missing
    ``may_answer``/``may_propose`` flags default to *closed* (``false``): the
    UI never invents affirmative recall authority for a degraded or older
    payload that did not declare it (issue #2016 constraint; ADR-0009).
    """

    authority_limits = [str(limit) for limit in recall.get("authority_limits") or []]
    limits = "".join(
        f'<li data-testid="recall-authority-limit">{_e(limit)}</li>'
        for limit in authority_limits
    )
    may_write = "true" if recall.get("may_write") else "false"
    receipt_ref = recall.get("receipt_reference") or recall.get("receipt_id") or ""
    return f"""
    <section class="memory-recall-provenance" data-testid="memory-recall-provenance"
      data-may-answer="{'true' if recall.get("may_answer") else 'false'}"
      data-may-propose="{'true' if recall.get("may_propose") else 'false'}"
      data-may-write="{may_write}">
      <p class="memory-recall-why-now" data-testid="memory-recall-why-now">
        {_e(recall.get("why_now") or "")}</p>
      <p class="memory-recall-receipt" data-testid="memory-recall-receipt">
        {_e(receipt_ref)}</p>
      <ul class="memory-recall-authority-limits" data-testid="memory-recall-authority-limits">
        {limits}
      </ul>
    </section>"""


def memory_authority_posture_surface(posture: dict) -> str:
    """Render server-declared authority posture without redefining it."""

    semantic = "true" if posture.get("semantic_authority") else "false"
    review_posture = posture.get("review_posture") or "unreviewed"
    return f"""
    <section class="memory-authority-posture" data-testid="memory-authority-posture"
      data-authority="{_e(posture.get("authority") or "non_authoritative")}"
      data-authority-role="{_e(posture.get("authority_role") or "candidate")}"
      data-semantic-authority="{semantic}">
      <p>{MEMORY_REVIEW_CALLOUT}</p>
      <p data-testid="memory-authority-review-posture">{_e(review_posture)}</p>
    </section>"""


def memory_review_queue_fragment(payload: dict) -> str:
    """Server-rendered review-queue fragment from the #1792 read payload.

    Pure render of runtime-declared data: counts, why-now, provenance, and
    authority posture exactly as supplied — nothing classified, nothing
    re-derived. Served at :data:`MEMORY_REVIEW_FRAGMENT_ROUTE` and injected
    into the drawer's queue region by the controller.
    """
    data = payload if isinstance(payload, dict) else {}
    candidates = [c for c in (data.get("candidates") or []) if isinstance(c, dict)]
    try:
        pending_count = int(data.get("pending_count", len(candidates)))
    except (TypeError, ValueError):
        pending_count = len(candidates)
    if candidates:
        body = "".join(_candidate_row(candidate) for candidate in candidates)
    else:
        body = (
            '<p class="memory-review-empty" data-testid="memory-review-empty">'
            "No candidates are waiting for review.</p>"
        )
    noun = "candidate" if pending_count == 1 else "candidates"
    # When the runtime payload also declares materialized (already-promoted)
    # memories and/or a recall-provenance receipt, the served fragment renders
    # those surfaces alongside the pending queue. Both are pure projections of
    # runtime-declared data; the UI classifies nothing and invents nothing.
    materialized = [
        m for m in (data.get("materialized_memories") or []) if isinstance(m, dict)
    ]
    materialized_html = "".join(
        materialized_memory_surface(memory) for memory in materialized
    )
    recall = data.get("recall")
    recall_html = (
        recall_provenance_surface(recall) if isinstance(recall, dict) else ""
    )
    return f"""
    <div class="memory-review-fragment" data-testid="memory-review-fragment"
      data-source="agent_memory.review_queue" data-pending-count="{pending_count}">
      <p class="memory-review-pending-count" data-testid="memory-review-pending-count">
        {pending_count} pending {noun} awaiting explicit review.</p>
      {body}
      {materialized_html}
      {recall_html}
    </div>"""


def memory_review_unavailable_fragment(detail: str = "") -> str:
    """Calm unavailable state: the queue could not be read, nothing decided."""
    detail_html = (
        f'<code class="memory-review-unavailable-detail">{_e(detail)}</code>'
        if detail
        else ""
    )
    return f"""
    <div class="memory-review-fragment" data-testid="memory-review-fragment"
      data-source="agent_memory.review_queue" data-pending-count="unknown">
      <p class="memory-review-unavailable" data-testid="memory-review-unavailable"
        data-tone="calm">Review queue unavailable — the runtime could not be
        reached. Nothing was decided and nothing was lost.</p>
      {detail_html}
    </div>"""


def memory_review_drawer_markup() -> str:
    """The right-drawer shell mounted on the shared overlay host.

    Renders closed (``data-open="false"``); the overlay host's ``memory``
    occupant adapter opens and closes it so the dismiss rule (Esc / scrim /
    close → document anchor) is enforced in one place. Styles are scoped in
    the block below so the drawer is self-contained on both the workspace
    shell and the orientation surface.
    """
    decided = " ".join(GOVERNED_DECIDED_STATUSES)
    return f"""
  <!-- Memory candidate review drawer (#1793, SEP-09b) — the only admissible
       place where candidate -> memory promotion is decided. Governed
       decisions route through the #1792 endpoints; the UI renders runtime
       outcomes and receipts and never classifies or promotes locally. -->
  <style>
    .memory-review-drawer {{
      background: var(--bg-surface, #0c1220);
      border-left: 1px solid var(--border-strong, #1e3050);
      bottom: 0;
      box-shadow: -18px 0 40px rgba(0, 0, 0, 0.45);
      display: flex;
      flex-direction: column;
      max-width: 92vw;
      overflow-y: auto;
      padding: 18px 20px 28px;
      position: fixed;
      right: 0;
      top: 0;
      transform: translateX(100%);
      transition: transform 160ms ease;
      width: 420px;
      z-index: 960;
    }}
    .memory-review-drawer[data-open="true"] {{ transform: translateX(0); }}
    .memory-review-head {{
      align-items: flex-start; display: flex; gap: 12px;
      justify-content: space-between;
    }}
    .memory-review-kicker {{
      color: var(--fg-3, #3d5570); font-size: 11px; letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .memory-review-title {{ color: var(--fg-1, #dce8f0); font-size: 17px; margin: 2px 0 0; }}
    .memory-review-close {{
      background: none; border: 1px solid var(--border, #152030);
      border-radius: 4px; color: var(--fg-2, #7a9ab8); cursor: pointer;
      font-size: 16px; line-height: 1; padding: 4px 9px;
    }}
    .memory-review-callout {{
      border: 1px solid var(--amber-dim, #805010);
      border-left: 3px solid var(--amber, #f09030);
      border-radius: 4px; color: var(--fg-1, #dce8f0); font-size: 13px;
      margin: 14px 0; padding: 9px 12px;
    }}
    .memory-review-candidate {{
      border: 1px solid var(--border, #152030); border-radius: 6px;
      margin: 0 0 12px; padding: 12px;
    }}
    .memory-candidate-head {{
      display: flex; flex-direction: column; gap: 4px; margin-bottom: 6px;
    }}
    .memory-candidate-title {{ color: var(--fg-1, #dce8f0); font-size: 14px; }}
    .memory-candidate-authority-tag {{
      color: var(--amber, #f09030); font-family: var(--font-mono, monospace);
      font-size: 11px;
    }}
    .memory-candidate-why-now {{ color: var(--fg-2, #7a9ab8); font-size: 13px; margin: 6px 0; }}
    .memory-candidate-provenance {{ margin: 8px 0; }}
    .memory-provenance-row {{
      color: var(--fg-3, #3d5570); display: flex; font-size: 12px; gap: 8px;
    }}
    .memory-provenance-row code {{ color: var(--fg-2, #7a9ab8); word-break: break-all; }}
    .memory-provenance-label {{
      flex: 0 0 92px; letter-spacing: 0.05em; text-transform: uppercase;
      font-size: 10px; line-height: 1.8;
    }}
    .memory-review-actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }}
    .memory-review-action {{
      background: var(--bg-raised, #111a2e); border: 1px solid var(--border-strong, #1e3050);
      border-radius: 4px; color: var(--fg-1, #dce8f0); cursor: pointer;
      font-size: 12px; padding: 6px 12px;
    }}
    .memory-review-action[data-governed="true"] {{ border-color: var(--accent-dim, #80621a); }}
    .memory-review-action:disabled {{ cursor: default; opacity: 0.45; }}
    .memory-decision-outcome[data-outcome-state="none"] {{ display: none; }}
    .memory-decision-outcome {{
      border-top: 1px dashed var(--border, #152030); color: var(--fg-2, #7a9ab8);
      font-size: 12px; margin-top: 10px; padding-top: 8px;
    }}
    .memory-outcome-receipt {{
      display: grid; gap: 2px 10px; grid-template-columns: auto 1fr; margin: 6px 0 0;
    }}
    .memory-outcome-receipt dt {{
      color: var(--fg-3, #3d5570); font-size: 10px; letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    .memory-outcome-receipt dd {{
      color: var(--fg-2, #7a9ab8); font-family: var(--font-mono, monospace);
      font-size: 11px; margin: 0; word-break: break-all;
    }}
    .memory-review-empty, .memory-review-unavailable, .memory-review-loading {{
      color: var(--fg-2, #7a9ab8); font-size: 13px;
    }}
    /* Overlay-host layer styles (duplicated verbatim from the workspace
       sheet so the host substrate is also styled on the orientation
       surface, where the drawer is reachable from the re-entry card). */
    .overlay-host-scrim {{
      background: rgba(7, 11, 18, 0.55); display: none; inset: 0;
      position: fixed; z-index: 900;
    }}
    .overlay-host-scrim[data-active="true"] {{ display: block; }}
  </style>
  <aside class="memory-review-drawer" id="memory-review-drawer"
    data-testid="memory-review-drawer" data-region="memory-review-drawer"
    data-overlay-id="memory" data-drawer-side="right" data-open="false"
    data-authority="proposal" data-decided-statuses="{decided}"
    data-reviewed-by="{_e(MEMORY_REVIEW_REVIEWER)}"
    role="dialog" aria-modal="false" aria-hidden="true"
    aria-label="Memory candidate review">
    <header class="memory-review-head">
      <div>
        <span class="memory-review-kicker">Memory review</span>
        <h2 class="memory-review-title">Pending candidates</h2>
      </div>
      {guidance_toggle_markup('memory')}
      <button type="button" class="memory-review-close"
        data-testid="memory-review-close" data-intent="overlay.dismiss"
        aria-label="Close and return to the document"
        onclick="overlayHost.dismiss()">&times;</button>
    </header>
    {guidance_callout_markup('memory')}
    <p class="memory-review-callout" data-testid="memory-review-callout"
      data-tone="advisory">{MEMORY_REVIEW_CALLOUT}</p>
    <div class="memory-review-queue" data-testid="memory-review-queue"
      data-loaded="false" data-source="agent_memory.review_queue">
      <p class="memory-review-loading">Loading review queue…</p>
    </div>
  </aside>"""


def memory_review_drawer_script() -> str:
    """The in-page controller mirroring the pure projections above.

    Must be emitted after :func:`overlay_host.overlay_host_script`: the
    drawer registers as the host's ``memory`` occupant so mount/dismiss (Esc,
    scrim, close button, ``memory.open`` affordances) is host-owned in one
    place. The controller carries no outcome literals — the decided-status
    vocabulary is read from the drawer markup, which is generated from the
    runtime contract constants — and renders receipts only from the runtime
    payload. It never navigates and never touches the document column.
    """
    return f"""
  <script>
  /* memory-review-drawer-controller */
  (function() {{
    var drawer = document.getElementById('memory-review-drawer');
    if (!drawer || !window.overlayHost) {{ return; }}
    var queueEl = drawer.querySelector('[data-testid="memory-review-queue"]');
    var DECIDED = (drawer.getAttribute('data-decided-statuses') || '').split(' ');
    var REVIEWER = drawer.getAttribute('data-reviewed-by') || '';
    function setOpen(open) {{
      drawer.setAttribute('data-open', open ? 'true' : 'false');
      drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
    }}
    function load() {{
      queueEl.setAttribute('data-loaded', 'false');
      fetch('{MEMORY_REVIEW_FRAGMENT_ROUTE}', {{method: 'GET'}})
        .then(function(r) {{ return r.text(); }})
        .then(function(html) {{
          queueEl.innerHTML = html;
          queueEl.setAttribute('data-loaded', 'true');
        }})
        .catch(function() {{
          queueEl.innerHTML = '<p class="memory-review-unavailable" ' +
            'data-testid="memory-review-unavailable" data-tone="calm">' +
            'Review queue unavailable \\u2014 the runtime could not be ' +
            'reached. Nothing was decided.</p>';
          queueEl.setAttribute('data-loaded', 'error');
        }});
    }}
    // Host occupant: the host owns mount/dismiss (Esc / scrim -> the
    // document anchor; no route reset, no data loss).
    window.overlayHost.register('memory', {{
      open: function() {{ setOpen(true); load(); }},
      close: function() {{ setOpen(false); }}
    }});
    window.memoryReviewDrawer = {{
      open: function() {{ window.overlayHost.mount('memory'); }},
      close: function() {{ window.overlayHost.dismiss(); }}
    }};
    // Mirrors memory_review_drawer.decision_outcome_view: the rendered
    // outcome comes from the runtime payload's declared status — never from
    // the action the UI requested — and a receipt renders only when the
    // runtime produced one. A 409 refusal renders calm and pending.
    function outcomeView(statusCode, payload) {{
      payload = (payload && typeof payload === 'object') ? payload : {{}};
      if (statusCode === 409) {{
        var detail = (payload.detail && typeof payload.detail === 'object') ? payload.detail : {{}};
        return {{ kind: 'refused', pending: true, receipt: null, status: '',
                 message: detail.message || ('The runtime declined to record ' +
                 'this decision. The candidate is still pending review; ' +
                 'nothing was decided.') }};
      }}
      if (statusCode !== 200) {{
        return {{ kind: 'unavailable', pending: true, receipt: null, status: '',
                 message: 'The runtime could not be reached. No decision was ' +
                 'recorded; the candidate is still pending review.' }};
      }}
      if (payload.status === 'deferred') {{
        return {{ kind: 'deferred', pending: true, receipt: null, status: payload.status,
                 message: payload.detail || ('Deferred \\u2014 the candidate ' +
                 'stays pending; no review decision was recorded and no ' +
                 'receipt exists.') }};
      }}
      if (DECIDED.indexOf(payload.status) === -1) {{
        return {{ kind: 'unconfirmed', pending: true, receipt: null, status: '',
                 message: 'The runtime did not declare a review outcome. The ' +
                 'candidate is treated as still pending review.' }};
      }}
      return {{ kind: 'governed_outcome', status: payload.status,
               pending: payload.candidate_pending === true,
               receipt: (payload.receipt && typeof payload.receipt === 'object') ? payload.receipt : null,
               revisionCandidateId: payload.revision_candidate_id || null,
               message: '' }};
    }}
    function renderOutcome(row, view) {{
      var out = row.querySelector('[data-testid="memory-decision-outcome"]');
      if (!out) {{ return; }}
      out.textContent = '';
      out.setAttribute('data-outcome-state', view.kind);
      row.setAttribute('data-review-state', view.pending ? 'pending' : view.status);
      var line = document.createElement('p');
      line.className = 'memory-outcome-line';
      line.setAttribute('data-testid', 'memory-outcome-status');
      line.textContent = view.kind === 'governed_outcome'
        ? 'Runtime outcome: ' + view.status
        : view.message;
      out.appendChild(line);
      if (view.revisionCandidateId) {{
        var rev = document.createElement('p');
        rev.className = 'memory-outcome-revision';
        rev.setAttribute('data-testid', 'memory-outcome-revision');
        rev.textContent = 'Sent back for revision as candidate ' + view.revisionCandidateId;
        out.appendChild(rev);
      }}
      if (view.receipt) {{
        // Runtime receipt projection rendered verbatim — never invented.
        var receipt = document.createElement('dl');
        receipt.className = 'memory-outcome-receipt';
        receipt.setAttribute('data-testid', 'memory-outcome-receipt');
        receipt.setAttribute('data-receipt-id', String(view.receipt.receipt_id || ''));
        receipt.setAttribute('data-receipt-source', String(view.receipt.source || ''));
        ['receipt_id', 'outcome', 'decided_by', 'decided_at', 'recorded_at',
         'decision_notes', 'revision_of'].forEach(function(key) {{
          if (view.receipt[key] === undefined || view.receipt[key] === null) {{ return; }}
          var dt = document.createElement('dt');
          dt.textContent = key.replace(/_/g, ' ');
          var dd = document.createElement('dd');
          dd.textContent = String(view.receipt[key]);
          receipt.appendChild(dt);
          receipt.appendChild(dd);
        }});
        out.appendChild(receipt);
      }}
      if (!view.pending) {{
        var actions = row.querySelector('[data-testid="memory-review-actions"]');
        if (actions) {{
          Array.prototype.forEach.call(actions.querySelectorAll('button'), function(btn) {{
            btn.disabled = true;
          }});
        }}
      }}
    }}
    function decide(row, action) {{
      var id = row.getAttribute('data-candidate-id');
      if (!id || row.getAttribute('data-decision-inflight')) {{ return; }}
      row.setAttribute('data-decision-inflight', action);
      fetch('{MEMORY_REVIEW_QUEUE_ENDPOINT}/' + encodeURIComponent(id) + '/decision', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{action: action, reviewed_by: REVIEWER}})
      }})
        .then(function(r) {{
          return r.json()
            .then(function(payload) {{ return {{code: r.status, payload: payload}}; }})
            .catch(function() {{ return {{code: r.status, payload: {{}}}}; }});
        }})
        .catch(function() {{ return {{code: 0, payload: {{}}}}; }})
        .then(function(res) {{
          row.removeAttribute('data-decision-inflight');
          renderOutcome(row, outcomeView(res.code, res.payload));
        }});
    }}
    queueEl.addEventListener('click', function(e) {{
      var btn = (e.target && e.target.closest) ? e.target.closest('[data-action]') : null;
      if (!btn || btn.disabled) {{ return; }}
      var row = btn.closest('[data-candidate-id]');
      if (!row) {{ return; }}
      decide(row, btn.getAttribute('data-action'));
    }});
  }})();
  /* /memory-review-drawer-controller */
  </script>"""
