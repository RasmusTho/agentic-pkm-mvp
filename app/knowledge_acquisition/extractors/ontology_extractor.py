"""Gated, proposal-only ontology extractor for YouTube Source Note v2 (YSNV2-08).

The deterministic relevance gate in ``ontology_proposals`` runs first. A failed gate returns an
empty, gate-bearing proposal output without any model call, so the ontology section is omitted.
A passing gate asks the model for anchored elements; the schema gives the model no ``status`` or
authority field, and each accepted element is stamped ``proposed`` locally. Elements that fail
anchoring, verbatim source-definition, or D6 checks are dropped and reported, never softened.

The extractor returns data only; it never writes concepts, relations, notes, or review state.
It is registered for explicit selection and is not part of the default extractor set.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.components.llm.constrained import CompletionFn, ConstrainedCompletionError, constrained_completion, register_schema
from app.components.llm.fabric import LLMTaskIntent
from app.components.llm.router import LLMRouter
from app.knowledge_acquisition.evidence_synthesis import system_language_for
from app.knowledge_acquisition.extraction_registry import ExtractionError, ExtractorSpec, register_extractor
from app.knowledge_acquisition.ontology_proposals import (
    ARTIFACT_CLASS,
    DEFAULT_GATE_CONFIG,
    ELEMENT_KINDS,
    OntologyGateConfig,
    evaluate_ontology_gate,
    validate_ontology_element,
)

EXTRACTOR_ID = "ontology"
EXTRACTOR_VERSION = 1
TASK_KIND = "extract.ontology"
ONTOLOGY_SCHEMA_REF = "knowledge_acquisition.extract.ontology.v1"

_ANCHOR_SCHEMA = {
    "type": "object",
    "properties": {"segment_index": {"type": "integer", "minimum": 0}, "start": {"type": "number"}, "end": {"type": "number"}},
    "required": ["segment_index", "start", "end"],
    "additionalProperties": False,
}
_ONTOLOGY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(ELEMENT_KINDS)},
                    "source_definition": {"type": ["string", "null"]},
                    "system_paraphrase": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "anchors": {"type": "array", "minItems": 1, "items": _ANCHOR_SCHEMA},
                },
                "required": ["kind", "source_definition", "system_paraphrase", "confidence", "anchors"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["elements"],
    "additionalProperties": False,
}
register_schema(ONTOLOGY_SCHEMA_REF, _ONTOLOGY_SCHEMA)


def _prompt(normalized: Mapping[str, Any]) -> tuple[str, str]:
    segments = normalized["segments"]
    language = system_language_for(normalized.get("language"))
    lines = [f"[{index} {segment.get('start')}..{segment.get('end')}] {segment['text']}" for index, segment in enumerate(segments)]
    system = (
        "Return only JSON. Propose ontology elements (concept, relation, distinction, mapping, "
        "alternative_interpretation, competency_question) that the transcript itself evidences. "
        "source_definition is null or an exact verbatim span of the anchored transcript text in its "
        f"original language, never a translation. system_paraphrase must be in {language} and must "
        "not repeat source_definition. Every element requires exact segment_index/start/end anchors. "
        "These are proposals only; do not assert canonical standing."
    )
    return system, "Transcript:\n" + "\n".join(lines)


def run(
    normalized: Mapping[str, Any],
    *,
    complete: CompletionFn | None = None,
    gate_config: OntologyGateConfig = DEFAULT_GATE_CONFIG,
) -> dict[str, Any]:
    segments = normalized.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason="normalized.segments must be a non-empty list")
    for index, segment in enumerate(segments):
        if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
            raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason=f"normalized.segments[{index}] must contain text")
    gate = evaluate_ontology_gate(normalized, config=gate_config)
    output: dict[str, Any] = {"artifact_class": ARTIFACT_CLASS, "gate": gate.as_dict(), "proposals": [], "dropped": []}
    if not gate.passed:
        return output
    system, user = _prompt(normalized)
    try:
        payload = constrained_completion(ONTOLOGY_SCHEMA_REF, system=system, user=user, task_kind=TASK_KIND, complete=complete)
    except ConstrainedCompletionError as exc:
        raise ExtractionError(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason=exc.reason) from exc
    for element in payload["elements"]:
        proposal, reason = validate_ontology_element(element, normalized)
        if proposal is None:
            output["dropped"].append({"kind": element.get("kind"), "reason": reason})
        else:
            output["proposals"].append(proposal)
    return output


def _model_identity() -> dict[str, str]:
    route = LLMRouter().route(LLMTaskIntent(task_kind=TASK_KIND, json_schema_required=True))
    return {"provider": route.provider, "model": route.model}


def register(*, complete: CompletionFn | None = None) -> None:
    register_extractor(ExtractorSpec(extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, input_content_type="transcript", output_schema_ref=ONTOLOGY_SCHEMA_REF, run=lambda normalized: run(normalized, complete=complete), model_identity=_model_identity))


register()
