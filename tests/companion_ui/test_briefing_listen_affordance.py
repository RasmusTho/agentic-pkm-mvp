from __future__ import annotations

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

