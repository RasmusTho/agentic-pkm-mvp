"""Fitness invariant: ``curation_citations_resolve`` (G2-4, #2999).

Invariant registry: docs/testing/invariant-tests.md :: curation_citations_resolve
Spec: docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md §4, §6.

Purpose: every contradiction finding carries >=2 in-vault source references
that resolve at materialization time; unresolvable evidence voids the finding
(no uncited "trust me" callouts) -- blocked loudly, never silently emitted and
never silently dropped without trace.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.contradiction import (
    UnresolvableContradictionCitationError,
    run_contradiction_pass,
)
from app.curation.findings import FindingClass
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse
from app.write_guard import WriteGuard


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _panel_note(uuid: str, extra_body: str = "") -> str:
    return (
        f"---\nuuid: {uuid}\nkind: note\n---\n\n"
        f"# {uuid}\n\n{extra_body}"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "\n"
        "## AI-åtgärder\n"
        "%% AI:End %%\n"
    )


def _write_note(vault_root: Path, rel_path: str, content: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _hit(doc_id: str, *, uuid: str, text: str, source_ref: str, score: float = 0.8) -> RetrievalHit:
    return RetrievalHit(
        object_id=doc_id,
        doc_id=doc_id,
        text=text,
        score=score,
        snippet=text,
        source_ref=source_ref,
        payload={"uuid": uuid},
    )


def test_citations_resolve(tmp_path: Path) -> None:
    """Production-call-site enforcement, both directions:

    1. A finding whose both citations resolve carries >=2 resolvable source
       references and materializes normally.
    2. A finding with an unresolvable citation raises loudly
       (``UnresolvableContradictionCitationError``) rather than materializing
       an uncited callout or silently vanishing.
    """
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "Mötet är kl 9.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "The meeting is at 10am.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    good_hits = [
        _hit("a", uuid="uuid-a", text="Mötet är kl 9.", source_ref="a.md"),
        _hit("b", uuid="uuid-b", text="The meeting is at 10am.", source_ref="b.md", score=0.75),
    ]

    def _good_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(query=request.query, hits=list(good_hits), trace_id=request.trace_id)

    report = run_contradiction_pass(
        vault_root=vault_root,
        queries=["meeting time"],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        retrieve_fn=_good_retrieve,
    )
    assert report.findings
    for finding in report.findings:
        assert finding.finding_class == FindingClass.CONTRADICTION_CLAIM_CONFLICT
        assert len(finding.evidence) >= 2
        for source in finding.evidence:
            resolved_path = vault_root / source
            assert resolved_path.exists(), f"citation {source!r} must resolve in-vault"

    # Unresolvable citation: one side's source file was never written.
    bad_hits = [
        _hit("a", uuid="uuid-a", text="Mötet är kl 9.", source_ref="a.md"),
        _hit(
            "ghost",
            uuid="uuid-ghost",
            text="The meeting is at 11am.",
            source_ref="ghost-note-never-written.md",
            score=0.7,
        ),
    ]

    def _bad_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(query=request.query, hits=list(bad_hits), trace_id=request.trace_id)

    with pytest.raises(UnresolvableContradictionCitationError):
        run_contradiction_pass(
            vault_root=vault_root,
            queries=["meeting time"],
            write_guard=_allow_all_guard(),
            outbox_path=outbox_path,
            retrieve_fn=_bad_retrieve,
        )

    # No stray checkbox was written for the voided finding.
    a_text = (vault_root / "a.md").read_text(encoding="utf-8")
    # Exactly the checkbox from the first (good) run, none from the failed run.
    assert a_text.count("- [ ]") == 1
