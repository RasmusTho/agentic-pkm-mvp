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


def _section_lines(text: str, heading: str) -> list[str]:
    """Return lines belonging to the markdown section starting with '## {heading}'."""
    lines = text.splitlines()
    in_section = False
    result: list[str] = []
    for line in lines:
        if line.startswith(f"## {heading}"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            result.append(line)
    return result


def test_code_inventory_classifies_known_legacy_candidates() -> None:
    """app/store is a distinct row in the Deprecated section.
    app/agent and app/plugins were removed in #1171 and are no longer in the deprecated table.
    """
    assert CODE_INVENTORY.exists(), "docs/CODE_INVENTORY.md is missing"
    text = CODE_INVENTORY.read_text(encoding="utf-8")
    assert "Deprecated" in text, (
        "docs/CODE_INVENTORY.md must contain a 'Deprecated' section"
    )
    deprecated_lines = _section_lines(text, "Deprecated Packages")
    # Match backtick-quoted cells so `app/store` cannot falsely match inside `app/stores`
    for pkg in ("app/store",):
        cell = f"`{pkg}`"
        assert any(cell in line for line in deprecated_lines), (
            f"docs/CODE_INVENTORY.md must have a '{cell}' row in the Deprecated section "
            f"(substring match on '{pkg}' is insufficient — it would match app/stores)"
        )
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
