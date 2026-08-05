"""Guard ADR-0050's temporary Bifrost hub-tracking condition in the SBS operating model.

Issue #4327 (review thread r3564898001 on PR #3496): the operating model's cross-repo
tracking statement must carry ADR-0050's limiting condition — hub tracking applies only
until Bifrost has its own board — so future agents do not read hub tracking as a
permanent routing rule. ADR-0050 stays authoritative; the operating model links to it.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATING_MODEL = REPO_ROOT / "docs" / "architecture" / "SBS_OPERATING_MODEL.md"
ADR_0050 = REPO_ROOT / "docs" / "adr" / "ADR-0050-cross-repo-governance-and-bifrost-client-repo.md"

# ADR-0050 :: Decision 1 ("One source of truth for tracking"): hub tracking holds only
# until Bifrost has its own board.
TRACKING_CONDITION = "until Bifrost has its own board"


def _cross_repo_scope_section(text: str) -> str:
    match = re.search(
        r"^### Cross-repo constituent-surface scope\n(.*?)(?=^#{2,3} )",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, (
        "SBS_OPERATING_MODEL.md no longer has the 'Cross-repo constituent-surface scope' "
        "subsection; update this test's anchor alongside the doc."
    )
    return match.group(1)


def test_bifrost_tracking_condition_matches_adr_0050() -> None:
    adr_text = ADR_0050.read_text(encoding="utf-8")
    assert TRACKING_CONDITION in adr_text, (
        "ADR-0050 no longer states the hub-tracking condition "
        f"{TRACKING_CONDITION!r}; it is the authority this test mirrors — "
        "re-align the operating model and this test with the superseding decision."
    )

    section = _cross_repo_scope_section(OPERATING_MODEL.read_text(encoding="utf-8"))
    assert TRACKING_CONDITION in section, (
        "SBS_OPERATING_MODEL.md :: Cross-repo constituent-surface scope states the hub "
        f"tracking posture without ADR-0050's limiting condition {TRACKING_CONDITION!r}; "
        "hub tracking is temporary, not a permanent routing rule (issue #4327)."
    )
    assert "ADR-0050" in section, (
        "The cross-repo scope subsection must keep referencing ADR-0050 as the "
        "authoritative decision record rather than duplicating its content."
    )
