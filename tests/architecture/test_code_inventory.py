from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CODE_INVENTORY = REPO_ROOT / "docs" / "CODE_INVENTORY.md"


def test_code_inventory_declares_canonical_runtime_paths() -> None:
    """CODE_INVENTORY.md exists and has a canonical runtime paths section."""
    assert CODE_INVENTORY.exists(), "docs/CODE_INVENTORY.md is missing"
    text = CODE_INVENTORY.read_text(encoding="utf-8")
    assert "Canonical Runtime Paths" in text, (
        "docs/CODE_INVENTORY.md must contain a 'Canonical Runtime Paths' section"
    )
    # Spot-check that at least a few primary runtime packages are listed
    for pkg in ("app/api", "app/watcher", "app/workers", "app/outbox"):
        assert pkg in text, (
            f"docs/CODE_INVENTORY.md must list {pkg} as a canonical runtime package"
        )


def test_code_inventory_classifies_known_legacy_candidates() -> None:
    """app/agent, app/plugins, and app/store are classified as deprecated."""
    assert CODE_INVENTORY.exists(), "docs/CODE_INVENTORY.md is missing"
    text = CODE_INVENTORY.read_text(encoding="utf-8")
    # The deprecated section must be present
    assert "Deprecated" in text, (
        "docs/CODE_INVENTORY.md must contain a 'Deprecated' section"
    )
    for pkg in ("app/agent", "app/plugins", "app/store"):
        assert pkg in text, (
            f"docs/CODE_INVENTORY.md must classify {pkg} under the deprecated section"
        )
    # Confirm the word 'deprecated' appears in relation to these packages in the doc
    lower = text.lower()
    assert "deprecated" in lower, (
        "docs/CODE_INVENTORY.md must use the word 'deprecated' for legacy packages"
    )


def test_code_inventory_distinguishes_planned_from_deprecated() -> None:
    """app/sync, app/orientation, and app/resurfacing are classified as planned (not deprecated)."""
    assert CODE_INVENTORY.exists(), "docs/CODE_INVENTORY.md is missing"
    text = CODE_INVENTORY.read_text(encoding="utf-8")
    assert "Planned" in text, (
        "docs/CODE_INVENTORY.md must contain a 'Planned' section"
    )
    for pkg in ("app/sync", "app/orientation", "app/resurfacing"):
        assert pkg in text, (
            f"docs/CODE_INVENTORY.md must list {pkg} under the planned section"
        )
    # Verify the doc distinguishes planned from deprecated (both words must appear)
    lower = text.lower()
    assert "planned" in lower, (
        "docs/CODE_INVENTORY.md must use the word 'planned' for reserved seam packages"
    )
    assert "deprecated" in lower, (
        "docs/CODE_INVENTORY.md must use the word 'deprecated' so the two statuses are distinguishable"
    )
    # The planned packages must not appear in a 'deprecated' table row
    lines = text.splitlines()
    deprecated_section = False
    planned_section = False
    deprecated_lines: list[str] = []
    planned_lines: list[str] = []
    for line in lines:
        if "## Deprecated" in line:
            deprecated_section = True
            planned_section = False
        elif "## Planned" in line:
            planned_section = True
            deprecated_section = False
        elif line.startswith("## "):
            deprecated_section = False
            planned_section = False
        if deprecated_section:
            deprecated_lines.append(line)
        if planned_section:
            planned_lines.append(line)

    for pkg in ("app/sync", "app/orientation", "app/resurfacing"):
        in_deprecated = any(pkg in l for l in deprecated_lines)
        assert not in_deprecated, (
            f"{pkg} must not appear in the Deprecated section — it is planned, not deprecated"
        )
        in_planned = any(pkg in l for l in planned_lines)
        assert in_planned, (
            f"{pkg} must appear in the Planned section"
        )
