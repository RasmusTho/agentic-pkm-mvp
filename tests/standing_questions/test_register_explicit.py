"""Path (b) -- explicit companion-UI registration (SQ-02).

Covers `docs/STANDING_QUESTIONS/REGISTER_QUESTIONS_FRICTION_FREE.md` AC7: taking the
explicit registration action *is* the human confirmation, so it writes through the
SQ-01 guarded seam directly with no proposal/confirm step.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.standing_questions.registration import register_question_explicitly
from app.write_guard import WriteGuard, WritesBlockedError

from tests.standing_questions._registration_fixtures import (
    healthy_store,
    make_vault,
    question_notes,
)

QUESTION = "What's our stance on cross-scope federation?"


def test_explicit_registration_writes_directly(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    store = healthy_store(vault)

    note, receipt = register_question_explicitly(
        text=QUESTION, scope="work", vault_root=vault, store=store
    )

    assert len(question_notes(vault)) == 1
    assert note["status"] == "open"
    assert note["registered_via"] == "explicit"
    # The human's own words, stored verbatim -- no classifier in this path at all.
    assert note["text"] == QUESTION
    assert note["scope"] == "work"
    assert note["evidence"] == []
    assert f"questions/{note['question_id']}.md" in str(receipt.locator)

    stored = store.read_question(note["question_id"])
    assert stored == note

    # No proposal surface is created on this path: there is nothing to confirm.
    assert list(vault.rglob("*.md")) == question_notes(vault)


def test_explicit_registration_rejects_blank_text(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    store = healthy_store(vault)

    with pytest.raises(ValueError):
        register_question_explicitly(text="   ", scope="work", vault_root=vault, store=store)

    assert question_notes(vault) == []


def test_explicit_registration_is_writeguard_gated(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    from app.standing_questions.question_store import QuestionStore

    blocked = QuestionStore(
        vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test"})
    )

    with pytest.raises(WritesBlockedError):
        register_question_explicitly(
            text=QUESTION, scope="work", vault_root=vault, store=blocked
        )

    assert question_notes(vault) == []
