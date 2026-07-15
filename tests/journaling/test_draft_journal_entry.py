from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
import multiprocessing
from pathlib import Path
import threading

import pytest

from app.journaling.day_context import assemble_day_context
from app.journaling.draft import (
    JOURNAL_DRAFT_WRITE_ACTION,
    UnresolvableJournalCitationError,
    draft_journal_entry,
    resolve_journal_draft_activation_receipt,
)
from app.knowledge_acquisition.candidate_writeback import ARTIFACT_CLASS, DEFAULT_SOURCES_DIR
from app.reasoning.schema import Claim, Inference, ReasoningOutput
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter


DAY = date(2026, 7, 15)


def _empty_reasoning(_object_ids: object, *, trace_id: str | None = None) -> ReasoningOutput:
    del trace_id
    return ReasoningOutput()


def _compose_journal_in_process(
    vault_root: str,
    session_id: str,
    start: object,
    outcomes: object,
) -> None:
    try:
        start.wait(timeout=10)  # type: ignore[attr-defined]
        result = draft_journal_entry(
            vault_context=VaultContext(
                status="selected", active_vault_path=vault_root
            ),
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
            reasoning_fn=_empty_reasoning,
        )
        outcomes.put(("ok", result.path, result.activation_receipt_id))  # type: ignore[attr-defined]
    except BaseException as exc:
        outcomes.put(("error", type(exc).__name__, str(exc)))  # type: ignore[attr-defined]


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test"})


def _seed_inputs(tmp_path: Path) -> tuple[Path, VaultContext, str, Path]:
    root = tmp_path / "vault"
    sources = root / DEFAULT_SOURCES_DIR
    sources.mkdir(parents=True)
    capture = sources / "capture-one.md"
    capture.write_text(
        f"""---
artifact_class: {ARTIFACT_CLASS}
review_state: draft
authority:
  requires_review: true
created: 2026-07-15T09:00:00Z
provenance:
  content_identity: capture-1
  source_kind: note
---
Capture one
""",
        encoding="utf-8",
    )
    session_id = "session-abc"
    session = root / ".chats" / "reflection" / "2026-07-15-evening.md"
    session.parent.mkdir(parents=True)
    session.write_text(
        f"""---
type: chat-session
note: "[[Reflection anchor]]"
note_uuid: reflection-anchor
date: 2026-07-15T20:00
session_id: {session_id}
---

## Session

**Agent:** What mattered today?

**Owner:** I connected several loose ends.
""",
        encoding="utf-8",
    )
    context = VaultContext(status="selected", active_vault_path=str(root))
    return root, context, session_id, capture


def _read_result(root: Path, path: str) -> tuple[dict[str, object], str]:
    return load_frontmatter((root / path).read_text(encoding="utf-8"))


def test_draft_synthesizes_from_transcript_and_context(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
        now=datetime(2026, 7, 15, 21, tzinfo=timezone.utc),
    )

    assert Path(result.path).parts[-3:] == ("drafts", "journal", "2026-07-15.md")
    assert result.compilation_draft.body is not None
    _frontmatter, body = _read_result(root, result.path)
    assert "I connected several loose ends." in body
    assert "capture-1" in body
    assert "I reflected" in body
    assert "AI-åtgärder" in body


def test_draft_write_asserts_guard_at_seam(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    seen: list[str] = []

    class BlockingGuard:
        def assert_writes_allowed(self, action: str) -> None:
            seen.append(action)
            raise WritesBlockedError("safe_mode", "test", action)

    with pytest.raises(WritesBlockedError):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=BlockingGuard(),  # type: ignore[arg-type]
        )

    assert seen == [JOURNAL_DRAFT_WRITE_ACTION]
    assert not list(root.glob("**/drafts/journal/2026-07-15*.md"))


def test_draft_frontmatter_carries_proposal_provenance(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        day_context=bundle,
        write_guard=_allowing_guard(),
    )

    frontmatter, _body = _read_result(root, result.path)
    expected_sources = {f"session:{session_id}"}
    expected_sources.update(
        item.provenance_ref
        for section in bundle.sections.values()
        for item in section.items
    )
    assert frontmatter["derived_by"] == "conversation"
    assert frontmatter["authority_state"] == "proposal"
    assert set(frontmatter["sources"]) == expected_sources
    assert frontmatter["activation_receipt_id"] == result.activation_receipt_id


def test_draft_preserves_provenance_separation(tmp_path: Path) -> None:
    root, context, session_id, capture = _seed_inputs(tmp_path)

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    _frontmatter, body = _read_result(root, result.path)
    assert "[^conversation-1]" in body
    assert "[^context-1]" in body
    assert f"[^conversation-1]: session:{session_id}" in body
    assert f"[^context-1]: {capture.relative_to(root).as_posix()}" in body
    assert body.index("[^conversation-1]") < body.index("[^context-1]")


