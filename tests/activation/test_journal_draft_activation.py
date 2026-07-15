from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.activation.gate import REASON_LOOP_PRECONDITION_NOT_GREEN
from app.activation.journal_draft import (
    JOURNAL_DRAFT_CAPABILITY_ID,
    build_journal_draft_posture,
    evaluate_journal_draft_activation,
)
from app.journaling.draft import JournalDraftBlockedError, draft_journal_entry
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard


def test_draft_requires_activation_record(tmp_path: Path) -> None:
    green = evaluate_journal_draft_activation(["session:abc", "Sources/day.md"])
    assert green.capability_id == JOURNAL_DRAFT_CAPABILITY_ID
    assert green.activatable is True
    assert green.receipt.outcome == "activatable"

    regressed = build_journal_draft_posture(loop_precondition_green=False)
    blocked = evaluate_journal_draft_activation(["session:abc"], posture=regressed)
    assert blocked.activatable is False
    assert REASON_LOOP_PRECONDITION_NOT_GREEN in blocked.blocked_reasons

    root = tmp_path / "vault"
    session = root / ".chats" / "reflection.md"
    session.parent.mkdir(parents=True)
    session.write_text(
        "---\ntype: chat-session\nsession_id: abc\n---\n\n**Owner:** A thought.\n",
        encoding="utf-8",
    )
    context = VaultContext(status="selected", active_vault_path=str(root))
    with pytest.raises(JournalDraftBlockedError, match="loop_precondition_not_green"):
        draft_journal_entry(
            vault_context=context,
            for_date=date(2026, 7, 15),
            session_id="abc",
            activation_posture=regressed,
            write_guard=WriteGuard(lambda: {"state": "healthy"}),
        )
    assert not list(root.rglob("2026-07-15*.md"))
