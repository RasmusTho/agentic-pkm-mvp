"""Shared fixtures for the SQ-02 registration acceptance tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.standing_questions.question_store import QuestionStore
from app.write_guard import WriteGuard

CAPTURE_REL_PATH = "captures/2026-07-14-rostanteckning.md"
EXTRACTED_QUESTION = "should we fully migrate to BGE-M3?"
CAPTURE_BODY = f"""---
uuid: capture-uuid-1
kind: capture
---

# Röstanteckning 2026-07-14

Note to self: {EXTRACTED_QUESTION} Find out before the Q3 planning round.

%% AI:Start %%
## AI-instruktion

## AI-åtgärder
%% AI:End %%
"""

NON_QUESTION_REL_PATH = "captures/2026-07-15-inkop.md"
NON_QUESTION_BODY = """---
uuid: capture-uuid-2
kind: capture
---

# Inköp

Bought oat milk and rye bread on the way home.

%% AI:Start %%
## AI-instruktion

## AI-åtgärder
%% AI:End %%
"""


def healthy_store(vault: Path) -> QuestionStore:
    return QuestionStore(vault, write_guard=WriteGuard(snapshot_fn=lambda: {"state": "healthy"}))


def healthy_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy"})


def write_capture(
    vault: Path,
    relative_path: str = CAPTURE_REL_PATH,
    body: str = CAPTURE_BODY,
) -> Path:
    path = vault / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


def completion_returning(raw: str | dict[str, Any]):
    """Deterministic raw-completion stub that records every prompt it saw."""
    payload = raw if isinstance(raw, str) else json.dumps(raw)
    prompts: list[str] = []

    def complete(
        *,
        system: str,
        user: str,
        trace_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        prompts.append(user)
        return payload

    complete.prompts = prompts  # type: ignore[attr-defined]
    return complete


def registration_payload(
    extracted: str | None = EXTRACTED_QUESTION,
    *,
    intent_class: str = "question_registration",
) -> dict[str, Any]:
    return {
        "intent_class": intent_class,
        "extracted_text": extracted,
        "rationale": "explicit note-to-self registration intent",
    }


def question_notes(vault: Path) -> list[Path]:
    questions_dir = vault / "questions"
    if not questions_dir.exists():
        return []
    return sorted(questions_dir.glob("sq-*.md"))


def check_the_box(capture_path: Path, extracted_text: str) -> None:
    """Simulate the human tapping the suggested checkbox in their editor."""
    text = capture_path.read_text(encoding="utf-8")
    needle = f'- [ ] Registrera stående fråga: "{extracted_text}"'
    assert needle in text, "no unchecked registration proposal to check"
    capture_path.write_text(
        text.replace(needle, needle.replace("- [ ]", "- [x]", 1), 1), encoding="utf-8"
    )