def test_unresolvable_citation_blocks_staging_loudly(tmp_path: Path) -> None:
    root, context, session_id, capture = _seed_inputs(tmp_path)
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    capture.unlink()

    with pytest.raises(UnresolvableJournalCitationError, match="capture-one.md"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            day_context=bundle,
            write_guard=_allowing_guard(),
        )

    assert not list(root.glob("**/drafts/journal/2026-07-15*.md"))


def test_atomic_write_failure_leaves_no_partial_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.journaling import draft as draft_module

    root, context, session_id, _capture = _seed_inputs(tmp_path)

    def fail_replace(
        _source: object, _target: object, **_kwargs: object
    ) -> None:
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(draft_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        )

    assert not list(root.glob("**/drafts/journal/2026-07-15.md"))
    assert not list(root.glob("**/drafts/journal/*.tmp"))


def test_staged_journal_draft_is_invisible_to_retrieval(tmp_path: Path) -> None:
    from app.ingest.vault_alpha import _select_candidates

    root, context, session_id, _capture = _seed_inputs(tmp_path)
    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    candidates, _ignored = _select_candidates(
        root,
        include_folders=None,
        ignore_glob=(),
        include_test_note=True,
        max_notes=0,
    )
    candidate_paths = {path.relative_to(root).as_posix() for path in candidates}
    assert result.path not in candidate_paths


def test_symlinked_staging_tree_cannot_escape_into_retrieval(
    tmp_path: Path,
) -> None:
    from app.ingest.vault_alpha import _select_candidates
    from app.vault.paths import get_vault_system_dir_rel

    root, context, session_id, _capture = _seed_inputs(tmp_path)
    inbox = root / "Inbox"
    inbox.mkdir()
    journal_parent = root / get_vault_system_dir_rel(root) / "drafts"
    journal_parent.mkdir(parents=True)
    (journal_parent / "journal").symlink_to(inbox, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        )

    candidates, _ignored = _select_candidates(
        root,
        include_folders=None,
        ignore_glob=(),
        include_test_note=True,
        max_notes=0,
    )
    assert root / "Inbox" / "2026-07-15.md" not in candidates


def test_symlinked_final_target_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    from app.vault.paths import get_vault_system_dir_rel

    root, context, session_id, _capture = _seed_inputs(tmp_path)
    inbox_note = root / "Inbox" / "owned.md"
    inbox_note.parent.mkdir()
    inbox_note.write_text("owner content", encoding="utf-8")
    journal_dir = root / get_vault_system_dir_rel(root) / "drafts" / "journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / "2026-07-15.md").symlink_to(inbox_note)

    with pytest.raises(ValueError, match="symlink"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        )

    assert inbox_note.read_text(encoding="utf-8") == "owner content"


def test_symlinked_bootstrap_lock_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    outside = tmp_path / "outside-lock"
    outside.write_text("owner content", encoding="utf-8")
    (root / ".journal-draft-bootstrap.lock").symlink_to(outside)

    with pytest.raises(ValueError, match="bootstrap lock path is a symlink"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        )

    assert outside.read_text(encoding="utf-8") == "owner content"


def test_symlinked_per_draft_lock_is_rejected_without_touching_target(
    tmp_path: Path,
) -> None:
    from app.vault.paths import get_vault_system_dir_rel

    root, context, session_id, _capture = _seed_inputs(tmp_path)
    outside = tmp_path / "outside-draft-lock"
    outside.write_text("owner content", encoding="utf-8")
    journal_dir = root / get_vault_system_dir_rel(root) / "drafts" / "journal"
    journal_dir.mkdir(parents=True)
    (journal_dir / ".2026-07-15.md.lock").symlink_to(outside)

    with pytest.raises(ValueError, match="journal draft lock path is a symlink"):
        draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        )

    assert outside.read_text(encoding="utf-8") == "owner content"


def test_draft_is_idempotent_same_day(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    first = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    second_session = root / ".chats" / "reflection" / "2026-07-15-later.md"
    second_session.write_text(
        """---
type: chat-session
session_id: session-later
---

**Owner:** I also made time to write.
""",
        encoding="utf-8",
    )
    second = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id="session-later",
        write_guard=_allowing_guard(),
    )

    assert second.path == first.path
    assert len(list((root / Path(first.path).parent).glob("2026-07-15.md"))) == 1
    frontmatter, body = _read_result(root, second.path)
    assert set(frontmatter["sources"]) >= {"session:session-abc", "session:session-later"}
    assert "I connected several loose ends." in body
    assert "I also made time to write." in body
    assert (
        resolve_journal_draft_activation_receipt(
            vault_context=context, receipt_id=first.activation_receipt_id
        )
        is not None
    )


