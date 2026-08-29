"""SQ-04 production-entrypoint acceptance tests."""

from __future__ import annotations

import json
import hashlib
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.expansion.create import CreateIdempotencyConflictError, SourceInput
from app.knowledge.errors import KnowledgeWriteConflict
from app.standing_questions import answer_refresh as refresh_module
from app.standing_questions.answer_refresh import refresh_answers_on_evidence_delta
from app.standing_questions.evidence_matching import (
    CandidateArtifact,
    run_standing_questions_tick,
)
from app.standing_questions.question_store import QuestionStore
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import load_frontmatter


def _guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy"})


def _store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=_guard())


def _dt(hour: int) -> datetime:
    return datetime(2026, 8, 29, hour, 0, tzinfo=timezone.utc)


def _evidence(ref: str, provenance: str, span: str, hour: int) -> dict[str, Any]:
    return {
        "artifact_ref": ref,
        "source_stream": "ingest.vault.changed",
        "matched_at": f"2026-08-29T{hour:02d}:00:00Z",
        "confidence_class": "high",
        "provenance_ref": provenance,
        "quoted_span": span,
        "content_hash": hashlib.sha256(span.encode("utf-8")).hexdigest(),
    }


def _source(provenance: str, text: str) -> SourceInput:
    return SourceInput(
        object_id=provenance,
        note_path="notes/evidence.md",
        text=text,
        language="en",
        review_state="reviewed",
    )


def _question(
    vault: Path, *, standing_answer_ref: str | None = None
) -> tuple[QuestionStore, dict[str, Any]]:
    store = _store(vault)
    note, _receipt = store.create_question(
        text="Which deployment boundary is supported?",
        scope="work",
        registered_via="explicit",
    )
    if standing_answer_ref is not None:
        note, _receipt = store.update_system_fields(
            note["question_id"], {"standing_answer_ref": standing_answer_ref}
        )
    return store, note


def _records(outbox: Path) -> list[dict[str, Any]]:
    if not outbox.exists():
        return []
    return [json.loads(line) for line in outbox.read_text(encoding="utf-8").splitlines()]


def test_delta_threshold_triggers_one_draft(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence(
        "vault://notes/evidence.md",
        "outbox://evidence/1",
        "the test channel is isolated",
        10,
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    summary = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )

    assert summary.refresh_candidates == (note["question_id"],)
    assert summary.drafted == (note["question_id"],)
    assert len([r for r in _records(outbox) if r["event"] == "expansion.create.proposed"]) == 1
    refreshed = store.read_question(note["question_id"])
    assert refreshed["candidate_answer_ref"].startswith("vault://")
    assert refreshed["last_refreshed_at"] == "2026-08-29T12:00:00Z"
    draft = vault / refreshed["candidate_answer_ref"][len("vault://") :]
    frontmatter, body = load_frontmatter(draft.read_text(encoding="utf-8"))
    assert len(frontmatter["sources"]) == 1
    assert frontmatter["sources"][0] != "outbox://evidence/1"
    assert frontmatter["provenance_refs"] == ["outbox://evidence/1"]
    assert frontmatter["proposed_by"]["cognition"]["outcome"] != "missing_input"
    assert frontmatter["authority_state"] == "proposal"
    assert evidence["quoted_span"] in body


def test_pending_review_not_clobbered_by_new_delta(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    first = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    second = _evidence("vault://notes/b.md", "outbox://evidence/2", "second evidence", 13)
    store.update_system_fields(note["question_id"], {"evidence": [first]})
    sources = {
        "outbox://evidence/1": _source("outbox://evidence/1", first["quoted_span"]),
        "outbox://evidence/2": _source("outbox://evidence/2", second["quoted_span"]),
    }
    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    prior_ref = store.read_question(note["question_id"])["candidate_answer_ref"]
    updated = store.read_question(note["question_id"])
    store.update_system_fields(note["question_id"], {"evidence": [*updated["evidence"], second]})

    summary = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(14),
    )

    assert summary.deferred_pending_review == (note["question_id"],)
    assert summary.drafted == ()
    assert store.read_question(note["question_id"])["candidate_answer_ref"] == prior_ref
    assert len([r for r in _records(outbox) if r["event"] == "expansion.create.proposed"]) == 1


def test_deferral_is_derived_not_persisted(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    first = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    second = _evidence("vault://notes/b.md", "outbox://evidence/2", "second evidence", 13)
    store.update_system_fields(note["question_id"], {"evidence": [first]})
    sources = {
        "outbox://evidence/1": _source("outbox://evidence/1", first["quoted_span"]),
        "outbox://evidence/2": _source("outbox://evidence/2", second["quoted_span"]),
    }
    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    current = store.read_question(note["question_id"])
    store.update_system_fields(note["question_id"], {"evidence": [*current["evidence"], second]})
    deferred = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(14),
    )
    assert deferred.deferred_pending_review == (note["question_id"],)
    after_defer = store.read_question(note["question_id"])
    assert set(after_defer) == set(current)
    assert "refresh_deferred" not in after_defer

    # Simulate the governed dismiss path clearing the candidate pointer. The
    # next tick recomputes state from the note and consumes the still-present delta.
    store.update_system_fields(note["question_id"], {"candidate_answer_ref": None})
    retried = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(15),
    )
    assert retried.drafted == (note["question_id"],)


