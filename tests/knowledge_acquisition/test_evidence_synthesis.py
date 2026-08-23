"""Contract tests for evidence-anchored synthesis rendering (YSNV2-05)."""

from app.knowledge_acquisition.evidence_synthesis import (
    render_evidence_anchored,
    validate_generated_language,
)


NORMALIZED = {
    "language": "en",
    "acquisition_method": "captions_auto",
    "segments": [{"start": 0.0, "end": 2.0, "text": "Original source wording."}],
}
ANCHOR = {"segment_index": 0, "start": 0.0, "end": 2.0}


def test_language_validation_rejects_invalid_d6_output() -> None:
    assert validate_generated_language("Cats sleep frequently.", "en")
    assert validate_generated_language("Katter sover ofta.", "sv")
    assert not validate_generated_language("Bonjour a Paris.", "en")
    assert not validate_generated_language("Cats sleep frequently.", "sv")


def test_renderer_drops_anchorless_claims_and_synthesis_sentences() -> None:
    rendered = render_evidence_anchored(
        normalized=NORMALIZED,
        model_confidence=0.9,
        synthesis_sentences=(
            {"text": "Anchored sentence.", "anchors": [ANCHOR]},
            {"text": "Anchorless sentence.", "anchors": []},
        ),
        claims=(
            {"source_wording": "Original source wording.", "system_paraphrase": "The source makes a claim.", "anchors": [ANCHOR]},
            {"source_wording": "Uncited", "system_paraphrase": "Uncited paraphrase", "anchors": []},
        ),
    )

    assert rendered.synthesis_sentences == ("Anchored sentence.",)
    assert len(rendered.claims) == 1
    assert rendered.dropped == ("synthesis_sentence", "claim")


def test_synthesis_coverage_uses_transcript_evidence_spans() -> None:
    normalized = {
        **NORMALIZED,
        "segments": [
            {"start": float(index), "end": float(index + 1), "text": f"Segment {index}."}
            for index in range(100)
        ],
    }
    rendered = render_evidence_anchored(
        normalized=normalized,
        model_confidence=0.95,
        synthesis_sentences=(
            {
                "text": "Anchored.",
                "anchors": [{"segment_index": 0, "start": 0.0, "end": 1.0}],
            },
        ),
        claims=(),
    )

    assert rendered.coverage == 0.01
    assert rendered.model_confidence == 0.95
    assert rendered.evidence_confidence == 0.01
    assert rendered.confidence == 0.01


def test_synthesis_language_policy_uses_english_unless_source_is_swedish_and_preserves_quotes() -> None:
    english = render_evidence_anchored(
        normalized={**NORMALIZED, "language": "fr"}, model_confidence=0.5,
        synthesis_sentences=(), claims=(),
    )
    swedish = render_evidence_anchored(
        normalized={**NORMALIZED, "language": "sv-SE"}, model_confidence=0.5,
        synthesis_sentences=(), claims=(),
    )

    assert english.system_language == "en"
    assert swedish.system_language == "sv"
    # Rendering returns the source wording untouched; it never translates it into a quote.
    source_wording = "Bonjour, ceci est la formulation source."
    rendered = render_evidence_anchored(
        normalized={**NORMALIZED, "language": "fr"}, model_confidence=0.5,
        synthesis_sentences=(),
        claims=({"source_wording": source_wording, "system_paraphrase": "The source says hello.", "anchors": [ANCHOR]},),
    )
    assert rendered.claims[0]["source_wording"] == source_wording
