from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.standing_questions.evidence_matching import (
    EVIDENCE_ASSOCIATION_SCHEMA_REF,
    EVIDENCE_ATTACH_CONFIDENCE_FLOOR,
    CandidateArtifact,
    ConfidenceClass,
    match_evidence_to_open_questions,
)
from app.standing_questions.question_store import (
    QuestionStore,
    parse_question_note,
    serialize_question_note,
)
from app.write_guard import WriteGuard

REPO_ROOT = Path(__file__).resolve().parents[2]

QUESTION_TEXT = "How should the event outbox be sharded once a single writer saturates?"
RELEVANT_BODY = (
    "Outbox notes\n\n"
    "We measured the single-writer ceiling at 1.2k events per second, so "
    "sharding by aggregate id is the only option that keeps ordering per stream.\n"
)
RELEVANT_SPAN = "sharding by aggregate id is the only option that keeps ordering per stream"
IRRELEVANT_BODY = "Grocery list\n\nOat milk, rye bread, and a new watering can for the balcony.\n"
CROSS_SCOPE_MARKER = "balcony-irrigation-schedule-for-the-personal-scope"


def _store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))


def _write_artifact(vault: Path, relative_path: str, body: str) -> str:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return f"vault://{relative_path}"


def _candidate(artifact_ref: str, *, scope: str = "work") -> CandidateArtifact:
    return CandidateArtifact(
        artifact_ref=artifact_ref,
        source_stream="ingest.vault.changed",
        scope=scope,
        provenance_ref=f"outbox://ingest.vault.changed/{artifact_ref}",
    )


class _Association:
    """Deterministic stand-in for the provider side of ``constrained_completion``.

    Records every prompt it is asked to complete so a test can assert that a
    filtered-out pair never reached the model at all.
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        # Keyed by a substring of the artifact content; the value is either a
        # payload dict, a raw string, or an exception instance to raise.
        self._responses = responses
        self.prompts: list[str] = []

    def __call__(
        self,
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        self.prompts.append(user)
        for marker, response in self._responses.items():
            if marker in user:
                if isinstance(response, Exception):
                    raise response
                if isinstance(response, str):
                    return response
                return json.dumps(response)
        return json.dumps({"related": False, "confidence_class": "low", "supporting_span": ""})


def _attached(span: str = RELEVANT_SPAN, confidence: str = "high") -> dict[str, Any]:
    return {
        "related": True,
        "confidence_class": confidence,
        "relation_label": "measures the ceiling this question is about",
        "supporting_span": span,
    }


def _hash_tree(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_relevant_artifact_attaches_irrelevant_does_not(tmp_path: Path) -> None:
    """AC1: a relevant fixture attaches with provenance and a verbatim span; an
    irrelevant one does not."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")

    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)
    irrelevant_ref = _write_artifact(vault, "notes/groceries.md", IRRELEVANT_BODY)
    association = _Association({"single-writer ceiling": _attached()})

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref), _candidate(irrelevant_ref)],
        store=store,
        complete=association,
    )

    assert summary.evaluated_pairs == 2
    assert summary.attached == 1
    assert summary.unrelated == 1

    evidence = store.read_question(note["question_id"])["evidence"]
    assert len(evidence) == 1
    entry = evidence[0]
    assert entry["artifact_ref"] == relevant_ref
    assert entry["source_stream"] == "ingest.vault.changed"
    assert entry["provenance_ref"] == f"outbox://ingest.vault.changed/{relevant_ref}"
    assert entry["confidence_class"] == ConfidenceClass.HIGH.value
    # Verbatim, never paraphrased: the stored span must occur in the artifact byte-for-byte.
    assert entry["quoted_span"] == RELEVANT_SPAN
    assert entry["quoted_span"] in (vault / "notes/outbox-measurements.md").read_text(
        encoding="utf-8"
    )
    assert entry["matched_at"].endswith("Z")


