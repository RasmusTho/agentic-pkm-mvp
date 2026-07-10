"""Read-only Daily Briefing adapter for the existing local TTS planner."""

from __future__ import annotations

from typing import Any

from app.tts.config import TTSConfig
from app.tts.planning import build_tts_plan


def build_briefing_speech_plan(
    *, briefing_text: str, config: TTSConfig, rate: float = 1.0
) -> dict[str, Any]:
    """Plan a briefing without changing TTS segmentation or voice routing."""

    return build_tts_plan(text=briefing_text, config=config, rate=rate)

