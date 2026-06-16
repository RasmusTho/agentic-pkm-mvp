"""ASK answer-synthesis grounding regression (#2026 quality follow-up).

The Expansion Activation Gate (#2026) moved the ASK synthesis trigger from the
``REASONING_ENABLE`` flag to the admissibility gate; it did not change what text
the LLM is grounded in. UAT then showed answers grounding weakly: a query whose
answer is documented verbatim in the top source was answered with "I'm unsure".

Root cause (deterministic, no LLM): retrieval keeps a short keyword-window
``snippet`` for display but the full note body was dropped on the way into the
synthesis context, so any answer content outside the ~300-char match window
never reached the model — while the 16k char budget went almost entirely unused.

These tests lock the fix at the context-construction boundary: the full body is
carried for grounding, content outside the display snippet reaches
``build_ask_context``, and the short display snippet is still preserved for the
API sources list / literal-snippet fallback.
"""
from __future__ import annotations

from pathlib import Path

from app.agents.ask.graph import _to_retrieved_hit
from app.agents.ask.utils import build_ask_context
from app.retrieval.hybrid import _snippet
from app.settings.models import AskSettings

_GOLDEN = Path(__file__).resolve().parents[3] / "docs" / "examples" / "vault_test_seed" / "golden.md"

# The four properties are documented in golden.md's "## Reproducibility" section,
# which sits past the ~300-char keyword window the display snippet captures.
_FOUR_PROPERTIES = ["Deterministic", "Minimal", "Representative", "Idempotent"]
_UAT_QUERY = "What is the golden test vault and what properties is it designed to have?"


def _production_shaped_hit() -> dict[str, object]:
    """A hybrid hit as it actually arrives in prod: full ``text`` + short window ``snippet``."""
    text = _GOLDEN.read_text(encoding="utf-8")
    return {
        "id": "golden-1",
        "doc_id": "golden-1",
        "text": text,
        "snippet": _snippet(text, _UAT_QUERY),
        "source_ref": "vault-test/Test/AgenticPKM-UAT/golden.md",
        "payload": {"title": "Golden Vault Test Seed", "origin": "vault"},
    }


def test_display_snippet_alone_misses_answer_content() -> None:
    """Premise check: the display snippet genuinely omits the four properties.

    If this ever fails the regression below is no longer exercising the gap it
    guards (the answer would happen to fall inside the match window).
    """
    hit = _production_shaped_hit()
    snippet = str(hit["snippet"])
    assert len(snippet) < 400  # a keyword window, not the body
    assert not all(prop in snippet for prop in _FOUR_PROPERTIES)


def test_retrieved_hit_carries_full_body_distinct_from_snippet() -> None:
    """The full note body is carried for grounding; the display snippet stays short."""
    mapped = _to_retrieved_hit(_production_shaped_hit(), ask_score=0.9)

    assert mapped.text is not None
    assert all(prop in mapped.text for prop in _FOUR_PROPERTIES)
    # Display snippet preserved and still the short window (API sources / fallback).
    assert mapped.snippet is not None
    assert len(mapped.snippet) < len(mapped.text)


def test_build_ask_context_includes_content_outside_snippet_window() -> None:
    """The verbatim answer reaches synthesis context, not just the match window.

    This is the regression for the UAT abstention: a high-rank source whose body
    documents the answer must surface that content into the LLM context.
    """
    mapped = _to_retrieved_hit(_production_shaped_hit(), ask_score=0.9)
    context = build_ask_context(_UAT_QUERY, [mapped.model_dump()], AskSettings())

    assert "## Reproducibility" in context
    for prop in _FOUR_PROPERTIES:
        assert prop in context, f"{prop!r} missing from synthesis context"

    # The unused-budget symptom is gone: the body is present, well under budget.
    assert len(context) > 1000
    assert len(context) <= AskSettings().max_context_chars
