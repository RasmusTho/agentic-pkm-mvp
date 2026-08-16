from __future__ import annotations

import io

from companion_ui.workspace.serve_dev_page import make_handler, render_index_html


def _html() -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001", fields={})


def _voice_surface(html: str) -> str:
    start = html.index('<section class="voice-push-to-talk"')
    return html[start : html.index("</section>", start) + len("</section>")]


def test_ask_loop_requires_no_typing() -> None:
    html = _html()
    surface = _voice_surface(html)

    assert 'data-testid="voice-push-to-talk-control"' in surface
    assert "MediaRecorder" in html
    assert "pointerdown" in html
    assert "pointerup" in html
    assert "fetch('/api/ask/voice', {method: 'POST'" in html
    assert "<input" not in surface
    assert "<textarea" not in surface


def test_push_to_talk_renders_answer_citations_and_audio() -> None:
    html = _html()

    for testid in (
        "voice-transcript",
        "voice-answer",
        "voice-citations",
        "voice-audio",
    ):
        assert f'data-testid="{testid}"' in html
    assert "renderSpeechPlan(plan)" in html
    assert "audio_url" in html
    assert "citation.url || citation.path" in html


def test_degrade_states_render_legibly() -> None:
    html = _html()

    assert "stt_unavailable" in html
    assert "I couldn't hear that clearly" in html
    assert "I couldn't answer that right now" in html
    assert "voice unavailable" in html
    assert "voiceControl.removeAttribute('disabled')" in html
    assert "audio.hidden = true" in html


def test_no_always_on_affordance() -> None:
    html = _html()
    surface = _voice_surface(html).lower()

    assert "wake" not in surface
    assert "always-on" not in surface
    assert "getusermedia" not in html.lower() or "mediarecorder" in html.lower()


def test_voice_audio_is_proxied_as_unchanged_multipart() -> None:
    class Client:
        def __init__(self) -> None:
            self.call: tuple[str, bytes, dict[str, str], float | None] | None = None

        def post_raw(
            self,
            path: str,
            *,
            content: bytes,
            headers: dict[str, str],
            timeout: float | None = None,
        ) -> dict[str, object]:
            self.call = (path, content, headers, timeout)
            return {"transcript": "hello", "answer": "Hi", "sources": []}

    client = Client()
    handler_cls = make_handler(client=client, api_base_url="http://127.0.0.1:18001")  # type: ignore[arg-type]
    raw = b"--voice-boundary\\r\\nexample-audio\\r\\n--voice-boundary--\\r\\n"
    handler = handler_cls.__new__(handler_cls)
    handler.path = "/api/ask/voice"
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.headers = {
        "Content-Length": str(len(raw)),
        "Content-Type": "multipart/form-data; boundary=voice-boundary",
    }
    captured: dict[str, object] = {}
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)  # type: ignore[method-assign]

    handler.do_POST()

    assert client.call == (
        "/api/ask/voice",
        raw,
        {"Content-Type": "multipart/form-data; boundary=voice-boundary"},
        120.0,
    )
    assert captured == {
        "status": 200,
        "payload": {"transcript": "hello", "answer": "Hi", "sources": []},
    }
