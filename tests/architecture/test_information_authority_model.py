"""Contract checks for the cross-plane information-authority model."""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = REPO_ROOT / "docs" / "architecture" / "INFORMATION_AUTHORITY_MODEL.md"


def test_direct_repair_pr_contract_exception_is_preserved() -> None:
    text = MODEL_PATH.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert (
        "For issue-backed work, the GitHub Issue remains the executable Builder task contract"
        in normalized
    )
    assert (
        "A bounded Issue-free direct-repair PR is the explicit exception"
        in normalized
    )
    assert "its complete `Direct Repair` block is the task contract" in normalized
    assert "PR still remains delivery and review evidence" in normalized
