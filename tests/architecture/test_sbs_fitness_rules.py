"""SBS fitness checks for low-risk mechanical boundary visibility.

These tests intentionally start narrow. They protect the mechanical SBS rules
that are stable enough to enforce without sweeping current runtime internals
into policy:

1. Target public SBS contracts must not reintroduce active-vault or vault-path
   identity outside the WSP ActiveContextSet seam.
2. The non-HKA target contracts (RCA/MEM/CAO/EXE) must not claim direct durable
   HKA/artifact mutation and must route knowledge mutation through GOV /
   GovernedWriteProtocol.
3. The human-flow SBS allocation view must not point at missing contract,
   architecture, or test references.

These read-only checks report violations but do not rewrite any policy, memory,
retrieval, knowledge, execution, or contract docs. The first two operate at the
contract-document level: the SBS Boundary Register lists most subsystems at
Partial/No physical module, so a literal Python module-import-direction check is
not cleanly feasible yet.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

# WSP owns ActiveContextSet and may discuss the active-vault transition there.
# These are the target SBS contracts whose public shape must consume
# ActiveContextSet/source bindings rather than passing vault path/root identity.
TARGET_SBS_CONTRACTS_OUTSIDE_WSP = (
    REPO_ROOT / "docs" / "contracts" / "ARTIFACT_CONTRACT.md",
    REPO_ROOT / "docs" / "contracts" / "GOVERNED_WRITE_PROTOCOL.md",
    REPO_ROOT / "docs" / "contracts" / "STORE_PORT.md",
    REPO_ROOT / "docs" / "contracts" / "CONTEXT_BUNDLE.md",
    REPO_ROOT / "docs" / "contracts" / "MEMORY_RECORD.md",
    REPO_ROOT / "docs" / "contracts" / "EXECUTION_REQUEST.md",
    REPO_ROOT / "docs" / "contracts" / "REPLICATION_ENVELOPE.md",
    REPO_ROOT / "docs" / "contracts" / "CAPABILITY_CONTRACT.md",
    REPO_ROOT / "docs" / "contracts" / "WORKFLOW_CONTRACT.md",
)

HUMAN_FLOW_TO_RUNTIME_MAP = REPO_ROOT / "docs" / "HUMAN_FLOW_TO_RUNTIME_MAP.md"

FORBIDDEN_ACTIVE_VAULT_CONTRACT_TERMS = (
    re.compile(r"\bactiveVault\b"),
    re.compile(r"\bvaultPath\b"),
    re.compile(r"\bactive_vault\b"),
    re.compile(r"\bvault_path\b"),
    re.compile(r"\bvault_root\b"),
    re.compile(r"\bvault\s+path\b", re.IGNORECASE),
    re.compile(r"\bvault\s+root\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ContractTermHit:
    path: Path
    line_number: int
    term: str
    line: str

    def format(self) -> str:
        relative = self.path.relative_to(REPO_ROOT)
        return f"{relative}:{self.line_number}: {self.term!r} in {self.line!r}"


def _find_forbidden_contract_terms(paths: Iterable[Path]) -> list[ContractTermHit]:
    hits: list[ContractTermHit] = []
    for path in paths:
        if not path.exists():
            raise AssertionError(f"Missing target SBS contract stub: {path}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for pattern in FORBIDDEN_ACTIVE_VAULT_CONTRACT_TERMS:
                if match := pattern.search(line):
                    hits.append(
                        ContractTermHit(
                            path=path,
                            line_number=line_number,
                            term=match.group(0),
                            line=line.strip(),
                        )
                    )
    return hits


def test_target_sbs_contracts_do_not_reintroduce_active_vault_identity() -> None:
    """Target public contracts outside WSP use ActiveContextSet/source bindings.

    Source: docs/architecture/SBS_FITNESS_RULES.md seed rule
    "No global activeVault as architecture contract outside WSP/EBF/HIX
    adapters." This read-only check reports violations but does not rewrite
    policy, memory, retrieval, knowledge, execution, or contract docs.
    """
    hits = _find_forbidden_contract_terms(TARGET_SBS_CONTRACTS_OUTSIDE_WSP)

    assert not hits, (
        "Target SBS contract stubs outside WSP must not expose active-vault "
        "or vault-path/root identity as public contract language. Use an "
        "ActiveContextSet reference plus source binding instead. Violations: "
        + "; ".join(hit.format() for hit in hits)
    )


# ---------------------------------------------------------------------------
# Rule: No direct HKA mutation from RCA / MEM / CAO / EXE (contract-doc level).
#
# Promotes the P0 fitness rule "No direct HKA mutation from RCA/MEM/CAO/EXE/EBF/
# HIX" to a deterministic CI check at the contract-document level. A literal
# code import-direction map is not cleanly feasible (the SBS Boundary Register
# shows these subsystems at Partial/No physical module), so this rail asserts
# the public contract stubs:
#   - do NOT assert direct durable HKA/artifact mutation as their own authority,
#     and
#   - explicitly route knowledge mutation/promotion through GOV /
#     GovernedWriteProtocol.
# HKA's own contract owns durable human-knowledge mutation and is excluded.
# ---------------------------------------------------------------------------

# Non-HKA target contracts whose owner subsystems must not become knowledge
# authority. Mapped to the P0 rule's named subsystems present as contract stubs:
# RCA (ContextBundle), MEM (MemoryRecord), CAO (CapabilityContract,
# WorkflowContract), EXE (ExecutionRequest).
NON_HKA_TARGET_CONTRACTS = (
    REPO_ROOT / "docs" / "contracts" / "CONTEXT_BUNDLE.md",
    REPO_ROOT / "docs" / "contracts" / "MEMORY_RECORD.md",
    REPO_ROOT / "docs" / "contracts" / "CAPABILITY_CONTRACT.md",
    REPO_ROOT / "docs" / "contracts" / "WORKFLOW_CONTRACT.md",
    REPO_ROOT / "docs" / "contracts" / "EXECUTION_REQUEST.md",
)

# A line claims direct durable HKA/artifact mutation when it pairs a mutation
# verb with an HKA/human-knowledge/durable-artifact object. Matching is
# case-insensitive and tolerant of intervening words ("write accepted human
# artifact state", "persist ... as accepted knowledge").
_DIRECT_HKA_MUTATION_CLAIM = re.compile(
    r"\b(write|writes|writing|mutate|mutates|mutating|persist|persists|"
    r"persisting|update|updates|updating|commit|commits|committing)\b"
    r"[^.\n]*?\b("
    r"hka|human\s+knowledge|human\s+artifact|accepted\s+knowledge|"
    r"accepted\s+human|durable\s+human|knowledge\s+artifact"
    r")\b",
    re.IGNORECASE,
)

# Negating qualifiers that turn a mutation+HKA line into a disclaimer/route
# (e.g. "RCA does not write HKA", "Do not write memory into HKA without GOV",
# "promotion to HKA only via GOV"). Their presence on the line means the line
# is forbidding or governing direct HKA mutation, not asserting it.
_HKA_MUTATION_NEGATORS = re.compile(
    r"\b(not|never|no|without|cannot|only|through|via|after|owns|owned)\b",
    re.IGNORECASE,
)

# At least one of these GOV-routing markers must appear in each non-HKA
# contract: proof the contract routes knowledge mutation through GOV /
# GovernedWriteProtocol rather than mutating durable knowledge itself.
_GOV_ROUTING_MARKERS = (
    re.compile(r"GovernedWriteProtocol", re.IGNORECASE),
    re.compile(r"\bHKA/GOV\b", re.IGNORECASE),
    re.compile(r"\bGOV/EXE\b", re.IGNORECASE),
    re.compile(r"\bthrough\s+GOV\b", re.IGNORECASE),
    re.compile(r"\bvia\s+GOV\b", re.IGNORECASE),
    re.compile(r"\bafter\s+GOV\b", re.IGNORECASE),
    re.compile(r"\bpromot\w*\s+through\s+GOV\b", re.IGNORECASE),
    re.compile(r"\bgoverned\s+promotion\b", re.IGNORECASE),
)


def _find_direct_hka_mutation_claims(paths: Iterable[Path]) -> list[ContractTermHit]:
    hits: list[ContractTermHit] = []
    for path in paths:
        if not path.exists():
            raise AssertionError(f"Missing non-HKA target SBS contract stub: {path}")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = _DIRECT_HKA_MUTATION_CLAIM.search(line)
            if not match:
                continue
            # A negator on the same line means the line disclaims or governs
            # direct HKA mutation (e.g. "does not write HKA", "only via GOV").
            if _HKA_MUTATION_NEGATORS.search(line):
                continue
            hits.append(
                ContractTermHit(
                    path=path,
                    line_number=line_number,
                    term=match.group(0),
                    line=line.strip(),
                )
            )
    return hits


def _contracts_missing_gov_routing(paths: Iterable[Path]) -> list[Path]:
    missing: list[Path] = []
    for path in paths:
        if not path.exists():
            raise AssertionError(f"Missing non-HKA target SBS contract stub: {path}")
        text = path.read_text(encoding="utf-8")
        if not any(marker.search(text) for marker in _GOV_ROUTING_MARKERS):
            missing.append(path)
    return missing


def test_non_hka_contracts_do_not_claim_direct_hka_mutation() -> None:
    """Non-HKA target contracts route knowledge mutation through GOV, not directly.

    Source: docs/architecture/SBS_FITNESS_RULES.md P0 rule
    "No direct HKA mutation from RCA/MEM/CAO/EXE/EBF/HIX." Implemented at the
    contract-document level because the SBS Boundary Register shows these
    subsystems at Partial/No physical module, so a literal code
    import-direction map is not cleanly feasible. This read-only check reports
    violations but does not rewrite policy, memory, retrieval, knowledge,
    execution, or contract docs.
    """
    direct_claims = _find_direct_hka_mutation_claims(NON_HKA_TARGET_CONTRACTS)
    assert not direct_claims, (
        "Non-HKA target contracts (RCA/MEM/CAO/EXE) must not assert direct "
        "durable HKA/artifact mutation as their own authority. Route knowledge "
        "mutation through GOV / GovernedWriteProtocol instead. Violations: "
        + "; ".join(hit.format() for hit in direct_claims)
    )

    missing_routing = _contracts_missing_gov_routing(NON_HKA_TARGET_CONTRACTS)
    assert not missing_routing, (
        "Non-HKA target contracts must state that knowledge mutation/promotion "
        "routes through GOV / GovernedWriteProtocol. Missing GOV-routing "
        "language in: "
        + "; ".join(str(path.relative_to(REPO_ROOT)) for path in missing_routing)
    )


# ---------------------------------------------------------------------------
# Rule: human-flow SBS allocation references resolve.
#
# This validates only low-ambiguity references in the allocation/verification
# tables: contract docs, SBS architecture docs, and concrete test paths. It
# deliberately does not turn the map into a requirements database or parse every
# prose anchor in owner docs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarkdownTable:
    headers: tuple[str, ...]
    rows: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class AllocationReferenceIssue:
    row_label: str
    column: str
    reference: str
    reason: str

    def format(self) -> str:
        return f"{self.row_label} [{self.column}] {self.reference!r}: {self.reason}"


_CONTRACT_DOC_REFERENCE = re.compile(r"docs/contracts/[A-Za-z0-9_./-]+\.md")
_SBS_ARCHITECTURE_DOC_REFERENCE = re.compile(
    r"docs/architecture/SBS_[A-Za-z0-9_./-]+\.md"
)
_TEST_PATH_REFERENCE = re.compile(
    r"tests/[A-Za-z0-9_./-]+\.py(?:::[A-Za-z0-9_./:-]+)?"
)
_MARKDOWN_CODE_OR_LINK_MARKS = str.maketrans("", "", "`[]()")


def _parse_markdown_tables(text: str) -> list[MarkdownTable]:
    tables: list[MarkdownTable] = []
    lines = text.splitlines()
    line_index = 0
    while line_index < len(lines) - 1:
        header = lines[line_index]
        separator = lines[line_index + 1]
        if not (_is_table_row(header) and _is_table_separator(separator)):
            line_index += 1
            continue

        headers = tuple(_split_table_row(header))
        rows: list[dict[str, str]] = []
        line_index += 2
        while line_index < len(lines) and _is_table_row(lines[line_index]):
            cells = _split_table_row(lines[line_index])
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
            line_index += 1

        tables.append(MarkdownTable(headers=headers, rows=tuple(rows)))

    return tables


def _is_table_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _normalize_markdown_reference(reference: str) -> str:
    return reference.translate(_MARKDOWN_CODE_OR_LINK_MARKS).rstrip(".,;:")


def _reference_path(reference: str) -> Path:
    path_part = _normalize_markdown_reference(reference).split("::", 1)[0]
    return REPO_ROOT / path_part


def _test_node_exists(path: Path, reference: str) -> bool:
    if "::" not in reference:
        return True

    node_parts = reference.split("::")[1:]
    module = ast.parse(path.read_text(encoding="utf-8"))
    current_body = module.body
    for node_part in node_parts:
        matching_node = next(
            (
                node
                for node in current_body
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == node_part
            ),
            None,
        )
        if matching_node is None:
            return False
        current_body = matching_node.body if isinstance(matching_node, ast.ClassDef) else []
    return True


def _allocation_reference_issues(table: MarkdownTable) -> list[AllocationReferenceIssue]:
    issues: list[AllocationReferenceIssue] = []
    for row in table.rows:
        row_label = row.get("Human flow") or row.get("Scenario") or "<unlabeled row>"
        verification = row.get("Verification anchor(s)", "").strip()
        if not verification:
            issues.append(
                AllocationReferenceIssue(
                    row_label=row_label,
                    column="Verification anchor(s)",
                    reference="",
                    reason="verification anchor cell is blank",
                )
            )
        elif not _has_concrete_reference(verification) and not _has_explicit_nonmechanical_marker(
            verification
        ):
            issues.append(
                AllocationReferenceIssue(
                    row_label=row_label,
                    column="Verification anchor(s)",
                    reference=verification,
                    reason="non-mechanical verification must say 'to define' or 'manual review now'",
                )
            )

        for column, cell in row.items():
            issues.extend(_missing_reference_issues(row_label, column, cell))
    return issues


def _has_concrete_reference(cell: str) -> bool:
    return any(
        pattern.search(cell)
        for pattern in (
            _CONTRACT_DOC_REFERENCE,
            _SBS_ARCHITECTURE_DOC_REFERENCE,
            _TEST_PATH_REFERENCE,
        )
    )


def _has_explicit_nonmechanical_marker(cell: str) -> bool:
    lowered = cell.lower()
    return "to define" in lowered or "manual review now" in lowered


def _missing_reference_issues(
    row_label: str,
    column: str,
    cell: str,
) -> list[AllocationReferenceIssue]:
    issues: list[AllocationReferenceIssue] = []
    for pattern in (
        _CONTRACT_DOC_REFERENCE,
        _SBS_ARCHITECTURE_DOC_REFERENCE,
        _TEST_PATH_REFERENCE,
    ):
        for match in pattern.finditer(cell):
            reference = _normalize_markdown_reference(match.group(0))
            path = _reference_path(reference)
            if not path.exists():
                issues.append(
                    AllocationReferenceIssue(
                        row_label=row_label,
                        column=column,
                        reference=reference,
                        reason="referenced path does not exist",
                    )
                )
            elif pattern == _TEST_PATH_REFERENCE and not _test_node_exists(path, reference):
                issues.append(
                    AllocationReferenceIssue(
                        row_label=row_label,
                        column=column,
                        reference=reference,
                        reason="referenced pytest node does not exist",
                    )
                )
    return issues


def test_human_flow_sbs_allocation_references_resolve() -> None:
    """Human-flow SBS allocation tables only point at existing local references.

    Source: docs/architecture/SBS_FITNESS_RULES.md roadmap check for the
    allocation/verification view. This read-only check validates referenced
    contract docs, SBS architecture docs, and concrete test files/functions.
    Rows may use explicit "to define" or "manual review now" wording where
    verification is not yet mechanical.
    """
    text = HUMAN_FLOW_TO_RUNTIME_MAP.read_text(encoding="utf-8")
    allocation_tables = [
        table
        for table in _parse_markdown_tables(text)
        if "Verification anchor(s)" in table.headers
    ]

    assert allocation_tables, "Expected at least one allocation table with Verification anchor(s)"

    issues: list[AllocationReferenceIssue] = []
    for table in allocation_tables:
        issues.extend(_allocation_reference_issues(table))

    assert not issues, (
        "Human-flow SBS allocation references must resolve, and non-mechanical "
        "verification rows must be explicit. Violations: "
        + "; ".join(issue.format() for issue in issues)
    )
