"""JRNL-04: governed review and acceptance of journal candidates.

These tests exercise the production review seam with vault-durable candidate
files.  The checked Panel action is the authority input; callers never pass
accepted text, a destination, or a separate approval flag.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

import app.journaling.review as review_module
from app.journaling.review import (
    JOURNAL_ENTRY_ACCEPT_WRITE_ACTION,
    JOURNAL_ENTRY_ACCEPTED_EVENT,
    JOURNAL_ENTRY_DECLINED_EVENT,
    JournalAcceptedEntryExistsError,
    JournalReviewError,
    JournalReviewState,
    journal_draft_relative_path,
    process_journal_review,
    project_journal_review,
)
from app.proposals.declined_ledger import DeclinedLedger
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


DAY = date(2026, 7, 15)
NOW = datetime(2026, 7, 15, 20, 30, tzinfo=timezone.utc)


class _RecordingGuard(WriteGuard):
    def __init__(self, snapshot: dict[str, object]) -> None:
        super().__init__(lambda: snapshot)
        self.actions: list[str] = []

    def assert_writes_allowed(self, action: str) -> None:
        self.actions.append(action)
        super().assert_writes_allowed(action)


def _context(root: Path) -> VaultContext:
    return VaultContext(status="selected", active_vault_path=str(root))


def _candidate_path(root: Path, *, addendum: bool = False) -> Path:
    return root / journal_draft_relative_path(root, DAY, is_addendum=addendum)


def _stage_candidate(
    root: Path,
    *,
    addendum: bool = False,
    body: str = "I reflected on the day from the generated draft.\n",
    accept_checked: bool = False,
    dismiss_checked: bool = False,
) -> Path:
    path = _candidate_path(root, addendum=addendum)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft_id = f"journal-{DAY.isoformat()}{'-addendum' if addendum else ''}"
    frontmatter = {
        "uuid": draft_id,
        "kind": "journal-draft",
        "journal_candidate_type": "addendum" if addendum else "primary",
        "for_date": DAY.isoformat(),
        "derived_by": "conversation",
        "authority_state": "proposal",
        "sources": ["session:session-abc", "Sources/capture-one.md"],
    }
    accept_label = (
        "Accept and append this addendum to today's journal"
        if addendum
        else "Accept this draft as today's journal entry"
    )
    review = (
        "\n%% AI:Start %%\n"
        "## AI-åtgärder\n\n"
        f"- [{'x' if accept_checked else ' '}] {accept_label}\n"
        f"- [{'x' if dismiss_checked else ' '}] Dismiss this journal candidate\n"
        "%% AI:End %%\n"
    )
    path.write_text(dump_frontmatter(frontmatter, body) + review, encoding="utf-8")
    return path


def _check_accept(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    checked = text.replace("- [ ] Accept", "- [x] Accept")
    assert checked != text
    path.write_text(checked, encoding="utf-8")


def _outbox(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_accept_requires_no_typing(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, accept_checked=True)
    outbox = tmp_path / "outbox.jsonl"

    projection = project_journal_review(vault_context=_context(root), for_date=DAY)
    assert projection.state is JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION
    assert projection.candidate_path == candidate.relative_to(root).as_posix()

    result = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
        now=NOW,
    )

    assert result.state is JournalReviewState.FULLY_MATERIALIZED
    assert result.action == "accept"
    assert result.canonical_path == "1_Calendar/Daily/2026-07-15.md"
    assert not candidate.exists()
    assert (root / result.canonical_path).is_file()


def test_edit_then_accept_promotes_edited_text(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, body="Generated text that I will replace.\n")
    human_edit = "HUMAN EDIT: this is the text I chose to own."
    text = candidate.read_text(encoding="utf-8")
    text = text.replace("Generated text that I will replace.", human_edit)
    candidate.write_text(text.replace("- [ ] Accept", "- [x] Accept"), encoding="utf-8")

    result = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=tmp_path / "outbox.jsonl",
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
        now=NOW,
    )

    _frontmatter, accepted_body = load_frontmatter(
        (root / result.canonical_path).read_text(encoding="utf-8")
    )
    assert human_edit in accepted_body
    assert "Generated text that I will replace." not in accepted_body


def test_dismiss_records_declined_ledger_entry(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, dismiss_checked=True)
    draft_frontmatter, _body = load_frontmatter(candidate.read_text(encoding="utf-8"))
    draft_id = str(draft_frontmatter["uuid"])
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    outbox = tmp_path / "outbox.jsonl"

    result = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        declined_ledger=ledger,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
        now=NOW,
    )

    assert result.action == "dismiss"
    assert result.state is JournalReviewState.DISMISSED
    assert ledger.is_declined(draft_id)
    assert not candidate.exists()
    assert not (root / "1_Calendar/Daily/2026-07-15.md").exists()
    assert [row["event"] for row in _outbox(outbox)] == [JOURNAL_ENTRY_DECLINED_EVENT]


def test_acceptance_asserts_guard_and_stamps_receipt_fields(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, accept_checked=True)
    candidate_frontmatter, _body = load_frontmatter(candidate.read_text(encoding="utf-8"))
    outbox = tmp_path / "outbox.jsonl"
    guard = _RecordingGuard({"state": "healthy"})

    result = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW,
    )

    assert guard.actions and set(guard.actions) == {JOURNAL_ENTRY_ACCEPT_WRITE_ACTION}
    accepted_frontmatter, accepted_body = load_frontmatter(
        (root / result.canonical_path).read_text(encoding="utf-8")
    )
    assert accepted_frontmatter["authority_state"] == "accepted"
    assert accepted_frontmatter["accepted_by"] == "human"
    assert accepted_frontmatter["accepted_at"] == "2026-07-15T20:30:00Z"
    assert accepted_frontmatter["acceptance_receipt_id"] == result.receipt_id
    assert accepted_frontmatter["decision_token_ref"] == result.decision_token_ref
    assert accepted_frontmatter["derived_by"] == "conversation"
    assert accepted_frontmatter["sources"] == candidate_frontmatter["sources"]
    assert "AI-åtgärder" not in accepted_body

    accepted_events = [
        row for row in _outbox(outbox) if row["event"] == JOURNAL_ENTRY_ACCEPTED_EVENT
    ]
    assert len(accepted_events) == 1
    payload = accepted_events[0]["payload"]
    assert payload["draft_id"] == candidate_frontmatter["uuid"]
    assert payload["final_note_path"] == result.canonical_path
    assert payload["sources"] == candidate_frontmatter["sources"]
    assert payload["authority_receipt_id"] == result.receipt_id


def test_engine_cannot_overwrite_accepted_entry(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    _stage_candidate(root, body="The human-owned primary entry.\n", accept_checked=True)
    outbox = tmp_path / "outbox.jsonl"
    guard = WriteGuard(lambda: {"state": "healthy"})
    first = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW,
    )
    canonical = root / first.canonical_path
    accepted_bytes = canonical.read_bytes()

    primary_again = _stage_candidate(
        root,
        body="Machine replacement that must never land.\n",
        accept_checked=True,
    )
    with pytest.raises(JournalAcceptedEntryExistsError):
        process_journal_review(
            vault_context=_context(root),
            for_date=DAY,
            outbox_path=outbox,
            write_guard=guard,
            now=NOW,
        )
    assert canonical.read_bytes() == accepted_bytes
    assert primary_again.exists()

    primary_again.unlink()
    addendum = _stage_candidate(root, addendum=True, body="A distinct later candidate.\n")
    projection = project_journal_review(vault_context=_context(root), for_date=DAY)
    assert projection.candidate_type == "addendum"
    assert projection.candidate_path == addendum.relative_to(root).as_posix()
    assert canonical.read_bytes() == accepted_bytes


def test_blocked_write_path_preserves_acceptance_intent_and_retries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, accept_checked=True)
    outbox = tmp_path / "outbox.jsonl"

    blocked = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=WriteGuard(
            lambda: {"state": "safe_mode", "reason": "operator hold"}
        ),
        now=NOW,
    )

    assert blocked.state is JournalReviewState.ACCEPTED_PENDING_MATERIALIZATION
    assert blocked.status_message == "Accepted — waiting to save"
    assert candidate.exists()
    assert "- [x] Accept" in candidate.read_text(encoding="utf-8")
    assert not (root / "1_Calendar/Daily/2026-07-15.md").exists()
    assert _outbox(outbox) == []

    # Simulate a later healthy process: the durable checked action is enough;
    # no second tap or in-memory pending object is supplied.
    retried = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=WriteGuard(lambda: {"state": "healthy"}),
        now=NOW,
    )
    assert retried.state is JournalReviewState.FULLY_MATERIALIZED
    assert not candidate.exists()
    assert (root / retried.canonical_path).exists()


def test_addendum_acceptance_appends_not_replaces(tmp_path: Path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    _stage_candidate(root, body="Original accepted reflection.\n", accept_checked=True)
    outbox = tmp_path / "outbox.jsonl"
    guard = WriteGuard(lambda: {"state": "healthy"})
    first = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW,
    )
    canonical = root / first.canonical_path
    original_frontmatter, original_body = load_frontmatter(
        canonical.read_text(encoding="utf-8")
    )

    _stage_candidate(
        root,
        addendum=True,
        body="Later reflection that may only be appended.\n",
        accept_checked=True,
    )
    second = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW.replace(hour=22),
    )

    current_frontmatter, current_body = load_frontmatter(
        canonical.read_text(encoding="utf-8")
    )
    assert second.action == "accept_addendum"
    assert current_frontmatter == original_frontmatter
    assert current_body.startswith(original_body)
    assert "Later reflection that may only be appended." in current_body
    assert current_body.count("Original accepted reflection.") == 1
    assert current_body.count("Later reflection that may only be appended.") == 1
    assert f"journal:addendum_receipt_id={second.receipt_id}" in current_body


def test_primary_retry_reconciles_materialization_before_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    candidate = _stage_candidate(root, accept_checked=True)
    outbox = tmp_path / "outbox.jsonl"
    guard = WriteGuard(lambda: {"state": "healthy"})
    real_emit = review_module._emit_event_once

    def interrupt_receipt(*_args: object, **_kwargs: object) -> None:
        raise JournalReviewError("simulated crash before receipt")

    monkeypatch.setattr(review_module, "_emit_event_once", interrupt_receipt)
    with pytest.raises(JournalReviewError, match="simulated crash"):
        process_journal_review(
            vault_context=_context(root),
            for_date=DAY,
            outbox_path=outbox,
            write_guard=guard,
            now=NOW,
        )

    canonical = root / "1_Calendar/Daily/2026-07-15.md"
    materialized = canonical.read_bytes()
    assert candidate.exists()

    monkeypatch.setattr(review_module, "_emit_event_once", real_emit)
    retried = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW.replace(hour=21),
    )

    assert canonical.read_bytes() == materialized
    assert not candidate.exists()
    rows = _outbox(outbox)
    assert len(rows) == 1
    assert rows[0]["event_id"] == retried.receipt_id
    assert rows[0]["timestamp"] == "2026-07-15T20:30:00Z"
    assert rows[0]["payload"]["accepted_at"] == "2026-07-15T20:30:00Z"


def test_addendum_retry_reconciles_append_before_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    outbox = tmp_path / "outbox.jsonl"
    guard = WriteGuard(lambda: {"state": "healthy"})
    _stage_candidate(root, accept_checked=True)
    primary = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW,
    )
    candidate = _stage_candidate(
        root,
        addendum=True,
        body="The append that survives receipt interruption.\n",
        accept_checked=True,
    )
    canonical = root / primary.canonical_path
    real_emit = review_module._emit_event_once

    def interrupt_receipt(*_args: object, **_kwargs: object) -> None:
        raise JournalReviewError("simulated crash before receipt")

    monkeypatch.setattr(review_module, "_emit_event_once", interrupt_receipt)
    with pytest.raises(JournalReviewError, match="simulated crash"):
        process_journal_review(
            vault_context=_context(root),
            for_date=DAY,
            outbox_path=outbox,
            write_guard=guard,
            now=NOW.replace(hour=22),
        )
    materialized = canonical.read_bytes()
    assert candidate.exists()

    monkeypatch.setattr(review_module, "_emit_event_once", real_emit)
    retried = process_journal_review(
        vault_context=_context(root),
        for_date=DAY,
        outbox_path=outbox,
        write_guard=guard,
        now=NOW.replace(hour=23),
    )

    assert canonical.read_bytes() == materialized
    assert not candidate.exists()
    accepted_rows = [
        row for row in _outbox(outbox) if row["event"] == JOURNAL_ENTRY_ACCEPTED_EVENT
    ]
    assert len(accepted_rows) == 2
    addendum_row = next(row for row in accepted_rows if row["event_id"] == retried.receipt_id)
    assert addendum_row["timestamp"] == "2026-07-15T22:30:00Z"
    assert addendum_row["payload"]["accepted_at"] == "2026-07-15T22:30:00Z"
