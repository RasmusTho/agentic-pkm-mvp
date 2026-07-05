"""#2987 (G2-2) -- propose-only while ``AUTOFIX_APPLY`` is unset (AC3).

Spec: ``docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md`` §1, §2, §6.

AC3: "With ``AUTOFIX_APPLY`` unset (the ratified-default state), every
finding -- including mechanical-allowlist classes -- materializes as an
unchecked, propose-track panel checkbox; no body edit occurs."

This is the enforcement test asserted at the production call site
(``write_curation_proposals``), not merely a unit check of the flag reader:
it proves that even a finding whose *class* is on the mechanical allowlist
(``FindingTrack.AUTO_FIX``) is written as a propose-track checkbox and never
as a direct body mutation, matching ``semantic_curation_never_autowrites``'s
sibling invariant (no code path from a propose-track finding -- or, here, any
finding while the flag is unset -- reaches a body write outside the governed
checkbox block).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.curation.findings import CurationFinding, FindingClass, FindingTrack
from app.curation.proposal_writer import (
    AUTOFIX_APPLY_ENV,
    autofix_apply_enabled,
    write_curation_proposals,
)
from app.write_guard import WriteGuard


def _allow_all_guard() -> WriteGuard:
    return WriteGuard(snapshot_fn=lambda: {"state": "healthy", "reason": None})


def _panel_note() -> str:
    return (
        "---\nuuid: uuid-note-1\nkind: note\n---\n\n"
        "# Note\n\n"
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


@pytest.fixture(autouse=True)
def _clear_autofix_apply_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(AUTOFIX_APPLY_ENV, raising=False)


def test_autofix_apply_absent_reads_as_disabled() -> None:
    assert AUTOFIX_APPLY_ENV not in os.environ
    assert autofix_apply_enabled() is False


@pytest.mark.parametrize("raw_value", ["0", "false", "False", "no", "off", ""])
def test_autofix_apply_falsy_values_read_as_disabled(
    raw_value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUTOFIX_APPLY_ENV, raw_value)
    assert autofix_apply_enabled() is False


@pytest.mark.parametrize("raw_value", ["1", "true", "True", "yes", "on"])
def test_autofix_apply_truthy_values_read_as_enabled(
    raw_value: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(AUTOFIX_APPLY_ENV, raw_value)
    assert autofix_apply_enabled() is True


@pytest.mark.parametrize(
    "finding_class",
    [
        # Every mechanical-allowlist class (FindingTrack.AUTO_FIX by the
        # class->track wall) -- the exact classes AC3 calls out by name.
        FindingClass.LINK_BROKEN_WIKILINK,
        FindingClass.MARKDOWN_MALFORMED_SYNTAX,
        FindingClass.FRONTMATTER_SCHEMA_VIOLATION,
        FindingClass.TEXT_MISSPELLING,
        FindingClass.TEXT_TRANSCRIPTION_ARTIFACT,
    ],
)
def test_mechanical_allowlist_finding_materializes_as_propose_checkbox(
    finding_class: FindingClass, tmp_path: Path
) -> None:
    """The production call site (write_curation_proposals) never body-edits a
    mechanical-allowlist finding while AUTOFIX_APPLY is unset -- it always
    inserts an unchecked checkbox instead."""
    assert AUTOFIX_APPLY_ENV not in os.environ  # sanity: unratified default

    vault_root = tmp_path / "vault"
    note_path = _write_note(vault_root, "note.md", _panel_note())
    original_text = note_path.read_text(encoding="utf-8")
    outbox_path = tmp_path / "outbox.jsonl"

    finding = CurationFinding.create(
        note_uuid="path:note.md",
        finding_class=finding_class,
        span="L5:body",
        observed="teh quikc fox",
        proposed="the quick fox",
        evidence=("note.md",),
    )
    # Confirm this finding really is on the mechanical allowlist -- the test
    # would be meaningless against a propose-track class.
    assert finding.track == FindingTrack.AUTO_FIX

    write_curation_proposals(
        [finding], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )

    updated_text = note_path.read_text(encoding="utf-8")

    # No body edit occurred outside the governed checkbox block: the
    # observed/proposed text is never substituted directly into the note
    # body -- it only appears inside a fresh, unchecked checkbox line.
    assert "teh quikc fox" not in updated_text  # observed text was never body-edited in place
    assert updated_text.count("- [x]") == 0
    assert updated_text.count("- [ ]") == 1
    assert original_text in updated_text or _panel_block_only_change(original_text, updated_text)


def _panel_block_only_change(original: str, updated: str) -> bool:
    """True if every line unique to *updated* is a proposal checkbox line
    (i.e. the diff is additive-only, confined to the AI-åtgärder block)."""
    original_lines = set(original.splitlines())
    new_lines = [line for line in updated.splitlines() if line not in original_lines]
    return all(line.strip().startswith("- [ ]") for line in new_lines)


def test_propose_only_regardless_of_autofix_apply_value_in_this_slice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Even if a caller sets AUTOFIX_APPLY=1, this slice's writer
    (write_curation_proposals) has no act-tier branch to take -- G2-2 ships
    with the apply path unbuilt (parent #2980: the auto-fix flip is deferred
    to the not-yet-filed G2-3). Setting the flag must not change this
    writer's behavior at all."""
    monkeypatch.setenv(AUTOFIX_APPLY_ENV, "1")
    assert autofix_apply_enabled() is True

    vault_root = tmp_path / "vault"
    note_path = _write_note(vault_root, "note.md", _panel_note())
    outbox_path = tmp_path / "outbox.jsonl"

    finding = CurationFinding.create(
        note_uuid="path:note.md",
        finding_class=FindingClass.LINK_BROKEN_WIKILINK,
        span="L5:body",
        observed="[[Old]]",
        proposed="[[New]]",
        evidence=("note.md",),
    )

    write_curation_proposals(
        [finding], vault_root=vault_root, write_guard=_allow_all_guard(), outbox_path=outbox_path
    )

    updated_text = note_path.read_text(encoding="utf-8")
    assert updated_text.count("- [ ]") == 1
    assert "[[New]]" not in updated_text.split("%% AI:Start %%")[0]  # no body edit outside panel