def test_cross_scope_artifact_excluded_content_free(tmp_path: Path) -> None:
    """AC2: a same-content, different-scope artifact is excluded before any content
    is read or shown to the model."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")

    foreign_ref = _write_artifact(
        vault,
        "notes/personal-outbox-measurements.md",
        RELEVANT_BODY + CROSS_SCOPE_MARKER + "\n",
    )
    # A judgment that would attach if the pair were ever evaluated at all.
    association = _Association({"single-writer ceiling": _attached()})

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(foreign_ref, scope="personal")],
        store=store,
        complete=association,
    )

    assert summary.excluded_cross_scope == 1
    assert summary.evaluated_pairs == 0
    assert summary.attached == 0
    assert store.read_question(note["question_id"])["evidence"] == []
    # Content-free denial: no prompt was built, so no span of the other scope's
    # artifact could leak into the association call.
    assert association.prompts == []


def test_matching_never_writes_to_source_artifact(tmp_path: Path) -> None:
    """AC3 (enforcement): no code path of the production matching entrypoint mutates a
    source artifact -- attach, below-threshold, degraded, and cross-scope alike."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")

    attaching_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)
    below_ref = _write_artifact(vault, "notes/weak-signal.md", "A weak signal about outboxes.\n")
    degraded_ref = _write_artifact(vault, "notes/degraded.md", "A backend outage artifact.\n")
    foreign_ref = _write_artifact(vault, "notes/other-scope.md", RELEVANT_BODY)

    association = _Association(
        {
            "single-writer ceiling": _attached(),
            "weak signal": _attached(span="A weak signal about outboxes", confidence="medium"),
            "backend outage": RuntimeError("association backend unavailable"),
        }
    )

    artifacts_root = vault / "notes"
    before = _hash_tree(artifacts_root)
    question_before = (vault / "questions" / f"{note['question_id']}.md").read_bytes()

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[
            _candidate(attaching_ref),
            _candidate(below_ref),
            _candidate(degraded_ref),
            _candidate(foreign_ref, scope="personal"),
        ],
        store=store,
        complete=association,
    )

    assert summary.attached == 1
    assert summary.below_threshold == 1
    assert summary.degraded == 1
    assert summary.excluded_cross_scope == 1
    # The question side gained state; the evidence side is byte-identical.
    assert (vault / "questions" / f"{note['question_id']}.md").read_bytes() != question_before
    assert _hash_tree(artifacts_root) == before


def test_below_threshold_judgment_does_not_attach(tmp_path: Path) -> None:
    """AC4: `related: true` under the RQ-SQ2 floor does not attach, and the floor is a
    single named constant documented as provisional."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)

    association = _Association({"single-writer ceiling": _attached(confidence="medium")})
    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=association,
    )

    assert summary.below_threshold == 1
    assert summary.attached == 0
    assert store.read_question(note["question_id"])["evidence"] == []
    assert EVIDENCE_ATTACH_CONFIDENCE_FLOOR is ConfidenceClass.HIGH

    # Doc writeback (AC4, non-behavioral half): the provisional-threshold section names
    # the single-sourced constant, so the doc and the code cannot drift apart silently.
    readme = (REPO_ROOT / "docs/STANDING_QUESTIONS/README.md").read_text(encoding="utf-8")
    section = readme.split("## Provisional thresholds (RQ-SQ1, RQ-SQ2)")[1].split("\n## ")[0]
    assert "EVIDENCE_ATTACH_CONFIDENCE_FLOOR" in section
    assert "app/standing_questions/evidence_matching.py" in section
    assert "provisional" in section.lower()


def test_degraded_association_never_fabricates_link(tmp_path: Path) -> None:
    """AC5: a provider failure or a schema-invalid completion yields no link."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")

    outage_ref = _write_artifact(vault, "notes/outage.md", "A backend outage artifact.\n")
    invalid_ref = _write_artifact(vault, "notes/invalid.md", "A schema violation artifact.\n")
    prose_ref = _write_artifact(vault, "notes/prose.md", "A prose wrapped artifact.\n")

    association = _Association(
        {
            "backend outage": RuntimeError("association backend unavailable"),
            # `related` missing entirely: validates against nothing the gate may act on.
            "schema violation": {"confidence_class": "high", "supporting_span": "whatever"},
            "prose wrapped": 'Sure! Here is the JSON: {"related": true, '
            '"confidence_class": "high", "supporting_span": "prose"}',
        }
    )

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(outage_ref), _candidate(invalid_ref), _candidate(prose_ref)],
        store=store,
        complete=association,
    )

    assert summary.degraded == 3
    assert summary.attached == 0
    assert store.read_question(note["question_id"])["evidence"] == []


