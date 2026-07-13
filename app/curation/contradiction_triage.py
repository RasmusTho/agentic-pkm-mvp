"""Scope-safe, zero-write read adapter for contradiction findings.

The adapter deliberately calls the delivered contradiction harness with
``materialize=False``.  It exposes only findings whose two citation handles
resolve in the caller's current admission scope; excluded details and scan
exceptions are collapsed to content-free diagnostics.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from app.curation.contradiction import (
    ContradictionPassConfig,
    ContradictionPassReport,
    run_contradiction_pass,
)
from app.curation.findings import CurationFinding, FindingClass


class ContradictionTriageScanStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


@dataclass(frozen=True)
class AdmittedContradictionCitation:
    """The minimal result of resolving one citation under current admission."""

    handle: str
    scope: str


@dataclass(frozen=True)
class ContradictionTriageAdmission:
    """Caller-owned current scope and citation-resolution boundary."""

    current_scope: str
    resolve_citation: Callable[[str], AdmittedContradictionCitation | None]


@dataclass(frozen=True)
class ContradictionTriageFinding:
    """Narrow projection of fields already emitted by the sanctioned harness."""

    finding_id: str
    observed: str
    citation_handles: tuple[str, str]
    interpretation: str


@dataclass(frozen=True)
class ContradictionTriageResult:
    status: ContradictionTriageScanStatus
    findings: tuple[ContradictionTriageFinding, ...]
    diagnostic: str


ContradictionHarness = Callable[..., ContradictionPassReport]


def _admit_finding(
    finding: CurationFinding,
    admission: ContradictionTriageAdmission,
) -> ContradictionTriageFinding | None:
    if finding.finding_class is not FindingClass.CONTRADICTION_CLAIM_CONFLICT:
        return None
    if not admission.current_scope or len(finding.evidence) != 2:
        return None

    handles = tuple(finding.evidence)
    if len(set(handles)) != 2:
        return None

    for handle in handles:
        try:
            resolved = admission.resolve_citation(handle)
        except Exception:
            return None
        if (
            resolved is None
            or resolved.handle != handle
            or resolved.scope != admission.current_scope
        ):
            return None

    return ContradictionTriageFinding(
        finding_id=finding.finding_id,
        observed=finding.observed,
        citation_handles=(handles[0], handles[1]),
        interpretation=finding.span,
    )


def run_contradiction_triage(
    *,
    vault_root: Path,
    queries: list[str],
    admission: ContradictionTriageAdmission,
    outbox_path: Path,
    config: ContradictionPassConfig | None = None,
    harness: ContradictionHarness | None = None,
) -> ContradictionTriageResult:
    """Read findings through the existing harness without materializing them."""

    runner = harness or run_contradiction_pass
    try:
        report = runner(
            vault_root=vault_root,
            queries=queries,
            config=config,
            outbox_path=outbox_path,
            materialize=False,
        )
    except Exception:
        return ContradictionTriageResult(
            status=ContradictionTriageScanStatus.FAILED,
            findings=(),
            diagnostic="scan_failed",
        )

    admitted: list[ContradictionTriageFinding] = []
    seen_ids: set[str] = set()
    excluded = False
    for finding in report.findings:
        if finding.finding_id in seen_ids:
            continue
        seen_ids.add(finding.finding_id)
        projected = _admit_finding(finding, admission)
        if projected is None:
            excluded = True
            continue
        admitted.append(projected)

    if admitted:
        diagnostic = "ok"
    elif excluded or report.suppressed_by_cross_scope_denial:
        diagnostic = "finding_excluded"
    else:
        diagnostic = "no_findings"
    return ContradictionTriageResult(
        status=ContradictionTriageScanStatus.SUCCESS,
        findings=tuple(admitted),
        diagnostic=diagnostic,
    )


__all__ = [
    "AdmittedContradictionCitation",
    "ContradictionTriageAdmission",
    "ContradictionTriageFinding",
    "ContradictionTriageResult",
    "ContradictionTriageScanStatus",
    "run_contradiction_triage",
]
