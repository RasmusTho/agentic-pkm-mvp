from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "AGENTS.md"
INTEGRATION = ROOT / ".codex/skills/pr-integration/SKILL.md"
CLOSURE = ROOT / ".codex/skills/verification-and-closure/SKILL.md"


def test_late_change_supersedes_affected_evidence() -> None:
    closure = CLOSURE.read_text(encoding="utf-8")
    integration = INTEGRATION.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")

    for text in (agents, integration, closure):
        normalized = text.lower()
        assert "late-change supersession" in normalized
        assert "affected evidence" in normalized
        assert "rerun" in normalized
        assert "mutable authority" in normalized
        assert "digest/version" in normalized

    assert "late_change_supersession_receipt.v1" in closure


def test_closure_rejects_stale_evidence_after_late_change() -> None:
    closure = CLOSURE.read_text(encoding="utf-8")
    merge_prerequisites = closure.split("Prerequisites for merge", 1)[1].split(
        "### Running the local review gate", 1
    )[0]

    assert "late-change supersession" in merge_prerequisites
    assert "must not merge or close" in merge_prerequisites
    assert "current head SHA" in merge_prerequisites
    assert "late_change_supersession_receipt.v1" in merge_prerequisites
    assert "mutable authority" in merge_prerequisites
