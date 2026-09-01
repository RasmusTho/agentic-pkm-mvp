"""Governance checks for the canonical Builder design-packet reading route."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDER_SURFACES = (
    "AGENTS.md",
    ".codex/skills/README.md",
    ".codex/skills/agentic-pkm/SKILL.md",
    ".codex/skills/issue-to-code/SKILL.md",
    ".codex/skills/docs-governance/SKILL.md",
)
ROUTE_REFERENCE = ".codex/skills/README.md :: Structural-work design packet route"
PRODUCT_PRINCIPLE_HEADINGS = (
    "Boundary-First Design",
    "Capability-Based Composition",
    "Interaction-First Architecture",
    "Foundation Before Agency",
    "Separation of System Layers",
    "Explicit Mutation Authority",
    "Governance Before Autonomy",
    "Contracts Over Implementations",
)


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _normalized(path: str) -> str:
    return " ".join(_read(path).split())


def test_structural_changes_use_minimal_design_packet() -> None:
    index = _normalized(".codex/skills/README.md")
    route = index.split("## Structural-work design packet route", maxsplit=1)[1].split(
        "## Skill routing", maxsplit=1
    )[0]

    assert "design_packet.v1" in route
    assert "app.governance.design_packet_resolver" in route
    for fact in (
        "changed_paths",
        "system_classification",
        "write_class",
        "persistence_class",
        "external_effects",
        "risk_triggers",
    ):
        assert fact in route
    assert "exact owner-document sections returned by the packet" in route
    assert "independently mandatory workflow contracts" in route
    assert all(
        (path == ".codex/skills/README.md" and "## Structural-work design packet route" in _normalized(path))
        or ROUTE_REFERENCE in _normalized(path)
        for path in BUILDER_SURFACES
    )


def test_packet_refusal_falls_back_to_explicit_authority_route() -> None:
    route = _normalized(".codex/skills/README.md").split(
        "## Structural-work design packet route", maxsplit=1
    )[1].split("## Skill routing", maxsplit=1)[0]

    assert "design_packet_refusal.v1" in route
    assert "resolver is unavailable" in route
    assert "existing explicit owner-document route" in route
    assert "must not waive mandatory workflow reads" in route
    assert "packet is a read-only routing projection" in route


def test_builder_route_points_to_product_authority_without_absorbing_it() -> None:
    index = _normalized(".codex/skills/README.md")
    route = index.split("## Structural-work design packet route", maxsplit=1)[1].split(
        "## Skill routing", maxsplit=1
    )[0]

    assert "Product/Runtime design authority remains in owner documents" in route
    assert "cannot redefine principles" in route
    for path in BUILDER_SURFACES:
        text = _normalized(path)
        if path == ".codex/skills/README.md":
            assert "## Structural-work design packet route" in text
        else:
            assert ROUTE_REFERENCE in text
        assert not any(heading in text for heading in PRODUCT_PRINCIPLE_HEADINGS)