def test_contradiction_surfaced_not_silently_rewritten(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answer = vault / "answers/current.md"
    answer.parent.mkdir()
    answer.write_text("The supported boundary is production.", encoding="utf-8")
    store, note = _question(vault, standing_answer_ref="vault://answers/current.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    def contradiction(
        *, system: str, user: str, trace_id: str | None = None, max_tokens: int | None = None
    ) -> str:
        assert "production" in user
        assert "test channel" in user
        return json.dumps(
            {
                "contradicts_standing_answer": True,
                "contradiction_basis": "the test channel is isolated",
            }
        )

    summary = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        contradiction_complete=contradiction,
        write_guard=_guard(),
        now=_dt(12),
    )
    assert summary.drafted == (note["question_id"],)
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradicts_standing_answer"] is True
    assert frontmatter["contradiction"] is True
    assert frontmatter["contradiction_basis"] == "the test channel is isolated"


def test_invalid_contradiction_basis_degrades_to_unknown(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answer = vault / "answers/current.md"
    answer.parent.mkdir()
    answer.write_text("The supported boundary is production.", encoding="utf-8")
    store, note = _question(vault, standing_answer_ref="vault://answers/current.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    def invalid_basis(**_kwargs: Any) -> str:
        return json.dumps(
            {
                "contradicts_standing_answer": True,
                "contradiction_basis": "the evidence is broadly different",
            }
        )

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        contradiction_complete=invalid_basis,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction_basis"] is None


def test_standing_answer_edit_during_cognition_blocks_stale_contradiction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answer = vault / "answers/current.md"
    answer.parent.mkdir()
    answer.write_text("The supported boundary is production.", encoding="utf-8")
    store, note = _question(vault, standing_answer_ref="vault://answers/current.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    original = refresh_module.run_create_pass

    def create_then_edit_answer(*args: Any, **kwargs: Any) -> Any:
        answer.write_text("The supported boundary is staging.", encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "run_create_pass", create_then_edit_answer)
    result = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )

    assert result.blocked == (note["question_id"],)
    assert store.read_question(note["question_id"])["candidate_answer_ref"] is None


def test_changed_source_bytes_cannot_replay_historical_evidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault)
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "original evidence", 10
    )
    evidence["content_hash"] = hashlib.sha256(b"original evidence").hexdigest()
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    summary = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", "edited evidence")
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )

    assert summary.blocked == (note["question_id"],)
    assert store.read_question(note["question_id"])["candidate_answer_ref"] is None


