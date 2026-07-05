"""KA-04 tests for the open extraction registry (`normalized` -> `extracted`).

Covers `docs/KNOWLEDGE_ACQUISITION/EXTRACTION_REGISTRY_AND_SUMMARY_EXTRACTOR.md`'s registry-side
acceptance criteria: register+run through the production pipeline call site without touching
pipeline/plugin code, lineage stamping (extractor id/version/model identity), and idempotent
version-replacement semantics. No network, no real LLM calls — every extractor run in this module
is a deterministic in-process stub via the existing `constrained_completion(complete=...)`
injection seam.
"""

from __future__ import annotations

import json

import pytest

from app.knowledge_acquisition.extraction_registry import (
    ExtractionError,
    ExtractionResult,
    ExtractorSpec,
    UnknownExtractorError,
    clear_registry,
    register_extractor,
    registered_extractor,
    registered_extractor_ids,
    run_extractor,
)

NORMALIZED_FIXTURE = {
    "stage": "normalize",
    "stage_version": 1,
    "source_content_identity": "sha256:fixture-content-identity",
    "acquisition_method": "captions_manual",
    "language": "en",
    "language_detected": True,
    "quality_note": "creator-provided manual captions; highest fidelity of the acquisition methods",
    "chapters": [],
    "segments": [
        {"start": 0.0, "end": 2.0, "text": "Hello world", "speaker": None},
        {"start": 2.0, "end": 4.0, "text": "This is a transcript.", "speaker": None},
    ],
}


@pytest.fixture(autouse=True)
def _reset_registry():
    """Every test gets a clean registry/result cache — registration and idempotency state must
    not leak between tests (this module registers ad hoc fixture extractors, not the production
    `summary` extractor, so it must not pollute or be polluted by other test modules' state)."""
    clear_registry()
    yield
    clear_registry()


def _make_echo_extractor(*, extractor_id: str = "fixture_echo", version: int = 1, calls: list | None = None) -> ExtractorSpec:
    """A trivial extractor used purely to exercise registry mechanics (not schema validation,
    which is the summary extractor's own concern — covered in test_summary_extractor.py)."""
    call_log = calls if calls is not None else []

    def _run(normalized):
        call_log.append(normalized["source_content_identity"])
        return {"echoed_segment_count": len(normalized.get("segments") or [])}

    return ExtractorSpec(
        extractor_id=extractor_id,
        version=version,
        input_content_type="transcript",
        output_schema_ref="fixture.echo.v1",
        run=_run,
        model_identity=lambda: {"provider": "mock", "model": "fixture-model"},
    )


# ---------------------------------------------------------------------------
# AC: register + run via the production pipeline call site, no pipeline/plugin
# code touched to add an extractor.
# ---------------------------------------------------------------------------


def test_register_and_run_via_pipeline_callsite() -> None:
    register_extractor(_make_echo_extractor())

    # The "pipeline call site" is exactly run_extractor(extractor_id, normalized) — a caller
    # that only knows the extractor_id, never importing the extractor module directly.
    result = run_extractor("fixture_echo", NORMALIZED_FIXTURE)

    assert isinstance(result, ExtractionResult)
    assert result.output == {"echoed_segment_count": 2}
    assert result.extractor_id == "fixture_echo"
    assert "fixture_echo" in registered_extractor_ids()

    # Registering a second, independent extractor requires zero changes to run_extractor's
    # signature or body, and zero interaction with the first extractor's spec — proving the
    # registry is open (adding extractor #2 touches nothing else).
    second_calls: list = []
    register_extractor(_make_echo_extractor(extractor_id="fixture_second", calls=second_calls))
    second_result = run_extractor("fixture_second", NORMALIZED_FIXTURE)
    assert second_result.extractor_id == "fixture_second"
    assert second_calls == ["sha256:fixture-content-identity"]

    # The first extractor is untouched by the second's registration.
    assert registered_extractor("fixture_echo").version == 1


def test_unregistered_extractor_id_fails_loud() -> None:
    with pytest.raises(UnknownExtractorError):
        run_extractor("no_such_extractor", NORMALIZED_FIXTURE)


# ---------------------------------------------------------------------------
# AC: lineage carries extractor id, version, and model identity.
# ---------------------------------------------------------------------------


