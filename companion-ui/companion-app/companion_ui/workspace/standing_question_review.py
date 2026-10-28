"""Standing-question list and review controls for the declared Memory drawer."""

from __future__ import annotations

STANDING_QUESTIONS_ENDPOINT = "/api/standing-questions"


def standing_question_review_markup() -> str:
    """Return the SQ-05 subview; all vault effects remain behind runtime APIs."""

    return f"""
  <style>
    .sq-review-view[hidden], .memory-review-view[hidden] {{ display: none !important; }}
    .memory-review-tabs {{ display: flex; gap: 8px; margin: 8px 0 14px; }}
    .memory-review-tab {{
      background: var(--bg-raised); border: 1px solid var(--border);
      border-radius: var(--radius-sm); color: var(--fg-2); cursor: pointer;
      font: inherit; padding: 7px 10px;
    }}
    .memory-review-tab[aria-selected="true"] {{
      border-color: var(--accent-dim); color: var(--fg-1);
    }}
    .sq-question-list {{ display: grid; gap: 6px; margin: 0 0 14px; }}
    .sq-question-row {{
      background: var(--bg-raised); border: 1px solid var(--border);
      border-radius: var(--radius-sm); color: var(--fg-1); cursor: pointer;
      padding: 9px 10px; text-align: left; width: 100%;
    }}
    .sq-question-row[aria-current="true"] {{ border-color: var(--border-focus); }}
    .sq-question-meta, .sq-question-evidence-meta {{ color: var(--fg-2); font-size: var(--text-xs); }}
    .sq-question-detail {{ border-top: 1px solid var(--border); padding-top: 12px; }}
    .sq-question-detail h3 {{ color: var(--fg-1); font-size: var(--text-md); }}
    .sq-question-evidence {{ border-top: 1px dashed var(--border); margin-top: 12px; padding-top: 8px; }}
    .sq-question-evidence-item {{ margin: 0 0 12px; }}
    .sq-question-evidence-item blockquote {{
      border-left: 2px solid var(--border-strong); color: var(--fg-1);
      margin: 6px 0; padding-left: 10px; white-space: pre-wrap;
    }}
    .sq-question-link {{ color: var(--cyan); }}
    .sq-question-candidate {{
      background: var(--bg-surface); border: 1px solid var(--border-strong);
      border-radius: var(--radius-md); margin-top: 12px; padding: 12px;
    }}
    .sq-question-candidate-body {{ color: var(--fg-1); white-space: pre-wrap; }}
    .sq-contradiction-marker {{
      background: var(--destructive-muted); border: 1px solid var(--status-danger);
      border-left: 4px solid var(--status-danger); border-radius: var(--radius-sm);
      color: var(--status-danger); font-weight: var(--weight-semibold);
      margin: 8px 0; padding: 8px 10px;
    }}
    .sq-review-actions {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .sq-review-action {{
      background: var(--bg-raised); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); color: var(--fg-1); cursor: pointer;
      font: inherit; font-size: var(--text-sm); padding: 7px 11px;
    }}
    .sq-review-action[data-primary="true"] {{ border-color: var(--accent-dim); }}
    .sq-review-action[data-destructive="true"] {{ border-color: var(--status-danger); }}
    .sq-review-action:disabled {{ cursor: default; opacity: 0.45; }}
    .sq-review-state {{ color: var(--fg-2); font-size: var(--text-sm); }}
    .sq-review-state[data-tone="danger"] {{ color: var(--status-danger); }}
    .sq-review-empty, .sq-review-loading {{ color: var(--fg-2); font-size: var(--text-sm); }}
  </style>
  <section class="sq-review-view" data-testid="standing-question-review"
    data-source="standing_questions" data-endpoint="{STANDING_QUESTIONS_ENDPOINT}"
    hidden aria-label="Standing question review">
    <div class="sq-review-toolbar">
      <button type="button" class="memory-review-tab" data-testid="sq-toggle-resolved"
        aria-pressed="false">Show resolved</button>
    </div>
    <p class="sq-review-state" data-testid="sq-review-state" aria-live="polite"></p>
    <div class="sq-question-list" data-testid="sq-question-list">
      <p class="sq-review-loading">Loading questions…</p>
    </div>
    <article class="sq-question-detail" data-testid="sq-question-detail" hidden></article>
  </section>"""


