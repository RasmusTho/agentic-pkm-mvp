"""The `summary` extractor (KA-04): one worked example proving the extraction registry contract.

Per `docs/KNOWLEDGE_ACQUISITION/EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md`: an LLM call over a
`normalized` transcript, routed per `docs/LLM_ROUTING.md`, whose output is schema-validated at the
boundary before it is ever returned — a schema mismatch is an explicit, item-scoped failure, never
a silent default (the correctness kernel's typed-LLM-boundary posture,
`STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN` in spirit). This extractor is proposal-class cognition
only (`docs/CAPABILITY_CONTRACT_MODEL.md`): it produces a schema-shaped `{"summary", "confidence"}`
payload and writes nothing — no vault write, no candidate assembly (KA-05), no governance-bearing
action of any kind.

Reuses the existing typed-LLM-boundary seam, `app.components.llm.constrained`
(`constrained_completion` / `register_schema` / `ConstrainedCompletionError`), rather than a new
client: it is the repo's one schema-gated completion boundary (KERNEL-07, #2769; already proven
by `app/components/llm/intent_classifier.py` and `app/planner/provider.py`). The raw completion
call is injectable (`complete=`) exactly as `constrained_completion` already supports, so tests
drive fake completions — no network, no real LLM call, in this extractor's tests.

Registers itself with the extraction registry (`app.knowledge_acquisition.extraction_registry`)
on import so the pipeline's one call site (`run_extractor("summary", normalized)`) can run it
without any pipeline-side import of this module.
"""

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
from app.knowledge_acquisition.extraction_registry import (
    ExtractionError,
    ExtractorSpec,
    register_extractor,
)

EXTRACTOR_ID = "summary"
EXTRACTOR_VERSION = 2
TASK_KIND = "extract.summary"

#: Registered schema for the summary completion (KERNEL-07 registry,
#: `app/components/llm/constrained.py`). The model must return exactly one JSON object of this
#: shape; anything else — including prose-wrapped JSON — is a validation failure.
SUMMARY_SCHEMA_REF = "knowledge_acquisition.extract.summary.v1"

_SUMMARY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["summary", "confidence"],
    "additionalProperties": False,
}

register_schema(SUMMARY_SCHEMA_REF, _SUMMARY_SCHEMA)

_SYSTEM_PROMPT = (
    "You summarize a transcript. Return ONLY a JSON object, no commentary: "
    '{"summary": "<free text>", "confidence": <0.0-1.0>}'
)

def _build_user_prompt(normalized: Mapping[str, Any]) -> str:
    segments = normalized.get("segments") or []
    # Every normalized segment is included. A prefix cap would make a partial summary appear to
    # cover the full transcript unless its exact window were carried into the rendered note.
    lines = [
        str(seg.get("text", "")).strip()
        for seg in segments
        if isinstance(seg, Mapping)
    ]
    transcript_text = "\n".join(line for line in lines if line)
    return f"Transcript:\n{transcript_text}\n\nSummarize the transcript above."


def _model_identity() -> dict[str, str]:
    """The model identity lineage requires: `{provider, model}` from the resolved route.

    Uses the same `LLMRouter` the fabric's `get_chat_client` uses internally, so the identity
    reported here always matches the route the completion actually ran against.
    """
    router = LLMRouter()
    route = router.route(LLMTaskIntent(task_kind=TASK_KIND, json_schema_required=True))
    return {"provider": route.provider, "model": route.model}


def run(normalized: Mapping[str, Any], *, complete: CompletionFn | None = None) -> dict[str, Any]:
    """Run the summary extractor against a `normalized` transcript artifact.

    Returns the schema-validated `{"summary": str, "confidence": float}` payload. Raises
    `ExtractionError` (item-scoped, loud) on any non-conforming model output — no silent
    coercion, no partial acceptance, no extraction artifact for a failed run.

    `complete` is the same injection seam `constrained_completion` already exposes: tests supply
    a deterministic stub; production leaves it `None` and the real chat client is resolved
    per `docs/LLM_ROUTING.md`.
    """
    try:
        payload = constrained_completion(
            SUMMARY_SCHEMA_REF,
            system=_SYSTEM_PROMPT,
            user=_build_user_prompt(normalized),
            task_kind=TASK_KIND,
            complete=complete,
        )
    except ConstrainedCompletionError as exc:
        raise ExtractionError(
            extractor_id=EXTRACTOR_ID, version=EXTRACTOR_VERSION, reason=exc.reason
        ) from exc
    confidence = payload["confidence"]
    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
        or not math.isfinite(confidence)
    ):
        raise ExtractionError(
            extractor_id=EXTRACTOR_ID,
            version=EXTRACTOR_VERSION,
            reason="confidence must be a finite number between 0.0 and 1.0",
        )
    return {"summary": payload["summary"], "confidence": confidence}


def _make_spec(*, complete: CompletionFn | None = None) -> ExtractorSpec:
    return ExtractorSpec(
        extractor_id=EXTRACTOR_ID,
        version=EXTRACTOR_VERSION,
        input_content_type="transcript",
        output_schema_ref=SUMMARY_SCHEMA_REF,
        run=lambda normalized: run(normalized, complete=complete),
        model_identity=_model_identity,
    )


def register(*, complete: CompletionFn | None = None) -> None:
    """Register the `summary` extractor with the shared extraction registry.

    Called at import time for production wiring (real fabric route). Tests that need a stubbed
    completion call this again with `complete=<stub>` to re-register a test-scoped spec — the
    registry's `register_extractor` treats re-registration under the same id as a replace, so
    tests never have to reach into registry internals.
    """
    register_extractor(_make_spec(complete=complete))


# Production registration: the pipeline's one call site (`run_extractor("summary", ...)`) can
# resolve this extractor without ever importing this module directly.
register()


__all__ = [
    "EXTRACTOR_ID",
    "EXTRACTOR_VERSION",
    "SUMMARY_SCHEMA_REF",
    "TASK_KIND",
    "register",
    "run",
]
