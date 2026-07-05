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


def _create_source(object_id: str, text: str, span: str):
    from app.expansion.create import SourceInput

    return SourceInput(
        object_id=object_id,
        note_path=f"{object_id}.md",
        text=text,
        quoted_spans=(span,),
        language="en",
        review_state="reviewed",
    )


def test_create_never_autowrites_canonical(tmp_path: Path) -> None:
    """Fitness invariant: ``create_never_autowrites_canonical`` (EXP-3, #2996).

    Invariant registry: docs/testing/invariant-tests.md :: create_never_autowrites_canonical.
    Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §2.3, §6.

    Production-call-site enforcement: running the real ``run_create_pass``
    end to end never writes anywhere outside the staging directory -- no
    canonical vault location gains a new file, and the staged draft carries
    an unchecked (never auto-checked) acceptance checkbox. Acceptance to
    canonical is EXP-4's scope (#2997), not reachable from this pass.
    """
    from app.expansion.create import CreateRequest, OutputKind, run_create_pass
    from app.write_guard import WriteGuard

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    # A pre-existing canonical note, to prove the pass never touches it.
    canonical_note = vault_root / "topic-x.md"
    canonical_note.write_text("---\nuuid: canonical-1\n---\n\n# Topic X\n", encoding="utf-8")
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})

    before_files = {p: p.read_text(encoding="utf-8") for p in vault_root.rglob("*.md")}

    sources = (_create_source("obj-a", "Alpha body about topic X.", "Alpha body about topic X."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Topic X overview", sources=sources)
    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=guard)

    assert report.activatable is True
    # The pre-existing canonical note is byte-identical -- untouched.
    assert canonical_note.read_text(encoding="utf-8") == before_files[canonical_note]
    # The only new file lives under the staging dir, never beside canonical notes.
    draft_path = vault_root / report.draft_path
    assert "drafts" in draft_path.parts
    assert draft_path.parent != vault_root
    draft_text = draft_path.read_text(encoding="utf-8")
    assert "- [x]" not in draft_text
    assert "authority_state: proposal" in draft_text


def test_synthesis_carries_source_provenance(tmp_path: Path) -> None:
    """Fitness invariant: ``synthesis_carries_source_provenance`` (EXP-3, #2996).

    Invariant registry: docs/testing/invariant-tests.md :: synthesis_carries_source_provenance.
    Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §2.2, §2.4, §6.

    Production-call-site enforcement: every synthesized draft's staged note
    carries its full `sources:` list in frontmatter (resolvable SourceRefs),
    and an unresolvable citation blocks the draft loudly rather than shipping
    an unsourced narrative.
    """
    from app.expansion.create import (
        CreateRequest,
        OutputKind,
        UnresolvableCitationError,
        run_create_pass,
    )
    from app.write_guard import WriteGuard

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})

    sources = (
        _create_source("obj-a", "Alpha body about topic X.", "Alpha body about topic X."),
        _create_source("obj-b", "Beta body also about topic X.", "Beta body also about topic X."),
    )
    request = CreateRequest(kind=OutputKind.ANSWER_NOTE, title="Topic X answer", sources=sources)
    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=guard)

    draft_text = (vault_root / report.draft_path).read_text(encoding="utf-8")
    for source in sources:
        assert source.object_id in draft_text

    # An unresolvable citation blocks loudly -- never a silently pruned claim.
    bad_sources = (
        _create_source("obj-c", "Gamma body.", "a span that was never written"),
    )
    bad_request = CreateRequest(kind=OutputKind.OVERVIEW, title="Bad", sources=bad_sources)
    with pytest.raises(UnresolvableCitationError):
        run_create_pass(bad_request, vault_root=vault_root, outbox_path=outbox_path, write_guard=guard)


def test_drafts_invisible_to_retrieval(tmp_path: Path) -> None:
    """Fitness invariant: ``staged_drafts_invisible_to_retrieval`` (EXP-3, #2996).

    Invariant registry: docs/testing/invariant-tests.md :: staged_drafts_invisible_to_retrieval.
    Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §2.3, §6.

    Production-call-site enforcement: a staged Create draft is never among
    the real ingest candidate set (`app.ingest.vault_alpha._select_candidates`)
    that feeds the object store / index -- the anti-laundering keystone. This
    is the same exclusion mechanism that already protects `_system/companions`,
    extended to also cover the Create staging subfolder.
    """
    from app.expansion.create import CreateRequest, OutputKind, run_create_pass
    from app.ingest.vault_alpha import _select_candidates
    from app.write_guard import WriteGuard

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"
    guard = WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})

    sources = (_create_source("obj-a", "Alpha body about topic X.", "Alpha body about topic X."),)
    request = CreateRequest(kind=OutputKind.OVERVIEW, title="Invisible draft", sources=sources)
    report = run_create_pass(request, vault_root=vault_root, outbox_path=outbox_path, write_guard=guard)
    draft_path = vault_root / report.draft_path
    assert draft_path.exists()

    candidates, _ = _select_candidates(
        vault_root, include_folders=None, ignore_glob=(), include_test_note=True, max_notes=0
    )
    candidate_paths = {p.relative_to(vault_root) for p in candidates}
    assert draft_path.relative_to(vault_root) not in candidate_paths


def test_create_requires_activation_record(tmp_path: Path) -> None:
    """Fitness invariant: ``expansion_requires_activation_record`` (EXP-3, #2996).

    Invariant registry: docs/testing/invariant-tests.md :: expansion_requires_activation_record.
    Spec: docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md §4, §6.

    A regressed activation posture (declared admissibility withdrawn) yields
    a deterministic blocked-with-reason decision -- never a silent run --
    proven directly against ``app.activation.gate.evaluate_activation`` using
    the exact posture ``app.expansion.create`` declares.
    """
    from app.activation.gate import evaluate_activation
    from app.expansion.create import build_create_activation_posture, build_create_candidates, OutputKind

    sources = (_create_source("obj-a", "Alpha body.", "Alpha body."),)
    candidates = build_create_candidates(sources)

    posture = build_create_activation_posture(OutputKind.OVERVIEW)
    green = evaluate_activation(posture, candidates)
    assert green.activatable is True

    regressed = posture.model_copy(update={"admissibility_declared": False})
    blocked = evaluate_activation(regressed, candidates)
    assert blocked.activatable is False
    assert "admissibility_undeclared" in blocked.blocked_reasons