def test_concurrent_same_day_composition_retains_both_sessions(tmp_path: Path) -> None:
    root, context, first_session_id, _capture = _seed_inputs(tmp_path)
    second_session = root / ".chats" / "reflection" / "2026-07-15-later.md"
    second_session.write_text(
        """---
type: chat-session
session_id: session-later
---

**Owner:** I also made time to write.
""",
        encoding="utf-8",
    )
    start = threading.Barrier(2)

    def compose(session_id: str) -> str:
        start.wait(timeout=5)
        return draft_journal_entry(
            vault_context=context,
            for_date=DAY,
            session_id=session_id,
            write_guard=_allowing_guard(),
        ).path

    with ThreadPoolExecutor(max_workers=2) as executor:
        paths = list(executor.map(compose, (first_session_id, "session-later")))

    assert paths[0] == paths[1]
    frontmatter, body = _read_result(root, paths[0])
    assert set(frontmatter["sources"]) >= {
        f"session:{first_session_id}",
        "session:session-later",
    }
    assert "I connected several loose ends." in body
    assert "I also made time to write." in body


def test_fresh_vault_cross_process_first_use_retains_both_sessions(
    tmp_path: Path,
) -> None:
    root, _context, first_session_id, _capture = _seed_inputs(tmp_path)
    second_session = root / ".chats" / "reflection" / "2026-07-15-later.md"
    second_session.write_text(
        """---
type: chat-session
session_id: session-later
---

**Owner:** I also made time to write.
""",
        encoding="utf-8",
    )
    assert not list(root.glob("**/drafts/journal"))

    process_context = multiprocessing.get_context("spawn")
    start = process_context.Barrier(2)
    outcomes = process_context.Queue()
    processes = [
        process_context.Process(
            target=_compose_journal_in_process,
            args=(str(root), session_id, start, outcomes),
        )
        for session_id in (first_session_id, "session-later")
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert not process.is_alive()
        assert process.exitcode == 0

    results = [outcomes.get(timeout=5) for _process in processes]
    assert [result[0] for result in results] == ["ok", "ok"], results
    assert results[0][1] == results[1][1]

    frontmatter, body = _read_result(root, results[0][1])
    assert set(frontmatter["sources"]) >= {
        f"session:{first_session_id}",
        "session:session-later",
    }
    assert "I connected several loose ends." in body
    assert "I also made time to write." in body
    receipt_ids = {
        str(receipt["event_id"])
        for receipt in frontmatter["activation_receipts"]
    }
    assert receipt_ids == {result[2] for result in results}


def test_successful_cognition_uses_resolvable_objects_and_synthesis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.stores import reset_memory_store_backend

    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_store_backend()
    from app.chat.reflection_conversation import ReflectionConversationService

    root, context, _manual_session_id, _capture = _seed_inputs(tmp_path)
    note = root / "Notes" / "Reflection anchor.md"
    note.parent.mkdir()
    note.write_text(
        "---\nuuid: reflection-anchor\ntype: note\n---\n\nAnchor.\n",
        encoding="utf-8",
    )
    bundle = assemble_day_context(vault_context=context, for_date=DAY)
    responses = ["What mattered today?", "What made that significant?"]
    service = ReflectionConversationService(
        vault_root=root,
        llm_fn=lambda _kind, _pack: responses.pop(0),
        now_fn=lambda: datetime(2026, 7, 15, 20, tzinfo=timezone.utc),
    )
    conversation = service.start(note_path=note, day_context=bundle)
    service.submit_owner_turn(conversation, "I connected the real session shape.")

    def successful_reasoning(
        object_ids: object, *, trace_id: str | None = None
    ) -> ReasoningOutput:
        del trace_id
        resolved_ids = tuple(object_ids)  # type: ignore[arg-type]
        claims = [
            Claim(
                id=f"claim-{index}",
                object_uuid=object_id,
                text=f"Grounded claim {index}",
                modality="assertion",
                confidence=0.8,
            )
            for index, object_id in enumerate(resolved_ids, start=1)
        ]
        return ReasoningOutput(
            claims=claims,
            inferences=[
                Inference(
                    id="cross-source",
                    premises=[claim.id for claim in claims[:2]],
                    conclusion_id=claims[0].id,
                    type="synthesis",
                    rationale="Grounded cross-source synthesis.",
                )
            ],
            outcome="success",
        )

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=conversation.session.session_id,
        day_context=bundle,
        write_guard=_allowing_guard(),
        reasoning_fn=successful_reasoning,
    )

    frontmatter, body = _read_result(root, result.path)
    cognition = frontmatter["proposed_by"]["cognition"]
    assert cognition["degraded"] is False
    assert cognition["claims"] >= 2
    assert cognition["inferences"] >= 1
    assert len(cognition["object_ids"]) >= 2
    assert "Machine cognition (not owner utterance)" in body
    assert "I connected the real session shape." in body


