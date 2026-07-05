"""#2987 (G2-2) -- deterministic mechanical-hygiene transforms + panel materialization.

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §2, §6.

Covers:
- each class-specific deterministic transform reproduces an exact,
  reproducible replacement for its mechanical-allowlist class,
- a transform that cannot reproduce a candidate exactly reports
  ``matched=False`` (the demotion signal AC1 requires),
- Panel suggested-checkbox materialization (``write_curation_proposals``) is
  idempotent on rerun and always inserts unchecked checkboxes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.curation.findings import CurationFinding, FindingClass
from app.curation.hygiene_transforms import (
    TransformResult,
    transform_broken_wikilink,
    transform_frontmatter_schema,
    transform_malformed_markdown,
    transform_text_span,
)
from app.curation.proposal_writer import (
    CURATION_PROPOSE_WRITE_ACTION,
    write_curation_proposals,
)
from app.write_guard import WriteGuard, WritesBlockedError


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "safe_mode", "reason": "test-blocked"})


def _panel_note(body_extra: str = "") -> str:
    return (
        "---\nuuid: uuid-note-1\nkind: note\n---\n\n"
        "# Note\n\n"
        "%% AI:Start %%\n"
        "## AI-instruktion\n"
        "\n"
        "## AI-åtgärder\n"
        "%% AI:End %%\n"
        f"{body_extra}"
    )


def _write_note(vault_root: Path, rel_path: str, content: str) -> Path:
    path = vault_root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Deterministic transforms: exact reproduction + demotion-on-mismatch (AC1)
# ---------------------------------------------------------------------------


def test_broken_wikilink_transform_matches_when_unambiguous() -> None:
    result = transform_broken_wikilink(observed="[[Old Name]]", candidate_targets=("New Name",))
    assert result.matched is True
    assert result.transformed == "[[New Name]]"


def test_broken_wikilink_transform_demotes_when_ambiguous() -> None:
    result = transform_broken_wikilink(
        observed="[[Old Name]]", candidate_targets=("New Name", "Other Name")
    )
    assert result.matched is False
    assert "ambiguous" in result.reason


def test_broken_wikilink_transform_demotes_when_unresolved() -> None:
    result = transform_broken_wikilink(observed="[[Old Name]]", candidate_targets=())
    assert result.matched is False


def test_malformed_markdown_transform_closes_unclosed_fence() -> None:
    span = "Some text\n```python\nprint('hi')\n"
    result = transform_malformed_markdown(span_text=span)
    assert result.matched is True
    assert result.transformed == span.rstrip("\n") + "\n```"
    # Reproducibility: re-running the transform over its own output is a no-op
    # (an already-closed fence never matches this transform again).
    rerun = transform_malformed_markdown(span_text=result.transformed)
    assert rerun.matched is False


def test_malformed_markdown_transform_does_not_match_already_closed_fence() -> None:
    span = "Some text\n```python\nprint('hi')\n```\n"
    result = transform_malformed_markdown(span_text=span)
    assert result.matched is False


def test_frontmatter_schema_transform_closes_unterminated_block() -> None:
    raw = "---\nuuid: abc\nkind: note\nThis never closes.\n"
    result = transform_frontmatter_schema(raw_frontmatter_block=raw)
    assert result.matched is True
    assert result.transformed.count("---") == 2


def test_frontmatter_schema_transform_does_not_match_terminated_block() -> None:
    raw = "---\nuuid: abc\nkind: note\n---\nBody.\n"
    result = transform_frontmatter_schema(raw_frontmatter_block=raw)
    assert result.matched is False


def test_text_span_transform_demotes_when_language_gate_failed() -> None:
    """AC1: if the transform cannot reproduce the LLM's suggestion under the
    Swedish safeguard, the finding demotes to propose-track -- this is the
    exact demotion path AC1 names."""
    result = transform_text_span(
        observed="fakta", llm_candidate="facts", language_gate_passed=False
    )
    assert result.matched is False
    assert "safeguard" in result.reason


def test_text_span_transform_matches_when_gate_passed_and_candidate_differs() -> None:
    result = transform_text_span(
        observed="teh", llm_candidate="the", language_gate_passed=True
    )
    assert result.matched is True
    assert result.transformed == "the"


def test_text_span_transform_demotes_when_no_differing_candidate() -> None:
    result = transform_text_span(
        observed="correct", llm_candidate="correct", language_gate_passed=True
    )
    assert result.matched is False


def test_transform_result_is_frozen_dataclass() -> None:
    result = TransformResult(matched=True, transformed="x")
    with pytest.raises(Exception):
        result.matched = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Panel suggested-checkbox materialization (AC4)
# ---------------------------------------------------------------------------


def _finding(note_uuid: str = "path:note.md", proposed: str = "fix the thing") -> CurationFinding:
    return CurationFinding.create(
        note_uuid=note_uuid,
        finding_class=FindingClass.STRUCTURE_GAP,
        span="L1:body",
        observed="observed text",
        proposed=proposed,
        evidence=("note.md",),
    )


def test_panel_materialization_writes_unchecked_checkbox(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    note_path = _write_note(vault_root, "note.md", _panel_note())
    outbox_path = tmp_path / "outbox.jsonl"

    finding = _finding()
    unresolved = write_curation_proposals(
        [finding],
        vault_root=vault_root,
        write_guard=_allow_all_guard(),
        outbox_path=outbox_path,
    )

    assert unresolved == []
    updated = note_path.read_text(encoding="utf-8")
    assert "- [ ]" in updated
    assert "- [x]" not in updated
    assert finding.finding_id[:12] in updated

    # panel.action.logged receipt was emitted.
    lines = outbox_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "panel.action.logged"
    assert record["payload"]["finding_id"] == finding.finding_id
    assert record["payload"]["reason"] == "curation_finding_proposed"


def test_panel_materialization_idempotent(tmp_path: Path) -> None:
    """Re-running proposal writing over an already-proposed finding is a no-op:
    no duplicate checkbox line, no duplicate receipt."""
    vault_root = tmp_path / "vault"
    note_path = _write_note(vault_root, "note.md", _panel_note())
    outbox_path = tmp_path / "outbox.jsonl"
    finding = _finding()

    write_curation_proposals(
        [finding], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )
    first_pass_text = note_path.read_text(encoding="utf-8")

    write_curation_proposals(
        [finding], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )
    second_pass_text = note_path.read_text(encoding="utf-8")

    assert second_pass_text == first_pass_text
    assert second_pass_text.count("- [ ]") == 1

    receipt_lines = outbox_path.read_text(encoding="utf-8").splitlines()
    assert len(receipt_lines) == 1  # no duplicate receipt on rerun


def test_panel_materialization_distinguishable_from_human_authored(tmp_path: Path) -> None:
    """The generated checkbox always carries the ai:option_id/ai:id/ai:proposed
    marker triplet, which is how the Panel parser distinguishes a machine
    proposal from a human-authored checkbox line."""
    vault_root = tmp_path / "vault"
    note_path = _write_note(vault_root, "note.md", _panel_note())
    outbox_path = tmp_path / "outbox.jsonl"

    write_curation_proposals(
        [_finding()], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )
    updated = note_path.read_text(encoding="utf-8")
    assert "<!--ai:option_id=" in updated
    assert "<!--ai:id=" in updated
    assert "<!--ai:proposed=" in updated


def test_panel_materialization_gated_by_write_guard(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    _write_note(vault_root, "note.md", _panel_note())
    outbox_path = tmp_path / "outbox.jsonl"

    with pytest.raises(WritesBlockedError) as exc_info:
        write_curation_proposals(
            [_finding()],
            vault_root=vault_root,
            write_guard=_blocking_guard(),
            outbox_path=outbox_path,
        )
    assert exc_info.value.action == CURATION_PROPOSE_WRITE_ACTION
    assert not outbox_path.exists()


def test_panel_materialization_skips_unresolvable_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outbox_path = tmp_path / "outbox.jsonl"

    finding = _finding(note_uuid="path:missing-note.md")
    unresolved = write_curation_proposals(
        [finding], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )

    assert unresolved == [finding]
