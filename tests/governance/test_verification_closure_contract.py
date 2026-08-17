from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / ".codex/skills/verification-and-closure/SKILL.md"


def test_terminal_closure_requires_source_thread_and_dispatcher_readback() -> None:
    text = SKILL.read_text(encoding="utf-8")

    triggered_section = text.split("[review-thread-closure]", 1)[0]
    assert "only when a review-thread closure trigger is present" in triggered_section
    assert "Preserve the lightweight hot path for ordinary PRs with no trigger" in triggered_section

    for requirement in (
        "original actionable thread node IDs",
        "every one before final closure",
        "re-read those same\n  original thread IDs through `reviewThreads`",
        "final resolved state",
        "matching\n  reply or disposition evidence for each",
        "Record that final readback in the delivery receipt",
        "python3 -m app.dispatcher status --json",
        "python3 -m app.dispatcher show <task-id> --json",
        "strict\nissue-readiness validation against that current body and labels",
        "Only then make the explicit lifecycle mutation and read it\nback",
    ):
        assert requirement in text
