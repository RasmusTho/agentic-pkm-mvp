from __future__ import annotations

import shutil
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from app.tts.config import TTSConfig


@dataclass(frozen=True)
class TTSVoice:
    provider: str
    language: str
    voice_id: str
    model_path: Path
    config_path: Path | None = None
    voice_path: Path | None = None
    command: str | None = None
    available: bool = False
    unavailable_reason: str | None = None


def _command(configured: str | None, fallback: str) -> str | None:
    if configured:
        return configured
    return shutil.which(fallback)


def _kokoro_python_available() -> bool:
    try:
        import kokoro_onnx  # noqa: F401
        import numpy  # noqa: F401
    except Exception:
        return False
    return True


def resolve_voice(config: TTSConfig, language: str) -> TTSVoice:
    if language == "sv-SE":
        command = _command(config.piper_command, "piper")
        model_path = config.model_dir / "piper" / "sv_SE-nst-medium" / "sv_SE-nst-medium.onnx"
        config_path = model_path.with_suffix(model_path.suffix + ".json")
        missing: list[str] = []
        if command is None:
            missing.append("piper command")
        if not model_path.exists():
            missing.append(str(model_path))
        if not config_path.exists():
            missing.append(str(config_path))
        return TTSVoice(
            provider="piper",
            language="sv-SE",
            voice_id="sv_SE-nst-medium",
            model_path=model_path,
            config_path=config_path,
            command=command,
            available=not missing,
            unavailable_reason=", ".join(missing) if missing else None,
        )

    voice_id = "bf_emma" if language == "en-GB" else "af_heart"
    command = _command(config.kokoro_command, "kokoro")
    model_path = config.model_dir / "kokoro" / "kokoro-v1.0.int8.onnx"
    voice_path = config.model_dir / "kokoro" / "voices-v1.0.bin"
    missing = []
    if command is None and not _kokoro_python_available():
        missing.append("kokoro command or kokoro_onnx package")
    if not model_path.exists():
        missing.append(str(model_path))
    if not voice_path.exists():
        missing.append(str(voice_path))
    return TTSVoice(
        provider="kokoro",
        language=language,
        voice_id=voice_id,
        model_path=model_path,
        voice_path=voice_path,
        command=command,
        available=not missing,
        unavailable_reason=", ".join(missing) if missing else None,
    )


def synthesize_with_voice(
    text: str,
    voice: TTSVoice,
    output_path: Path,
    *,
    rate: float = 1.0,
) -> None:
    if not voice.available:
        raise RuntimeError(voice.unavailable_reason or "tts provider unavailable")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if voice.provider == "piper":
        if voice.command is None:
            raise RuntimeError(voice.unavailable_reason or "piper command unavailable")
        subprocess.run(
            [
                voice.command,
                "--model",
                str(voice.model_path),
                "--length_scale",
                str(1 / rate),
                "--output_file",
                str(output_path),
            ],
            input=text,
            text=True,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return
    if voice.provider == "kokoro":
        if voice.command is not None:
            subprocess.run(
                [
                    voice.command,
                    "--model",
                    str(voice.model_path),
                    "--voice",
                    str(voice.voice_path),
                    "--output",
                    str(output_path),
                    "--speed",
                    str(rate),
                    "--text",
                    text,
                    "--lang",
                    voice.language.lower(),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return
        _synthesize_with_kokoro_onnx(text, voice, output_path, rate=rate)
        return
    raise RuntimeError(f"unsupported tts provider: {voice.provider}")


def _synthesize_with_kokoro_onnx(
    text: str,
    voice: TTSVoice,
    output_path: Path,
    *,
    rate: float = 1.0,
) -> None:
    import numpy as np
    from kokoro_onnx import Kokoro

    if voice.voice_path is None:
        raise RuntimeError("kokoro voices path unavailable")
    lang = "en-gb" if voice.language == "en-GB" else "en-us"
    kokoro = Kokoro(str(voice.model_path), str(voice.voice_path))
    audio, sample_rate = kokoro.create(text, voice=voice.voice_id, speed=rate, lang=lang)
    samples = np.clip(audio, -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
