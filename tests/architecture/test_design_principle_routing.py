"""Static checks for the canonical whole-system design-principle kernel."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PRINCIPLES = REPO_ROOT / "docs" / "DESIGN_PRINCIPLES.md"
PROJECTION_DOCS = (
    REPO_ROOT / "docs" / "PROJECT_KERNEL.md",
    REPO_ROOT / "docs" / "MODULAR_ARCHITECTURE.md",
)

EXPECTED_PRINCIPLES = {
    "1. Boundary-First Design": "DP-01",
    "2. Capability-Based Composition": "DP-02",
    "2A. Interaction-First Architecture": "DP-02A",
    "2B. Foundation Before Agency": "DP-02B",
    "3. Separation of System Layers": "DP-03",
    "4. Explicit Mutation Authority": "DP-04",
    "5. Governance Before Autonomy": "DP-05",
    "6. Contracts Over Implementations": "DP-06",
    "7. Modularity With Replaceability": "DP-07",
    "8. Flexibility Without Semantic Drift": "DP-08",
    "9. Volatility Isolation": "DP-09",
    "10. Single-Operator Scale": "DP-10",
    "11. Shared Visual Language": "DP-11",
}
EXPECTED_IDS = tuple(EXPECTED_PRINCIPLES.values())
ALLOWED_ENFORCEMENT = {"blocking", "advisory", "manual-review"}

ROUTING_LINE = re.compile(
    r"^\*\*Routing metadata:\*\* "
    r"ID `(?P<id>DP-[0-9A-Z]+)`; "
    r"applicability `(?P<applicability>[a-z0-9-]+)`; "
    r"owner `(?P<owner>[^`]+)`; "
    r"required reading `(?P<required_reading>[^`]+)`; "
    r"enforcement `(?P<enforcement>[a-z-]+)`\.$",
    re.MULTILINE,
)
PRINCIPLE_HEADING = re.compile(r"^### (?P<title>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class RoutingMetadata:
    title: str
    principle_id: str
    applicability: str
    owner: str
    required_reading: str
    enforcement: str


def _parse_routing_metadata(text: str) -> list[RoutingMetadata]:
    headings = list(PRINCIPLE_HEADING.finditer(text))
    parsed: list[RoutingMetadata] = []
    for index, heading in enumerate(headings):
        title = heading.group("title")
        if title not in EXPECTED_PRINCIPLES:
            continue
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        matches = list(ROUTING_LINE.finditer(text, heading.end(), section_end))
        assert len(matches) == 1, (
            f"Canonical principle {title!r} must contain exactly one routing metadata line; "
            f"found {len(matches)}"
        )
        match = matches[0]
        parsed.append(
            RoutingMetadata(
                title=title,
                principle_id=match.group("id"),
                applicability=match.group("applicability"),
                owner=match.group("owner"),
                required_reading=match.group("required_reading"),
                enforcement=match.group("enforcement"),
            )
        )
    return parsed


def _reference_resolves(reference: str) -> bool:
    path_text, separator, section = reference.partition(" :: ")
    path = REPO_ROOT / path_text
    if not path.is_file():
        return False
    if not separator:
        return True
    headings = {
        match.group("title").strip()
        for match in re.finditer(r"^#{1,6} (?P<title>.+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    }
    return section in headings


def test_canonical_principles_have_unique_resolvable_routing_metadata() -> None:
    text = CANONICAL_PRINCIPLES.read_text(encoding="utf-8")
    metadata = _parse_routing_metadata(text)

    assert [entry.title for entry in metadata] == list(EXPECTED_PRINCIPLES)
    assert [entry.principle_id for entry in metadata] == list(EXPECTED_IDS)
    assert len({entry.principle_id for entry in metadata}) == len(metadata)

    for entry in metadata:
        expected_owner = f"docs/DESIGN_PRINCIPLES.md :: {entry.title}"
        assert entry.applicability
        assert entry.owner == expected_owner
        assert _reference_resolves(entry.owner), f"Unresolvable owner reference: {entry.owner}"
        assert _reference_resolves(entry.required_reading), (
            f"Unresolvable required-reading reference: {entry.required_reading}"
        )
        assert entry.enforcement in ALLOWED_ENFORCEMENT


def test_principle_projections_reference_canonical_ids_without_redefining_them() -> None:
    canonical_pointer = "docs/DESIGN_PRINCIPLES.md :: System Design Principles"

    for path in PROJECTION_DOCS:
        text = path.read_text(encoding="utf-8")
        assert canonical_pointer in text, f"{path.name} lacks the canonical principle pointer"
        assert "projection only; it is not a second principle registry" in text
        for principle_id in EXPECTED_IDS:
            assert f"`{principle_id}`" in text, f"{path.name} lacks {principle_id}"
        assert "**Routing metadata:**" not in text
