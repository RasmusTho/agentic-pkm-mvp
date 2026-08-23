"""Schema-gated, evidence-anchored synthesis extractor for YouTube Source Note v2."""

from __future__ import annotations

import math
from typing import Any, Mapping

from app.components.llm.constrained import (
    CompletionFn,
    ConstrainedCompletionError,
    constrained_completion,
    register_schema,
)
from app.components.llm.fabric import LLMTaskIntent
from app.components.llm.router import LLMRouter
from app.knowledge_acquisition.evidence_synthesis import (
    system_language_for,
    validate_generated_language,
    validate_resolvable_anchor,
)
from app.knowledge_acquisition.extraction_registry import (
    ExtractionError,
    ExtractorSpec,
    register_extractor,
)

EXTRACTOR_ID = "synthesis"
EXTRACTOR_VERSION = 1
TASK_KIND = "extract.synthesis"
SYNTHESIS_SCHEMA_REF = "knowledge_acquisition.extract.synthesis.v1"

_ANCHOR_SCHEMA = {
    "type": "object",
    "properties": {
        "segment_index": {"type": "integer", "minimum": 0},
        "start": {"type": "number"},
        "end": {"type": "number"},
    },
    "required": ["segment_index", "start", "end"],
    "additionalProperties": False,
}
_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "synthesis_sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "anchors": {"type": "array", "minItems": 1, "items": _ANCHOR_SCHEMA},
                },
                "required": ["text", "anchors"],
                "additionalProperties": False,
            },
        },
        "model_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["synthesis_sentences", "model_confidence"],
    "additionalProperties": False,
}
register_schema(SYNTHESIS_SCHEMA_REF, _SYNTHESIS_SCHEMA)


def _prompt(normalized: Mapping[str, Any]) -> tuple[str, str]:
    segments = normalized.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ExtractionError(
            extractor_id=EXTRACTOR_ID,
            version=EXTRACTOR_VERSION,
            reason="normalized.segments must be a non-empty list",
        )
    language = system_language_for(normalized.get("language"))
    lines: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            raise ExtractionError(
                extractor_id=EXTRACTOR_ID,
                version=EXTRACTOR_VERSION,
                reason=f"normalized.segments[{index}] must contain text",
            )
        lines.append(f"[{index} {segment.get('start')}..{segment.get('end')}] {segment['text']}")
    system = (
        "Return only JSON. Produce concise source-bound synthesis sentences. "
        f"Generated prose must be in {language}. Every sentence requires one or more exact "
        "segment_index/start/end anchors contained by the cited transcript segments."
    )
    return system, "Transcript:\n" + "\n".join(lines)


def run(normalized: Mapping[str, Any], *, complete: CompletionFn | None = None) -> dict[str, Any]:
    system, user = _prompt(normalized)
    try:
        payload = constrained_completion(
            SYNTHESIS_SCHEMA_REF,
            system=system,
            user=user,
            task_kind=TASK_KIND,
            complete=complete,
        )
    except ConstrainedCompletionError as exc:
        raise ExtractionError(
            extractor_id=EXTRACTOR_ID,
            version=EXTRACTOR_VERSION,
            reason=exc.reason,
        ) from exc

    confidence = payload.get("model_confidence")
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
    ):
        raise ExtractionError(
            extractor_id=EXTRACTOR_ID,
            version=EXTRACTOR_VERSION,
            reason="model_confidence must be a finite number between 0.0 and 1.0",
        )
    segments = normalized["segments"]
    expected_language = system_language_for(normalized.get("language"))
    for sentence in payload["synthesis_sentences"]:
        if not validate_generated_language(sentence["text"], expected_language):
            raise ExtractionError(
                extractor_id=EXTRACTOR_ID,
                version=EXTRACTOR_VERSION,
                reason="synthesis sentence language is not allowed by D6",
            )
        if not all(
            validate_resolvable_anchor(anchor, segments) for anchor in sentence["anchors"]
        ):
            raise ExtractionError(
                extractor_id=EXTRACTOR_ID,
                version=EXTRACTOR_VERSION,
                reason="synthesis anchor is not resolvable",
            )
    return payload


def _model_identity() -> dict[str, str]:
    route = LLMRouter().route(LLMTaskIntent(task_kind=TASK_KIND, json_schema_required=True))
    return {"provider": route.provider, "model": route.model}


def register(*, complete: CompletionFn | None = None) -> None:
    register_extractor(
        ExtractorSpec(
            extractor_id=EXTRACTOR_ID,
            version=EXTRACTOR_VERSION,
            input_content_type="transcript",
            output_schema_ref=SYNTHESIS_SCHEMA_REF,
            run=lambda normalized: run(normalized, complete=complete),
            model_identity=_model_identity,
        )
    )


register()
