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

    # --- Path 3: the worker's real `ingest.object.created` dispatch branch -------
    # Wired at the dispatch table (not inside the indexer handler) so the
    # vault-changed path above cannot double-match; exercised through the same
    # `_dispatch_topic` entry the daemon loop and `run_once` both use.
    monkeypatch.setenv("VAULT_ROOT", str(vault))
    api_object_uuid = str(uuid.uuid4())
    outbox_worker._dispatch_topic(
        outbox_worker.INGEST_OBJECT_CREATED,
        {
            "uuid": api_object_uuid,
            "title": "api ingested artifact",
            "review_state": "draft",
            # POST /ingest carries no separate frontmatter field; scope rides
            # inside the content itself and must still resolve.
            "content": f"---\nscope: work\n---\n\n{RELEVANT_BODY}",
        },
        trace_id="trace-object-created",
        message={},
    )
    object_entries = evidence()
    assert len(object_entries) == 3
    assert object_entries[2]["source_stream"] == "ingest.object.created"
    assert object_entries[2]["artifact_ref"] == f"object://{api_object_uuid}"

    # --- Path 4: the Heimdal observation-log cursor tick -------------------------
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
    assert len(heimdal_entries) == 4
    assert heimdal_entries[3]["source_stream"] == "heimdal.observations"
    assert heimdal_entries[3]["artifact_ref"] == f"heimdal://observations/{observation_id}"
    assert heimdal_entries[3]["provenance_ref"] == f"heimdal.observations:{observation_id}"

    # The tick owns a durable per-consumer cursor: a re-tick reads nothing new
    # and appends nothing (consumer-id contract, mirrors the ERE read path).
    assert HEIMDAL_EVIDENCE_CONSUMER_ID.startswith("mimer.standing_questions")
    retick = run_heimdal_evidence_matching_tick(vault_root=vault)
    assert retick.evaluated_pairs == 0
    assert len(evidence()) == 4

    # Cross-check the durable note on disk, not just the store API: the real
    # guarded seam wrote every consumer path's entry into the vault note.
    question_note_path = vault / "questions" / f"{question_id}.md"
    raw = question_note_path.read_text(encoding="utf-8")
    for marker in (
        "ingest.vault.changed",
        "knowledge_acquisition.stage.completed",
        "ingest.object.created",
        "heimdal.observations",
    ):
        assert marker in raw

    # --- Regression: the watcher loop must not destroy or index questions --------
    # Matcher appends re-enter ingest through the watcher (the vault-wide scan
    # includes questions/). Engine-owned Question notes are excluded from the
    # generic ingest fan-out entirely: uuid-healing one made it schema-invalid
    # (additionalProperties: false -- silently dropping the question from
    # matching and its projection), and ingesting it without a uuid minted a
    # fresh random index identity per event. Asserted through the REAL schema
    # validator on the note the handler just processed.
    ingest_summary = outbox_worker.handle_ingest_vault_changed(
        {
            "vault_path": str(question_note_path),
            "relative_path": f"questions/{question_id}.md",
            "hash": "q-hash",
            "mtime": 124.0,
        },
        vault_root=vault,
    )
    assert ingest_summary.ingested == 0
    surviving = store.read_question(question_id)  # parses via the real validator
    assert "uuid" not in surviving
    assert len(surviving["evidence"]) == 4
    assert not any(
        entry["artifact_ref"].startswith("vault://questions/")
        for entry in surviving["evidence"]
    )


def test_vault_alpha_ingest_never_touches_question_notes(tmp_path: Path, monkeypatch) -> None:
    """The second production watcher seam (#4610 round-3 review): the alpha
    ingest walk (`run_watcher_tick` -> `run_vault_alpha_ingest_paths`) must skip
    engine-owned Question notes -- it uuid-healed them exactly like the worker
    seam did, breaking the closed schema on the watcher's first pass."""
    from app.ingest.vault_alpha import run_vault_alpha_ingest_paths

    reset_memory_stores()
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))

    vault = tmp_path / "vault"
    vault.mkdir()
    store = QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))
    note, _ = store.create_question(text=QUESTION_TEXT, scope="work", registered_via="explicit")
    question_id = note["question_id"]
    note_path = vault / "questions" / f"{question_id}.md"
    before = note_path.read_bytes()

    summary = run_vault_alpha_ingest_paths(vault, [note_path])

    assert summary.ingested == 0
    assert note_path.read_bytes() == before  # no healed uuid, no rewrite at all
    surviving = store.read_question(question_id)  # still parses via the real validator
    assert "uuid" not in surviving