def test_degraded_contradiction_judgment_lands_unknown_not_false(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answer = vault / "answers/current.md"
    answer.parent.mkdir()
    answer.write_text("The supported boundary is production.", encoding="utf-8")
    store, note = _question(vault, standing_answer_ref="vault://answers/current.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    def degraded(**_kwargs: Any) -> str:
        return "not json"

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        contradiction_complete=degraded,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_unreadable_standing_answer_lands_unknown_not_false(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault, standing_answer_ref="vault://answers/missing.md")
    evidence = _evidence("vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])},
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_invalid_utf8_standing_answer_lands_unknown_not_false(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answer = vault / "answers/corrupt.md"
    answer.parent.mkdir()
    answer.write_bytes(b"standing answer with invalid utf-8: \xff")
    store, note = _question(vault, standing_answer_ref="vault://answers/corrupt.md")
    evidence = _evidence("vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])},
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_surrogate_standing_answer_ref_lands_unknown_not_false(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault, standing_answer_ref="vault://answers/placeholder.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    question_path = vault / "questions" / f"{note['question_id']}.md"
    question_path.write_text(
        question_path.read_text(encoding="utf-8").replace(
            "standing_answer_ref: vault://answers/placeholder.md",
            'standing_answer_ref: "vault://answers/\\ud800.md"',
        ),
        encoding="utf-8",
    )

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_symlink_loop_standing_answer_ref_lands_unknown_not_false(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    answers = vault / "answers"
    answers.mkdir()
    os.symlink("loop", answers / "loop")
    store, note = _question(vault, standing_answer_ref="vault://answers/loop/answer.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})

    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_standing_answer_stat_error_lands_unknown_not_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault, standing_answer_ref="vault://answers/current.md")
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    real_is_file = Path.is_file

    def permission_race(path: Path) -> bool:
        if path == vault / "answers" / "current.md":
            raise PermissionError("standing answer permissions changed")
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", permission_race)
    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    frontmatter, _body = load_frontmatter(
        (vault / refreshed["candidate_answer_ref"][len("vault://") :]).read_text(encoding="utf-8")
    )
    assert frontmatter["contradiction"] == "unknown"
    assert frontmatter["contradiction"] is not False


def test_unreadable_pending_candidate_is_deferred_not_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    first = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    second = _evidence("vault://notes/b.md", "outbox://evidence/2", "second evidence", 13)
    store.update_system_fields(note["question_id"], {"evidence": [first]})
    sources = {
        "outbox://evidence/1": _source("outbox://evidence/1", first["quoted_span"]),
        "outbox://evidence/2": _source("outbox://evidence/2", second["quoted_span"]),
    }
    refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources, store=store,
        write_guard=_guard(), now=_dt(12)
    )
    current = store.read_question(note["question_id"])
    store.update_system_fields(note["question_id"], {"evidence": [*current["evidence"], second]})
    candidate_path = vault / current["candidate_answer_ref"][len("vault://") :]
    real_is_file = Path.is_file

    def permission_race(path: Path) -> bool:
        if path == candidate_path:
            raise PermissionError("candidate permissions changed")
        return real_is_file(path)

    monkeypatch.setattr(Path, "is_file", permission_race)
    summary = refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources, store=store,
        write_guard=_guard(), now=_dt(14)
    )
    assert summary.deferred_pending_review == (note["question_id"],)
    assert summary.drafted == ()
    assert store.read_question(note["question_id"])["candidate_answer_ref"] == current["candidate_answer_ref"]
    assert len([r for r in _records(outbox) if r["event"] == "expansion.create.proposed"]) == 1


def test_concurrent_refreshes_cannot_clobber_pending_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence("vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    sources = {"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])}
    original = refresh_module.run_create_pass

    def slow_create(*args: Any, **kwargs: Any) -> Any:
        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "run_create_pass", slow_create)

    def tick() -> Any:
        return refresh_answers_on_evidence_delta(
            vault_root=vault,
            outbox_path=outbox,
            evidence_sources=sources,
            store=store,
            write_guard=_guard(),
            now=_dt(12),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        summaries = list(executor.map(lambda _index: tick(), range(2)))

    assert sum(summary.drafted == (note["question_id"],) for summary in summaries) == 1
    assert sum(summary.refresh_candidates == (note["question_id"],) for summary in summaries) == 1
    assert len([r for r in _records(outbox) if r["event"] == "expansion.create.proposed"]) == 1


def test_draft_never_sets_standing_answer_ref(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault)
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    refreshed = store.read_question(note["question_id"])
    assert refreshed["standing_answer_ref"] is None
    assert refreshed["status"] == "open"


def test_last_refreshed_at_only_advances_on_success(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://missing", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    blocked = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources={},
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    assert blocked.blocked == (note["question_id"],)
    assert store.read_question(note["question_id"])["last_refreshed_at"] is None

    successful = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources={"outbox://missing": _source("outbox://missing", evidence["quoted_span"])},
        store=store,
        write_guard=_guard(),
        now=_dt(13),
    )
    assert successful.drafted == (note["question_id"],)
    assert store.read_question(note["question_id"])["last_refreshed_at"] == "2026-08-29T13:00:00Z"


def test_refresh_path_never_writes_status(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    store, note = _question(vault)
    evidence = _evidence(
        "vault://notes/evidence.md", "outbox://evidence/1", "the test channel is isolated", 10
    )
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    updates: list[dict[str, Any]] = []
    original = store.update_system_fields_if_unchanged

    def recording(
        question_id: str,
        expected: dict[str, Any],
        fields: dict[str, Any],
        *,
        expected_version: str,
    ) -> tuple[dict[str, Any], Any]:
        updates.append(dict(fields))
        return original(question_id, expected, fields, expected_version=expected_version)

    store.update_system_fields_if_unchanged = recording  # type: ignore[method-assign]
    refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=tmp_path / "outbox.jsonl",
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])
        },
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )
    assert updates
    assert all("status" not in fields and "standing_answer_ref" not in fields for fields in updates)
    assert store.read_question(note["question_id"])["status"] == "open"


