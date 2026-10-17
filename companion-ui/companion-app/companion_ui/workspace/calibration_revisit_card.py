"""Pure Companion rendering for the CAL-03 decision-revisit card.

The runtime owns the projection and both mutation routes.  This module only
renders the server-declared state and provides a thin same-origin controller
for the two forms.  It deliberately does not classify a failed request as an
empty surface or manufacture a receipt.
"""

from __future__ import annotations

import html as _html
import json
from urllib.parse import quote


OUTCOME_LABELS: tuple[tuple[str, str], ...] = (
    ("held", "Held"),
    ("partly_held", "Partly held"),
    ("did_not_hold", "Did not hold"),
    ("unknown_yet", "Not sure yet"),
)
REVISIT_BASE = "/api/companion/calibration/revisits/"


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _surface_state(surface: object) -> str:
    if not isinstance(surface, dict):
        return "absent"
    if bool(surface.get("degraded")) or surface.get("state") == "degraded":
        return "degraded"
    if surface.get("state") == "empty":
        return "empty"
    if surface.get("decision_id"):
        return "pending"
    return "absent"


def calibration_revisit_card_markup(
    surface: object,
    *,
    note_path: str = "",
) -> str:
    """Render one card from a runtime payload or its honest absence."""

    state = _surface_state(surface)
    payload = surface if isinstance(surface, dict) else {}
    if state == "empty":
        return """
        <section class="cal cal-quiet calibration-revisit-card"
          data-testid="calibration-revisit-card" data-state="empty"
          data-degraded="false" aria-labelledby="calibration-revisit-absent-heading">
          <h3 id="calibration-revisit-absent-heading" class="cal-eyebrow" tabindex="-1">Decision calibration</h3>
          <p class="cal-body">No revisit due.</p>
        </section>"""

    if state == "absent":
        return """
        <section class="cal calibration-revisit-card"
          data-testid="calibration-revisit-card" data-state="absent"
          data-degraded="true" aria-labelledby="calibration-revisit-unknown-heading">
          <header class="cal-head"><span class="cal-eyebrow">Decision calibration · revisit</span><span class="cal-badge cal-badge--amber">Unavailable</span></header>
          <div class="cal-lead">
            <h3 id="calibration-revisit-unknown-heading" class="cal-q" tabindex="-1">Calibration revisit state unavailable.</h3>
            <p class="cal-body">The workspace did not provide a readable revisit state. Pending revisits are unknown, not zero.</p>
          </div>
        </section>"""

    if state == "degraded":
        reason = _e(payload.get("degraded_reason") or "scheduler_unavailable")
        return f"""
        <section class="cal calibration-revisit-card"
          data-testid="calibration-revisit-card" data-state="degraded"
          data-degraded="true" data-degraded-reason="{reason}"
          aria-labelledby="calibration-revisit-degraded-heading">
          <header class="cal-head"><span class="cal-eyebrow">Decision calibration · revisit</span><span class="cal-badge cal-badge--amber">Unavailable</span></header>
          <div class="cal-lead">
            <h3 id="calibration-revisit-degraded-heading" class="cal-q" tabindex="-1">Calibration revisits unavailable.</h3>
            <p class="cal-body">Revisit state could not be read. Pending revisits are unknown, not zero.</p>
          </div>
        </section>"""

    decision_id = str(payload.get("decision_id") or "")
    decision_object_id = str(payload.get("decision_object_id") or "")
    rung_index = _e(payload.get("rung_index") if payload.get("rung_index") is not None else "")
    quoted_id = quote(decision_id, safe="")
    title = _e(payload.get("title") or "Untitled decision")
    decided_on = _e(payload.get("decided_on") or "unknown date")
    rung_days = _e(payload.get("rung_days") or "")
    heading_id = "calibration-revisit-question"
    answer_action = f"{REVISIT_BASE}{quoted_id}/decision"
    dismiss_action = f"{REVISIT_BASE}{quoted_id}/dismiss"
    picks = "".join(
        f'<button class="cal-pick" type="submit" name="outcome" '
        f'value="{_e(value)}" data-outcome="{_e(value)}">{_e(label)}</button>'
        for value, label in OUTCOME_LABELS
    )
    # Native forms remain usable with JavaScript disabled.  The controller
    # enhances these forms with JSON POSTs and keeps the server as authority.
    return f"""
        <section class="cal calibration-revisit-card"
          data-testid="calibration-revisit-card" data-state="pending"
          data-decision-id="{_e(decision_id)}" data-decision-object-id="{_e(decision_object_id)}"
          data-rung-index="{rung_index}" data-note-path="{_e(note_path)}" data-decided-on="{decided_on}"
          data-rung-days="{rung_days}" data-degraded="false"
          aria-labelledby="{heading_id}">
          <header class="cal-head"><span class="cal-eyebrow">Decision calibration · revisit</span><span class="cal-badge">Pending</span></header>
          <div class="cal-lead">
            <h3 id="{heading_id}" class="cal-q" tabindex="-1">You decided <span class="cal-title">{title}</span> on <time datetime="{decided_on}">{decided_on}</time> — did it hold?</h3>
            <p class="cal-meta">Decided {decided_on} · {rung_days}-day rung</p>
          </div>
          <form class="cal-answer" method="post" action="{_e(answer_action)}" data-intent="answer" aria-labelledby="{heading_id}">
            <input type="hidden" name="rung_index" value="{rung_index}">
            <input type="hidden" name="decision_object_id" value="{_e(decision_object_id)}">
            <fieldset class="cal-pick-group">
              <legend>Did it hold?</legend>
              <div class="cal-picks">{picks}</div>
            </fieldset>
            <label class="cal-note-label" for="calibration-revisit-note">Note (optional)</label>
            <textarea id="calibration-revisit-note" class="cal-note" name="note" rows="2" placeholder="Optional context"></textarea>
            <div class="cal-alert" data-calibration-feedback hidden></div>
          </form>
          <form class="cal-foot" method="post" action="{_e(dismiss_action)}" data-intent="dismiss">
            <input type="hidden" name="rung_index" value="{rung_index}">
            <input type="hidden" name="decision_object_id" value="{_e(decision_object_id)}">
            <button class="cal-dismiss" type="submit" aria-describedby="calibration-revisit-dismiss-help">Dismiss for now</button>
            <p class="cal-hint" id="calibration-revisit-dismiss-help">Defers this revisit. Records no outcome.</p>
          </form>
        </section>"""


