"""Fitness invariants for the graduated-curation capability (G2).

Invariant registry: docs/testing/invariant-tests.md ::
``curation_citations_resolve``, ``semantic_curation_never_autowrites``.
Spec: docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md §7.

Purpose:

- ``curation_citations_resolve``: every ``contradiction.claim_conflict``
  finding carries >=2 in-vault source references that resolve AT
  MATERIALIZATION TIME; unresolvable evidence voids the finding rather than
  materializing an uncited callout.
- ``semantic_curation_never_autowrites``: propose-track findings (including
  ``contradiction.claim_conflict``) can only materialize as unchecked
  ``AI-åtgärder`` checkboxes + receipts; no code path from a propose-track
  finding reaches a body write or governed effect in the same pass.
"""
from __future__ import annotations

from pathlib import Path

from app.curation.findings import MECHANICAL_ALLOWLIST, FindingClass, FindingTrack, track_for_class
from app.expansion.contradiction import (
    MIN_RESOLVABLE_CITATIONS,
    ClaimCandidate,
    run_contradiction_pass,
)
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


# ---------------------------------------------------------------------------
# semantic_curation_never_autowrites (contradiction is a propose-track class)
# ---------------------------------------------------------------------------


def test_contradiction_class_is_disjoint_from_mechanical_allowlist() -> None:
    """Static, construction-level guarantee: the class enum is closed and
    `contradiction.claim_conflict` is never a member of the auto-fix
    allowlist -- no configuration can move it there."""
    assert FindingClass.CONTRADICTION_CLAIM_CONFLICT not in MECHANICAL_ALLOWLIST


def test_semantic_never_autowrites() -> None:
    """No config can move `contradiction.claim_conflict` onto the auto-fix
    track: `track_for_class` derives the track from class membership ALONE,
    so it resolves to `propose` unconditionally."""
    assert track_for_class(FindingClass.CONTRADICTION_CLAIM_CONFLICT) == FindingTrack.PROPOSE


def test_contradiction_pass_never_materializes_a_checked_box(tmp_path: Path) -> None:
    """Production-call-site enforcement: running the real pass end to end
    never writes a checked (`- [x]`) box or a `[!contradiction]` callout --
    the only path from finding to note text is `write_curation_proposals`,
    which is propose-only by construction."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "Claim A is true.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "Claim A is false.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="a.md",
        scope=None,
        claim_text="Claim A is true.",
        interpretation="Direct negation between the two notes.",
    )
    b = ClaimCandidate(
        note_uuid="uuid-b",
        rel_path="b.md",
        scope=None,
        claim_text="Claim A is false.",
        interpretation="Direct negation between the two notes.",
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[(a, b)],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert len(report.findings) == 2
    updated_a = (vault_root / "a.md").read_text(encoding="utf-8")
    updated_b = (vault_root / "b.md").read_text(encoding="utf-8")
    assert "- [x]" not in updated_a and "- [x]" not in updated_b
    assert "[!contradiction]" not in updated_a and "[!contradiction]" not in updated_b


# ---------------------------------------------------------------------------
# curation_citations_resolve
# ---------------------------------------------------------------------------


def test_citations_resolve(tmp_path: Path) -> None:
    """Every emitted contradiction finding carries >= MIN_RESOLVABLE_CITATIONS
    in-vault source references that resolve at materialization time; a
    finding whose resolvable count falls below the floor voids rather than
    materializes (this is the single canonical assertion the invariant
    registry names, mirroring `tests/curation/test_contradiction_citations_resolve.py`'s
    more detailed AC-level coverage)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "The launch date is March 1.\n\n"))
    _write_note(vault_root, "b.md", _panel_note("uuid-b", "The launch date is April 1.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="a.md",
        scope=None,
        claim_text="The launch date is March 1.",
        interpretation="Conflicting launch dates.",
    )
    b = ClaimCandidate(
        note_uuid="uuid-b",
        rel_path="b.md",
        scope=None,
        claim_text="The launch date is April 1.",
        interpretation="Conflicting launch dates.",
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[(a, b)],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert len(report.findings) == 2
    for finding in report.findings:
        resolvable_paths = [e for e in finding.evidence if e in ("a.md", "b.md")]
        assert len(resolvable_paths) >= MIN_RESOLVABLE_CITATIONS


def test_citations_resolve_voids_finding_with_dangling_citation(tmp_path: Path) -> None:
    """The mirror case: a candidate pair where one side's note does not
    exist in the vault never materializes -- no uncited "trust me" callout
    is ever written."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_note(vault_root, "a.md", _panel_note("uuid-a", "The launch date is March 1.\n\n"))
    outbox_path = tmp_path / "outbox.jsonl"

    a = ClaimCandidate(
        note_uuid="uuid-a",
        rel_path="a.md",
        scope=None,
        claim_text="The launch date is March 1.",
        interpretation="Conflicting launch dates.",
    )
    ghost = ClaimCandidate(
        note_uuid="uuid-ghost",
        rel_path="ghost.md",
        scope=None,
        claim_text="The launch date is April 1.",
        interpretation="Conflicting launch dates.",
    )

    report = run_contradiction_pass(
        vault_root=vault_root,
        claim_pairs=[(a, ghost)],
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert report.findings == ()
    assert report.voided_by_unresolvable_citation == 1
    a_text = (vault_root / "a.md").read_text(encoding="utf-8")
    assert "- [ ]" not in a_text
