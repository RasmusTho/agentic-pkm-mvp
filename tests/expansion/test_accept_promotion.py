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
import os
from pathlib import Path

import pytest

from app.expansion.accept import (
    ACCEPT_MATERIALIZE_WRITE_ACTION,
    CREATE_ACCEPTED_EVENT,
    CREATE_DECLINED_EVENT,
    AcceptError,
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
    question_id: str | None = None,
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
        request,
        vault_root=vault_root,
        outbox_path=outbox_path,
        write_guard=_allow_all_guard(),
        draft_frontmatter_enricher=(
            (lambda _draft: {"question_id": question_id}) if question_id is not None else None
        ),
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
    from app.expansion import accept as accept_module
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path, kind=kind)
    _check_the_box(draft_path)
    original_draft_bytes = draft_path.read_bytes()

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
    # The staged draft is retired into an inert, receipt-bound recovery archive.
    assert not draft_path.exists()
    _pending_name, retired_name = accept_module._receipt_retirement_names(
        draft_path.name, result.receipt_id
    )
    retired_path = draft_path.parent / retired_name
    assert retired_path.read_bytes() == original_draft_bytes
    assert not retired_path.name.endswith(".md")
    assert retired_path not in vault_root.rglob("*.md")
    from app.expansion.create import sweep_expired_drafts

    sweep = sweep_expired_drafts(vault_root=vault_root, outbox_path=outbox_path)
    assert not sweep.expired
    assert retired_path.exists()

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


def test_accept_destination_prefix_sibling_is_outside_vault(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)
    sibling_destination = tmp_path / "vault-backup" / "outside.md"

    with pytest.raises(AcceptError, match="outside the vault root"):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="../vault-backup/outside.md",
            write_guard=_allow_all_guard(),
        )

    assert not sibling_destination.exists()
    assert draft_path.exists()
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_code_fenced_html_comment_does_not_hide_the_generated_control(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    text = text.replace("%% AI:Start %%", "```html\n<!--\n```\n%% AI:Start %%", 1)
    draft_path.write_text(text, encoding="utf-8")
    _check_the_box(draft_path)

    result = accept_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/topic-x.md",
    )

    assert isinstance(result, AcceptResult)
    assert (vault_root / "notes/topic-x.md").exists()


