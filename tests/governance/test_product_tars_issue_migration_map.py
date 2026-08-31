from __future__ import annotations

import re
from pathlib import Path


MAP = Path(__file__).resolve().parents[2] / "docs/deployment/PRODUCT_TARS_CHANNEL_ISSUE_MIGRATION_MAP.md"
EXPECTED_ISSUES = {
    5237, 5181, 5056, 5052, 4918, 4913, 4899, 4785, 4773, 4767, 4749, 4741,
    4697, 4076, 3925, 3843, 3793, 3788, 3690, 3657, 3604, 3603, 3409, 3376,
    3341, 3340, 3335, 3331, 3325, 3314, 3191, 3175, 3169, 2965, 2292, 2086, 3367,
}
ALLOWED = {
    "valid control/client use",
    "topology reconciliation",
    "human gate after prerequisites",
    "superseded",
    "protected in-progress",
}


def _rows() -> list[tuple[int, str, str]]:
    rows: list[tuple[int, str, str]] = []
    for line in MAP.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| #(\d+) \| ([^|]+) \| ([^|]+) \|$", line)
        if match:
            rows.append((int(match.group(1)), match.group(2).strip(), match.group(3).strip()))
    return rows


def test_every_live_material_issue_has_one_disposition() -> None:
    rows = _rows()
    assert {issue for issue, _disposition, _next_action in rows} == EXPECTED_ISSUES
    assert len(rows) == len(EXPECTED_ISSUES)
    for _issue, disposition, next_action in rows:
        assert disposition in ALLOWED
        assert next_action.endswith(".")
        assert len(next_action) > len("next action")


def test_migration_map_preserves_authority_boundaries() -> None:
    text = MAP.read_text(encoding="utf-8")
    assert "does not change Issue lifecycle" in text
    assert "VM 102 remains" in text
    assert "Product Runtime channel placement remains the" in text
    assert "local Compose/Colima remains fallback-only" in text


def test_migration_map_declares_reproducible_snapshot_provenance() -> None:
    text = MAP.read_text(encoding="utf-8")
    assert "gh issue list --repo RasmusTho/agentic-pkm-mvp --state open" in text
    assert "searching Issue title and body" in text
    assert "37 matches" in text
    assert "#3314 and #3367" in text
