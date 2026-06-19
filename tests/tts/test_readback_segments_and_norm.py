"""Regression tests for the TTS read-back residuals from audit #2148 (issue #2189).

Each test asserts the fixed behaviour on the production call path:

- AC1: the dev read-back UI no longer hard-blocks uncached mixed-language synthesis,
  so a mixed plan actually reaches ``synthesize_tts``.
- AC2: per-segment ``provider``/``voice_id`` survive the public plan schema
  (``CompanionTTSPlanResponse.model_validate``) instead of being dropped.
- AC3: underscore emphasis (``_x_`` / ``__x__``) is stripped by ``normalize_tts_text``.
- AC4: ``scripts/fetch_tts_models.sh`` provisions a custom Swedish Piper voice into
  the directory ``resolve_voice`` looks in.
- AC5: ``TTS_ENABLED`` is forwarded into the API container and its compose
  interpolation source carries the flag.
"""

from __future__ import annotations

import subprocess
import sys
import wave
from array import array
from pathlib import Path

from app.api.routes.companion import CompanionTTSPlanResponse
from app.tts.config import TTSConfig
from app.tts.normalization import normalize_tts_text
from app.tts.planning import build_tts_plan
from app.tts.providers import TTSVoice, resolve_voice

REPO_ROOT = Path(__file__).resolve().parents[2]

# The Companion UI dev page (read-back surface) lives in a sibling package that
# is only on sys.path via tests/companion_ui/conftest.py. Add it here too so the
# AC1/AC2 UI assertions below can import the production render function.
_COMPANION_APP = REPO_ROOT / "companion-ui" / "companion-app"
if str(_COMPANION_APP) not in sys.path:
    sys.path.insert(0, str(_COMPANION_APP))


def _config(tmp_path: Path) -> TTSConfig:
    model_dir = tmp_path / "models"
    piper_dir = model_dir / "piper" / "sv_SE-lisa-medium"
    kokoro_dir = model_dir / "kokoro"
    piper_dir.mkdir(parents=True, exist_ok=True)
    kokoro_dir.mkdir(parents=True, exist_ok=True)
    (piper_dir / "sv_SE-lisa-medium.onnx").write_bytes(b"model")
    (piper_dir / "sv_SE-lisa-medium.onnx.json").write_text("{}", encoding="utf-8")
    (kokoro_dir / "kokoro-v1.0.int8.onnx").write_bytes(b"model")
    (kokoro_dir / "voices-v1.0.bin").write_bytes(b"voice")
    return TTSConfig(
        enabled=True,
        local_only=True,
        model_dir=model_dir,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        cache_max_gb=2,
        cache_eviction="lru",
        max_concurrent_jobs=1,
        max_chars_per_request=4000,
        allow_browser_fallback=False,
        allow_cloud_fallback=False,
        piper_command="/bin/echo",
        kokoro_command="/bin/echo",
    )


