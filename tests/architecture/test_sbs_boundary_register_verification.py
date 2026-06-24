"""Verify that every row in the SBS Boundary Register has non-empty
"Verification owner" and "Expected receipts/artifacts" cells.

This is AC2 of issue #2477 — per-subsystem verification and receipt
responsibility register.

The test parses the register table programmatically, compares the parsed
set of subsystem rows against the canonical 15-row SBS subsystem set
(14 Level-2 subsystems + CES), and asserts that both new cells are
non-empty for every row.  A deleted or renamed row is caught because
the canonical set is checked against the parsed set, not only the
other way around.
"""

from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SBS_REGISTER = REPO_ROOT / "docs" / "architecture" / "SBS_BOUNDARY_REGISTER.md"

# ---------------------------------------------------------------------------
# Canonical subsystem set — 14 Level-2 control-boundary subsystems + CES
# (docs/SYSTEM_BREAKDOWN_STRUCTURE.md :: Level 2 subsystems).
# Any deleted or renamed register row will be caught against this set.
# ---------------------------------------------------------------------------

CANONICAL_SUBSYSTEMS: frozenset[str] = frozenset(
    {
        "HIX",
        "WSP",
        "HKA",
        "SIP",
        "GOV",
        "EBF",
        "PDM",
        "DRI",
        "RCA",
        "MEM",
        "CAO",
        "EXE",
        "SFC",
        "OEF",
        "CES",
    }
)

# Column headers as they appear in the Markdown table
_VERIFICATION_OWNER_HEADER = "Verification owner"
_EXPECTED_RECEIPTS_HEADER = "Expected receipts/artifacts"


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------


def _find_col_index(header_row: str, col_name: str) -> int:
    """Return the 0-based column index for *col_name* in a Markdown header row.

    Raises AssertionError with a descriptive message when the column is absent.
    """
    cols = [c.strip() for c in header_row.strip().strip("|").split("|")]
    for idx, col in enumerate(cols):
        if col == col_name:
            return idx
    raise AssertionError(
        f"Column {col_name!r} not found in SBS_BOUNDARY_REGISTER.md header row.\n"
        f"Columns seen: {cols!r}\n"
        "Add the column to the register table or correct the column name here."
    )


def _parse_register() -> dict[str, dict[str, str]]:
    """Parse the boundary register table and return per-subsystem cell values.

    Returns
    -------
    dict mapping subsystem prefix (e.g. "HIX") to a dict with keys
    "verification_owner" and "expected_receipts", containing the raw cell text.
    An empty string means the cell was blank or missing.
    """
    text = SBS_REGISTER.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate the header row that contains both target column names.
    header_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            stripped.startswith("|")
            and _VERIFICATION_OWNER_HEADER in stripped
            and _EXPECTED_RECEIPTS_HEADER in stripped
        ):
            header_idx = i
            break

    assert header_idx is not None, (
        f"Could not find a Markdown table header containing both "
        f"{_VERIFICATION_OWNER_HEADER!r} and {_EXPECTED_RECEIPTS_HEADER!r} "
        f"in {SBS_REGISTER.relative_to(REPO_ROOT)}.\n"
        "Ensure both columns exist in the register table header row."
    )

    header_row = lines[header_idx]
    vo_idx = _find_col_index(header_row, _VERIFICATION_OWNER_HEADER)
    er_idx = _find_col_index(header_row, _EXPECTED_RECEIPTS_HEADER)

    result: dict[str, dict[str, str]] = {}

    # Data rows follow the header; skip the separator line
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            # End of table
            break
        # Skip separator rows (only dashes, pipes, colons, spaces)
        if re.fullmatch(r"[\|\-\:\s]+", stripped):
            continue

        cols = [c.strip() for c in stripped.strip("|").split("|")]

        # Extract subsystem prefix from the first cell (e.g. "HIX" from "HIX - …")
        boundary_cell = cols[0].strip() if cols else ""
        prefix_match = re.match(r"([A-Z]+)\b", boundary_cell)
        if not prefix_match:
            continue
        prefix = prefix_match.group(1)

        vo_val = cols[vo_idx].strip() if len(cols) > vo_idx else ""
        er_val = cols[er_idx].strip() if len(cols) > er_idx else ""

        result[prefix] = {
            "verification_owner": vo_val,
            "expected_receipts": er_val,
        }

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sbs_register_exists() -> None:
    """The register file must exist — if this fails, the test suite is misconfigured."""
    assert SBS_REGISTER.exists(), (
        f"SBS_BOUNDARY_REGISTER.md not found at expected path: {SBS_REGISTER}"
    )


