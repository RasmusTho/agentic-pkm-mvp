"""KA-04 tests for the `summary` extractor (schema-gated, fail-loud LLM output).

Covers `docs/KNOWLEDGE_ACQUISITION/EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md`'s summary-side
acceptance criterion: a malformed LLM response fails loud, item-scoped, and produces no extraction
artifact — no silent coercion, no partial acceptance. No network, no real LLM call: every test
here drives a deterministic stub through the same `complete=` injection seam
`constrained_completion` already exposes (KERNEL-07, `app/components/llm/constrained.py`).
"""

from __future__ import annotations

import json

import pytest

from app.knowledge_acquisition.extraction_registry import (
    ExtractionError,
    clear_registry,
    run_extractor,
)
from app.knowledge_acquisition.extractors import summary_extractor
from app.knowledge_acquisition.extractors.summary_extractor import (
    EXTRACTOR_ID,
    EXTRACTOR_VERSION,
    SUMMARY_SCHEMA_REF,
    run,
)

NORMALIZED_FIXTURE = {
    "stage": "normalize",
    "stage_version": 1,
    "source_content_identity": "sha256:summary-fixture-identity",
    "acquisition_method": "captions_manual",
    "language": "en",
    "language_detected": True,
    "quality_note": "creator-provided manual captions; highest fidelity of the acquisition methods",
    "chapters": [],
    "segments": [
        {"start": 0.0, "end": 2.0, "text": "Hello world", "speaker": None},
        {"start": 2.0, "end": 4.0, "text": "This is a transcript about testing.", "speaker": None},
    ],
}


def _stub_completion(raw: str):
    """Deterministic raw-completion stub — signature-compatible with `constrained.CompletionFn`."""

    calls: list[dict[str, object]] = []

    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        calls.append({"system": system, "user": user})
        return raw

    complete.calls = calls  # type: ignore[attr-defined]
    return complete


@pytest.fixture(autouse=True)
def _reset_registry():
    """Re-register the production `summary` extractor after each test's registry reset, so this
    module never leaks a stubbed spec into other test modules that rely on the real registration
    (importing `summary_extractor` performs `register()` once at import time; `clear_registry()`
    wipes that, so it must be restored)."""
    yield
    clear_registry()
    summary_extractor.register()


# ---------------------------------------------------------------------------
# AC: malformed LLM response fails loud, item-scoped, no artifact.
# ---------------------------------------------------------------------------


def test_schema_mismatch_fails_loud_no_artifact() -> None:
    valid = json.dumps({"summary": "A short transcript about testing.", "confidence": 0.8})
    payload = run(NORMALIZED_FIXTURE, complete=_stub_completion(valid))
    assert payload == {"summary": "A short transcript about testing.", "confidence": 0.8}

    malformed_outputs = [
        "",  # empty completion
        "this is not json at all",  # prose
        "[1, 2, 3]",  # JSON, but not an object
        '"just a string"',  # JSON scalar
        json.dumps({"summary": "no confidence field"}),  # missing required key
        json.dumps({"confidence": 0.5}),  # missing required key
        json.dumps({"summary": "", "confidence": 0.5}),  # summary fails minLength
        json.dumps({"summary": "ok", "confidence": 1.5}),  # confidence out of range
        json.dumps({"summary": "ok", "confidence": -0.1}),  # confidence out of range
        json.dumps({"summary": "ok", "confidence": "high"}),  # wrong type
        json.dumps({"summary": "ok", "confidence": 0.5, "extra": "field"}),  # additionalProperties
        # JSON embedded in prose must not be fished out (no regex extraction).
        'Sure! Here you go: {"summary": "ok", "confidence": 0.5} — hope that helps.',
    ]
    for raw in malformed_outputs:
        with pytest.raises(ExtractionError) as excinfo:
            run(NORMALIZED_FIXTURE, complete=_stub_completion(raw))
        assert excinfo.value.extractor_id == EXTRACTOR_ID
        assert excinfo.value.version == EXTRACTOR_VERSION