def test_lineage_stamped() -> None:
    register_extractor(_make_echo_extractor())
    result = run_extractor("fixture_echo", NORMALIZED_FIXTURE)

    assert result.extractor_id == "fixture_echo"
    assert result.extractor_version == 1
    assert result.model_identity == {"provider": "mock", "model": "fixture-model"}
    assert result.source_content_identity == "sha256:fixture-content-identity"
    assert result.stage == "extracted"
    assert result.created_at is not None

    as_dict = result.as_dict()
    assert as_dict["extractor_id"] == "fixture_echo"
    assert as_dict["extractor_version"] == 1
    assert as_dict["model_identity"] == {"provider": "mock", "model": "fixture-model"}
    assert as_dict["source_content_identity"] == "sha256:fixture-content-identity"
    # Deterministic, JSON-serializable projection.
    json.dumps(as_dict)


def test_lineage_requires_source_content_identity() -> None:
    register_extractor(_make_echo_extractor())
    malformed = {k: v for k, v in NORMALIZED_FIXTURE.items() if k != "source_content_identity"}
    with pytest.raises(ExtractionError):
        run_extractor("fixture_echo", malformed)


# ---------------------------------------------------------------------------
# AC: same input + same version -> idempotent no-op; bumped version -> replaces.
# ---------------------------------------------------------------------------


def test_version_replacement_semantics() -> None:
    calls: list = []
    register_extractor(_make_echo_extractor(calls=calls))

    first = run_extractor("fixture_echo", NORMALIZED_FIXTURE)
    assert first.replayed is False
    assert calls == ["sha256:fixture-content-identity"]

    # Re-running the same extractor id + version over the SAME source content identity is an
    # idempotent no-op: the extractor's run() is not invoked again.
    second = run_extractor("fixture_echo", NORMALIZED_FIXTURE)
    assert second.replayed is True
    assert calls == ["sha256:fixture-content-identity"], "run() must not be invoked again on no-op replay"
    assert second.output == first.output
    assert second.extractor_id == first.extractor_id
    assert second.extractor_version == first.extractor_version

    # A different (bumped) version for the SAME source content identity always runs fresh and
    # replaces — never treated as the prior version's no-op.
    def _run_v2(normalized):
        calls.append(normalized["source_content_identity"])
        return {"echoed_segment_count": len(normalized.get("segments") or []), "bumped": True}

    register_extractor(
        ExtractorSpec(
            extractor_id="fixture_echo",
            version=2,
            input_content_type="transcript",
            output_schema_ref="fixture.echo.v1",
            run=_run_v2,
            model_identity=lambda: {"provider": "mock", "model": "fixture-model-v2"},
        )
    )
    bumped = run_extractor("fixture_echo", NORMALIZED_FIXTURE)
    assert bumped.replayed is False
    assert bumped.extractor_version == 2
    assert bumped.output["bumped"] is True
    assert calls == ["sha256:fixture-content-identity", "sha256:fixture-content-identity"]

    # A different source content identity is a distinct cache key: it always runs fresh even at
    # the same (bumped) version, and does not disturb the first identity's cached v2 result.
    other_fixture = dict(NORMALIZED_FIXTURE, source_content_identity="sha256:different-identity")
    third = run_extractor("fixture_echo", other_fixture)
    assert third.replayed is False
    assert calls[-1] == "sha256:different-identity"

    replay_of_first_v2 = run_extractor("fixture_echo", NORMALIZED_FIXTURE)
    assert replay_of_first_v2.replayed is True
    assert replay_of_first_v2.extractor_version == 2


def test_failed_run_is_not_cached_as_a_no_op() -> None:
    """A failed extraction produces no artifact — a subsequent call must not be treated as an
    idempotent replay of a nonexistent success (fail-loud, item-scoped, per
    REFINEMENT_PIPELINE_CONTRACT § Stage execution model)."""
    attempts: list[int] = []

    def _flaky_run(normalized):
        attempts.append(1)
        if len(attempts) == 1:
            raise ValueError("boom: simulated malformed output")
        return {"ok": True}

    register_extractor(
        ExtractorSpec(
            extractor_id="fixture_flaky",
            version=1,
            input_content_type="transcript",
            output_schema_ref="fixture.flaky.v1",
            run=_flaky_run,
        )
    )

    with pytest.raises(ExtractionError) as excinfo:
        run_extractor("fixture_flaky", NORMALIZED_FIXTURE)
    assert excinfo.value.extractor_id == "fixture_flaky"
    assert excinfo.value.version == 1
    assert "boom" in excinfo.value.reason

    # The retry actually re-runs (not served from a bogus cached failure).
    result = run_extractor("fixture_flaky", NORMALIZED_FIXTURE)
    assert result.replayed is False
    assert result.output == {"ok": True}
    assert len(attempts) == 2
