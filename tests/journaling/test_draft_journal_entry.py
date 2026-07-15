from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.journaling.day_context import assemble_day_context
from app.journaling.draft import (
    JOURNAL_DRAFT_WRITE_ACTION,
    UnresolvableJournalCitationError,
    draft_journal_entry,
)
from app.knowledge_acquisition.candidate_writeback import ARTIFACT_CLASS, DEFAULT_SOURCES_DIR
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter


DAY = date(2026, 7, 15)


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

    def fail_replace(_source: object, _target: object) -> None:
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