def test_register_has_verification_columns() -> None:
    """The register table header must carry both new columns.

    This catches a future accidental column removal before the per-row checks run.
    """
    text = SBS_REGISTER.read_text(encoding="utf-8")
    assert _VERIFICATION_OWNER_HEADER in text, (
        f"Column {_VERIFICATION_OWNER_HEADER!r} is absent from SBS_BOUNDARY_REGISTER.md. "
        "Add it to the table header."
    )
    assert _EXPECTED_RECEIPTS_HEADER in text, (
        f"Column {_EXPECTED_RECEIPTS_HEADER!r} is absent from SBS_BOUNDARY_REGISTER.md. "
        "Add it to the table header."
    )


def test_every_subsystem_has_verification_owner() -> None:
    """Every canonical SBS subsystem row must have non-empty 'Verification owner'
    AND 'Expected receipts/artifacts' cells.

    Three checks are performed:
    1. Canonical completeness: every subsystem in CANONICAL_SUBSYSTEMS is present in
       the parsed register (guards against a row being deleted or renamed).
    1b. No unexpected rows: the parsed set contains no prefix outside the canonical
       set (guards against typos or silently added rows).
    2. Cell completeness: every PARSED row has non-empty values in both cells
       (guards against any row — canonical or newly added — being left blank).
    """
    parsed = _parse_register()

    # 1. Canonical completeness check
    missing_rows = CANONICAL_SUBSYSTEMS - set(parsed.keys())
    assert not missing_rows, (
        "The following canonical SBS subsystems have no parseable row in "
        "SBS_BOUNDARY_REGISTER.md (deleted, renamed, or unparsed). "
        "Every canonical subsystem must have a register row:\n\n"
        + "\n".join(f"  {s}" for s in sorted(missing_rows))
    )

    # 1b. No unexpected rows — only the canonical 15 subsystems are allowed.
    unexpected_rows = set(parsed.keys()) - CANONICAL_SUBSYSTEMS
    assert not unexpected_rows, (
        "Unexpected (non-canonical) subsystem rows parsed from "
        "SBS_BOUNDARY_REGISTER.md. If a new subsystem was genuinely added, "
        "update CANONICAL_SUBSYSTEMS in this test:\n\n"
        + "\n".join(f"  {s}" for s in sorted(unexpected_rows))
    )

    # 2. Cell completeness check — iterate PARSED rows (not just the canonical set),
    #    so a newly added row with blank cells is also caught.
    blank_vo: list[str] = []
    blank_er: list[str] = []

    for subsystem in sorted(parsed.keys()):
        row = parsed.get(subsystem, {})
        if not row.get("verification_owner"):
            blank_vo.append(subsystem)
        if not row.get("expected_receipts"):
            blank_er.append(subsystem)

    errors: list[str] = []
    if blank_vo:
        errors.append(
            "Subsystems with an empty 'Verification owner' cell:\n"
            + "\n".join(f"  {s}" for s in blank_vo)
        )
    if blank_er:
        errors.append(
            "Subsystems with an empty 'Expected receipts/artifacts' cell:\n"
            + "\n".join(f"  {s}" for s in blank_er)
        )

    assert not errors, (
        "SBS_BOUNDARY_REGISTER.md is missing verification ownership data.\n"
        "Fill both 'Verification owner' and 'Expected receipts/artifacts' for every row.\n\n"
        + "\n\n".join(errors)
    )
