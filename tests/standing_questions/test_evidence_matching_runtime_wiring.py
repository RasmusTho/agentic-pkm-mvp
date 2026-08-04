"""Runtime wiring for SQ-03 evidence matching (#4610).

PR #4588 shipped the matcher with no production caller: normal ingestion never
constructed a ``CandidateArtifact`` or invoked the matching tick. These tests
exercise the REAL production consumer paths named by
``docs/STANDING_QUESTIONS/MATCH_EVIDENCE_TO_OPEN_QUESTIONS.md`` -- the worker's
``ingest.vault.changed`` handler, the worker's
``knowledge_acquisition.stage.completed`` handler, and the Heimdal
observation-log cursor tick -- end to end into a real evidence append on a real
Question note. The only stub is the fenced LLM boundary
(``constrained_completion``), replaced with a deterministic completion that
still validates against the registered association schema; every consumer,
candidate-construction, matcher, and guarded-store path is the production code.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest

from app.heimdal.cursor_store import reset_memory_cursor_store
from app.heimdal.observation_log import reset_memory_observation_log
from app.heimdal.publish import publish_observation
from app.standing_questions import evidence_matching
from app.standing_questions.ingest_consumers import (
    HEIMDAL_EVIDENCE_CONSUMER_ID,
    run_heimdal_evidence_matching_tick,
)
from app.standing_questions.question_store import QuestionStore
from app.workers import outbox_worker
from app.write_guard import WriteGuard
from tests.helpers.pkm_alpha_helper import reset_memory_stores

pytestmark = pytest.mark.not_pg

QUESTION_TEXT = "How should the event outbox be sharded once a single writer saturates?"
RELEVANT_BODY = (
    "We measured the single-writer ceiling at 1.2k events per second, so "
    "sharding by aggregate id is the only option that keeps ordering per stream.\n"
)
RELEVANT_SPAN = "sharding by aggregate id is the only option that keeps ordering per stream"


def _fake_constrained_completion(
    schema_ref: str,
    *,
    system: str = "",
    user: str,
    task_kind: str = "decide",
    trace_id: str | None = None,
    max_tokens: int | None = None,
    complete: Any = None,
) -> dict[str, Any]:
    """Deterministic stand-in for the fenced LLM boundary only.

    Returns a schema-validated attach judgment whenever the artifact span is in
    the prompt, mirroring what a live backend would return for a clearly
    relevant artifact. Validated through the real registered schema so the
    association contract stays live.
    """
    from app.components.llm.constrained import validate_payload

    related = RELEVANT_SPAN in user
    payload = {
        "related": related,
        "confidence_class": "high" if related else "low",
        "relation_label": "states the sharding decision" if related else None,
        "supporting_span": RELEVANT_SPAN if related else "",
    }
    return validate_payload(schema_ref, payload)


def _write_note(vault: Path, relative_path: str, *, scope: str, body: str) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    note_uuid = str(uuid.uuid4())
    path.write_text(
        f"---\nuuid: {note_uuid}\nscope: {scope}\n---\n\n{body}",
        encoding="utf-8",
    )
    return path


def test_ingest_consumers_invoke_question_matching(tmp_path: Path, monkeypatch) -> None:
    """Every production ingest consumer path constructs candidate artifacts and
    invokes the standing-question matching tick (issue #4610 AC1)."""
    reset_memory_stores()
    reset_memory_observation_log()
    reset_memory_cursor_store()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setattr(
        evidence_matching, "constrained_completion", _fake_constrained_completion
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    question_id = note["question_id"]

    def evidence() -> list[dict[str, Any]]:
        return store.read_question(question_id)["evidence"]

    # --- Path 1: the worker's real `ingest.vault.changed` consumer ---------------
    note_path = _write_note(vault, "Inbox/outbox-measurements.md", scope="work", body=RELEVANT_BODY)
    summary = outbox_worker.handle_ingest_vault_changed(
        {
            "vault_path": str(note_path),
            "relative_path": "Inbox/outbox-measurements.md",
            "hash": "test-hash",
            "mtime": 123.0,
        },
        vault_root=vault,
    )
    assert summary.ingested == 1
    vault_entries = evidence()
    assert len(vault_entries) == 1
    assert vault_entries[0]["source_stream"] == "ingest.vault.changed"
    assert vault_entries[0]["artifact_ref"] == "vault://Inbox/outbox-measurements.md"
    assert vault_entries[0]["quoted_span"] == RELEVANT_SPAN

    # --- Path 2: the worker's real KA `stage.completed` consumer -----------------
    _write_note(vault, "sources/candidate-outbox.md", scope="work", body=RELEVANT_BODY)
    outbox_worker.handle_knowledge_acquisition_stage_completed(
        {
            "stage": "candidate",
            "stage_version": 1,
            "content_identity": "sha256:" + "0" * 64,
            "artifact_path": "sources/candidate-outbox.md",
        },
        vault_root=vault,
    )
    ka_entries = evidence()
    assert len(ka_entries) == 2
    assert ka_entries[1]["source_stream"] == "knowledge_acquisition.stage.completed"
    assert ka_entries[1]["artifact_ref"] == "vault://sources/candidate-outbox.md"

    # A non-terminal stage completion offers no candidate and attaches nothing.
    outbox_worker.handle_knowledge_acquisition_stage_completed(
        {
            "stage": "normalize",
            "stage_version": 1,
            "content_identity": "sha256:" + "1" * 64,
        },
        vault_root=vault,
    )
    assert len(evidence()) == 2

    # --- Path 3: the Heimdal observation-log cursor tick -------------------------
    observation_id = "obs-" + str(uuid.uuid4())
    published = publish_observation(
        topic="heimdal.observation.published.v1",
        observation_id=observation_id,
        payload={
            "observation_id": observation_id,
            "content": RELEVANT_BODY,
            "scope_hint": "work",
        },
        source="test",
    )
    assert published is not None
    tick = run_heimdal_evidence_matching_tick(vault_root=vault)
    assert tick.attached == 1
    heimdal_entries = evidence()
    assert len(heimdal_entries) == 3
    assert heimdal_entries[2]["source_stream"] == "heimdal.observations"
    assert heimdal_entries[2]["artifact_ref"] == f"heimdal://observations/{observation_id}"
    assert heimdal_entries[2]["provenance_ref"] == f"heimdal.observations:{observation_id}"

    # The tick owns a durable per-consumer cursor: a re-tick reads nothing new
    # and appends nothing (consumer-id contract, mirrors the ERE read path).
    assert HEIMDAL_EVIDENCE_CONSUMER_ID.startswith("mimer.standing_questions")
    retick = run_heimdal_evidence_matching_tick(vault_root=vault)
    assert retick.evaluated_pairs == 0
    assert len(evidence()) == 3

    # Cross-check the durable note on disk, not just the store API: the real
    # guarded seam wrote all three consumer paths' entries into the vault note.
    raw = (vault / "questions" / f"{question_id}.md").read_text(encoding="utf-8")
    for marker in (
        "ingest.vault.changed",
        "knowledge_acquisition.stage.completed",
        "heimdal.observations",
    ):
        assert marker in raw