def test_standing_questions_tick_matches_then_refreshes(tmp_path: Path) -> None:
    """The production composition must not return after SQ-03 alone."""
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    candidate = CandidateArtifact(
        artifact_ref="vault://notes/evidence.md",
        source_stream="ingest.vault.changed",
        scope="work",
        provenance_ref="outbox://evidence/1",
        content="the test channel is isolated",
    )

    def match_and_refresh_completion(
        *, system: str, user: str, trace_id: str | None = None, max_tokens: int | None = None
    ) -> str:
        if "Return only JSON matching the supplied schema" in system:
            return json.dumps(
                {
                    "contradicts_standing_answer": False,
                    "contradiction_basis": None,
                }
            )
        return json.dumps(
            {
                "related": True,
                "confidence_class": "high",
                "supporting_span": "the test channel is isolated",
            }
        )

    result = run_standing_questions_tick(
        vault_root=vault,
        candidates=[candidate],
        evidence_sources={
            "outbox://evidence/1": _source("outbox://evidence/1", candidate.content or "")
        },
        outbox_path=outbox,
        store=store,
        complete=match_and_refresh_completion,
        write_guard=_guard(),
        now=_dt(12),
    )

    assert result.matching.attached == 1
    assert result.refresh.drafted == (note["question_id"],)
    assert store.read_question(note["question_id"])["candidate_answer_ref"]


