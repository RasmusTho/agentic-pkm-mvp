"""Shared knowledge-acquisition test guards."""

from __future__ import annotations

from typing import Any

import pytest

from app.knowledge_acquisition import source_frames as frames_module


@pytest.fixture(autouse=True)
def _no_default_media_capture_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    """Acquisition attempts bounded frame capture by default (#5746).

    Tests that do not inject a ``SourceMediaCapture`` must never reach the production yt-dlp or
    ffmpeg boundaries; the refusal degrades capture to timestamps-only like unavailable media.
    Tests that exercise those boundaries replace them with their own fakes.
    """

    def _refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("test media boundary: real yt-dlp/ffmpeg capture is disabled in tests")

    monkeypatch.setattr(frames_module, "_youtube_dl", _refuse)
    monkeypatch.setattr(frames_module, "_run_ffmpeg", _refuse)
