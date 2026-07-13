from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.contradiction import ContradictionPassReport
from app.curation.contradiction_triage import (
    AdmittedContradictionCitation,
    ContradictionTriageAdmission,
    ContradictionTriageScanStatus,
    run_contradiction_triage,
)
from app.curation.findings import CurationFinding, FindingClass


def _finding(*, finding_id: str = "finding-1") -> CurationFinding:
    finding = CurationFinding.create(
        note_uuid="uuid-a",
        finding_class=FindingClass.CONTRADICTION_CLAIM_CONFLICT,
        span="Agent interpretation: tension only; no truth verdict.",
        observed="Claim A (a.md): Alpha.\nClaim B (b.md): Beta.",
        proposed="existing panel proposal",
        evidence=("a.md", "b.md"),
    )
    return CurationFinding(
        finding_id=finding_id,
        note_uuid=finding.note_uuid,
        finding_class=finding.finding_class,
        track=finding.track,
        span=finding.span,
        observed=finding.observed,
        proposed=finding.proposed,
        evidence=finding.evidence,
        language_verdict=finding.language_verdict,
        reversal=finding.reversal,
    )


def _report(*findings: CurationFinding) -> ContradictionPassReport:
    return ContradictionPassReport(
        findings=tuple(findings),
        pairs_considered=1,
        suppressed_by_decline=0,
        suppressed_by_cap=0,
        suppressed_by_cross_scope_denial=0,
    )


def _admission(
    resolved: dict[str, AdmittedContradictionCitation],
    *,
    current_scope: str = "work",
) -> ContradictionTriageAdmission:
    return ContradictionTriageAdmission(
        current_scope=current_scope,
        resolve_citation=lambda handle: resolved.get(handle),
    )


def test_adapter_requires_two_resolvable_current_scope_citations(tmp_path: Path) -> None:
    finding = _finding()
    admission = _admission(
        {
            "a.md": AdmittedContradictionCitation(handle="a.md", scope="work"),
            "b.md": AdmittedContradictionCitation(handle="b.md", scope="work"),
        }
    )

    result = run_contradiction_triage(
        vault_root=tmp_path,
        queries=["conflict"],
        admission=admission,
        outbox_path=tmp_path / "outbox.jsonl",
        harness=lambda **_: _report(finding, finding),
    )

    assert result.status is ContradictionTriageScanStatus.SUCCESS
    assert len(result.findings) == 1
    assert result.findings[0].citation_handles == ("a.md", "b.md")
    assert result.findings[0].observed == finding.observed


def test_adapter_fails_closed_without_cross_scope_disclosure(tmp_path: Path) -> None:
    finding = _finding()
    admission = _admission(
        {
            "a.md": AdmittedContradictionCitation(handle="a.md", scope="work"),
            "b.md": AdmittedContradictionCitation(handle="b.md", scope="personal"),
        }
    )

    result = run_contradiction_triage(
        vault_root=tmp_path,
        queries=["conflict"],
        admission=admission,
        outbox_path=tmp_path / "outbox.jsonl",
        harness=lambda **_: _report(finding),
    )

    assert result.status is ContradictionTriageScanStatus.SUCCESS
    assert result.findings == ()
    assert result.diagnostic == "finding_excluded"
    rendered = repr(result)
    assert "personal" not in rendered
    assert "b.md" not in rendered
    assert "Beta" not in rendered


def test_adapter_is_zero_write_at_production_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.curation import contradiction_triage as adapter_module

    calls: list[dict[str, object]] = []

    def production_harness(**kwargs: object) -> ContradictionPassReport:
        calls.append(kwargs)
        return _report()

    monkeypatch.setattr(adapter_module, "run_contradiction_pass", production_harness)
    outbox = tmp_path / "outbox.jsonl"
    before = set(tmp_path.rglob("*"))

    result = run_contradiction_triage(
        vault_root=tmp_path,
        queries=["none"],
        admission=_admission({}),
        outbox_path=outbox,
    )

    assert result.status is ContradictionTriageScanStatus.SUCCESS
    assert len(calls) == 1
    assert calls[0]["materialize"] is False
    assert set(tmp_path.rglob("*")) == before
    assert not outbox.exists()


def test_adapter_distinguishes_failure_from_no_findings(tmp_path: Path) -> None:
    empty = run_contradiction_triage(
        vault_root=tmp_path,
        queries=["none"],
        admission=_admission({}),
        outbox_path=tmp_path / "outbox.jsonl",
        harness=lambda **_: _report(),
    )

    def fail(**_: object) -> ContradictionPassReport:
        raise RuntimeError("private source details")

    failed = run_contradiction_triage(
        vault_root=tmp_path,
        queries=["none"],
        admission=_admission({}),
        outbox_path=tmp_path / "outbox.jsonl",
        harness=fail,
    )

    assert empty.status is ContradictionTriageScanStatus.SUCCESS
    assert empty.diagnostic == "no_findings"
    assert failed.status is ContradictionTriageScanStatus.FAILED
    assert failed.diagnostic == "scan_failed"
    assert "private source details" not in repr(failed)
