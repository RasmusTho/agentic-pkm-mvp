from __future__ import annotations

import re


_SWEDISH_RE = re.compile(
    r"[åäöÅÄÖ]|\b(och|det|att|som|för|inte|är|på|med|till|jag|du|vi)\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?", re.MULTILINE)


def normalize_language(language: str | None) -> str | None:
    if not language:
        return None
    value = language.strip().replace("_", "-").lower()
    if value in {"sv", "sv-se"}:
        return "sv-SE"
    if value in {"en", "en-us", "en_us"}:
        return "en-US"
    if value in {"en-gb", "en_uk", "en-uk", "en_gb"}:
        return "en-GB"
    return None


def detect_language(text: str, requested: str | None = None) -> str:
    normalized = normalize_language(requested)
    if normalized is not None:
        return normalized
    if _SWEDISH_RE.search(text):
        return "sv-SE"
    return "en-US"


def segment_by_language(text: str, requested: str | None = None) -> list[dict[str, str | int]]:
    forced = normalize_language(requested)
    parts = [match.group(0).strip() for match in _SENTENCE_RE.finditer(text) if match.group(0).strip()]
    if not parts and text.strip():
        parts = [text.strip()]

    segments: list[dict[str, str | int]] = []
    for index, part in enumerate(parts):
        language = forced or detect_language(part)
        segments.append({"index": index, "text": part, "language": language})
    return segments

