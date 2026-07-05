"""#2999 (G2-4) -- Contradiction pass harness: sourced citations resolve.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §4, §6, §7.

Covers the issue's behavioral Acceptance Criteria:

- AC1: a fixture vault with two notes making conflicting claims produces a
  ``contradiction.claim_conflict`` finding with both claims verbatim and >=2
  resolvable source links.
- AC2: an unresolvable citation voids the finding rather than materializing
  an uncited callout.
- AC4: a declined contradiction finding is suppressed on rerun via the
  shared declined-proposal ledger (EXP-2).
- ``curation_citations_resolve`` invariant (also covered in
  ``tests/invariants/test_curation_invariants.py``).
"""
from __future__ import annotations

from pathlib import Path

from app.curation.findings import FindingClass, FindingTrack
from app.expansion.contradiction import (
    MIN_RESOLVABLE_CITATIONS,
    ClaimCandidate,
    ContradictionPassConfig,
    run_contradiction_pass,
)
from app.proposals.declined_ledger import DeclinedLedger
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


def _two_note_vault(tmp_path: Path) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root,
        "meeting-a.md",
        _panel_note("uuid-a", "Mötet är kl 14:00 på tisdag.\n\n"),
    )
    _write_note(
        vault_root,
        "meeting-b.md",
        _panel_note("uuid-b", "The meeting is at 15:00 on Tuesday.\n\n"),
    )
    return vault_root


def _claim_pair(scope_a: str | None = None, scope_b: str | None = None):
    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="meeting-a.md",
        scope=scope_a,
        claim_text="Mötet är kl 14:00 på tisdag.",
        interpretation="The two notes disagree on the meeting start time.",
    )
    b = ClaimCandidate(
        note_uuid="uuid-b",
        rel_path="meeting-b.md",
        scope=scope_b,
        claim_text="The meeting is at 15:00 on Tuesday.",
        interpretation="The two notes disagree on the meeting start time.",
    )
    return (a, b)


# ---------------------------------------------------------------------------
# AC1: conflicting claims -> contradiction.claim_conflict finding, verbatim
# claims + >=2 resolvable source links
# ---------------------------------------------------------------------------


def test_conflicting_claims_produce_finding_with_verbatim_claims_and_two_citations(
    tmp_path: Path,
) -> None:
    vault_root = _two_note_vault(tmp_path)
    outbox_path = tmp_path / "outbox.jsonl"

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert len(report.findings) == 2  # one CurationFinding per side
    finding_ids = {f.finding_id for f in report.findings}
    assert len(finding_ids) == 1  # both sides share one logical finding_id

    for finding in report.findings:
        assert finding.finding_class == FindingClass.CONTRADICTION_CLAIM_CONFLICT
        assert finding.track == FindingTrack.PROPOSE
        # >= 2 resolvable citations (own path + other side's path, at least).
        resolvable_paths = [e for e in finding.evidence if e in ("meeting-a.md", "meeting-b.md")]
        assert len(resolvable_paths) >= MIN_RESOLVABLE_CITATIONS

    # Both claims appear verbatim (untranslated) somewhere in the findings.
    all_text = " ".join(f.observed for f in report.findings)
    assert "Mötet är kl 14:00 på tisdag." in all_text
    assert "The meeting is at 15:00 on Tuesday." in all_text

    # Materialized as an unchecked propose-track checkbox on both notes.
    a_text = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    b_text = (vault_root / "meeting-b.md").read_text(encoding="utf-8")
    assert a_text.count("- [ ]") == 1
    assert b_text.count("- [ ]") == 1
    assert "- [x]" not in a_text and "- [x]" not in b_text
    # The Swedish-language self-contained label per spec §4's example format.
    assert "Motstridigt:" in a_text


def test_contradiction_finding_class_is_propose_track() -> None:
    from app.curation.findings import MECHANICAL_ALLOWLIST, track_for_class

    assert FindingClass.CONTRADICTION_CLAIM_CONFLICT not in MECHANICAL_ALLOWLIST
    assert track_for_class(FindingClass.CONTRADICTION_CLAIM_CONFLICT) == FindingTrack.PROPOSE