def test_matching_never_attaches_an_unquotable_span(tmp_path: Path) -> None:
    """A high-confidence judgment whose span is not verbatim in the artifact is refused
    rather than stored as a paraphrase (CitationChecker discipline)."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)

    association = _Association(
        {"single-writer ceiling": _attached(span="they decided to shard by tenant id")}
    )
    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=association,
    )

    assert summary.unverifiable_span == 1
    assert summary.attached == 0
    assert store.read_question(note["question_id"])["evidence"] == []


def test_matching_idempotent_per_pair(tmp_path: Path) -> None:
    """AC6: re-ticking the same (question_id, artifact_ref) basis never duplicates."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)
    association = _Association({"single-writer ceiling": _attached()})

    first = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=association,
    )
    note_after_first = (vault / "questions" / f"{note['question_id']}.md").read_bytes()
    second = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=association,
    )

    assert first.attached == 1
    assert second.attached == 0
    assert second.duplicate_basis == 1
    assert len(store.read_question(note["question_id"])["evidence"]) == 1
    # No write at all on the idempotent re-tick.
    assert (vault / "questions" / f"{note['question_id']}.md").read_bytes() == note_after_first


def test_matching_skips_non_open_questions(tmp_path: Path) -> None:
    """AC7 (INV-SQ-F): `answered`/`closed` are terminal for the engine."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    note_path = vault / "questions" / f"{note['question_id']}.md"
    # `status` is human-owned, so the human-side transition is written directly, not
    # through the engine seam (which refuses it).
    human_edited = {**parse_question_note(note_path.read_text(encoding="utf-8")), "status": "answered"}
    note_path.write_text(serialize_question_note(human_edited), encoding="utf-8")
    before = note_path.read_bytes()

    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)
    association = _Association({"single-writer ceiling": _attached()})

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=association,
    )

    assert summary.excluded_non_open == 1
    assert summary.evaluated_pairs == 0
    assert summary.attached == 0
    assert association.prompts == []
    assert note_path.read_bytes() == before
    assert store.read_question(note["question_id"])["evidence"] == []


def test_question_closed_mid_tick_is_never_resurrected(tmp_path: Path) -> None:
    """INV-SQ-F partial failure: the write path re-checks status immediately before the
    guarded append and drops the write if the human closed the question mid-tick."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store = _store(vault)
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    note_path = vault / "questions" / f"{note['question_id']}.md"
    relevant_ref = _write_artifact(vault, "notes/outbox-measurements.md", RELEVANT_BODY)

    def close_then_answer(
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        current = parse_question_note(note_path.read_text(encoding="utf-8"))
        note_path.write_text(
            serialize_question_note({**current, "status": "closed"}), encoding="utf-8"
        )
        return json.dumps(_attached())

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate(relevant_ref)],
        store=store,
        complete=close_then_answer,
    )

    assert summary.attached == 0
    assert summary.excluded_non_open == 1
    assert store.read_question(note["question_id"])["evidence"] == []


def test_missing_questions_directory_is_a_no_op_tick(tmp_path: Path) -> None:
    """A vault that never registered a question yields an empty tick, not a crash --
    matching is a read-only consumer, so the projection's fail-loud posture (which
    exists to prevent a TRUNCATE wipe) does not apply here."""
    vault = tmp_path / "vault"
    vault.mkdir()
    association = _Association({})

    summary = match_evidence_to_open_questions(
        vault_root=vault,
        candidates=[_candidate("vault://notes/anything.md")],
        complete=association,
    )

    assert summary.evaluated_pairs == 0
    assert summary.attached == 0
    assert association.prompts == []


def test_association_schema_is_registered_and_rejects_unknown_confidence() -> None:
    """The association contract is a registered, named schema; the model may not invent
    a confidence class the deterministic gate does not rank."""
    from app.components.llm.constrained import ConstrainedCompletionError, validate_payload

    with pytest.raises(ConstrainedCompletionError):
        validate_payload(
            EVIDENCE_ASSOCIATION_SCHEMA_REF,
            {"related": True, "confidence_class": "certain", "supporting_span": "x"},
        )
