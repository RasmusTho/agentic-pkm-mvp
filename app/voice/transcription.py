"""Ephemeral voice-ask transcription through the shared local ASR engine.

This module deliberately owns only the voice-side temporary-file lifetime.
The model and its cache remain owned by :mod:`app.media.transcribe`; voice
queries must not enter Heimdal's governed capture/raw-read path.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from app.heimdal.asr_stage import LocalAsrUnavailableError
from app.media.transcribe import ffmpeg_to_wav
from app.media.transcribe import run_asr


def transcribe_voice_wav(wav_bytes: bytes) -> dict[str, Any]:
    """Transcribe one voice query without persisting or governing its audio.

    ``run_asr`` is the sole Whisper/faster-whisper owner for every consumer.
    The temporary WAV exists only while that shared engine reads it and is
    unlinked even when local ASR fails.  Failures retain the established
    ``LocalAsrUnavailableError`` shape; there is no cloud fallback.
    """

    return transcribe_voice_audio(wav_bytes, suffix=".wav")


def transcribe_voice_audio(audio_bytes: bytes, *, suffix: str = ".wav") -> dict[str, Any]:
    """Decode one supported client container then call the single ASR owner.

    The source and decoded WAV are both temporary query material.  This is
    intentionally separate from Heimdal's raw-read/capture lifecycle.
    """

    source_path: Path | None = None
    wav_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            source_path = Path(handle.name)
            handle.write(audio_bytes)
        wav_path = source_path if suffix == ".wav" else ffmpeg_to_wav(source_path)
        try:
            return run_asr(wav_path)
        except LocalAsrUnavailableError:
            raise
        except Exception as exc:
            raise LocalAsrUnavailableError("Shared local ASR engine is unavailable") from exc
    finally:
        if wav_path is not None and wav_path != source_path:
            wav_path.unlink(missing_ok=True)
        if source_path is not None:
            source_path.unlink(missing_ok=True)
