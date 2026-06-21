"""SBS fitness checks for low-risk mechanical boundary visibility.

These tests intentionally start narrow. They protect the first mechanical
SBS rule that is stable enough to enforce without sweeping current runtime
vault internals into policy: target public SBS contracts must not reintroduce
active-vault or vault-path identity outside the WSP ActiveContextSet seam.
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
