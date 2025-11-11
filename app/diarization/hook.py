from __future__ import annotations

import os
from typing import Dict, Iterable, List

import httpx


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ensure_segments(payload: Dict[str, any]) -> List[Dict[str, str]]:
    segments = payload.get("segments") or []
    if segments:
        return [
            {"speaker": str(seg.get("speaker", "spk_0")), "text": str(seg.get("text", ""))}
            for seg in segments
        ]
    text = payload.get("text", "")
    return [{"speaker": "spk_0", "text": str(text)}]


class BaseDiarizer:
    def segment(self, payload: Dict[str, any]) -> List[Dict[str, str]]:
        raise NotImplementedError


class NullDiarizer(BaseDiarizer):
    def segment(self, payload: Dict[str, any]) -> List[Dict[str, str]]:
        return _ensure_segments(payload)


class MockDiarizer(BaseDiarizer):
    def segment(self, payload: Dict[str, any]) -> List[Dict[str, str]]:
        text = str(payload.get("text", "")).strip()
        if not text:
            return [{"speaker": "spk_0", "text": ""}]
        sentences = [part.strip() for part in text.replace("?", ".").replace("!", ".").split(".") if part.strip()]
        if len(sentences) < 2:
            sentences = text.splitlines()
        if len(sentences) < 2:
            sentences = [text[: len(text) // 2], text[len(text) // 2 :]]
        segments = []
        for idx, chunk in enumerate(sentences):
            segments.append({"speaker": f"spk_{idx % 2}", "text": chunk.strip()})
        return segments


class ExternalDiarizer(BaseDiarizer):
    def __init__(self, endpoint: str | None = None, timeout: float | None = None) -> None:
        self.endpoint = endpoint or os.getenv("DIARIZE_HTTP_ENDPOINT", "").strip()
        if not self.endpoint:
            raise RuntimeError("DIARIZE_HTTP_ENDPOINT is required for external diarizer")
        self.timeout = timeout or float(os.getenv("DIARIZE_HTTP_TIMEOUT", "3.0"))

    def segment(self, payload: Dict[str, any]) -> List[Dict[str, str]]:
        try:
            resp = httpx.post(
                self.endpoint,
                json={"text": payload.get("text", ""), "segments": payload.get("segments")},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json() or {}
            segments = data.get("segments") or []
            if not segments:
                raise RuntimeError("empty segmentation response")
            return [
                {"speaker": str(seg.get("speaker", "spk_0")), "text": str(seg.get("text", ""))}
                for seg in segments
            ]
        except Exception:
            return MockDiarizer().segment(payload)


def _select_provider(name: str | None = None) -> BaseDiarizer:
    provider = (name or os.getenv("DIARIZE_PROVIDER", "mock")).strip().lower()
    if provider in ("none", "", "off"):
        return NullDiarizer()
    if provider in ("mock", "demo"):
        return MockDiarizer()
    if provider in ("external", "http"):
        return ExternalDiarizer()
    return NullDiarizer()


def apply_diarization(payload: Dict[str, any]) -> Dict[str, any]:
    if not _truthy(os.getenv("DIARIZE_ENABLE")):
        return payload
    provider = _select_provider()
    segments = provider.segment(payload)
    result = dict(payload)
    result["segments"] = segments
    if not result.get("text") and segments:
        result["text"] = " ".join(seg["text"] for seg in segments).strip()
    return result


__all__ = ["apply_diarization"]