def standing_question_review_script() -> str:
    """Browser controller; it renders API text with textContent and posts only declared actions."""

    return f"""
  <script>
  /* standing-question-review-controller */
  (function() {{
    var drawer = document.getElementById('memory-review-drawer');
    var root = drawer && drawer.querySelector('[data-testid="standing-question-review"]');
    if (!root) {{ return; }}
    var list = root.querySelector('[data-testid="sq-question-list"]');
    var detail = root.querySelector('[data-testid="sq-question-detail"]');
    var state = root.querySelector('[data-testid="sq-review-state"]');
    var resolvedToggle = root.querySelector('[data-testid="sq-toggle-resolved"]');
    var tabButtons = drawer.querySelectorAll('[data-drawer-tab]');
    var memoryView = drawer.querySelector('[data-drawer-view="memory"]');
    var showResolved = false;
    var selectedId = '';
    var selectedQuestion = null;
    var listItems = [];

    function text(tag, value, className) {{
      var node = document.createElement(tag);
      if (className) {{ node.className = className; }}
      node.textContent = value == null ? '' : String(value);
      return node;
    }}
    function setState(message, tone) {{
      state.textContent = message || '';
      state.setAttribute('data-tone', tone || 'calm');
    }}
    function detailMessage(payload) {{
      var value = payload && payload.detail;
      if (value && typeof value === 'object') {{
        return value.message || value.error || 'The review action was not completed.';
      }}
      return typeof value === 'string' ? value : 'The review action was not completed.';
    }}
    function fetchJson(url, options) {{
      return fetch(url, options || {{method: 'GET'}}).then(function(response) {{
        return response.json().catch(function() {{ return {{}}; }}).then(function(payload) {{
          if (!response.ok) {{
            var error = new Error(detailMessage(payload));
            error.payload = payload;
            error.status = response.status;
            throw error;
          }}
          return payload;
        }});
      }});
    }}
    function renderList(items) {{
      listItems = items;
      list.textContent = '';
      if (!items.length) {{
        list.appendChild(text('p', showResolved ? 'No questions to show.' : 'No open questions.', 'sq-review-empty'));
        return;
      }}
      items.forEach(function(item) {{
        var button = text('button', item.text, 'sq-question-row');
        button.type = 'button';
        button.setAttribute('data-question-id', item.question_id);
        button.setAttribute('aria-current', item.question_id === selectedId ? 'true' : 'false');
        button.setAttribute('data-testid', 'sq-question-row');
        var meta = text('span', item.status + ' · ' + item.evidence_count + ' evidence items', 'sq-question-meta');
        button.appendChild(document.createElement('br'));
        button.appendChild(meta);
        list.appendChild(button);
      }});
    }}
    function renderEvidence(items) {{
      var section = text('section', '', 'sq-question-evidence');
      section.appendChild(text('h4', 'Evidence'));
      if (!items.length) {{
        section.appendChild(text('p', 'No evidence recorded.', 'sq-review-empty'));
        return section;
      }}
      items.forEach(function(item) {{
        var article = text('article', '', 'sq-question-evidence-item');
        article.appendChild(text('p', item.source_stream + ' · ' + item.matched_at + ' · ' + item.confidence_class, 'sq-question-evidence-meta'));
        if (item.provenance_ref) {{ article.appendChild(text('p', 'Provenance: ' + item.provenance_ref, 'sq-question-evidence-meta')); }}
        article.appendChild(text('blockquote', item.quoted_span));
        article.appendChild(text('code', 'Content hash: ' + item.content_hash, 'sq-question-evidence-meta'));
        article.appendChild(text('p', item.artifact_ref, 'sq-question-evidence-meta'));
        if (item.source_note_path) {{
          var link = text('a', 'Open source note');
          link.className = 'sq-question-link';
          link.href = '/workspace?note_path=' + encodeURIComponent(item.source_note_path);
          article.appendChild(link);
        }}
        section.appendChild(article);
      }});
      return section;
    }}
    function isContradiction(value) {{
      return value === true || (typeof value === 'string' && ['true', 'yes'].indexOf(value.toLowerCase()) !== -1);
    }}
    function actionButton(label, action, options) {{
      options = options || {{}};
      var button = text('button', label, 'sq-review-action');
      button.type = 'button';
      button.setAttribute('data-sq-action', action);
      if (options.primary) {{ button.setAttribute('data-primary', 'true'); }}
      if (options.destructive) {{ button.setAttribute('data-destructive', 'true'); }}
      return button;
    }}
    function renderDetail(item) {{
      selectedQuestion = item;
      selectedId = item.question_id;
      detail.textContent = '';
      detail.hidden = false;
      detail.appendChild(text('h3', item.text));
      detail.appendChild(text('p', item.status + ' · ' + item.scope, 'sq-question-meta'));
      detail.appendChild(renderEvidence(item.evidence || []));
      var candidate = item.candidate_answer;
      if (candidate) {{
        var card = text('section', '', 'sq-question-candidate');
        card.setAttribute('data-testid', 'sq-question-candidate');
        card.appendChild(text('h4', 'Candidate answer'));
        if (isContradiction(candidate.contradicts_standing_answer)) {{
          var marker = text('p', 'Contradicts the standing answer');
          marker.className = 'sq-contradiction-marker';
          marker.setAttribute('data-testid', 'standing-question-contradiction-marker');
          marker.setAttribute('data-contradicts-standing-answer', 'true');
          card.appendChild(marker);
          if (candidate.contradiction_basis) {{ card.appendChild(text('p', candidate.contradiction_basis, 'sq-question-meta')); }}
        }}
        if (candidate.body) {{ card.appendChild(text('p', candidate.body, 'sq-question-candidate-body')); }}
        if (candidate.state === 'acknowledgement_indeterminate') {{
          card.appendChild(text('p', 'Review acknowledgement is indeterminate. The question remains unresolved and needs reconciliation.', 'sq-review-state'));
        }} else if (candidate.state === 'missing') {{
          card.appendChild(text('p', 'The candidate file is missing; no answer was recorded.', 'sq-review-state'));
        }} else if (candidate.state === 'unreadable' || candidate.state === 'not_selectable') {{
          card.appendChild(text('p', 'This candidate cannot be reviewed safely.', 'sq-review-state'));
        }}
        if (candidate.acceptance_control && item.status === 'open') {{
          card.appendChild(actionButton('Accept answer', 'accept', {{primary: true}}));
        }}
        if (candidate.state === 'pending' && item.status === 'open') {{
          card.appendChild(actionButton('Dismiss candidate', 'dismiss', {{destructive: true}}));
        }}
        detail.appendChild(card);
      }}
      var actions = text('div', '', 'sq-review-actions');
      actions.setAttribute('data-testid', 'sq-review-actions');
      if (item.status === 'open') {{ actions.appendChild(actionButton('Close question', 'close')); }}
      if (item.status === 'closed') {{ actions.appendChild(actionButton('Reopen question', 'reopen')); }}
      detail.appendChild(actions);
      renderList(listItems);
    }}
    function loadList() {{
      list.textContent = '';
      list.appendChild(text('p', 'Loading questions…', 'sq-review-loading'));
      var query = showResolved ? '?include_resolved=true' : '';
      return fetchJson('{STANDING_QUESTIONS_ENDPOINT}' + query, {{method: 'GET'}})
        .then(function(payload) {{ renderList(payload.questions || []); setState(''); }})
        .catch(function(error) {{ list.textContent = ''; list.appendChild(text('p', error.message, 'sq-review-state')); setState('Question list unavailable.', 'danger'); }});
    }}
    function loadDetail(questionId) {{
      selectedId = questionId;
      return fetchJson('{STANDING_QUESTIONS_ENDPOINT}/' + encodeURIComponent(questionId), {{method: 'GET'}})
        .then(renderDetail)
        .catch(function(error) {{ detail.hidden = false; detail.textContent = ''; detail.appendChild(text('p', error.message, 'sq-review-state')); setState('Question detail unavailable.', 'danger'); }});
    }}
    function mutate(button) {{
      if (!selectedQuestion) {{ return; }}
      var action = button.getAttribute('data-sq-action');
      var version = selectedQuestion.question_version;
      var url = '';
      var payload = {{expected_question_version: version}};
      if (action === 'accept') {{
        url = '/api/panel/checkbox-projection';
        payload = selectedQuestion.candidate_answer.acceptance_control;
      }} else if (['dismiss', 'close', 'reopen'].indexOf(action) !== -1) {{
        url = '{STANDING_QUESTIONS_ENDPOINT}/' + encodeURIComponent(selectedQuestion.question_id) + '/' + action;
      }} else {{ return; }}
      var buttons = detail.querySelectorAll('button');
      Array.prototype.forEach.call(buttons, function(item) {{ item.disabled = true; }});
      setState('Saving review…');
      fetchJson(url, {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(payload)}})
        .then(function(result) {{
          if (result.state === 'acknowledgement_indeterminate' || (result.receipt && result.receipt.status === 'acknowledgement_indeterminate')) {{
            setState('Review acknowledgement is indeterminate; the question remains unresolved.', 'danger');
          }} else {{ setState('Review recorded: ' + (result.status || 'completed')); }}
          return loadList().then(function() {{ return loadDetail(selectedQuestion.question_id); }});
        }})
        .catch(function(error) {{
          var payload = error.payload && error.payload.detail;
          var outcome = payload && typeof payload === 'object' ? payload.state : null;
          setState(outcome === 'acknowledgement_indeterminate'
            ? 'Review acknowledgement is indeterminate; the question remains unresolved.'
            : error.message, outcome === 'acknowledgement_indeterminate' ? 'danger' : 'calm');
          return loadList().then(function() {{ return loadDetail(selectedQuestion.question_id); }});
        }});
    }}
    root.addEventListener('click', function(event) {{
      var questionButton = event.target.closest('[data-question-id]');
      if (questionButton) {{ loadDetail(questionButton.getAttribute('data-question-id')); return; }}
      var actionButtonNode = event.target.closest('[data-sq-action]');
      if (actionButtonNode) {{ mutate(actionButtonNode); }}
    }});
    resolvedToggle.addEventListener('click', function() {{
      showResolved = !showResolved;
      resolvedToggle.setAttribute('aria-pressed', showResolved ? 'true' : 'false');
      resolvedToggle.textContent = showResolved ? 'Hide resolved' : 'Show resolved';
      loadList();
    }});
    function activateTab(name) {{
      var questionsActive = name === 'standing-questions';
      root.hidden = !questionsActive;
      if (memoryView) {{ memoryView.hidden = questionsActive; }}
      Array.prototype.forEach.call(tabButtons, function(button) {{
        button.setAttribute('aria-selected', button.getAttribute('data-drawer-tab') === name ? 'true' : 'false');
      }});
      if (questionsActive) {{ loadList(); }}
    }}
    Array.prototype.forEach.call(tabButtons, function(button) {{
      button.addEventListener('click', function() {{ activateTab(button.getAttribute('data-drawer-tab')); }});
    }});
    drawer.addEventListener('sq-review-refresh', loadList);
    activateTab('memory');
    window.standingQuestionReview = {{refresh: loadList, open: function() {{ activateTab('standing-questions'); }}}};
  }})();
  </script>"""


__all__ = [
    "STANDING_QUESTIONS_ENDPOINT",
    "standing_question_review_markup",
    "standing_question_review_script",
]
