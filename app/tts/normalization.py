from __future__ import annotations

import re
import unicodedata


_WHITESPACE_RE = re.compile(r"\s+")
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_INLINE_CODE_RE = re.compile(r"`+([^`]*)`+")
_EMPHASIS_RE = re.compile(r"\*{1,3}([^*]+)\*{1,3}")
_UNDERSCORE_EMPHASIS_RE = re.compile(r"(?<!\w)_{1,2}([^_]+?)_{1,2}(?!\w)")
_MARKDOWN_SYNTAX_RE = re.compile(r"(^|\s)(#{1,6}|[-*]{1,3}|>{1,3})\s*", re.MULTILINE)


def normalize_tts_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text or "")
    normalized = normalized.replace("\u00a0", " ")
    normalized = _FENCED_CODE_RE.sub(" ", normalized)
    normalized = _LINK_RE.sub(r"\1", normalized)
    normalized = _INLINE_CODE_RE.sub(r"\1", normalized)
    normalized = _EMPHASIS_RE.sub(r"\1", normalized)
    normalized = _UNDERSCORE_EMPHASIS_RE.sub(r"\1", normalized)
    normalized = _MARKDOWN_SYNTAX_RE.sub(" ", normalized)
    normalized = normalized.replace("`", "").replace("*", "")
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def tts_normalization_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    if _FENCED_CODE_RE.search(text or ""):
        warnings.append("skipped code block")
    return warnings
