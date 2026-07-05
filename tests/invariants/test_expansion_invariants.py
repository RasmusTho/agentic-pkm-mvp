"""Fitness invariant: ``connect_proposals_candidate_only`` (EXP-1, #2994).

Invariant registry: docs/testing/invariant-tests.md :: connect_proposals_candidate_only
Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §6.

Purpose: `connect.*` classes map to propose-track by construction (no
configuration can move them); connect evidence enters downstream context
clamped to `background` at most; no connect output applies a link without
the governed acceptance path (the checkbox).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.curation.findings import (
    CONNECT_FINDING_CLASSES,
    MECHANICAL_ALLOWLIST,
    FindingClass,
    FindingTrack,
    track_for_class,
)
from app.expansion.connect import CONNECT_EVIDENCE_ROLE, run_connect_pass
from app.knowledge_compilation.proposal_builders import _MACHINE_DERIVATIONS
from app.retrieval.capability import RetrievalHit, RetrievalRequest, RetrievalResponse
from app.write_guard import WriteGuard


def test_connect_classes_are_disjoint_from_mechanical_allowlist() -> None:
    """Static, construction-level guarantee: no `connect.*` class is a member
    of the auto-fix allowlist, under any current or future enum edit that
    respects the module's own import-time assertion."""
    assert CONNECT_FINDING_CLASSES.isdisjoint(MECHANICAL_ALLOWLIST)


@pytest.mark.parametrize(
    "finding_class",
    [
        FindingClass.CONNECT_RELATED_UNLINKED,
        FindingClass.CONNECT_THEMATIC_LINK,
        FindingClass.CONNECT_CLUSTER_EMERGENCE,
    ],
)
def test_connect_candidate_only(finding_class: FindingClass) -> None:
    """No config can move a `connect.*` class onto the auto-fix track:
    ``track_for_class`` derives the track from class membership ALONE, so
    every connect class resolves to ``propose`` unconditionally."""
    assert track_for_class(finding_class) == FindingTrack.PROPOSE


def test_connect_pass_never_materializes_a_checked_box(tmp_path: Path) -> None:
    """Production-call-site enforcement: running the real pass end to end
    never writes a checked (`- [x]`) box, and never body-edits a note outside
    the governed checkbox block -- the only path from finding to note text is
    `write_curation_proposals`, which is propose-only by construction."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    for rel, uuid in (("a.md", "uuid-a"), ("b.md", "uuid-b")):
        (vault_root / rel).write_text(
            f"---\nuuid: {uuid}\nkind: note\n---\n\n# {uuid}\n\n"
            "%% AI:Start %%\n## AI-instruktion\n\n## AI-åtgärder\n%% AI:End %%\n",
            encoding="utf-8",
        )
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})

    def _fake_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(
            query=request.query,
            hits=[
                RetrievalHit(
                    object_id="a",
                    doc_id="a",
                    text="shared alpha beta gamma",
                    score=0.9,
                    snippet="shared alpha beta gamma",
                    source_ref="a.md",
                    payload={"uuid": "uuid-a"},
                ),
                RetrievalHit(
                    object_id="b",
                    doc_id="b",
                    text="shared alpha beta gamma",
                    score=0.85,
                    snippet="shared alpha beta gamma",
                    source_ref="b.md",
                    payload={"uuid": "uuid-b"},
                ),
            ],
        )

    report = run_connect_pass(
        vault_root=vault_root,
        queries=["shared alpha beta gamma"],
        write_guard=guard,
        outbox_path=outbox_path,
        retrieve_fn=_fake_retrieve,
    )

    assert report.findings  # sanity: the pass actually found the pair
    for rel in ("a.md", "b.md"):
        text = (vault_root / rel).read_text(encoding="utf-8")
        assert "- [x]" not in text
        assert text.count("- [ ]") == 1


def test_connect_evidence_role_never_exceeds_background() -> None:
    """Connect-derived material never claims a stronger evidence role than
    `background` -- the literal constant this module exposes, and it must
    match the retrieval-derived machine-derivation refusal
    (`proposal_builders._MACHINE_DERIVATIONS`) that already refuses to
    launder retrieval-derived material as authority."""
    assert CONNECT_EVIDENCE_ROLE == "background"
    # `retrieval` is one of the machine-derivations proposal_builders already
    # refuses to launder as authority -- Connect's evidence role composes
    # with that refusal rather than needing a second, separate guard.
    assert "retrieval" in _MACHINE_DERIVATIONS


def test_connect_finding_classes_all_covered_by_candidate_only_parametrization() -> None:
    """Guards against a future class addition to CONNECT_FINDING_CLASSES that
    forgets to extend this invariant's parametrization -- every member of the
    closed connect set must resolve to propose."""
    for finding_class in CONNECT_FINDING_CLASSES:
        assert track_for_class(finding_class) == FindingTrack.PROPOSE


def test_declined_not_reproposed(tmp_path: Path) -> None:
    """Fitness invariant: ``declined_findings_not_reproposed`` (EXP-2, #2995).

    Invariant registry: docs/testing/invariant-tests.md :: declined_findings_not_reproposed.
    Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §3, §6.

    Production-call-site enforcement: a finding declined through the real
    `app.proposals.declined_ledger.DeclinedLedger` is suppressed -- not
    re-emitted -- on the next `run_connect_pass` invocation over an
    unchanged vault, and the suppression is visible in the pass receipt.
    Full behavioral coverage (content-basis reset, delete-safety, and the
    never-enters-context enforcement) lives in
    `tests/proposals/test_declined_ledger.py`, this invariant's `Verify:`
    target; this test is the one-assertion fitness probe co-located with its
    sibling Connect invariants.
    """
    from app.expansion.connect import ConnectPassConfig, run_connect_pass
    from app.proposals.declined_ledger import DeclinedLedger

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    for rel, uuid in (("a.md", "uuid-a"), ("b.md", "uuid-b")):
        (vault_root / rel).write_text(
            f"---\nuuid: {uuid}\nkind: note\n---\n\n# {uuid}\n\n"
            "%% AI:Start %%\n## AI-instruktion\n\n## AI-åtgärder\n%% AI:End %%\n",
            encoding="utf-8",
        )
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    config = ConnectPassConfig(declined_ledger=ledger)

    def _fake_retrieve(request: RetrievalRequest) -> RetrievalResponse:
        return RetrievalResponse(
            query=request.query,
            hits=[
                RetrievalHit(
                    object_id="a", doc_id="a", text="shared alpha beta gamma", score=0.9,
                    snippet="shared alpha beta gamma", source_ref="a.md", payload={"uuid": "uuid-a"},
                ),
                RetrievalHit(
                    object_id="b", doc_id="b", text="shared alpha beta gamma", score=0.85,
                    snippet="shared alpha beta gamma", source_ref="b.md", payload={"uuid": "uuid-b"},
                ),
            ],
        )

    first = run_connect_pass(
        vault_root=vault_root, queries=["shared alpha beta gamma"], config=config,
        write_guard=guard, outbox_path=outbox_path, retrieve_fn=_fake_retrieve,
    )
    assert first.findings
    finding_id = first.findings[0].finding_id
    ledger.record_decline(finding_id, finding_class="connect.related_unlinked", write_guard=guard)

    second = run_connect_pass(
        vault_root=vault_root, queries=["shared alpha beta gamma"], config=config,
        write_guard=guard, outbox_path=outbox_path, retrieve_fn=_fake_retrieve,
    )
    assert second.findings == ()
    assert second.suppressed_by_decline == 1