def test_refresh_cas_snapshot_is_taken_before_drafting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Question edit while cognition runs must invalidate publication."""
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    first = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    second = _evidence("vault://notes/b.md", "outbox://evidence/2", "second evidence", 11)
    store.update_system_fields(note["question_id"], {"evidence": [first]})
    sources = {
        "outbox://evidence/1": _source("outbox://evidence/1", first["quoted_span"]),
        "outbox://evidence/2": _source("outbox://evidence/2", second["quoted_span"]),
    }
    original = refresh_module.run_create_pass
    mutated = False

    def create_then_mutate(*args: Any, **kwargs: Any) -> Any:
        nonlocal mutated
        if not mutated:
            current = store.read_question(note["question_id"])
            store.update_system_fields(
                note["question_id"], {"evidence": [*current["evidence"], second]}
            )
            mutated = True
        return original(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "run_create_pass", create_then_mutate)
    result = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(12),
    )

    assert result.drafted == ()
    assert result.blocked == (note["question_id"],)
    final = store.read_question(note["question_id"])
    assert final["candidate_answer_ref"] is None
    assert final["last_refreshed_at"] is None

    retry = refresh_answers_on_evidence_delta(
        vault_root=vault,
        outbox_path=outbox,
        evidence_sources=sources,
        store=store,
        write_guard=_guard(),
        now=_dt(13),
    )
    assert retry.drafted == (note["question_id"],)
    final = store.read_question(note["question_id"])
    candidate_path = vault / final["candidate_answer_ref"][len("vault://") :]
    assert candidate_path.exists()
    assert len(list(candidate_path.parent.glob("*.md"))) == 2
    assert len([r for r in _records(outbox) if r["event"] == "expansion.create.proposed"]) == 2


def test_refresh_replay_reuses_draft_and_receipt_bytes(tmp_path: Path) -> None:
    """A crash/CAS retry with the same evidence generation cannot rewrite a receipted draft."""
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    sources = {"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])}

    original = store.update_system_fields_if_unchanged
    failed = True

    def fail_once(*args: Any, **kwargs: Any) -> Any:
        nonlocal failed
        if failed:
            failed = False
            raise KnowledgeWriteConflict("simulated crash after proposal receipt")
        return original(*args, **kwargs)

    store.update_system_fields_if_unchanged = fail_once  # type: ignore[method-assign]
    first = refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources,
        store=store, write_guard=_guard(), now=_dt(12)
    )
    assert first.blocked == (note["question_id"],)
    records_before = _records(outbox)
    proposal_before = [r for r in records_before if r["event"] == "expansion.create.proposed"]
    assert len(proposal_before) == 1
    draft_before = (vault / proposal_before[0]["payload"]["draft_path"]).read_bytes()

    second = refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources,
        store=store, write_guard=_guard(), now=_dt(13)
    )
    assert second.drafted == (note["question_id"],)
    records_after = _records(outbox)
    proposal_after = [r for r in records_after if r["event"] == "expansion.create.proposed"]
    assert proposal_after == proposal_before
    draft_path = vault / proposal_after[0]["payload"]["draft_path"]
    assert draft_path.read_bytes() == draft_before

    # The receipt binds raw bytes, not text normalized through universal-newline decoding.
    draft_path.write_bytes(draft_before.replace(b"\n", b"\r\n", 1))
    store.update_system_fields(
        note["question_id"], {"candidate_answer_ref": None, "last_refreshed_at": None}
    )
    with pytest.raises(CreateIdempotencyConflictError, match="does not match draft"):
        refresh_answers_on_evidence_delta(
            vault_root=vault, outbox_path=outbox, evidence_sources=sources,
            store=store, write_guard=_guard(), now=_dt(14)
        )


def test_refresh_replay_rejects_receipt_payload_collision(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    sources = {"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])}
    original = store.update_system_fields_if_unchanged

    def conflict(*_args: Any, **_kwargs: Any) -> Any:
        raise KnowledgeWriteConflict("simulated crash after proposal receipt")

    store.update_system_fields_if_unchanged = conflict  # type: ignore[method-assign]
    refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources,
        store=store, write_guard=_guard(), now=_dt(12)
    )
    records = _records(outbox)
    proposal = next(record for record in records if record["event"] == "expansion.create.proposed")
    proposal["payload"]["kind"] = "create.digest"
    outbox.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    store.update_system_fields_if_unchanged = original  # type: ignore[method-assign]

    with pytest.raises(CreateIdempotencyConflictError, match="receipt payload"):
        refresh_answers_on_evidence_delta(
            vault_root=vault, outbox_path=outbox, evidence_sources=sources,
            store=store, write_guard=_guard(), now=_dt(13)
        )


def test_refresh_retry_after_question_text_edit_derives_new_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    store, note = _question(vault)
    evidence = _evidence("vault://notes/a.md", "outbox://evidence/1", "first evidence", 10)
    store.update_system_fields(note["question_id"], {"evidence": [evidence]})
    sources = {"outbox://evidence/1": _source("outbox://evidence/1", evidence["quoted_span"])}
    original = refresh_module.run_create_pass
    changed = False

    def create_then_edit(*args: Any, **kwargs: Any) -> Any:
        nonlocal changed
        if not changed:
            path = vault / "questions" / f"{note['question_id']}.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    "Which deployment boundary is supported?",
                    "Which deployment boundary is supported after the edit?",
                    1,
                ),
                encoding="utf-8",
            )
            changed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(refresh_module, "run_create_pass", create_then_edit)
    first = refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources,
        store=store, write_guard=_guard(), now=_dt(12)
    )
    assert first.blocked == (note["question_id"],)
    monkeypatch.setattr(refresh_module, "run_create_pass", original)
    retry = refresh_answers_on_evidence_delta(
        vault_root=vault, outbox_path=outbox, evidence_sources=sources,
        store=store, write_guard=_guard(), now=_dt(13)
    )
    assert retry.drafted == (note["question_id"],)
