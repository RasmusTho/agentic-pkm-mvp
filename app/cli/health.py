from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path
from typing import Any, Dict

import httpx

from app.obs.log import span, with_trace_id


def _result(ok: bool, detail: str, *, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {"ok": ok, "detail": detail}
    if data:
        out["data"] = data
    return out


def _check_ffmpeg() -> Dict[str, Any]:
    ok = shutil.which("ffmpeg") is not None
    detail = "ffmpeg hittades i PATH" if ok else "ffmpeg saknas i PATH"
    return _result(ok, detail)


def _check_yt_dlp() -> Dict[str, Any]:
    try:
        importlib.import_module("yt_dlp")
        return _result(True, "yt-dlp kan importeras")
    except Exception as exc:  # pragma: no cover - import side-effects differ per env
        return _result(False, f"yt-dlp import misslyckades: {exc!s}")


def _check_outbox_path() -> Dict[str, Any]:
    path = Path(os.environ.get("INDEX_OUTBOX_PATH", "./tmp/index-outbox.jsonl")).expanduser()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8"):
            ...
        return _result(True, f"Skrivåtkomst bekräftad: {path}")
    except Exception as exc:
        return _result(False, f"Kan inte skriva till {path}: {exc!s}")


def _check_ollama() -> Dict[str, Any]:
    provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
    if provider != "ollama":
        return _result(True, "Hoppar över Ollama-koll (LLM_PROVIDER != ollama)", data={"skipped": True})
    base = os.environ.get("OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
    try:
        resp = httpx.get(f"{base}/api/tags", timeout=float(os.environ.get("LLM_TIMEOUT", "5")))
        resp.raise_for_status()
        data = resp.json()
        return _result(True, f"Ollama nåddes ({base})", data={"models": [m.get("name") for m in data.get("models", [])] if isinstance(data, dict) else None})
    except Exception as exc:
        return _result(False, f"Ollama svarade inte ({base}): {exc!s}")


@span("health.check")
def run_health(*, trace_id: str | None = None, **kwargs: Any) -> Dict[str, Any]:
    trace_id = with_trace_id(trace_id)
    checks = {
        "ffmpeg": _check_ffmpeg(),
        "yt_dlp": _check_yt_dlp(),
        "index_outbox": _check_outbox_path(),
        "ollama": _check_ollama(),
    }
    ok = all(item.get("ok") for item in checks.values())
    return {"ok": bool(ok), "checks": checks, "trace_id": trace_id}


__all__ = ["run_health"]