def calibration_revisit_card_script() -> str:
    """Enhance the native forms while preserving server authority."""

    labels = _json(dict(OUTCOME_LABELS))
    return f"""
  <script>
  (function() {{
    var card = document.querySelector('[data-testid="calibration-revisit-card"]');
    if (!card || card.getAttribute('data-state') !== 'pending') return;
    var busy = false;
    var labels = {labels};
    var answer = card.querySelector('form[data-intent="answer"]');
    var dismiss = card.querySelector('form[data-intent="dismiss"]');
    var feedback = card.querySelector('[data-calibration-feedback]');
    function setFeedback(message, failure) {{
      if (!feedback) return;
      feedback.hidden = false;
      feedback.textContent = message;
      feedback.setAttribute('data-failure', failure || '');
    }}
    function setBusy(form, value, label) {{
      if (!form) return;
      form.setAttribute('aria-busy', value ? 'true' : 'false');
      Array.prototype.forEach.call(form.querySelectorAll('button'), function(button) {{
        button.disabled = value;
        if (value && label) {{
          if (!button.getAttribute('data-calibration-label')) button.setAttribute('data-calibration-label', button.textContent || '');
          button.textContent = label;
        }} else if (!value && button.getAttribute('data-calibration-label')) {{
          button.textContent = button.getAttribute('data-calibration-label');
        }}
      }});
    }}
    function rereadWorkspace() {{
      var notePath = card.getAttribute('data-note-path') || '';
      var query = notePath ? ('?note_path=' + encodeURIComponent(notePath)) : '';
      return fetch('/api/companion/workspace' + query, {{headers: {{'Accept': 'application/json'}}}})
        .then(function(response) {{
          return response.json().catch(function() {{ return {{}}; }}).then(function(data) {{
            if (!response.ok || !data || !data.calibration_revisit) throw new Error('Workspace reread unavailable.');
            return data;
          }});
        }});
    }}
    function submit(url, body, form, intent) {{
      if (busy) return;
      busy = true;
      setBusy(form, true, intent === 'answer' ? 'Recording…' : 'Deferring…');
      fetch(url, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body || {{}})}})
        .then(function(response) {{ return response.json().catch(function() {{ return {{}}; }}).then(function(data) {{ return {{ok: response.ok, data: data}}; }}); }})
        .then(function(result) {{
          if (!result.ok) throw new Error((result.data && result.data.detail && result.data.detail.message) || 'The runtime did not record this action.');
          var expectedStatus = intent === 'answer' ? 'answered' : 'dismissed';
          if (!result.data || result.data.status !== expectedStatus || String(result.data.decision_id) !== String(card.getAttribute('data-decision-id')) || String(result.data.rung_index) !== String(card.getAttribute('data-rung-index'))) {{
            throw new Error('The runtime returned an unexpected action state.');
          }}
          return rereadWorkspace().then(function() {{
            card.setAttribute('data-state', expectedStatus);
            card.setAttribute('data-outcome', intent === 'answer' ? (body.outcome || '') : '');
            card.hidden = true;
            window.location.reload();
          }});
        }})
        .catch(function(error) {{
          busy = false;
          setBusy(form, false, '');
          setFeedback('Nothing durable happened. You can retry this ' + intent + '.', 'failed');
        }});
    }}
    if (answer) answer.addEventListener('submit', function(event) {{
      event.preventDefault();
      var button = event.submitter || answer.querySelector('button[data-outcome]:focus');
      var outcome = button && button.getAttribute('data-outcome');
      if (!outcome || !Object.prototype.hasOwnProperty.call(labels, outcome)) return;
      var note = answer.querySelector('textarea[name="note"]');
      var body = {{outcome: outcome}};
      var rung = card.getAttribute('data-rung-index');
      var objectId = card.getAttribute('data-decision-object-id');
      if (rung !== '') body.rung_index = Number(rung);
      if (objectId) body.decision_object_id = objectId;
      if (note && note.value.trim()) body.note = note.value.trim();
      submit(answer.action, body, answer, 'answer');
    }});
    if (dismiss) dismiss.addEventListener('submit', function(event) {{
      event.preventDefault();
      var body = {{}};
      var rung = card.getAttribute('data-rung-index');
      var objectId = card.getAttribute('data-decision-object-id');
      if (rung !== '') body.rung_index = Number(rung);
      if (objectId) body.decision_object_id = objectId;
      submit(dismiss.action, body, dismiss, 'dismiss');
    }});
  }})();
  </script>"""


__all__ = ["calibration_revisit_card_markup", "calibration_revisit_card_script"]