def test_schema_mismatch_via_registry_produces_no_extraction_result() -> None:
    """Enforcement: the failure is item-scoped through the production registry call site
    (`run_extractor`), not only the extractor function in isolation — and no `ExtractionResult`
    is cached/returned for the failed attempt."""
    summary_extractor.register(complete=_stub_completion("not json"))
    try:
        with pytest.raises(ExtractionError):
            run_extractor(EXTRACTOR_ID, NORMALIZED_FIXTURE)

        # A subsequent, valid completion still runs fresh (the failed attempt cached nothing).
        summary_extractor.register(
            complete=_stub_completion(json.dumps({"summary": "recovered", "confidence": 0.6}))
        )
        result = run_extractor(EXTRACTOR_ID, NORMALIZED_FIXTURE)
        assert result.replayed is False
        assert result.output == {"summary": "recovered", "confidence": 0.6}
    finally:
        summary_extractor.register()


def test_registered_schema_rejects_non_object_and_prose_wrapped_json() -> None:
    """Direct schema-registry check: the summary schema itself (not just the extractor's
    error-mapping) is strict — enum/type/shape all enforced by the shared jsonschema validator."""
    import jsonschema

    from app.components.llm.constrained import registered_schema

    schema = registered_schema(SUMMARY_SCHEMA_REF)
    valid_payload = {"summary": "ok", "confidence": 0.42}
    jsonschema.validate(valid_payload, schema)

    invalid_payloads = [
        {"summary": "ok"},
        {"confidence": 0.5},
        {"summary": "", "confidence": 0.5},
        {"summary": "ok", "confidence": 2.0},
        {"summary": "ok", "confidence": 0.5, "extra": True},
    ]
    for payload in invalid_payloads:
        with pytest.raises(jsonschema.exceptions.ValidationError):
            jsonschema.validate(payload, schema)


# ---------------------------------------------------------------------------
# Lineage / provenance carried through the extractor's registered spec.
# ---------------------------------------------------------------------------


def test_summary_extractor_lineage_via_registry() -> None:
    raw = json.dumps({"summary": "Deterministic stub summary.", "confidence": 0.9})
    summary_extractor.register(complete=_stub_completion(raw))
    try:
        result = run_extractor(EXTRACTOR_ID, NORMALIZED_FIXTURE)
    finally:
        summary_extractor.register()

    assert result.extractor_id == EXTRACTOR_ID
    assert result.extractor_version == EXTRACTOR_VERSION
    assert result.output == {"summary": "Deterministic stub summary.", "confidence": 0.9}
    assert result.source_content_identity == "sha256:summary-fixture-identity"
    # Model identity lineage: {provider, model} from the resolved LLMRoute — deterministic
    # under the test-session LLM_PROVIDER=mock default (conftest.py autouse fixture).
    assert set(result.model_identity.keys()) == {"provider", "model"}
    assert result.model_identity["provider"] == "mock"


def test_summary_coverage_is_complete_or_explicitly_declared() -> None:
    """The complete normalized transcript reaches the model; no silent 500-segment prefix."""
    segments = [
        {"start": float(index), "end": float(index + 1), "text": f"segment-{index}"}
        for index in range(501)
    ]
    normalized = {**NORMALIZED_FIXTURE, "segments": segments}
    completion = _stub_completion(
        json.dumps({"summary": "A complete-input summary.", "confidence": 0.7})
    )

    payload = run(normalized, complete=completion)

    assert payload == {"summary": "A complete-input summary.", "confidence": 0.7}
    assert "segment-0" in completion.calls[0]["user"]
    assert "segment-500" in completion.calls[0]["user"]


def test_no_network_no_real_llm_call() -> None:
    """Hard-constraint guard: calling `run()` without an injected stub must not attempt any real
    network call. With LLM_PROVIDER=mock (test-session default, `conftest.py` autouse fixture),
    the fabric resolves to the deterministic mock provider, which never opens a socket. The mock
    provider's generic canned response doesn't happen to satisfy this extractor's schema (no
    `summary` key), so the uninjected default path fails loud through the same schema-gate this
    module tests elsewhere — proving no hidden network path is taken and no artifact is produced
    for it, without needing to mock socket/HTTP internals directly."""
    with pytest.raises(ExtractionError):
        run(NORMALIZED_FIXTURE, complete=None)
