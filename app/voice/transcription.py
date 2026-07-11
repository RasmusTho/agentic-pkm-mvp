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
from app.media.transcribe import run_asr


def transcribe_voice_wav(wav_bytes: bytes) -> dict[str, Any]:
    """Transcribe one voice query without persisting or governing its audio.

    ``run_asr`` is the sole Whisper/faster-whisper owner for every consumer.
    The temporary WAV exists only while that shared engine reads it and is
    unlinked even when local ASR fails.  Failures retain the established
    ``LocalAsrUnavailableError`` shape; there is no cloud fallback.
    """

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(wav_bytes)
        try:
            return run_asr(temp_path)
        except LocalAsrUnavailableError:
            raise
        except Exception as exc:
            raise LocalAsrUnavailableError("Shared local ASR engine is unavailable") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
