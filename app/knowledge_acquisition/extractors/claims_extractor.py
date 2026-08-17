"""Schema-gated, source-bound claims extractor for YouTube Source Note v2."""

from __future__ import annotations

from typing import Any, Mapping

from app.components.llm.constrained import CompletionFn, ConstrainedCompletionError, constrained_completion, register_schema
from app.components.llm.fabric import LLMTaskIntent
from app.components.llm.router import LLMRouter
from app.knowledge_acquisition.evidence_synthesis import system_language_for
from app.knowledge_acquisition.extraction_registry import ExtractionError, ExtractorSpec, register_extractor

EXTRACTOR_ID = "claims"
EXTRACTOR_VERSION = 1
TASK_KIND = "extract.claims"
CLAIMS_SCHEMA_REF = "knowledge_acquisition.extract.claims.v1"

_ANCHOR_SCHEMA = {
    "type": "object",
    "properties": {"segment_index": {"type": "integer", "minimum": 0}, "start": {"type": "number"}, "end": {"type": "number"}},
    "required": ["segment_index", "start", "end"],
    "additionalProperties": False,
}
_CLAIMS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {"type": "object", "properties": {"source_wording": {"type": "string", "minLength": 1}, "system_paraphrase": {"type": "string", "minLength": 1}, "anchors": {"type": "array", "minItems": 1, "items": _ANCHOR_SCHEMA}}, "required": ["source_wording", "system_paraphrase", "anchors"], "additionalProperties": False}}},
    "required": ["claims"],
    "additionalProperties": False,
}
register_schema(CLAIMS_SCHEMA_REF, _CLAIMS_SCHEMA)


def _prompt(normalized: Mapping[str, Any]) -> tuple[str, str]:
    segments = normalized.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason="normalized.segments must be a non-empty list")
    language = system_language_for(normalized.get("language"))
    lines: list[str] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason=f"normalized.segments[{index}] must contain text")
        lines.append(f"[{index} {segment.get('start')}..{segment.get('end')}] {segment['text']}")
    system = (
        "Return only JSON. Extract source-bound claims. source_wording must preserve the original source language; "
        f"system_paraphrase must be in {language} and must not repeat source_wording verbatim. "
        "Every claim requires one or more exact segment_index/start/end anchors."
    )
    return system, "Transcript:\n" + "\n".join(lines)


def run(normalized: Mapping[str, Any], *, complete: CompletionFn | None = None) -> dict[str, Any]:
    system, user = _prompt(normalized)
    try:
        payload = constrained_completion(CLAIMS_SCHEMA_REF, system=system, user=user, task_kind=TASK_KIND, complete=complete)
    except ConstrainedCompletionError as exc:
        raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason=exc.reason) from exc
    segments = normalized["segments"]
    for claim in payload["claims"]:
        if claim["source_wording"].strip() == claim["system_paraphrase"].strip():
            raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason="source_wording and system_paraphrase must remain distinct")
        for anchor in claim["anchors"]:
            index = anchor["segment_index"]
            if index >= len(segments) or anchor["start"] > anchor["end"]:
                raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason="claim anchor is not resolvable")
    return payload


def _model_identity() -> dict[str, str]:
    route = LLMRouter().route(LLMTaskIntent(task_kind=TASK_KIND, json_schema_required=True))
    return {"provider": route.provider, "model": route.model}


def register(*, complete: CompletionFn | None = None) -> None:
    register_extractor(ExtractorSpec(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, input_content_type="transcript", output_schema_ref=CLAIMS_SCHEMA_REF, run=lambda normalized: run(normalized, complete=complete), model_identity=_model_identity))


register()
