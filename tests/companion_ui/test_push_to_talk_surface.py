from __future__ import annotations

import io
import json
import subprocess

from companion_ui.workspace.serve_dev_page import make_handler, render_index_html
from tests.companion_ui._orphan_text import assert_no_orphan_text


def _html() -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001", fields={})


def _voice_surface(html: str) -> str:
    start = html.index('<section class="voice-push-to-talk"')
    return html[start : html.index("</section>", start) + len("</section>")]


def _voice_script(html: str) -> str:
    start = html.index("  <script>", html.index("function escapeHtml")) + len("  <script>")
    return html[start : html.index("</script>", start)]


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
    assert "'/?note_path=' + encodeURIComponent(citation.path)" in html
    assert "audio.play().then" in html
    assert "Tap play to listen." in html


def test_degrade_states_render_legibly() -> None:
    html = _html()

    assert "stt_unavailable" in html
    assert "I couldn't hear that clearly" in html
    assert "I couldn't answer that right now" in html
    assert "voice unavailable" in html
    assert "voiceControl.removeAttribute('disabled')" in html
    assert "audio.hidden = true" in html
    assert "captureState === 'requesting'" in html
    assert "cancelPendingTap" in html
    assert "Microphone permission pending. Release recorded; no audio will be sent." in html
    assert "mediaStream.getTracks().forEach(function (track) { track.stop(); });" in html


def test_no_always_on_affordance() -> None:
    html = _html()
    surface = _voice_surface(html).lower()

    assert "wake" not in surface
    assert "always-on" not in surface
    assert "getusermedia" not in html.lower() or "mediarecorder" in html.lower()
    assert_no_orphan_text(html)


