"""DEBRIEF-03 rail card: review fresh Episode debriefs (accept / dismiss).

The runtime owns the read-only projection and the disposition route. This
module renders API text with textContent and posts only the two declared
dispositions; a failed read is shown as unavailable, never as an empty list.
Dismiss archives the debrief; nothing here can delete it.
"""

from __future__ import annotations

EPISODE_DEBRIEFS_ENDPOINT = "/api/companion/episode-debriefs"


def episode_debrief_review_markup() -> str:
    return f"""
        <section class="debrief-review-card" data-testid="episode-debrief-review"
          data-endpoint="{EPISODE_DEBRIEFS_ENDPOINT}" aria-labelledby="episode-debrief-review-heading">
          <h3 id="episode-debrief-review-heading" class="debrief-review-eyebrow">Episode debriefs</h3>
          <p class="debrief-review-state" data-testid="episode-debrief-review-state" aria-live="polite"></p>
          <div class="debrief-review-list" data-testid="episode-debrief-review-list">
            <p class="debrief-review-loading">Loading debriefs…</p>
          </div>
        </section>"""


def episode_debrief_review_style() -> str:
    return """
    /* ---- DEBRIEF-03 episode debrief review card ---- */
    .debrief-review-card { border: 1px solid var(--border); border-radius: var(--radius-md); padding: 12px; }
    .debrief-review-eyebrow { color: var(--fg-2); font-size: var(--text-xs); margin: 0 0 8px; }
    .debrief-review-item { border-top: 1px solid var(--border); padding: 10px 0; }
    .debrief-review-item h4 { color: var(--fg-1); font-size: var(--text-md); margin: 0 0 6px; }
    .debrief-review-body { color: var(--fg-1); font-size: var(--text-sm); max-height: 14em; overflow: auto; white-space: pre-wrap; }
    .debrief-review-actions { display: flex; gap: 8px; margin-top: 8px; }
    .debrief-review-action { background: var(--bg-raised); border: 1px solid var(--border-strong);
      border-radius: var(--radius-sm); color: var(--fg-1); cursor: pointer; font: inherit; font-size: var(--text-sm); padding: 6px 10px; }
    .debrief-review-action:disabled { cursor: default; opacity: 0.45; }
    .debrief-review-state, .debrief-review-empty, .debrief-review-loading, .debrief-review-hint { color: var(--fg-2); font-size: var(--text-sm); }
    .debrief-review-state[data-tone="danger"] { color: var(--status-danger); }
"""


def episode_debrief_review_script() -> str:
    return f"""
  <script>
  /* episode-debrief-review-controller */
  (function() {{
    var root = document.querySelector('[data-testid="episode-debrief-review"]');
    if (!root) {{ return; }}
    var list = root.querySelector('[data-testid="episode-debrief-review-list"]');
    var state = root.querySelector('[data-testid="episode-debrief-review-state"]');
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
    function fetchJson(url, options) {{
      return fetch(url, options).then(function(response) {{
        return response.json().catch(function() {{ return {{}}; }}).then(function(payload) {{
          if (!response.ok) {{
            var detail = payload && payload.detail;
            throw new Error((detail && (detail.message || detail.error)) || 'The debrief action was not completed.');
          }}
          return payload;
        }});
      }});
    }}
    function button(label, disposition, debriefId) {{
      var node = text('button', label, 'debrief-review-action');
      node.type = 'button';
      node.setAttribute('data-debrief-disposition', disposition);
      node.setAttribute('data-debrief-id', debriefId);
      return node;
    }}
    function render(items) {{
      list.textContent = '';
      if (!items.length) {{ list.appendChild(text('p', 'No debriefs waiting for review.', 'debrief-review-empty')); return; }}
      items.forEach(function(item) {{
        var article = document.createElement('article');
        article.className = 'debrief-review-item';
        article.setAttribute('data-debrief-id', item.debrief_id);
        article.appendChild(text('h4', item.title || item.episode_id));
        article.appendChild(text('div', item.body, 'debrief-review-body'));
        var actions = document.createElement('div');
        actions.className = 'debrief-review-actions';
        actions.appendChild(button('Accept', 'accepted', item.debrief_id));
        actions.appendChild(button('Dismiss', 'dismissed', item.debrief_id));
        article.appendChild(actions);
        article.appendChild(text('p', 'Dismiss archives the debrief; it is never deleted.', 'debrief-review-hint'));
        list.appendChild(article);
      }});
    }}
    function load() {{
      return fetchJson('{EPISODE_DEBRIEFS_ENDPOINT}', {{method: 'GET'}})
        .then(function(payload) {{ render(payload.fresh || []); }})
        .catch(function(error) {{ list.textContent = ''; setState('Debriefs unavailable: ' + error.message, 'danger'); }});
    }}
    root.addEventListener('click', function(event) {{
      var target = event.target.closest('[data-debrief-disposition]');
      if (!target) {{ return; }}
      var buttons = root.querySelectorAll('[data-debrief-id="' + target.getAttribute('data-debrief-id') + '"] button');
      Array.prototype.forEach.call(buttons, function(item) {{ item.disabled = true; }});
      setState('Saving review…');
      fetchJson('{EPISODE_DEBRIEFS_ENDPOINT}/' + encodeURIComponent(target.getAttribute('data-debrief-id')) + '/review', {{
        method: 'POST', headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{disposition: target.getAttribute('data-debrief-disposition')}})
      }}).then(function(result) {{ setState('Debrief ' + result.review_state + '.'); return load(); }})
        .catch(function(error) {{ setState(error.message, 'danger'); return load(); }});
    }});
    load();
  }})();
  </script>"""