def _write_wav(path: Path, *, framerate: int, num_frames: int, value: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = array("h", [value]) * num_frames
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(framerate)
        wav.writeframes(samples.tobytes())


# --- AC1: mixed-language UI requests reach synthesis -------------------------


def test_dev_readback_ui_does_not_block_mixed_language() -> None:
    # The read-back UI must let an uncached mixed-language plan proceed to
    # /tts/synthesize now that per-segment mixed synthesis is supported.
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(api_base_url="http://127.0.0.1:8000")

    # The old hard-block threw on any uncached mixed plan before synthesizing.
    assert "Local TTS stopped: uncertain mixed-language text." not in html
    # The synthesis call path is still wired.
    assert "/api/companion/tts/synthesize" in html


def test_uncached_mixed_plan_reaches_synthesis(tmp_path: Path, monkeypatch) -> None:
    # The backend production path synthesizes an uncached mixed-language plan
    # rather than refusing it.
    config = _config(tmp_path)
    text = "Hej, jag laser den har anteckningen. Then I continue in English."

    plan = build_tts_plan(text=text, config=config)
    assert plan["mixed_language"] is True

    calls: list[str] = []

    def fake_synthesize(seg_text: str, voice: TTSVoice, output_path: Path, *, rate: float = 1.0) -> None:
        calls.append(voice.provider)
        rate_hz = 22050 if voice.provider == "piper" else 24000
        _write_wav(output_path, framerate=rate_hz, num_frames=100)

    monkeypatch.setattr("app.tts.service.synthesize_with_voice", fake_synthesize)
    from app.tts.service import synthesize_tts

    result = synthesize_tts(text=text, config=config)

    assert result["ok"] is True
    assert result["state"] == "generated"
    assert calls  # synthesis actually ran for the mixed plan


# --- AC2: segment voice fields survive the public plan schema ----------------


def test_plan_schema_preserves_per_segment_voice_fields(tmp_path: Path) -> None:
    # CompanionTTSPlanResponse.model_validate must keep each segment's resolved
    # provider/voice_id; before the fix these fields were silently dropped.
    config = _config(tmp_path)
    text = "Hej, jag laser den har anteckningen. Then I continue in English."

    plan = build_tts_plan(text=text, config=config)
    response = CompanionTTSPlanResponse.model_validate(plan)

    assert response.mixed_language is True
    sv_segment, en_segment = response.segments
    assert (sv_segment.provider, sv_segment.voice_id) == ("piper", "sv_SE-lisa-medium")
    assert (en_segment.provider, en_segment.voice_id) == ("kokoro", "bf_isabella")


def test_dev_readback_ui_renders_segment_voice(tmp_path: Path) -> None:
    # The dev inspection panel renders each segment's own provider/voice rather
    # than only the top-level plan voice.
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(api_base_url="http://127.0.0.1:8000")
    assert "segment.provider" in html
    assert "segment.voice_id" in html


# --- AC3: underscore emphasis is stripped before read-back -------------------


def test_normalize_strips_underscore_emphasis() -> None:
    assert normalize_tts_text("_emphasis_") == "emphasis"
    assert normalize_tts_text("__strong__") == "strong"
    assert normalize_tts_text("read _this_ aloud") == "read this aloud"
    assert normalize_tts_text("a __bold__ word") == "a bold word"
    assert normalize_tts_text("runtime_env_path") == "runtime_env_path"
    assert normalize_tts_text("snake_case and _em_") == "snake_case and em"
    # Existing asterisk behaviour is preserved.
    assert normalize_tts_text("*em* and **strong**") == "em and strong"


# --- AC4: provisioning honours a custom Swedish voice -----------------------


def test_fetch_tts_models_honours_custom_sv_voice(tmp_path: Path) -> None:
    # With a custom TTS_SV_VOICE the fetch script must land the .onnx/.onnx.json
    # where resolve_voice() looks: model_dir/piper/<voice_id>/<voice_id>.onnx
    script = REPO_ROOT / "scripts" / "fetch_tts_models.sh"
    dest = tmp_path / "models"
    voice_id = "sv_SE-nst-medium"

    # Stub curl so the script does not hit the network; it just creates files.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "curl"
    stub.write_text(
        '#!/usr/bin/env bash\n'
        'out=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  if [ "$1" = "-o" ]; then out="$2"; shift 2; continue; fi\n'
        '  shift\n'
        'done\n'
        'printf data > "$out"\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "TTS_SV_VOICE": voice_id,
        "PIPER_SV_ONNX_URL": "https://example.invalid/sv_SE-nst-medium.onnx",
        "PIPER_SV_JSON_URL": "https://example.invalid/sv_SE-nst-medium.onnx.json",
    }
    subprocess.run(
        ["bash", str(script), str(dest)],
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )

    expected_dir = dest / "piper" / voice_id
    assert (expected_dir / f"{voice_id}.onnx").is_file()
    assert (expected_dir / f"{voice_id}.onnx.json").is_file()

    # And that is exactly the path resolve_voice() probes.
    config = TTSConfig(
        enabled=True,
        local_only=True,
        model_dir=dest,
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        cache_max_gb=2,
        cache_eviction="lru",
        max_concurrent_jobs=1,
        max_chars_per_request=4000,
        allow_browser_fallback=False,
        allow_cloud_fallback=False,
        piper_command="/bin/echo",
        kokoro_command=None,
        sv_voice=voice_id,
    )
    voice = resolve_voice(config, "sv-SE")
    assert voice.model_path == expected_dir / f"{voice_id}.onnx"
    assert voice.available is True


def test_fetch_tts_models_rejects_custom_sv_voice_without_matching_urls(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts" / "fetch_tts_models.sh"
    dest = tmp_path / "models"

    result = subprocess.run(
        ["bash", str(script), str(dest)],
        check=False,
        env={
            "PATH": "/usr/bin:/bin",
            "TTS_SV_VOICE": "sv_SE-nst-medium",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires PIPER_SV_ONNX_URL and PIPER_SV_JSON_URL" in result.stderr
    assert not (dest / "piper" / "sv_SE-nst-medium").exists()


# --- AC5: TTS_ENABLED is forwarded into the API container -------------------


def test_compose_forwards_tts_enabled() -> None:
    compose = (REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    assert "TTS_ENABLED: ${TTS_ENABLED:-false}" in compose


def test_runtime_env_export_carries_tts_enabled() -> None:
    # The --env-file interpolation source (tmp/runtime.env) must carry
    # TTS_ENABLED so the compose interpolation is not always the default.
    export_script = (REPO_ROOT / "scripts" / "export_runtime_env.sh").read_text(encoding="utf-8")
    assert "TTS_ENABLED" in export_script
