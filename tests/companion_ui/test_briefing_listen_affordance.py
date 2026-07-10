from __future__ import annotations

import json
import subprocess

from companion_ui.workspace.briefing_listen import render_briefing_listen_affordance


_BRIEFING = "# Daglig briefing\n\nDu behöver svara Anna. Review the launch decision."


def test_one_tap_listen_triggers_plan_and_synthesize() -> None:
    html = render_briefing_listen_affordance(
        briefing_text=_BRIEFING,
        tts_available=True,
    )

    assert 'data-testid="briefing-listen"' in html
    assert 'onclick="briefingListen.play(this)"' in html
    plan = html.index("postJson('/api/companion/tts/plan'")
    synthesize = html.index("postJson('/api/companion/tts/synthesize'")
    playback = html.index("audio.play()", synthesize)
    assert plan < synthesize < playback
    assert "plan.normalized_text" in html
    assert html.index("renderSpeechPlan(surface, plan)", plan) < synthesize


def test_degrades_to_text_only_when_tts_unavailable() -> None:
    html = render_briefing_listen_affordance(
        briefing_text=_BRIEFING,
        tts_available=False,
        unavailable_reason="Local TTS provider/model unavailable.",
    )

    assert _BRIEFING in html
    assert 'data-testid="briefing-text"' in html
    assert 'data-testid="briefing-listen"' in html
    assert "disabled" in html
    assert 'aria-disabled="true"' in html
    assert "Local TTS provider/model unavailable." in html


def test_no_autoplay_on_render() -> None:
    html = render_briefing_listen_affordance(
        briefing_text=_BRIEFING,
        tts_available=True,
    )

    play_function = html[html.index("play: function") :]
    before_play_function = html[: html.index("play: function")]
    assert "audio.play()" in play_function
    assert "audio.play()" not in before_play_function
    assert "DOMContentLoaded" not in html
    assert "autoplay" not in html.lower()


def _run_affordance_script(fetch_responses: list[dict[str, object]]) -> dict[str, object]:
    html = render_briefing_listen_affordance(
        briefing_text=_BRIEFING,
        tts_available=True,
    )
    script = html[html.index("<script>") + len("<script>") : html.index("</script>")]
    harness = f"""
const events = [];
const status = {{textContent: ''}};
const planNode = {{
  hidden: true,
  _html: '',
  set innerHTML(value) {{ this._html = value; events.push('render-plan'); }},
  get innerHTML() {{ return this._html; }}
}};
const surface = {{
  getAttribute: () => {json.dumps(json.dumps(_BRIEFING))},
  querySelector: (selector) => selector.includes('speech-plan') ? planNode : status
}};
const button = {{
  disabled: false,
  closest: () => surface,
  setAttribute: (name, value) => events.push(name + '=' + value)
}};
const responses = {json.dumps(fetch_responses)};
global.window = {{}};
global.fetch = (path) => {{
  events.push(path.includes('/plan') ? 'fetch-plan' : 'fetch-synthesize');
  const response = responses.shift();
  return Promise.resolve({{
    ok: response.ok,
    json: () => Promise.resolve(response.body)
  }});
}};
global.Audio = function (url) {{
  this.play = () => {{ events.push('play'); return Promise.resolve(); }};
}};
{script}
window.briefingListen.play(button);
setTimeout(() => console.log(JSON.stringify({{
  events,
  status: status.textContent,
  planHtml: planNode.innerHTML,
  planHidden: planNode.hidden,
  disabled: button.disabled
}})), 25);
"""
    result = subprocess.run(
        ["node", "-e", harness],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_speech_plan_is_rendered_before_synthesis_and_playback() -> None:
    result = _run_affordance_script(
        [
            {
                "ok": True,
                "body": {
                    "enabled": True,
                    "normalized_text": "Hej Anna. Review the launch.",
                    "mixed_language": True,
                    "cached": False,
                    "provider_available": True,
                    "warnings": ["uncertain mixed-language text"],
                    "segments": [
                        {
                            "text": "Hej Anna.",
                            "language": "sv-SE",
                            "provider": "piper",
                            "voice_id": "sv_SE-lisa-medium",
                        },
                        {
                            "text": "Review the launch.",
                            "language": "en-US",
                            "provider": "kokoro",
                            "voice_id": "bf_isabella",
                        },
                    ],
                },
            },
            {"ok": True, "body": {"ok": True, "audio_url": "/briefing.wav"}},
        ]
    )

    events = result["events"]
    assert events.index("fetch-plan") < events.index("render-plan")
    assert events.index("render-plan") < events.index("fetch-synthesize")
    assert events.index("fetch-synthesize") < events.index("play")
    assert result["planHidden"] is False
    plan_html = str(result["planHtml"])
    for value in (
        "Hej Anna. Review the launch.",
        "sv-SE",
        "piper",
        "sv_SE-lisa-medium",
        "en-US",
        "kokoro",
        "bf_isabella",
        "not cached",
        "uncertain mixed-language text",
        "mixed_language",
    ):
        assert value in plan_html


def test_structured_tts_rejection_surfaces_honest_reason() -> None:
    result = _run_affordance_script(
        [
            {
                "ok": False,
                "body": {
                    "detail": {
                        "reason": "piper model unavailable",
                        "message": "Local provider could not synthesize",
                    }
                },
            }
        ]
    )

    assert result["status"] == "piper model unavailable"
    assert "[object Object]" not in str(result["status"])
    assert result["disabled"] is True
    assert "aria-disabled=true" in result["events"]
    assert "fetch-synthesize" not in result["events"]
    assert "play" not in result["events"]
