"""Contract tests for gated, proposal-only ontology extraction (YSNV2-08, #4115).

Every enforcement test drives the production path: a raw record through ``assemble_candidate``
(normalize -> registry ``run_extractor`` -> ontology extractor) and, where a note is involved,
``write_candidate_note`` into a temp vault. The only stub is the injected LLM completion.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest
import yaml

from app.knowledge_acquisition import ontology_proposals
from app.knowledge_acquisition.candidate_writeback import (
    CANDIDATE_WRITE_ACTION,
    CandidateAssemblyError,
    REVIEW_STATE_DRAFT,
    TRIAGE_STATE_CAPTURED,
    assemble_candidate,
    render_candidate_note,
    write_candidate_note,
)
from app.knowledge_acquisition.extraction_registry import ExtractionError, ExtractionResult, clear_registry
from app.knowledge_acquisition.extractors import (
    claims_extractor,
    ontology_extractor,
    summary_extractor,
    synthesis_extractor,
)
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

ENGLISH_ONTOLOGY_LINES = (
    "A habit is defined as a behaviour repeated in a stable context.",
    "Motivation differs from habit because it fades over time.",
    "A cue refers to the trigger that starts the routine.",
    "The difference between a goal and a system matters here.",
    "Thanks for watching this video today.",
)
SWEDISH_ONTOLOGY_LINES = (
    "En vana definieras som ett beteende som upprepas i ett stabilt sammanhang.",
    "Motivation skiljer sig från vana eftersom den avtar med tiden.",
    "En signal syftar på det som startar rutinen.",
    "Skillnaden mellan ett mål och ett system är viktig här.",
)


def _vtt(lines: tuple[str, ...]) -> str:
    cues = [
        f"00:00:{2 * i:02d}.000 --> 00:00:{2 * i + 2:02d}.000\n{line}\n"
        for i, line in enumerate(lines)
    ]
    return "WEBVTT\n\n" + "\n".join(cues)


def _raw(lines: tuple[str, ...], *, language: str = "en", identity: str = "sha256:ontology-fixture") -> dict:
    return {
        "source_kind": "youtube_url",
        "item_ref": "ontology-video",
        "url": "https://youtube.com/watch?v=ontology-video",
        "content_identity": identity,
        "acquisition_method": "captions_manual",
        "caption_language": language,
        "caption_body": _vtt(lines),
        "metadata": {"title": "Habits and Systems", "channel": "Fixture", "publish_date": "20260101", "chapters": []},
        "provenance": {"source_kind": "youtube_url", "url": "https://youtube.com/watch?v=ontology-video"},
    }


def _anchor(index: int) -> dict:
    return {"segment_index": index, "start": float(2 * index), "end": float(2 * index + 2)}


class _Completion:
    def __init__(self, payload: dict) -> None:
        self.raw = json.dumps(payload)
        self.calls: list[str] = []

    def __call__(self, *, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        self.calls.append(system)
        return self.raw


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
    clear_registry()
    summary_extractor.register()
    synthesis_extractor.register()
    claims_extractor.register()
    ontology_extractor.register()


def _candidate(raw: dict, payload: dict):
    completion = _Completion(payload)
    ontology_extractor.register(complete=completion)
    return assemble_candidate(raw, extractor_ids=("ontology",)), completion


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(status="selected", active_vault_id="vault-test", active_vault_name="Vault Test", active_vault_path=str(root))


ENGLISH_ELEMENTS = {
    "elements": [
        {
            "kind": "concept",
            "source_definition": "a behaviour repeated in a stable context",
            "system_paraphrase": "The video treats a habit as behaviour that recurs in the same setting.",
            "confidence": 0.7,
            "anchors": [_anchor(0)],
        },
        {
            "kind": "distinction",
            "source_definition": None,
            "system_paraphrase": "The speaker separates short-lived motivation from durable habits.",
            "confidence": 0.6,
            "anchors": [_anchor(1)],
        },
        {
            "kind": "competency_question",
            "source_definition": None,
            "system_paraphrase": "Which trigger starts a given routine in this model?",
            "confidence": 0.5,
            "anchors": [_anchor(2)],
        },
    ]
}


def _ontology_output(candidate) -> dict:
    return next(r.output for r in candidate.extractions if r.extractor_id == "ontology")


# ---------------------------------------------------------------------------
# AC1: deterministic gate needs distinct, repeated, anchored signals.
# ---------------------------------------------------------------------------


def test_ontology_gate_requires_distinct_repeated_anchored_signals() -> None:
    # Pass: definition x2 and distinction x2, each in distinct time-bounded segments.
    candidate, completion = _candidate(_raw(ENGLISH_ONTOLOGY_LINES), ENGLISH_ELEMENTS)
    output = _ontology_output(candidate)
    assert output["gate"]["passed"] is True
    assert set(output["gate"]["qualifying_families"]) == {"definition", "distinction"}
    assert output["gate"]["family_segments"]["definition"] == [0, 2]
    assert len(completion.calls) == 1
    assert candidate.rendered_ontology is not None
    assert "### Ontology proposals" in render_candidate_note(candidate)

    failing_sources = {
        # One family repeated many times is not two distinct families.
        "single_family": (
            "A habit is defined as a routine.",
            "A cue refers to a trigger.",
            "A reward is called the payoff.",
            "We define a loop as the cycle.",
        ),
        # Two families, but the second occurs only once (not repeated).
        "unrepeated_family": (
            "A habit is defined as a routine.",
            "A cue refers to a trigger.",
            "Motivation differs from habit.",
            "Thanks for watching.",
        ),
        # Repetition within a single segment is not repeated anchored evidence.
        "same_segment_repetition": (
            "A habit is defined as a routine and a cue refers to a trigger; motivation differs "
            "from habit, and the difference between goals and systems matters.",
            "Thanks for watching.",
        ),
        "no_signals": ("Hello and welcome.", "Today we cook pasta.", "Enjoy your meal."),
    }
    for name, lines in failing_sources.items():
        candidate, completion = _candidate(_raw(lines, identity=f"sha256:{name}"), ENGLISH_ELEMENTS)
        output = _ontology_output(candidate)
        assert output["gate"]["passed"] is False, name
        assert output["proposals"] == [], name
        # A failed gate spends no model call and produces no filler section.
        assert completion.calls == [], name
        assert candidate.rendered_ontology is None, name
        assert "Ontology proposals" not in render_candidate_note(candidate), name

    # Signals only count in anchorable segments: an invalid time bound is not anchored evidence.
    normalized = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "A habit is defined as a routine."},
            {"start": 5.0, "end": 3.0, "text": "A cue refers to a trigger."},
            {"start": 6.0, "end": 8.0, "text": "Motivation differs from habit."},
            {"start": float("nan"), "end": 9.0, "text": "The difference between goals and systems."},
        ],
    }
    gate = ontology_proposals.evaluate_ontology_gate(normalized)
    assert gate.passed is False
    assert gate.family_segments == {"definition": (0,), "distinction": (2,)}


# ---------------------------------------------------------------------------
# AC2: output is proposal-class and fully anchored.
# ---------------------------------------------------------------------------


def test_ontology_output_is_proposal_class_and_fully_anchored() -> None:
    payload = {
        "elements": [
            *ENGLISH_ELEMENTS["elements"],
            {  # unresolvable anchor
                "kind": "relation",
                "source_definition": None,
                "system_paraphrase": "Cues lead to routines according to the speaker.",
                "confidence": 0.6,
                "anchors": [{"segment_index": 99, "start": 0.0, "end": 1.0}],
            },
            {  # source definition not present in the anchored source text
                "kind": "concept",
                "source_definition": "an invented definition the source never said",
                "system_paraphrase": "The video describes an invented idea about habits.",
                "confidence": 0.9,
                "anchors": [_anchor(0)],
            },
        ]
    }
    candidate, _ = _candidate(_raw(ENGLISH_ONTOLOGY_LINES), payload)
    output = _ontology_output(candidate)
    segments = 5
    assert output["artifact_class"] == "ontology_proposal"
    assert [p["kind"] for p in output["proposals"]] == ["concept", "distinction", "competency_question"]
    assert [d["reason"] for d in output["dropped"]] == [
        "element anchor is not resolvable",
        "source_definition is not verbatim anchored source wording",
    ]
    for proposal in output["proposals"]:
        assert proposal["status"] == "proposed"
        assert proposal["system_paraphrase"]["wording_class"] == "system_paraphrase"
        if proposal["source_definition"] is not None:
            assert proposal["source_definition"]["wording_class"] == "source_definition"
        assert 0.0 <= proposal["confidence"] <= 1.0
        assert proposal["anchors"]
        assert all(0 <= a["segment_index"] < segments for a in proposal["anchors"])

    note = render_candidate_note(candidate)
    section = note.split("### Ontology proposals", 1)[1].split("## Evidence and lineage", 1)[0]
    assert section.count("status `proposed`") == 3
    assert section.count("(`system_paraphrase`, en)") == 3
    assert section.count("(`source_definition`, en)") == 1
    assert section.count("**Anchors:**") == 3
    assert "invented" not in section and "Cues lead to routines" not in section

    # The model has no status/authority field: a self-asserted standing is a schema refusal.
    promoting = {"elements": [{**ENGLISH_ELEMENTS["elements"][0], "status": "canonical"}]}
    ontology_extractor.register(complete=_Completion(promoting))
    with pytest.raises(CandidateAssemblyError, match="'status' was unexpected"):
        assemble_candidate(_raw(ENGLISH_ONTOLOGY_LINES, identity="sha256:promoting"), extractor_ids=("ontology",))

    # Rendering re-checks persisted output: tampered standing or stripped anchors are omitted.
    good = output["proposals"][0]
    tampered = {
        **output,
        "proposals": [{**good, "status": "canonical"}, {**good, "anchors": []}, good],
    }
    base = assemble_candidate(_raw(ENGLISH_ONTOLOGY_LINES, identity="sha256:tampered"), extractor_ids=())
    result = ExtractionResult(
        extractor_id="ontology", extractor_version=1, source_content_identity="sha256:tampered",
        output=tampered, model_identity={"provider": "mock", "model": "mock"},
    )
    tampered_candidate = assemble_candidate(
        _raw(ENGLISH_ONTOLOGY_LINES, identity="sha256:tampered"), extraction_results=[result]
    )
    assert base.rendered_ontology is None
    assert tampered_candidate.rendered_ontology is not None
    assert len(tampered_candidate.rendered_ontology.elements) == 1
    assert tampered_candidate.rendered_ontology.dropped == (
        "element status is not proposed",
        "element has no anchors",
    )


# ---------------------------------------------------------------------------
# AC3: no canonical write and no authority transition.
# ---------------------------------------------------------------------------


def test_ontology_extraction_has_no_canonical_write_or_authority_transition(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault = _vault(vault_root)
    existing = vault_root / "Concepts" / "habit.md"
    existing.parent.mkdir(parents=True)
    existing_text = "---\nartifact_class: concept\nreview_state: reviewed\n---\n\nHabit.\n"
    existing.write_text(existing_text, encoding="utf-8")

    candidate, _ = _candidate(_raw(ENGLISH_ONTOLOGY_LINES), ENGLISH_ELEMENTS)
    assert candidate.rendered_ontology is not None

    actions: list[str] = []
    guard = WriteGuard(lambda: {"state": "healthy"})
    original = guard.assert_writes_allowed

    def _tracking(action: str) -> None:
        actions.append(action)
        original(action)

    guard.assert_writes_allowed = _tracking  # type: ignore[method-assign]
    result = write_candidate_note(candidate, vault_context=vault, write_guard=guard)

    assert result.status == "written"
    # The only governed write is the candidate note itself; no concept/relation artifact appears.
    assert actions == [CANDIDATE_WRITE_ACTION]
    files = sorted(p.relative_to(vault_root).as_posix() for p in vault_root.rglob("*") if p.is_file())
    assert files == sorted(["Concepts/habit.md", result.artifact_path])
    assert existing.read_text(encoding="utf-8") == existing_text

    note = (vault_root / result.artifact_path).read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(note.split("---\n", 2)[1])
    # Candidate review/triage posture is not advanced by ontology output.
    assert frontmatter["review_state"] == REVIEW_STATE_DRAFT
    assert frontmatter["triage_state"] == TRIAGE_STATE_CAPTURED
    assert frontmatter["authority"]["requires_review"] is True
    assert frontmatter["artifact_class"] == "youtube_source_note"
    assert "canonical" not in json.dumps(frontmatter, default=str)
    # Ontology content lives only inside the non-authoritative proposal band.
    proposals_band = note.split("## Proposals (non-authoritative)", 1)[1].split("## Evidence and lineage", 1)[0]
    assert "### Ontology proposals" in proposals_band
    assert "It is not canonical" in proposals_band

    # Structural fence: the ontology modules cannot reach a write, promotion, or persistence seam.
    forbidden = (
        "app.knowledge.write_ops", "app.write_guard", "app.vault", "app.promotion",
        "app.proposals", "app.knowledge_acquisition.extraction_persistence",
        "app.knowledge_acquisition.candidate_writeback", "app.ports", "app.db",
    )
    for module in (ontology_proposals, ontology_extractor):
        tree = ast.parse(inspect.getsource(module))
        imported = {
            node.module if isinstance(node, ast.ImportFrom) else alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in (node.names if isinstance(node, ast.Import) else [node])  # type: ignore[list-item]
        }
        assert not {m for m in imported if m and m.startswith(forbidden)}, module.__name__


# ---------------------------------------------------------------------------
# AC4: D6 language policy for system_paraphrase; source wording keeps its language.
# ---------------------------------------------------------------------------


def test_ontology_system_paraphrase_follows_source_language_policy() -> None:
    swedish_definition = "ett beteende som upprepas i ett stabilt sammanhang"
    swedish_payload = {
        "elements": [
            {  # Swedish source -> Swedish paraphrase; definition kept verbatim in Swedish.
                "kind": "concept",
                "source_definition": swedish_definition,
                "system_paraphrase": "Videon beskriver en vana som ett beteende som återkommer i samma miljö.",
                "confidence": 0.7,
                "anchors": [_anchor(0)],
            },
            {  # English paraphrase for a Swedish source violates D6.
                "kind": "distinction",
                "source_definition": None,
                "system_paraphrase": "The speaker separates short-lived motivation from durable habits.",
                "confidence": 0.6,
                "anchors": [_anchor(1)],
            },
            {  # A translated "source definition" is not source wording.
                "kind": "concept",
                "source_definition": "a behaviour repeated in a stable context",
                "system_paraphrase": "Videon beskriver en vana som ett beteende som återkommer i samma miljö.",
                "confidence": 0.7,
                "anchors": [_anchor(0)],
            },
        ]
    }
    candidate, completion = _candidate(_raw(SWEDISH_ONTOLOGY_LINES, language="sv"), swedish_payload)
    output = _ontology_output(candidate)
    assert "must be in sv" in completion.calls[0]
    assert [p["kind"] for p in output["proposals"]] == ["concept"]
    proposal = output["proposals"][0]
    assert proposal["system_paraphrase"]["language"] == "sv"
    assert proposal["source_definition"] == {
        "wording_class": "source_definition", "text": swedish_definition, "language": "sv",
    }
    assert [d["reason"] for d in output["dropped"]] == [
        "system_paraphrase language is not allowed by D6",
        "source_definition is not verbatim anchored source wording",
    ]
    note = render_candidate_note(candidate)
    assert swedish_definition in note

    # Non-Swedish, non-English source (French): paraphrase must be English; quote stays French.
    french_lines = (
        "Une habitude est définie comme un comportement, ce qui is defined as a routine.",
        "La motivation differs from habit selon l'orateur.",
        "Un signal refers to le déclencheur de la routine.",
        "The difference between un but et un système est importante.",
    )
    french_definition = "Une habitude est définie comme un comportement"
    french_payload = {
        "elements": [
            {
                "kind": "concept",
                "source_definition": french_definition,
                "system_paraphrase": "The speaker describes a habit as a kind of repeated behaviour.",
                "confidence": 0.7,
                "anchors": [_anchor(0)],
            },
            {
                "kind": "concept",
                "source_definition": None,
                "system_paraphrase": "L'orateur décrit une habitude comme un comportement répété.",
                "confidence": 0.7,
                "anchors": [_anchor(0)],
            },
        ]
    }
    candidate, completion = _candidate(_raw(french_lines, language="fr", identity="sha256:fr"), french_payload)
    output = _ontology_output(candidate)
    assert "must be in en" in completion.calls[0]
    assert len(output["proposals"]) == 1
    assert output["proposals"][0]["system_paraphrase"]["language"] == "en"
    assert output["proposals"][0]["source_definition"]["text"] == french_definition
    assert output["proposals"][0]["source_definition"]["language"] == "fr"
    assert output["dropped"] == [{"kind": "concept", "reason": "system_paraphrase language is not allowed by D6"}]
    assert french_definition in render_candidate_note(candidate)


def test_ontology_extractor_rejects_unusable_normalized_input() -> None:
    with pytest.raises(ExtractionError, match="non-empty list"):
        ontology_extractor.run({"segments": []}, complete=_Completion({"elements": []}))
