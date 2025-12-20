from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple
from uuid import uuid4

try:
    from faster_whisper import WhisperModel  # type: ignore
except Exception:  # pragma: no cover
    WhisperModel = None  # type: ignore
try:
    from yt_dlp import YoutubeDL  # type: ignore
except ImportError:  # pragma: no cover
    YoutubeDL = None  # type: ignore

from app.diarization.hook import apply_diarization
from app.index.outbox import append_jsonl
from app.obs.log import span, with_trace_id

_MODEL_CACHE: Dict[Tuple[str, str], WhisperModel] = {}


def download_audio(source: str) -> Path:
    """
    Download a YouTube/audio URL or validate an existing file path.
    Returns the local path to the downloaded file.
    """
    if source.startswith(("http://", "https://")):
        if YoutubeDL is None:
            raise RuntimeError("yt-dlp är inte installerat; installera yt_dlp eller använd lokala filer.")
        out_dir = Path(os.getenv("TRANSCRIBE_CACHE_DIR", "./tmp/audio"))
        out_dir.mkdir(parents=True, exist_ok=True)
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "noprogress": True,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(source, download=True)
            filename = ydl.prepare_filename(info)
        return Path(filename)

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Audio source not found: {source}")
    return path


def ffmpeg_to_wav(path: Path) -> Path:
    """
    Convert arbitrary audio file to wav mono 16kHz via ffmpeg.
    """
    output = path.with_suffix(".wav")
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(path),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return output


def _get_model() -> WhisperModel:
    if WhisperModel is None:
        raise RuntimeError("faster-whisper saknas; installera dependency eller använd LLM_PROVIDER=mock.")
    name = os.getenv("ASR_MODEL", "base")
    device = os.getenv("ASR_DEVICE", "auto")
    key = (name, device)
    if key not in _MODEL_CACHE:
        _MODEL_CACHE[key] = WhisperModel(name, device=device, compute_type="int8")
    return _MODEL_CACHE[key]


def run_asr(path_wav: Path, *, model_env: str = "ASR_MODEL") -> Dict[str, Any]:
    if WhisperModel is None:
        raise RuntimeError("faster-whisper saknas; installera dependency eller använd LLM_PROVIDER=mock.")
    model = _get_model()
    segments_iter, info = model.transcribe(str(path_wav), beam_size=5)
    segments: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    for seg in segments_iter:
        chunk = {
            "start": float(getattr(seg, "start", 0.0)),
            "end": float(getattr(seg, "end", 0.0)),
            "text": (getattr(seg, "text", "") or "").strip(),
        }
        if chunk["text"]:
            text_parts.append(chunk["text"])
        segments.append(chunk)
    return {
        "text": " ".join(text_parts).strip(),
        "segments": segments,
        "language": getattr(info, "language", None) or "unknown",
    }


def _record_outbox(source: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    entry = {
        "object_id": str(uuid4()),
        "kind": "transcript",
        "source_ref": source,
        "payload": payload,
    }
    append_jsonl(entry)
    return entry


def _is_temporary(path: Path) -> bool:
    tmp_dir = Path(tempfile.gettempdir())
    try:
        path.resolve().relative_to(tmp_dir)
        return True
    except Exception:
        return False


@span("transcribe")
def transcribe_source(source: str, *, trace_id: str | None = None) -> Dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    audio_path = download_audio(source)
    wav_path = ffmpeg_to_wav(audio_path)
    asr_output = run_asr(wav_path)
    asr_output = apply_diarization(asr_output)
    record = _record_outbox(source, asr_output)
    record["trace_id"] = trace_id
    # Clean up temporary wav to save disk
    if _is_temporary(wav_path):
        try:
            wav_path.unlink()
        except Exception:
            pass
    return record


__all__ = [
    "download_audio",
    "ffmpeg_to_wav",
    "run_asr",
    "transcribe_source",
]
