"""Verify that every non-CES SBS subsystem row in the Boundary Register
has at least one concrete ``app/*`` module anchor, and that every listed
anchor path actually exists on disk.

This test parses the register's Markdown table programmatically so that any
update to the register is automatically validated — no manual sync required.

AC2 of issue #2474.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SBS_REGISTER = REPO_ROOT / "docs" / "architecture" / "SBS_BOUNDARY_REGISTER.md"

# CES is a stewardship practice (no app/* embodiment); its anchor is intentionally absent.
CES_PREFIX = "CES"

# Canonical non-CES SBS Level-2 subsystems (docs/SYSTEM_BREAKDOWN_STRUCTURE.md ::
# Level 2 control-boundary subsystems). The register must carry a row for every one of
# these so a deleted or renamed row cannot silently shrink the module index.
EXPECTED_NON_CES_SUBSYSTEMS = frozenset(
    {"HIX", "WSP", "HKA", "SIP", "GOV", "EBF", "PDM", "DRI", "RCA", "MEM", "CAO", "EXE", "SFC", "OEF"}
)

# Sentinel used in the register for the CES row's current-modules cell.
_CES_SENTINEL_RE = re.compile(r"stewardship practice", re.IGNORECASE)

# Column header as it appears in the Markdown table.
_CURRENT_MODULES_HEADER = "Current modules"

# Backtick-quoted paths like `app/foo/bar.py`
_PATH_RE = re.compile(r"`(app/[^`]+)`")


def _find_current_modules_col_index(header_row: str) -> int:
    """Return the 0-based column index of the 'Current modules' column."""
    cols = [c.strip() for c in header_row.strip().strip("|").split("|")]
    for idx, col in enumerate(cols):
        if col == _CURRENT_MODULES_HEADER:
            return idx
    raise AssertionError(
        f"Column '{_CURRENT_MODULES_HEADER}' not found in SBS_BOUNDARY_REGISTER.md header row. "
        f"Header columns seen: {cols!r}"
    )


def _parse_register() -> dict[str, list[str]]:
    """Return mapping of {subsystem_prefix: [app/path, ...]} from the register table.

    CES rows are mapped to an empty list (exempt from path requirements).
    Subsystem prefix is the uppercase tag before the first space/dash, e.g. 'HIX'.
    """
    text = SBS_REGISTER.read_text(encoding="utf-8")

    lines = text.splitlines()

    # Locate the table: find the header row (contains all column names)
    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _CURRENT_MODULES_HEADER in line and line.strip().startswith("|"):
            header_idx = i
            break

    assert header_idx is not None, (
        f"Could not find a Markdown table header containing '{_CURRENT_MODULES_HEADER}' "
        f"in {SBS_REGISTER.relative_to(REPO_ROOT)}"
    )

    col_idx = _find_current_modules_col_index(lines[header_idx])

    result: dict[str, list[str]] = {}

    # Rows follow the header; skip the separator line (contains only dashes/pipes)
    for line in lines[header_idx + 1 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            # End of table
            break
        # Skip separator rows like |---|---:|...
        if re.fullmatch(r"[\|\-\:\s]+", stripped):
            continue

        cols = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cols) <= col_idx:
            continue

        boundary_cell = cols[0].strip()
        modules_cell = cols[col_idx].strip()

        # Extract the subsystem prefix (e.g. "HIX" from "HIX - Human Interaction…")
        prefix_match = re.match(r"([A-Z]+)\b", boundary_cell)
        if not prefix_match:
            continue
        prefix = prefix_match.group(1)

        if prefix == CES_PREFIX:
            # CES is exempt; record it as empty so completeness check skips it
            result[prefix] = []
            continue

        paths = _PATH_RE.findall(modules_cell)
        result[prefix] = paths

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sbs_register_exists() -> None:
    """The register file itself must exist — if this fails, the test suite is misconfigured."""
    assert SBS_REGISTER.exists(), (
        f"SBS_BOUNDARY_REGISTER.md not found at expected path: {SBS_REGISTER}"
    )


def test_subsystem_module_anchors_exist() -> None:
    """Every app/* anchor listed in the register must exist on disk."""
    anchors = _parse_register()

    missing: list[str] = []
    for subsystem, paths in anchors.items():
        for rel_path in paths:
            full_path = REPO_ROOT / rel_path
            if not full_path.exists():
                missing.append(f"  {subsystem}: {rel_path!r} — path does not exist")

    assert not missing, (
        "The following SBS module anchors listed in SBS_BOUNDARY_REGISTER.md do not exist on disk.\n"
        "Either add the file, correct the path in the register, or update the anchor.\n\n"
        + "\n".join(missing)
    )


def test_every_non_ces_subsystem_has_at_least_one_anchor() -> None:
    """Every non-CES subsystem must have a register row with at least one app/* anchor.

    Guards two forms of silent index rot: (1) an entire subsystem row being deleted or
    renamed away — caught by comparing parsed prefixes against the canonical SBS subsystem
    set — and (2) a present row losing all of its anchors.
    """
    anchors = _parse_register()

    missing_rows = EXPECTED_NON_CES_SUBSYSTEMS - set(anchors.keys())
    assert not missing_rows, (
        "The following canonical SBS subsystems have no row in SBS_BOUNDARY_REGISTER.md "
        "(deleted, renamed, or unparsed) — the module index no longer covers every subsystem:\n\n"
        + "\n".join(f"  {s}" for s in sorted(missing_rows))
    )

    without_anchor = [
        subsystem
        for subsystem, paths in anchors.items()
        if subsystem != CES_PREFIX and not paths
    ]

    assert not without_anchor, (
        "The following non-CES subsystems in SBS_BOUNDARY_REGISTER.md have no app/* anchor "
        "in the 'Current modules' column. Add at least one existing app/* path for each:\n\n"
        + "\n".join(f"  {s}" for s in sorted(without_anchor))
    )


@pytest.mark.parametrize(
    "subsystem,path",
    [
        (sub, p)
        for sub, paths in _parse_register().items()
        for p in paths
    ],
)
def test_anchor_path_exists_parametrized(subsystem: str, path: str) -> None:
    """Parametrized mirror of the bulk test — names the exact subsystem+path on failure."""
    full_path = REPO_ROOT / path
    assert full_path.exists(), (
        f"SBS anchor for {subsystem!r} points to a missing file: {path!r}\n"
        f"Full path checked: {full_path}"
    )