@pytest.mark.parametrize(
    ("outcome", "provided_reason", "expected_reason"),
    (
        ("provider_failure", "provider leaked internal detail", "provider_failure"),
        ("empty_output", "empty_provider_output", "empty_provider_output"),
    ),
)
def test_journal_preserves_explicit_degraded_reasoning_outcome_without_fabrication(
    tmp_path: Path, outcome: str, provided_reason: str, expected_reason: str
) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)

    def degraded_reasoning(
        _object_ids: object, *, trace_id: str | None = None
    ) -> ReasoningOutput:
        del trace_id
        return ReasoningOutput(  # type: ignore[arg-type]
            outcome=outcome, degraded_reason=provided_reason
        )

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
        reasoning_fn=degraded_reasoning,
    )

    frontmatter, body = _read_result(root, result.path)
    cognition = frontmatter["proposed_by"]["cognition"]
    assert cognition["outcome"] == outcome
    assert cognition["degraded"] is True
    assert cognition["degraded_reason"] == expected_reason
    assert provided_reason not in body
    assert cognition["claims"] == 0
    assert cognition["inferences"] == 0
    assert "I connected several loose ends." in body
    assert "Cognition degraded; the citation-grounded collation remains available." in body
    assert "Cross-source synthesis" not in body


def test_journal_keeps_mixed_degraded_cognition_separate_from_collation(
    tmp_path: Path,
) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)

    def mixed_reasoning(
        object_ids: object, *, trace_id: str | None = None
    ) -> ReasoningOutput:
        del trace_id
        first_object_id = tuple(object_ids)[0]  # type: ignore[arg-type]
        return ReasoningOutput(
            claims=[
                Claim(
                    id="real-provider-claim",
                    object_uuid=first_object_id,
                    text="One provider returned this grounded claim.",
                    modality="assertion",
                    confidence=0.8,
                )
            ],
            outcome="provider_failure",
            degraded_reason="provider_failure",
        )

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
        reasoning_fn=mixed_reasoning,
    )

    frontmatter, body = _read_result(root, result.path)
    cognition = frontmatter["proposed_by"]["cognition"]
    assert cognition["outcome"] == "provider_failure"
    assert cognition["degraded"] is True
    assert cognition["degraded_reason"] == "provider_failure"
    assert cognition["claims"] == 1
    assert cognition["inferences"] == 0
    assert "One provider returned this grounded claim." in body
    assert "Cross-source synthesis" not in body
    assert body.index("## My reflection") < body.index(
        "## Machine cognition (not owner utterance)"
    )
    assert "I connected several loose ends." in body


def test_draft_preserves_unreviewed_capture_posture(tmp_path: Path) -> None:
    root, context, session_id, capture = _seed_inputs(tmp_path)

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    capture_ref = next(
        ref
        for ref in result.compilation_draft.source_refs
        if ref.note_path == capture.relative_to(root).as_posix()
    )
    assert capture_ref.review_state == "unreviewed"


def test_activation_receipt_resolves_after_restart(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    receipt = resolve_journal_draft_activation_receipt(
        vault_context=VaultContext(status="selected", active_vault_path=str(root)),
        receipt_id=result.activation_receipt_id,
    )

    assert receipt is not None
    assert receipt["event_id"] == result.activation_receipt_id
    assert receipt["payload"]["capability_id"] == "journal_draft_proposal"
    assert receipt["payload"]["outcome"] == "activatable"


def test_draft_after_acceptance_produces_addendum_not_overwrite(tmp_path: Path) -> None:
    root, context, session_id, _capture = _seed_inputs(tmp_path)
    accepted = root / "1_Calendar" / "Daily" / "2026-07-15.md"
    accepted.parent.mkdir(parents=True)
    accepted.write_text(
        "---\nauthority_state: accepted\naccepted_by: human\n---\n\nHuman-owned text.\n",
        encoding="utf-8",
    )
    before = accepted.read_bytes()

    result = draft_journal_entry(
        vault_context=context,
        for_date=DAY,
        session_id=session_id,
        write_guard=_allowing_guard(),
    )

    assert result.is_addendum is True
    assert result.path.endswith("2026-07-15-addendum.md")
    frontmatter, body = _read_result(root, result.path)
    assert frontmatter["journal_candidate_type"] == "addendum"
    assert "Addendum candidate" in body
    assert accepted.read_bytes() == before
