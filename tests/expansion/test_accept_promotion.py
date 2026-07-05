"""#2997 (EXP-4) -- Governed acceptance/promotion of staged Create drafts.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/EXPANSION_CONNECT_AND_CREATE.md`` §2.4, §5.

Covers every behavioral Acceptance Criterion from the issue, asserted at the
production call site (``app.expansion.accept.accept_draft`` /
``decline_draft``), driven by a *real* staged draft produced by EXP-3's
``run_create_pass`` -- not a hand-rolled fixture -- so the two slices are
exercised as one vertical loop:

- AC1: accepting a ``create.overview`` / ``create.answer_note`` draft
  materializes a new note at the human-chosen destination with linked
  ``expansion.create.accepted`` receipts and intact provenance
  (``sources``, ``derived_by: synthesis``, ``accepted_by: human``, receipt id).
- AC2: declining a draft writes an entry to the EXP-2 declined ledger and
  produces no canonical note; the draft is removed with its receipt kept.
- AC3: edited-then-accepted -- the materialized note reflects the human's
  edited draft text, not the original generated draft.
- AC4: the modify-existing-note variant is held at ``ask-you`` -- never
  materialized as a lighter-tier action.

Plus the critical negative/enforcement paths (the point of this slice):

- an UNCHECKED draft is never materialized (``create_never_autowrites_canonical``);
- acceptance mints a decision token + emits an acceptance receipt
  (``authority_transition_requires_decision_token_and_receipt``) and never
  self-authorizes (``execution_cannot_authorize_itself``);
- a cited source that no longer resolves at acceptance time blocks loudly;
- re-accepting an already-accepted draft is idempotent (no double-materialize).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.expansion.accept import (
    ACCEPT_MATERIALIZE_WRITE_ACTION,
    CREATE_ACCEPTED_EVENT,
    CREATE_DECLINED_EVENT,
    AcceptResult,
    DraftNotAcceptedError,
    ModifyExistingRequiresAskError,
    UnresolvableCitationError,
    accept_draft,
    decline_draft,
)
from app.expansion.create import CreateRequest, OutputKind, SourceInput, run_create_pass
from app.write_guard import WriteGuard, WritesBlockedError


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _blocked_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "unhealthy", "reason": "test-blocked"})


def _outbox_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _source(object_id: str, text: str, span: str, *, language: str = "en") -> SourceInput:
    return SourceInput(
        object_id=object_id,
        note_path=f"{object_id}.md",
        text=text,
        quoted_spans=(span,),
        language=language,
        review_state="reviewed",
    )


def _stage_draft(
    tmp_path: Path,
    *,
    kind: OutputKind = OutputKind.OVERVIEW,
    title: str = "Topic X overview",
    sources: tuple[SourceInput, ...] | None = None,
) -> tuple[Path, Path, str]:
    """Produce a real staged draft via EXP-3's run_create_pass; return
    (vault_root, draft_abs_path, outbox_path)."""
    vault_root = tmp_path / "vault"
    vault_root.mkdir(exist_ok=True)
    outbox_path = tmp_path / "outbox.jsonl"
    if sources is None:
        sources = (
            _source("obj-a", "Alpha body about topic X.", "Alpha body about topic X."),
            _source("obj-b", "Beta body about topic X.", "Beta body about topic X."),
        )
    request = CreateRequest(kind=kind, title=title, sources=sources, question="What is X?")
    report = run_create_pass(
        request, vault_root=vault_root, outbox_path=outbox_path, write_guard=_allow_all_guard()
    )
    assert report.draft_path is not None
    return vault_root, vault_root / report.draft_path, outbox_path


def _check_the_box(draft_path: Path) -> None:
    text = draft_path.read_text(encoding="utf-8")
    checked = text.replace("- [ ] Accept", "- [x] Accept")
    assert checked != text, "expected an unchecked acceptance checkbox to flip"
    draft_path.write_text(checked, encoding="utf-8")


# --- AC1: accept materializes a new note with linked receipts + provenance ---


@pytest.mark.parametrize("kind", [OutputKind.OVERVIEW, OutputKind.ANSWER_NOTE])
def test_accept_materializes_note_with_receipts_and_provenance(
    tmp_path: Path, kind: OutputKind
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path, kind=kind)
    _check_the_box(draft_path)

    result = accept_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/topic-x-accepted.md",
        write_guard=_allow_all_guard(),
    )

    assert isinstance(result, AcceptResult)
    assert result.status == "accepted"
    assert result.final_note_path == "notes/topic-x-accepted.md"
    assert result.receipt_id
    assert result.decision_token_ref  # decision token was minted
    assert result.transition_id  # governed AuthorityTransition recorded

    final_note = vault_root / result.final_note_path
    assert final_note.exists()
    # The staged draft is consumed (not left dangling for re-acceptance).
    assert not draft_path.exists()

    fm, body = load_frontmatter(final_note.read_text(encoding="utf-8"))
    # Provenance survives acceptance permanently.
    assert fm["derived_by"] == "synthesis"
    assert fm["authority_state"] == "accepted"
    assert fm["accepted_by"] == "human"
    assert fm["acceptance_receipt_id"] == result.receipt_id
    assert fm["decision_token_ref"] == result.decision_token_ref
    assert fm["sources"] == ["obj-a", "obj-b"]
    # Not silently upgraded: stays derived_by synthesis, no evidence role stamped.
    assert "evidence_role" not in fm
    # The accepted canonical note carries no live acceptance checkbox.
    assert "- [x]" not in body and "- [ ]" not in body

    # Linked acceptance receipt in the outbox (draft -> final note -> sources).
    accepted = [r for r in _outbox_records(outbox_path) if r["event"] == CREATE_ACCEPTED_EVENT]
    assert len(accepted) == 1
    payload = accepted[0]["payload"]
    assert payload["final_note_path"] == "notes/topic-x-accepted.md"
    assert payload["sources"] == ["obj-a", "obj-b"]
    assert payload["decision_token_ref"] == result.decision_token_ref
    assert payload["authority_receipt_id"] == result.receipt_id


# --- create_never_autowrites_canonical: unchecked draft is NOT materialized ---


def test_unchecked_draft_is_never_materialized(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    # Do NOT check the box.
    before = {p.relative_to(vault_root) for p in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    # No canonical note was written; the staged draft is untouched.
    after = {p.relative_to(vault_root) for p in vault_root.rglob("*.md")}
    assert after == before
    assert draft_path.exists()
    assert not (vault_root / "notes/should-not-exist.md").exists()
    # No acceptance receipt was emitted for an unchecked draft.
    assert not [r for r in _outbox_records(outbox_path) if r["event"] == CREATE_ACCEPTED_EVENT]


# --- authority_transition / WriteGuard: gated by the named action -------------


def test_acceptance_is_writeguard_gated_by_named_action(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)

    with pytest.raises(WritesBlockedError) as excinfo:
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/topic-x.md",
            write_guard=_blocked_guard(),
        )
    # The block names exactly this slice's materialization action -- so the
    # canonical write is gated by a real, named WriteGuard action.
    assert excinfo.value.action == ACCEPT_MATERIALIZE_WRITE_ACTION
    assert not (vault_root / "notes/topic-x.md").exists()


# --- synthesis_carries_source_provenance: stale citation blocks loudly --------


def test_unresolvable_citation_at_acceptance_blocks_loudly(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)

    # The caller supplies the live source set; one cited source has vanished.
    with pytest.raises(UnresolvableCitationError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/topic-x.md",
            live_source_ids={"obj-a"},  # obj-b no longer resolves
            write_guard=_allow_all_guard(),
        )
    assert not (vault_root / "notes/topic-x.md").exists()
    assert draft_path.exists()


# --- AC3: edited-then-accepted -> the edited text is what materializes ---------


def test_edited_then_accepted_materializes_edited_text(tmp_path: Path) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)

    text = draft_path.read_text(encoding="utf-8")
    edited_marker = "HUMAN EDIT: this is the human's authoritative revision."
    text = text.replace("## Sources", f"{edited_marker}\n\n## Sources")
    text = text.replace("- [ ] Accept", "- [x] Accept")
    draft_path.write_text(text, encoding="utf-8")

    result = accept_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/edited.md",
        write_guard=_allow_all_guard(),
    )
    _fm, body = load_frontmatter((vault_root / result.final_note_path).read_text(encoding="utf-8"))
    assert edited_marker in body  # human edit survived into canonical


# --- AC4: modify-existing-note variant stays ask-you --------------------------


def test_modify_existing_note_variant_stays_ask_you(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)

    # A canonical note already exists at the chosen destination -- materializing
    # over it is a body edit, held at ask-you, never a lighter-tier auto-write.
    existing = vault_root / "hub.md"
    existing.write_text("---\nuuid: hub-1\n---\n\n# Existing hub\nhuman prose\n", encoding="utf-8")
    before = existing.read_text(encoding="utf-8")

    with pytest.raises(ModifyExistingRequiresAskError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="hub.md",
            write_guard=_allow_all_guard(),
        )
    # The existing canonical note is byte-identical -- not touched at a lighter tier.
    assert existing.read_text(encoding="utf-8") == before
    # The staged draft is preserved (the human can still choose a new destination).
    assert draft_path.exists()


# --- AC2: decline -> ledger entry + no canonical note; receipt kept -----------


def test_decline_writes_ledger_entry_and_no_note(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    ledger_path = tmp_path / "declined.jsonl"

    from app.proposals.declined_ledger import DeclinedLedger

    ledger = DeclinedLedger(ledger_path)

    before = {p.relative_to(vault_root) for p in vault_root.rglob("*.md")}
    draft_id = draft_path.stem

    result = decline_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        reason="not useful",
        declined_ledger=ledger,
        write_guard=_allow_all_guard(),
    )
    assert result.status == "declined"
    assert result.ledger_recorded is True
    assert result.receipt_id

    # No canonical note was produced; the staged draft is removed.
    after = {p.relative_to(vault_root) for p in vault_root.rglob("*.md")}
    assert draft_path.relative_to(vault_root) not in after
    assert after.issubset(before)  # nothing new appeared

    # The decline is recorded in the EXP-2 declined ledger (suppresses re-propose).
    assert ledger.is_declined(draft_id)
    # The decline receipt is kept in the outbox.
    declined = [r for r in _outbox_records(outbox_path) if r["event"] == CREATE_DECLINED_EVENT]
    assert len(declined) == 1
    assert declined[0]["payload"]["draft_id"] == draft_id


# --- Idempotency: re-accepting an already-accepted draft does not double-write -


def test_reaccept_is_idempotent(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)

    first = accept_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/topic-x.md",
        write_guard=_allow_all_guard(),
    )
    assert first.status == "accepted"
    final_note = vault_root / first.final_note_path
    accepted_text = final_note.read_text(encoding="utf-8")

    # Re-run the acceptor against the accepted canonical note itself (an
    # already-accepted artifact): must be a no-op, not a second materialize.
    second = accept_draft(
        final_note,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/topic-x-2.md",
        write_guard=_allow_all_guard(),
    )
    assert second.status == "already_accepted"
    # No second canonical note was written.
    assert not (vault_root / "notes/topic-x-2.md").exists()
    # The accepted note is byte-identical -- not re-materialized.
    assert final_note.read_text(encoding="utf-8") == accepted_text
    # Exactly one acceptance receipt was emitted across both calls.
    accepted_receipts = [
        r for r in _outbox_records(outbox_path) if r["event"] == CREATE_ACCEPTED_EVENT
    ]
    assert len(accepted_receipts) == 1
