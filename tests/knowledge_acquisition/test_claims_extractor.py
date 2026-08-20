"""Contract test for the structured claims extractor (YSNV2-05)."""

import json

import pytest

from app.knowledge_acquisition.extraction_registry import ExtractionError
from app.knowledge_acquisition.extractors.claims_extractor import run
from app.knowledge_acquisition.extractors.synthesis_extractor import run as run_synthesis


NORMALIZED = {
    "source_content_identity": "sha256:claims-fixture",
    "language": "fr",
    "segments": [{"start": 0.0, "end": 2.0, "text": "Le texte source."}],
}


def _completion(raw: str):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return raw

    return complete


def test_claim_wording_and_paraphrase_are_structurally_distinct() -> None:
    payload = {
        "claims": [{
            "source_wording": "Le texte source.",
            "system_paraphrase": "The source provides its text.",
            "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
        }]
    }
    assert run(NORMALIZED, complete=_completion(json.dumps(payload))) == payload

    payload["claims"][0]["system_paraphrase"] = "Le texte source."
    with pytest.raises(ExtractionError, match="must remain distinct"):
        run(NORMALIZED, complete=_completion(json.dumps(payload)))


def test_non_swedish_paraphrase_language_is_rejected() -> None:
    payload = {
        "claims": [{
            "source_wording": "The source wording.",
            "system_paraphrase": "Le texte source est important.",
            "anchors": [{"segment_index": 0, "start": 0.0, "end": 2.0}],
        }]
    }

    with pytest.raises(ExtractionError, match="system_paraphrase language"):
        run(NORMALIZED, complete=_completion(json.dumps(payload)))


def test_synthesis_rejects_any_invalid_anchor_before_persistence() -> None:
    payload = {
        "synthesis_sentences": [{
            "text": "Cats sleep frequently.",
            "anchors": [
                {"segment_index": 0, "start": 0.0, "end": 2.0},
                {"segment_index": 0, "start": 2.0, "end": 3.0},
            ],
        }],
        "model_confidence": 0.8,
    }

    with pytest.raises(ExtractionError, match="synthesis anchor is not resolvable"):
        run_synthesis({**NORMALIZED, "language": "en"}, complete=_completion(json.dumps(payload)))
