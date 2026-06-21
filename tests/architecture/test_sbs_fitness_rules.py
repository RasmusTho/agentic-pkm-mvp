"""SBS fitness checks for low-risk mechanical boundary visibility.

These tests intentionally start narrow. They protect the mechanical SBS rules
that are stable enough to enforce without sweeping current runtime internals
into policy:

1. Target public SBS contracts must not reintroduce active-vault or vault-path
   identity outside the WSP ActiveContextSet seam.
2. The non-HKA target contracts (RCA/MEM/CAO/EXE) must not claim direct durable
   HKA/artifact mutation and must route knowledge mutation through GOV /
   GovernedWriteProtocol.

Both checks operate at the contract-document level: the SBS Boundary Register
lists most subsystems at Partial/No physical module, so a literal Python
module-import-direction check is not cleanly feasible yet. These read-only
checks report violations but do not rewrite any policy, memory, retrieval,
knowledge, execution, or contract docs.
"""

from __future__ import annotations

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
