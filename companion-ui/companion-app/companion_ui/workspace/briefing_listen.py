"""Read-only, one-tap local-TTS affordance for a composed Daily Briefing."""

from __future__ import annotations

import html
import json


def render_briefing_listen_affordance(
    *,
    briefing_text: str,
    tts_available: bool,
    unavailable_reason: str | None = None,
) -> str:
    """Render briefing text plus an availability-honest listen control."""

    text = html.escape(briefing_text)
    encoded_text = html.escape(json.dumps(briefing_text), quote=True)
    disabled = "" if tts_available else " disabled"
    aria_disabled = "false" if tts_available else "true"
    reason = "" if tts_available else html.escape(
        unavailable_reason or "Local TTS is unavailable."
    )
    return f"""
<section class="briefing-audio-surface" data-authority="read-only-projection"
         data-briefing-text="{encoded_text}">
  <article data-testid="briefing-text" class="briefing-text">{text}</article>
  <button type="button" data-testid="briefing-listen"
          aria-disabled="{aria_disabled}"{disabled}
          onclick="briefingListen.play(this)">Listen</button>
  <p data-testid="briefing-listen-status" role="status">{reason}</p>
  <section data-testid="briefing-speech-plan" hidden></section>
</section>
<script>
(function () {{
  function errorMessage(data) {{
    var detail = data && data.detail;
    if (detail && typeof detail === 'object') {{
      return detail.reason || detail.message || 'Local TTS unavailable.';
    }}
    return detail || (data && (data.reason || data.message)) || 'Local TTS unavailable.';
  }}

  function postJson(path, payload) {{
    return fetch(path, {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(payload)
    }}).then(function (response) {{
      return response.json().then(function (data) {{
        if (!response.ok) {{
          throw new Error(errorMessage(data));
        }}
        return data;
      }});
    }});
  }}

  function surfaceFor(button) {{
    return button && button.closest('.briefing-audio-surface');
  }}

  function briefingText(surface) {{
    return JSON.parse(surface.getAttribute('data-briefing-text') || '\"\"');
  }}

  function setStatus(surface, message) {{
    var status = surface.querySelector('[data-testid="briefing-listen-status"]');
    if (status) {{ status.textContent = message; }}
  }}

  function escapeHtml(value) {{
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }}

  function renderSpeechPlan(surface, plan) {{
    var node = surface.querySelector('[data-testid="briefing-speech-plan"]');
    if (!node || !plan) {{ return; }}
    var warnings = Array.isArray(plan.warnings) ? plan.warnings.slice() : [];
    if (plan.mixed_language && warnings.indexOf('mixed_language') < 0) {{
      warnings.push('mixed_language');
    }}
    if (plan.provider_available === false) {{
      warnings.push(plan.provider_reason || 'provider_available false');
    }}
    var cache = plan.cached ? 'cached' : 'not cached';
    var segments = Array.isArray(plan.segments) ? plan.segments : [];
    var segmentRows = segments.map(function (segment) {{
      return '<li>' + escapeHtml(segment.language || plan.language || 'unknown') +
        ' / ' + escapeHtml(segment.provider || plan.provider || 'unknown') +
        ' / ' + escapeHtml(segment.voice_id || plan.voice_id || 'unknown') +
        ' / ' + cache + ': ' + escapeHtml(segment.text || '') + '</li>';
    }}).join('');
    var warningRows = warnings.map(function (warning) {{
      return '<li class="tts-warning">' + escapeHtml(warning) + '</li>';
    }}).join('');
    node.hidden = false;
    node.innerHTML =
      '<div class="tts-plan-text">' + escapeHtml(plan.normalized_text || '') + '</div>' +
      '<ul class="tts-plan-segments">' + segmentRows + '</ul>' +
      '<ul class="tts-plan-warnings">' + warningRows + '</ul>';
  }}

  window.briefingListen = {{
    play: function (button) {{
      var surface = surfaceFor(button);
      if (!surface || button.disabled) {{ return; }}
      var text = briefingText(surface);
      button.disabled = true;
      setStatus(surface, 'Planning local audio.');
      postJson('/api/companion/tts/plan', {{text: text, rate: 1.0}})
        .then(function (plan) {{
          renderSpeechPlan(surface, plan);
          if (plan.enabled === false) {{
            throw new Error('Local TTS is disabled.');
          }}
          if (!plan.cached && plan.provider_available === false) {{
            throw new Error(plan.provider_reason || 'Local TTS provider/model unavailable.');
          }}
          setStatus(surface, 'Synthesizing local audio.');
          return postJson('/api/companion/tts/synthesize', {{
            text: plan.normalized_text,
            rate: plan.rate || 1.0
          }});
        }})
        .then(function (result) {{
          if (!result.ok || !result.audio_url) {{
            throw new Error(result.reason || 'Local TTS unavailable.');
          }}
          var audio = new Audio(result.audio_url);
          audio.onended = function () {{
            button.disabled = false;
            setStatus(surface, 'Briefing audio finished.');
          }};
          audio.onerror = function () {{
            button.disabled = false;
            setStatus(surface, 'Briefing audio failed.');
          }};
          setStatus(surface, 'Playing briefing.');
          return audio.play();
        }})
        .catch(function (error) {{
          button.disabled = true;
          button.setAttribute('aria-disabled', 'true');
          setStatus(
            surface,
            error && error.message ? error.message : 'Local TTS unavailable.'
          );
        }});
    }}
  }};
}}());
</script>
""".strip()
