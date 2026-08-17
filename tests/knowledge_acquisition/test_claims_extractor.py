"""Contract test for the structured claims extractor (YSNV2-05)."""

import json

import pytest

from app.knowledge_acquisition.extraction_registry import ExtractionError
from app.knowledge_acquisition.extractors.claims_extractor import run


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