def test_indented_html_comment_does_not_hide_the_generated_control(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    text = text.replace("%% AI:Start %%", "    <!--\n\n%% AI:Start %%", 1)
    draft_path.write_text(text, encoding="utf-8")
    _check_the_box(draft_path)

    result = accept_draft(
        draft_path,
        vault_root=vault_root,
        outbox_path=outbox_path,
        destination="notes/topic-x.md",
    )

    assert isinstance(result, AcceptResult)
    assert (vault_root / "notes/topic-x.md").exists()


def test_mixed_space_tab_indented_comment_cannot_hide_unchecked_control(
    tmp_path: Path,
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    # A tab after three spaces advances to CommonMark column four, so this is
    # literal indented code, not an HTML comment that can hide the control.
    replacement = f"{checked_literal}\n   \t<!--\n{unchecked}\n-->"
    draft_path.write_text(text.replace(unchecked, replacement, 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "mixed indentation must not hide the generated control"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize("tag", ["pre", "code", "div", "script", "textarea", "svg", "custom-panel"])
def test_checked_lookalike_inside_html_block_does_not_authorize_acceptance(
    tmp_path: Path, tag: str
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    text = text.replace(unchecked, f"<{tag}>\n{checked_literal}\n</{tag}>", 1)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "literal HTML code must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_checked_lookalike_inside_unclosed_html_block_does_not_authorize_acceptance(
    tmp_path: Path,
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    text = text.replace(unchecked, f"<pre>\n{checked_literal}", 1)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "an unclosed literal HTML block must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize(
    "html_prefix",
    ["<div></div>", "<div><!-- visible block opener -->", "<!DOCTYPE html>"],
    ids=["same-line-open-close", "comment-after-opener", "declaration"],
)
def test_checked_lookalike_in_markdown_html_block_does_not_authorize_acceptance(
    tmp_path: Path, html_prefix: str
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    replacement = f"{html_prefix}\n{checked_literal}\n\n{unchecked}"
    draft_path.write_text(text.replace(unchecked, replacement, 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "literal Markdown HTML must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_unclosed_html_comment_cannot_hide_generated_unchecked_control(
    tmp_path: Path,
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    draft_path.write_text(
        text.replace(unchecked, f"{checked_literal}\n<!--\n{unchecked}", 1),
        encoding="utf-8",
    )
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "an open HTML comment must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_nonbreaking_space_cannot_be_normalized_into_acceptance_control(
    tmp_path: Path,
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    draft_path.write_text(text.replace(unchecked, f"\u00a0{checked_literal}", 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "a visually similar Unicode-prefixed line is not the control"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_unicode_line_separator_cannot_create_a_false_checkbox_line(tmp_path: Path) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    draft_path.write_text(text.replace(unchecked, f"\u2028{checked_literal}", 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "a Unicode line separator must not create a Markdown control line"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_self_closing_pre_remains_a_raw_html_block_until_its_end_tag(tmp_path: Path) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    replacement = f"<pre />\n\n{checked_literal}\n</pre>"
    draft_path.write_text(text.replace(unchecked, replacement, 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "a self-closing raw-block opener must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_markdown_fence_after_self_closing_pre_cannot_be_hidden_from_parser(tmp_path: Path) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    replacement = f"<pre />\n</pre>\n```\n\n{checked_literal}"
    draft_path.write_text(text.replace(unchecked, replacement, 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "a fence following a closed raw block must remain literal"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize(
    "literal_html",
    [
        "<pre>\n<pre></pre>\n{control}\n</pre>",
        "</pre><pre>\n{control}\n</pre>",
        '<pre title="</pre>">\n{control}\n</pre>',
    ],
    ids=["nested-same-tag", "close-then-open", "close-text-in-attribute"],
)
def test_nested_html_block_cannot_expose_a_checked_lookalike(
    tmp_path: Path, literal_html: str
) -> None:
    from scripts.yaml_roundtrip import load_frontmatter

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    frontmatter, text = load_frontmatter(draft_path.read_text(encoding="utf-8"))
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked_literal = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    draft_path.write_text(
        text.replace(unchecked, literal_html.replace("{control}", checked_literal), 1),
        encoding="utf-8",
    )
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists(), "nested literal markup must leave the draft staged"
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


# --- create_never_autowrites_canonical: unchecked draft is NOT materialized ---


def test_checked_unrelated_task_does_not_authorize_acceptance(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    draft_path.write_text("- [x] unrelated task\n" + text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination="notes/should-not-exist.md",
            write_guard=_allow_all_guard(),
        )

    after = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}
    assert after == before
    assert draft_path.exists()
    assert not (vault_root / "notes/should-not-exist.md").exists()
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize("control_mutation", ["wrong_draft_id", "duplicate_control"])
def test_acceptance_control_must_be_bound_and_unique(tmp_path: Path, control_mutation: str) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    control = next(line for line in text.splitlines() if line.startswith("- [ ] Accept this draft into the vault"))
    if control_mutation == "wrong_draft_id":
        checked_wrong_control = control.replace("- [ ]", "- [x]", 1).replace("(draft ", "(draft wrong-", 1)
        text = text.replace(control, checked_wrong_control, 1)
    else:
        checked_control = control.replace("- [ ]", "- [x]", 1)
        text = text.replace(control, f"{checked_control}\n{checked_control}", 1)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    after = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}
    assert after == before
    assert draft_path.exists()
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize("example_location", ["fenced_body", "frontmatter", "indented_body"])
def test_acceptance_examples_do_not_mint_authority(tmp_path: Path, example_location: str) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(text)
    draft_id = str(frontmatter["uuid"])
    generated_control = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(generated_control) == 1
    # Leave the example as the only possible acceptance signal, so each case
    # would have reproduced an implementation that treated literal text as authority.
    text = text.replace(generated_control + "\n", "", 1)
    checked = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    if example_location == "fenced_body":
        text = text.replace(
            "%% AI:Start %%\n",
            "%% AI:Start %%\n```markdown\n" + checked + "\n```\n",
            1,
        )
    elif example_location == "indented_body":
        text = text.replace("%% AI:Start %%\n", "%% AI:Start %%\n  " + checked + "\n", 1)
    else:
        parts = text.split("---", 2)
        assert len(parts) == 3, "staged draft must have YAML frontmatter"
        parts[1] += (
            "acceptance_example: |-\n"
            "  %% AI:Start %%\n"
            f"  {checked}\n"
            "  %% AI:End %%\n"
        )
        text = "---".join(parts)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_commented_acceptance_control_does_not_mint_authority(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(text)
    draft_id = str(frontmatter["uuid"])
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    text = text.replace(unchecked + "\n", "", 1)
    text = text.replace(
        "%% AI:Start %%\n",
        "%% AI:Start %%\n<!--\n" + checked + "\n-->\n",
        1,
    )
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_visible_checked_copy_cannot_replace_unchecked_control_hidden_in_comment(
    tmp_path: Path,
) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(text)
    draft_id = str(frontmatter["uuid"])
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    checked = f"- [x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    replacement = f"{checked}\n<!--\n{unchecked}\n-->"
    draft_path.write_text(text.replace(unchecked, replacement, 1), encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert draft_path.exists()
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


def test_html_comment_fragments_cannot_synthesize_acceptance_control(tmp_path: Path) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    text = draft_path.read_text(encoding="utf-8")
    from scripts.yaml_roundtrip import load_frontmatter

    frontmatter, _body = load_frontmatter(text)
    draft_id = str(frontmatter["uuid"])
    unchecked = f"- [ ] Accept this draft into the vault (draft {draft_id[:12]})"
    fragmented = f"- [<!-- hidden -->x] Accept this draft into the vault (draft {draft_id[:12]})"
    assert text.count(unchecked) == 1
    text = text.replace(unchecked + "\n", fragmented + "\n", 1)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


@pytest.mark.parametrize("panel_mutation", ["nested_start", "unmatched_end", "unmatched_start"])
def test_malformed_acceptance_panel_fails_closed(tmp_path: Path, panel_mutation: str) -> None:
    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    _check_the_box(draft_path)
    text = draft_path.read_text(encoding="utf-8")
    if panel_mutation == "nested_start":
        text = text.replace("%% AI:Start %%", "%% AI:Start %%\n%% AI:Start %%", 1)
    elif panel_mutation == "unmatched_end":
        text = text.replace("%% AI:End %%", "%% AI:End %%\n%% AI:End %%", 1)
    else:
        text = text.replace("%% AI:End %%", "", 1)
    draft_path.write_text(text, encoding="utf-8")
    before = {path.relative_to(vault_root) for path in vault_root.rglob("*.md")}

    with pytest.raises(DraftNotAcceptedError):
        accept_draft(draft_path, vault_root=vault_root, outbox_path=outbox_path)

    assert {path.relative_to(vault_root) for path in vault_root.rglob("*.md")} == before
    assert not [record for record in _outbox_records(outbox_path) if record["event"] == CREATE_ACCEPTED_EVENT]


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


def test_decline_preserves_candidate_edit_arriving_after_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.expansion import accept as accept_module
    from app.proposals.declined_ledger import DeclinedLedger

    vault_root, draft_path, outbox_path = _stage_draft(tmp_path)
    ledger = DeclinedLedger(tmp_path / "declined.jsonl")
    emit_receipt = accept_module._emit_receipt
    marker = "Manual edit after the decline snapshot was recorded."

    def emit_then_edit(event: str, payload: dict, **kwargs: object) -> str:
        receipt_id = emit_receipt(event, payload, **kwargs)
        if event == CREATE_DECLINED_EVENT:
            draft_path.write_text(
                draft_path.read_text(encoding="utf-8") + f"\n{marker}\n",
                encoding="utf-8",
            )
        return receipt_id

    monkeypatch.setattr(accept_module, "_emit_receipt", emit_then_edit)

    with pytest.raises(accept_module.AcceptanceReconciliationError) as unresolved:
        decline_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            reason="not useful",
            declined_ledger=ledger,
            write_guard=_allow_all_guard(),
        )

    assert unresolved.value.receipt_id
    assert unresolved.value.recovery_paths
    assert ledger.is_declined(draft_path.stem)
    assert draft_path.exists()
    assert marker in draft_path.read_text(encoding="utf-8")
    declined = [r for r in _outbox_records(outbox_path) if r["event"] == CREATE_DECLINED_EVENT]
    assert len(declined) == 1
    assert declined[0]["payload"]["draft_id"] == draft_path.stem


@pytest.mark.parametrize("edit_mode", ["in_place", "atomic_replace_same_bytes", "atomic_replace_changed_bytes"])
def test_exp4_retirement_restores_changed_or_replaced_draft(
    edit_mode: str, tmp_path: Path
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    original = loaded.raw_content
    changed = original + b"\nA concurrent editor changed this draft.\n"

    if edit_mode == "in_place":
        draft_path.write_bytes(changed)
        expected = changed
    else:
        replacement = draft_path.with_name(f"{draft_path.name}.replacement")
        expected = original if edit_mode == "atomic_replace_same_bytes" else changed
        replacement.write_bytes(expected)
        if edit_mode == "atomic_replace_same_bytes":
            os.utime(replacement, ns=(replacement.stat().st_atime_ns, loaded.file_identity[3]))
        replacement.replace(draft_path)

    with pytest.raises(accept_module.AcceptanceReconciliationError):
        accept_module._retire_loaded_draft_if_unchanged(loaded, receipt_id="test-receipt")

    assert draft_path.read_bytes() == expected
    assert not tuple(draft_path.parent.glob(f".{draft_path.name}.exp4-retire-*.pending"))
    assert not tuple(draft_path.parent.glob(f".{draft_path.name}.exp4-retired-*.recovery"))


@pytest.mark.parametrize("crash_after", ["pending", "retired"])
def test_exp4_retirement_retry_finishes_each_rename_state(
    crash_after: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    receipt_id = f"crash-{crash_after}"
    pending_name, retired_name = accept_module._receipt_retirement_names(
        draft_path.name, receipt_id
    )
    rename = accept_module._atomic_rename_noreplace_at
    crash_name = pending_name if crash_after == "pending" else retired_name

    def crash_after_rename(source_fd: int, source: str, dest_fd: int, dest: str) -> None:
        rename(source_fd, source, dest_fd, dest)
        if dest == crash_name:
            raise SystemExit("simulated process crash after rename")

    monkeypatch.setattr(accept_module, "_atomic_rename_noreplace_at", crash_after_rename)
    with pytest.raises(SystemExit, match="simulated process crash"):
        accept_module._retire_loaded_draft_if_unchanged(loaded, receipt_id=receipt_id)

    monkeypatch.setattr(accept_module, "_atomic_rename_noreplace_at", rename)
    archived = Path(
        accept_module._retire_loaded_draft_if_unchanged(loaded, receipt_id=receipt_id)
    )
    assert archived.name == retired_name
    assert archived.read_bytes() == loaded.raw_content
    assert not draft_path.exists()
    assert not (draft_path.parent / pending_name).exists()


def test_exp4_retirement_preserves_edit_between_pending_verification_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    _pending_name, retired_name = accept_module._receipt_retirement_names(
        draft_path.name, "edit-during-retirement"
    )
    edited = loaded.raw_content + b"\nEdited while being retired.\n"
    rename = accept_module._atomic_rename_noreplace_at

    def edit_before_archive(source_fd: int, source: str, dest_fd: int, dest: str) -> None:
        if dest == retired_name:
            descriptor = os.open(source, os.O_WRONLY | os.O_TRUNC, dir_fd=source_fd)
            try:
                os.write(descriptor, edited)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        rename(source_fd, source, dest_fd, dest)

    monkeypatch.setattr(accept_module, "_atomic_rename_noreplace_at", edit_before_archive)
    with pytest.raises(accept_module.AcceptanceReconciliationError):
        accept_module._retire_loaded_draft_if_unchanged(
            loaded, receipt_id="edit-during-retirement"
        )

    assert draft_path.read_bytes() == edited
    assert not (draft_path.parent / retired_name).exists()


def test_exp4_retirement_preserves_both_files_when_restore_name_is_occupied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    pending_name, _retired_name = accept_module._receipt_retirement_names(
        draft_path.name, "restore-collision"
    )
    replacement = b"A newer file appeared at the original path.\n"
    read_named = accept_module._read_named_draft

    def collide_while_reading(directory_fd: int, name: str) -> tuple[bytes, os.stat_result]:
        raw, info = read_named(directory_fd, name)
        if name == pending_name:
            draft_path.write_bytes(replacement)
            return raw + b"changed", info
        return raw, info

    monkeypatch.setattr(accept_module, "_read_named_draft", collide_while_reading)
    with pytest.raises(accept_module.AcceptanceReconciliationError) as conflict:
        accept_module._retire_loaded_draft_if_unchanged(loaded, receipt_id="restore-collision")

    assert draft_path.read_bytes() == replacement
    assert (draft_path.parent / pending_name).read_bytes() == loaded.raw_content
    assert str(draft_path.parent / pending_name) in conflict.value.recovery_paths


def test_exp4_retired_archive_preserves_writes_from_an_already_open_editor(
    tmp_path: Path
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    editor_fd = os.open(draft_path, os.O_RDWR)
    try:
        archive = Path(
            accept_module._retire_loaded_draft_if_unchanged(
                loaded, receipt_id="open-editor"
            )
        )
        later_edit = loaded.raw_content + b"\nLate write through the editor descriptor.\n"
        os.lseek(editor_fd, 0, os.SEEK_SET)
        os.ftruncate(editor_fd, 0)
        os.write(editor_fd, later_edit)
        os.fsync(editor_fd)
    finally:
        os.close(editor_fd)

    assert not draft_path.exists()
    assert archive.exists()
    assert archive.read_bytes() == later_edit


def test_exp4_missing_path_reconciles_a_receipt_bound_pending_archive(
    tmp_path: Path,
) -> None:
    from app.expansion import accept as accept_module

    _vault_root, draft_path, _outbox_path = _stage_draft(tmp_path)
    loaded = accept_module._load_draft(draft_path)
    receipt_id = "reconcile-pending"
    pending_name, retired_name = accept_module._receipt_retirement_names(
        draft_path.name, receipt_id
    )
    directory_fd = os.open(draft_path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        accept_module._atomic_rename_noreplace_at(
            directory_fd,
            draft_path.name,
            directory_fd,
            pending_name,
        )
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

    assert not draft_path.exists()
    archived = accept_module.reconcile_missing_draft_retirement(
        draft_path,
        receipt_id=receipt_id,
        expected_content_sha256=loaded.raw_content_sha256,
    )

    assert archived == str(draft_path.parent / retired_name)
    assert Path(archived).read_bytes() == loaded.raw_content
    assert not (draft_path.parent / pending_name).exists()


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


def test_question_acceptance_recovery_checks_write_guard_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.expansion import accept as accept_module

    vault_root, draft_path, outbox_path = _stage_draft(
        tmp_path,
        kind=OutputKind.ANSWER_NOTE,
        question_id="sq-00000000-0000-0000-0000-000000000001",
    )
    _check_the_box(draft_path)
    destination = "notes/question-answer.md"
    destination_path = vault_root / destination
    retire = accept_module._retire_loaded_draft_if_unchanged

    def crash_before_retirement(_loaded, *, receipt_id: str) -> str:
        raise OSError("simulated crash before draft retirement")

    monkeypatch.setattr(accept_module, "_retire_loaded_draft_if_unchanged", crash_before_retirement)
    with pytest.raises(OSError, match="simulated crash"):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination=destination,
            write_guard=_allow_all_guard(),
        )
    monkeypatch.setattr(accept_module, "_retire_loaded_draft_if_unchanged", retire)

    leftover_link = destination_path.with_name(f".{destination_path.name}.leftover.tmp")
    os.link(destination_path, leftover_link)
    destination_stat = destination_path.stat()
    assert draft_path.exists()
    assert leftover_link.exists()

    with pytest.raises(WritesBlockedError):
        accept_draft(
            draft_path,
            vault_root=vault_root,
            outbox_path=outbox_path,
            destination=destination,
            write_guard=_blocked_guard(),
        )

    assert draft_path.exists()
    assert leftover_link.exists()
    assert os.stat(leftover_link).st_ino == destination_stat.st_ino
