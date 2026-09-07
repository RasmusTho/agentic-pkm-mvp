import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
OPERATIONS_CONTRACT = (
    REPO_ROOT / "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md"
)
MCP_V2_TASK = (
    REPO_ROOT
    / "docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/EXPOSE_AND_PROVE_MCP_V2_PARITY.md"
)


def _section(document: str, heading: str, next_heading: str) -> str:
    start = document.index(heading)
    end = document.index(next_heading, start + len(heading))
    return document[start:end]


def test_mcp_v2_requires_superseding_adr_before_surface_expansion() -> None:
    contract = OPERATIONS_CONTRACT.read_text(encoding="utf-8")
    task = MCP_V2_TASK.read_text(encoding="utf-8")

    v2_profile = _section(
        contract,
        "### MCP v2 parity profile",
        "## Conformance and acceptance",
    )
    task_gate = _section(task, "## Governance gate", "## Concretely")

    for text in (v2_profile, task_gate):
        normalized = re.sub(r"\s+", " ", text)
        assert "superseding accepted ADR" in normalized
        assert "matching owner-contract update" in normalized
        assert "broader external MCP operation set" in normalized

    v1_profile = _section(
        contract,
        "### MCP v1 compatibility profile",
        "### MCP v2 parity profile",
    )
    assert "exact boundary" in v1_profile
    normalized_contract = re.sub(r"\s+", " ", contract).casefold()
    for operation in ("ask", "capture", "retrieve", "read note", "health"):
        assert operation in normalized_contract
