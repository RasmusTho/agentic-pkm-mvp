import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ADR = REPO_ROOT / "docs/adr/ADR-0069-mcp-v2-authority-profile.md"
ADR_INDEX = REPO_ROOT / "docs/adr/INDEX.md"
DOCS_INDEX = REPO_ROOT / "docs/DOCS_INDEX.md"
MIMER_CLIENT = REPO_ROOT / "docs/contracts/MIMER_CLIENT_CONTRACT.md"
OPERATIONS = REPO_ROOT / "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md"
MCP_TASK = (
    REPO_ROOT / "docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/EXPOSE_AND_PROVE_MCP_V2_PARITY.md"
)


def _section(document: str, heading: str, next_heading: str) -> str:
    start = document.index(heading)
    end = document.index(next_heading, start + len(heading))
    return document[start:end]


def _normalized(document: str) -> str:
    return re.sub(r"\s+", " ", document).casefold()


def test_accepted_v2_adr_preserves_v1_and_owner_receipt() -> None:
    adr = ADR.read_text(encoding="utf-8")
    normalized = _normalized(adr)

    assert "status: accepted" in normalized
    assert "5340#issuecomment-6489124965" in normalized
    assert "5340#issuecomment-6488956317" in normalized
    assert "39a8ab716cab2d562577b73c8216c7205483a7c9c45cbd88eb6d85fb28327f4c" in normalized
    assert "partially supersede adr-0061" in normalized
    assert "only for the external operation boundary" in normalized
    for invariant in ("a2", "b1", "c1", "stdio-only", "no network listener"):
        assert invariant in normalized
    for operation in ("ask", "governed `capture`", "retrieve/search", "note-read", "health"):
        assert operation in adr
    for family in (
        "discovery, read, search, and related resources",
        "typed creation",
        "identity-preserving move",
        "classification, tags, and ordering",
        "archive and restore",
        "finite batch execution",
        "receipt, convergence, and recovery observation",
    ):
        assert family in normalized
    for bound in (
        "shared authenticated production operations http boundary",
        "mvr-05c",
        "decisiontoken",
        "expected versions",
        "typed-unavailable",
        "durable readback and reconciliation before retry",
        "not a runtime or deployment receipt",
    ):
        assert bound in normalized


def test_v2_contracts_preserve_scoped_api_authority_and_recovery() -> None:
    mimer = MIMER_CLIENT.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")
    mimer_v1 = _section(
        mimer,
        "### MCP v1 compatibility profile (ADR-0061)",
        "### Accepted MCP v2 authority profile",
    )
    mimer_v2 = _section(
        mimer,
        "### Accepted MCP v2 authority profile",
        "## 3. Authority envelope",
    )
    mutation_invariant = _section(
        mimer,
        "2. **Every durable mutation stays inside a named path.**",
        "3. **Never a hidden source of truth.**",
    )
    operations_v1 = _section(
        operations,
        "### MCP v1 compatibility profile",
        "### MCP v2 parity profile",
    )
    operations_v2 = _section(
        operations,
        "### MCP v2 parity profile",
        "## Conformance and acceptance",
    )

    v1 = _normalized(mimer_v1 + operations_v1)
    for operation in ("ask", "governed capture", "retrieve/search", "note-read", "health"):
        assert operation in v1
    for exclusion in (
        "exact boundary",
        "no network listener",
        "separate receipt read-back",
        "direct-filesystem fallback",
        "internal `vault_tools`",
    ):
        assert exclusion in v1

    for statement in (
        "adr-0069",
        "shared authenticated production operations http boundary",
        "qualified, supported owner-native",
        "typed-unavailable",
        "mvr-05c",
        "decisiontoken",
        "bounded scope and cardinality",
        "expected versions",
        "original native/gov receipt truth",
        "v1's receipt-readback exclusion remains unchanged",
        "durable api readback and reconciliation before retry",
        "client-supplied paths",
        "separately declared grants",
    ):
        assert statement in _normalized(mimer_v2)

    for statement in (
        "mcp v1 delegates capture to the governed api",
        "mcp v2 delegates only the admitted operations to that same governed api",
        "neither protocol profile adds a third write path",
    ):
        assert statement in _normalized(mutation_invariant)

    for statement in (
        "adr-0069",
        "matching update in the",
        "mimer client contract",
        "capability-derived, versioned tools and resources",
        "qualified owner-native",
        "operation version, schemas, authority/side-effect class, preview support, and maturity",
        "only contract-ready operations may be mapped",
        "typed-unavailable",
        "mvr-05c effect-capable",
        "expected versions",
        "receipt-readback exclusion remains unchanged",
        "durable readback and reconciliation before retry",
        "cannot convert ambiguity into success",
        "not establish installed runtime capability",
        "superseding accepted adr",
        "matching owner-contract update",
    ):
        assert statement in _normalized(operations_v2)


def test_ratification_keeps_runtime_acceptance_and_source_links_explicit() -> None:
    task = MCP_TASK.read_text(encoding="utf-8")
    operations = OPERATIONS.read_text(encoding="utf-8")
    docs_index = DOCS_INDEX.read_text(encoding="utf-8")
    adr_index = ADR_INDEX.read_text(encoding="utf-8")
    task_gate = _section(task, "## Governance gate", "## Concretely")
    acceptance = _section(operations, "## Conformance and acceptance", "## Invariants")

    assert "satisfied when" in _normalized(task_gate)
    assert "current sha direct/http/companion/mcp conformance" in _normalized(task_gate)
    assert "negative-authority and failure/restart proof" in _normalized(task_gate)
    assert "isolated real-client journey" in _normalized(task_gate)
    assert "companion uat" in _normalized(task_gate)
    assert "owner-document promotion" in _normalized(task_gate)
    assert "a real external mcp client completes the composed journey in an isolated runtime" in _normalized(
        acceptance
    )
    assert "current-state owner docs are promoted only after that evidence exists" in _normalized(
        acceptance
    )

    for source, reference in (
        (ADR, "ADR-0061-mimer-mcp-client-adapter.md"),
        (ADR, "../contracts/MIMER_CLIENT_CONTRACT.md"),
        (ADR, "../contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md"),
        (ADR, "../YGGDRASIL_AUTONOMOUS_OPERATIONS/EXPOSE_AND_PROVE_MCP_V2_PARITY.md"),
    ):
        assert (source.parent / reference).resolve().is_file()
    for source, reference in (
        (MCP_TASK, "../adr/ADR-0069-mcp-v2-authority-profile.md"),
        (MCP_TASK, "../contracts/MIMER_CLIENT_CONTRACT.md#accepted-mcp-v2-authority-profile"),
        (MCP_TASK, "../contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md#mcp-v2-parity-profile"),
    ):
        assert (source.parent / reference.split("#", 1)[0]).resolve().is_file()

    assert "ADR-0069-mcp-v2-authority-profile.md" in adr_index
    assert "docs/adr/ADR-0069-mcp-v2-authority-profile.md" in docs_index
    for authority_doc in (
        "docs/contracts/MIMER_CLIENT_CONTRACT.md",
        "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md",
        "docs/YGGDRASIL_AUTONOMOUS_OPERATIONS/EXPOSE_AND_PROVE_MCP_V2_PARITY.md",
    ):
        assert authority_doc in docs_index
    assert "v2 runtime qualification and production activation remain separately gated" in docs_index
