from __future__ import annotations

import ast
import inspect

import app.source_understanding.lenses as lenses
from app.source_understanding import (
    SourceUnderstandingRequest,
    build_concept_critique_lenses,
    build_source_understanding_packet,
)


def _packet(**overrides):
    data = {
        "source_id": "source-1685",
        "source_ref": "docs/source.md#L20-L32",
        "title": "Source-bounded concepts",
        "scope": "selected_passage",
        "selection_start_line": 20,
        "selection_end_line": 32,
        "text": (
            "Working memory is the limited capacity used to hold active context.\n"
            "Concept critique requires human review before stabilization.\n"
            "The limitation is that the passage does not address long-term recall."
        ),
    }
    data.update(overrides)
    return build_source_understanding_packet(SourceUnderstandingRequest(**data))


def test_concept_lens_separates_source_defined_and_agent_clarified_terms() -> None:
    lens = build_concept_critique_lenses(_packet())

    concepts_by_posture = {concept.posture: concept for concept in lens.concepts}

    source_defined = concepts_by_posture["source_defined"]
    agent_clarified = concepts_by_posture["agent_clarified"]
    assert source_defined.term == "Working memory"
    assert source_defined.source_excerpt
    assert source_defined.agent_clarification is None
    assert source_defined.source_anchor.source_ref == "docs/source.md#L20-L32"

    assert agent_clarified.term
    assert agent_clarified.source_excerpt is None
    assert agent_clarified.agent_clarification
    assert "verify" in agent_clarified.agent_clarification


def test_agent_clarified_concepts_skip_words_from_source_defined_multiword_terms() -> None:
    lens = build_concept_critique_lenses(_packet())

    agent_terms = {
        concept.term.casefold()
        for concept in lens.concepts
        if concept.posture == "agent_clarified"
    }

    assert "working" not in agent_terms
    assert "memory" not in agent_terms


def test_concept_lens_degrades_when_term_anchors_are_unavailable() -> None:
    lens = build_concept_critique_lenses(
        _packet(selection_start_line=None, selection_end_line=None)
    )

    assert lens.source.limitation == (
        "Selection text is available, but exact source line anchors were not supplied."
    )
    assert all(concept.anchor_limitation for concept in lens.concepts)
    assert any("Source identity is present" not in item for item in lens.review_posture)


def test_critique_lens_separates_source_limits_from_agent_inference() -> None:
    lens = build_concept_critique_lenses(_packet())

    source_limits = [item for item in lens.critique if item.posture == "source_stated_limit"]
    inferred = [item for item in lens.critique if item.posture == "agent_inferred_review_item"]

    assert source_limits
    assert any("does not address long-term recall" in item.statement for item in source_limits)
    assert all(item.source_excerpt for item in source_limits)
    assert inferred
    assert all(item.source_excerpt is None for item in inferred)
    assert all("Agent-inferred concern" in (item.agent_interpretation or "") for item in inferred)


def test_critique_lens_marks_review_needed_without_overclaiming() -> None:
    lens = build_concept_critique_lenses(_packet())

    assert lens.critique
    assert all(item.review_needed is True for item in lens.critique)
    assert all(item.settled_defect is False for item in lens.critique)
    assert any("review-needed" in item for item in lens.review_posture)


def test_selection_concept_critique_lenses_stay_selection_scoped() -> None:
    lens = build_concept_critique_lenses(_packet())

    assert lens.scope == "selected_passage"
    assert any("selected passage" in item for item in lens.review_posture)
    assert not any("whole-document understanding" in item for item in lens.review_posture)


def test_concept_critique_lenses_are_read_only() -> None:
    lens = build_concept_critique_lenses(_packet())

    assert lens.durable_writes is False
    assert lens.memory_writes is False
    assert lens.canonical_artifact_created is False
    assert lens.mutation_intents == []

    src = inspect.getsource(lenses)
    tree = ast.parse(src)
    imported_modules: set[str] = set()
    used_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            imported_modules.add(module)
            for alias in node.names:
                imported_modules.add(f"{module}.{alias.name}".lower())
                used_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name):
            used_names.add(node.id)
        elif isinstance(node, ast.Attribute):
            used_names.add(node.attr)

    for forbidden in (
        "app.db",
        "app.events",
        "app.index",
        "app.objects",
        "app.outbox",
        "app.vault",
        "app.write_guard",
    ):
        assert not any(forbidden in module for module in imported_modules)
    for symbol in ("ObjectStore", "VaultPort", "WriteGuard", "emit", "open"):
        assert symbol not in used_names