# ---------------------------------------------------------------------------
# AC2: an unresolvable citation voids the finding rather than materializing
# an uncited callout
# ---------------------------------------------------------------------------


def test_unresolvable_citation_voids_finding(tmp_path: Path) -> None:
    """Only ONE side of the pair actually exists in the vault -- the other
    note was deleted/never existed, so at most one citation (this side's own
    path) can resolve. The finding must be voided, never materialized."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(
        vault_root,
        "meeting-a.md",
        _panel_note("uuid-a", "Mötet är kl 14:00 på tisdag.\n\n"),
    )
    outbox_path = tmp_path / "outbox.jsonl"

    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="meeting-a.md",
        scope=None,
        claim_text="Mötet är kl 14:00 på tisdag.",
        interpretation="Conflict on meeting time.",
    )
    b = ClaimCandidate(
        note_uuid="uuid-ghost",
        rel_path="does-not-exist.md",
        scope=None,
        claim_text="The meeting is at 15:00 on Tuesday.",
        interpretation="Conflict on meeting time.",
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[(a, b)],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert report.findings == ()
    assert report.voided_by_unresolvable_citation == 1

    # No checkbox was written to the one note that DOES exist -- the voided
    # finding never reaches the propose writer.
    a_text = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    assert "- [ ]" not in a_text


def test_exactly_two_resolvable_citations_is_sufficient(tmp_path: Path) -> None:
    """The floor is >=2, not >2 -- exactly two resolvable citations (one per
    side's own path) is enough to materialize."""
    vault_root = _two_note_vault(tmp_path)
    outbox_path = tmp_path / "outbox.jsonl"

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert len(report.findings) == 2
    assert report.voided_by_unresolvable_citation == 0


# ---------------------------------------------------------------------------
# AC4: a declined contradiction finding is suppressed on rerun via the
# shared declined-proposal ledger (EXP-2)
# ---------------------------------------------------------------------------


def test_declined_contradiction_suppressed(tmp_path: Path) -> None:
    vault_root = _two_note_vault(tmp_path)
    outbox_path = tmp_path / "outbox.jsonl"
    ledger_path = tmp_path / "declined.jsonl"
    ledger = DeclinedLedger(ledger_path)

    # First pass: discover the finding_id, then decline it (mirroring the
    # human confirming a "reject" choice on the decision surface).
    first = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        config=ContradictionPassConfig(declined_ledger=ledger),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
        materialize=False,
    )
    assert len(first.findings) == 2
    finding_id = first.findings[0].finding_id

    ledger.record_decline(
        finding_id,
        finding_class=FindingClass.CONTRADICTION_CLAIM_CONFLICT.value,
        reason="human rejected",
        write_guard=_allow_all_guard(),
    )

    second = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        config=ContradictionPassConfig(declined_ledger=ledger),
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert second.findings == ()
    assert second.suppressed_by_decline == 1

    # No checkbox written for the declined finding.
    a_text = (vault_root / "meeting-a.md").read_text(encoding="utf-8")
    assert "- [ ]" not in a_text


# ---------------------------------------------------------------------------
# Idempotency: rerun over an unchanged vault is a no-op
# ---------------------------------------------------------------------------


def test_rerun_over_unchanged_vault_is_idempotent(tmp_path: Path) -> None:
    vault_root = _two_note_vault(tmp_path)
    outbox_path = tmp_path / "outbox.jsonl"

    first = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )
    a_text_after_first = (vault_root / "meeting-a.md").read_text(encoding="utf-8")

    second = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[_claim_pair()],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )
    a_text_after_second = (vault_root / "meeting-a.md").read_text(encoding="utf-8")

    first_ids = {f.finding_id for f in first.findings}
    second_ids = {f.finding_id for f in second.findings}
    assert first_ids == second_ids
    assert a_text_after_first == a_text_after_second
    assert a_text_after_second.count("- [ ]") == 1
