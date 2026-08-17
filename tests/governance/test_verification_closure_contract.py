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
        "For a verified\nGitHub-label-only fallback",
        "dispatcher unavailability or a missing dispatcher task does not invalidate\nthat fallback",
        "do not unblock\nan Issue carrying `agent:needs-human`",
        "prospective post-unblock label set by replacing\n`agent:blocked` with `agent:ready`",
        "strict issue-readiness validation against that current\nbody and prospective label set",
        "Only then make the explicit lifecycle mutation and read it back",
    ):
        assert requirement in text