def test_voice_browser_interactions_converge_across_permission_and_recorder_interleavings() -> None:
    """Exercise the browser state machine, not just its rendered source text."""
    script = json.dumps(_voice_script(_html()))
    harness = f"""
const voiceScript = {script};
function assert(condition, message) {{ if (!condition) throw new Error(message); }}
async function ticks() {{ for (let i = 0; i < 6; i += 1) await Promise.resolve(); }}
function boot(mode) {{
  const control = {{listeners: {{}}, attrs: {{}}, addEventListener(n, f) {{ this.listeners[n] = f; }}, setAttribute(n, v) {{ this.attrs[n] = v; }}, removeAttribute(n) {{ delete this.attrs[n]; }}}};
  const status = {{textContent: ''}};
  const result = {{hidden: true}}; const transcript = {{textContent: ''}}; const answer = {{textContent: ''}};
  const citations = {{innerHTML: ''}}; const degraded = {{hidden: true}};
  const audio = {{hidden: true, src: '', removeAttribute() {{ this.src = ''; }}, play() {{ return Promise.reject(new Error('gesture policy')); }}}};
  const nodes = {{
    '[data-testid="voice-push-to-talk-control"]': control, '[data-testid="voice-push-to-talk-status"]': status,
    '[data-testid="voice-turn-result"]': result, '[data-testid="voice-transcript"]': transcript,
    '[data-testid="voice-answer"]': answer, '[data-testid="voice-citations"]': citations,
    '[data-testid="voice-tts-degraded"]': degraded, '[data-testid="voice-audio"]': audio
  }};
  const surface = {{querySelector(sel) {{ return nodes[sel]; }}}}; let ready;
  global.window = global; global.document = {{addEventListener(_, cb) {{ ready = cb; }}, querySelector() {{ return surface; }}}};
  let resolveMedia; const pending = new Promise((resolve) => {{ resolveMedia = resolve; }});
  Object.defineProperty(global, 'navigator', {{value: {{mediaDevices: {{getUserMedia() {{ return pending; }}}}}}, configurable: true}});
  let starts = 0; let current = null; let uploads = 0;
  class Recorder {{
    constructor() {{ if (mode === 'constructor') throw new Error('constructor'); this.state = 'inactive'; this.mimeType = 'audio/webm'; current = this; }}
    start() {{ if (mode === 'start') throw new Error('start'); this.state = 'recording'; starts += 1; }}
    stop() {{ if (this.state === 'inactive') return; this.state = 'inactive'; if (this.ondataavailable) this.ondataavailable({{data: {{size: 1}}}}); if (this.onstop) this.onstop(); }}
  }}
  Recorder.isTypeSupported = () => true; global.MediaRecorder = Recorder;
  global.Blob = class {{ constructor(parts) {{ this.parts = parts; }} }}; global.FormData = class {{ append() {{}} }};
  global.fetch = () => {{ uploads += 1; return Promise.resolve({{ok: true, json: () => Promise.resolve({{transcript: 'heard', answer: 'answer', sources: [{{path: 'Inbox/a b.md'}}], audio_url: '/answer.mp3'}})}}); }};
  eval(voiceScript); ready();
  const track = {{stops: 0, stop() {{ this.stops += 1; }}}}; const media = {{getTracks() {{ return [track]; }}}};
  function fire(name, event) {{ control.listeners[name](Object.assign({{pointerId: 1, timeStamp: 0, detail: 1, preventDefault() {{}}}}, event || {{}})); }}
  return {{control, status, citations, audio, track, resolveMedia, fire, get starts() {{ return starts; }}, get uploads() {{ return uploads; }}}};
}}
(async () => {{
  let app = boot('ok'); app.fire('pointerdown', {{timeStamp: 0}}); app.fire('pointerup', {{timeStamp: 500}}); app.resolveMedia({{getTracks: app.track ? () => [app.track] : null}}); await ticks();
  assert(app.starts === 0 && app.track.stops === 1 && app.uploads === 0, 'hold release while permission is pending must cancel, stop tracks, and never upload: ' + JSON.stringify({{starts: app.starts, stops: app.track.stops, uploads: app.uploads, status: app.status.textContent}}));
  app = boot('ok'); app.fire('pointerdown', {{timeStamp: 0}}); app.fire('pointercancel', {{timeStamp: 20}}); app.resolveMedia({{getTracks: () => [app.track]}}); await ticks();
  assert(app.starts === 0 && app.track.stops === 1 && app.uploads === 0, 'pointercancel must cancel pending capture with cleanup');
  for (const failure of ['constructor', 'start']) {{ app = boot(failure); app.fire('pointerdown', {{timeStamp: 0}}); app.resolveMedia({{getTracks: () => [app.track]}}); await ticks(); assert(app.track.stops === 1 && app.control.attrs.disabled === undefined && app.status.textContent.includes('could not start'), failure + ' failure must clean up and rearm'); }}
  app = boot('ok'); app.fire('pointerdown', {{timeStamp: 0}}); app.fire('pointerup', {{timeStamp: 100}}); app.resolveMedia({{getTracks: () => [app.track]}}); await ticks(); assert(app.starts === 1, 'first short tap must start once after delayed permission');
  app.fire('pointerdown', {{timeStamp: 1000}}); app.fire('pointerup', {{timeStamp: 1100}}); await ticks();
  assert(app.uploads === 1, 'second short tap must send exactly once'); assert(app.citations.innerHTML.includes('/?note_path=Inbox%2Fa%20b.md'), 'path citations must route to the Companion note URL'); assert(app.audio.src === '/answer.mp3' && app.status.textContent === 'Answer ready. Tap play to listen.', 'requested answer audio may attempt playback and truthfully degrade on rejection');
  app = boot('ok'); app.fire('click', {{detail: 0}}); app.resolveMedia({{getTracks: () => [app.track]}}); await ticks(); app.fire('click', {{detail: 0}}); await ticks(); assert(app.uploads === 1, 'keyboard/AT click fallback must toggle deterministically');
}})().catch((error) => {{ console.error(error.stack); process.exit(1); }});
"""
    result = subprocess.run(
        ["node", "-e", harness], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


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
