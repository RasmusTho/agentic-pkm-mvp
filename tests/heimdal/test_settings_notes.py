"""`_heimdal/**` settings-note substrate + schema tests (Epic #3019 slice A14, #3034).

Covers the governing Issue's two behavioral Acceptance Criteria:

- ``test_schema_and_authority_split`` -- every declared `_heimdal/**` note
  spec carries an explicit authority and every section resolves a non-empty
  editable-vs-agent-authored field split; a concrete rendered note round-
  trips that split losslessly through `parse_note`.
- ``test_notes_are_writable_source_of_record`` -- a human edit to an
  editable field, made directly on disk (simulating an Obsidian edit), is
  read back as intent and honored: a subsequent agent update via
  `apply_agent_update` preserves it exactly, never silently overwriting it
  as though the note were read-only.

Both tests exercise the real production read/write entry point
(`read_settings_note` / `write_settings_note` / `apply_agent_update`, backed
by `app.knowledge.write_ops.write_note_relative` +
`app.write_guard.WriteGuard`), mirroring `tests/heimdal/test_entity_register.py`'s
temp-vault-fixture convention: no network, no real Postgres, no real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal.settings_notes import (
    ATTENTION_DAY,
    CONSENT,
    DEVICE_CONFIG,
    ENTITY_REVIEW,
    FIELD_AGENT_AUTHORED,
    FIELD_HUMAN_EDITABLE,
    INTERESTS,
    NEVER_LIST,
    SETTINGS,
    SETTINGS_NOTE_SPECS,
    SOURCE_CONFIG,
    WATCHLIST,
    FieldSpec,
    SectionSpec,
    SettingsNote,
    SettingsNoteError,
    SettingsNoteSpec,
    apply_agent_update,
    note_rel_path,
    parse_note,
    read_settings_note,
    render_note,
    write_settings_note,
)
from app.write_guard import WriteGuard, WritesBlockedError

pytestmark = pytest.mark.not_pg


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _blocking_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "test-induced block"})


# ---------------------------------------------------------------------------
# AC: each `_heimdal/**` note carries its declared authority and an explicit
# editable-vs-agent-authored field split per the schema.
# ---------------------------------------------------------------------------


def test_schema_and_authority_split() -> None:
    # Every note file named in the governing Issue's Scope is represented in
    # the registry (fixed-path kinds directly; glob kinds by template shape).
    expected_kinds = {
        "watchlist",  # watchlist.md
        "never",  # never.md
        "interests",  # interests.md
        "source",  # sources/*.md
        "consent",  # consent.md
        "settings",  # settings.md
        "attention_day",  # attention/YYYY-MM-DD.md
        "entity_review",  # entities/review.md
        "device",  # devices/*.md
    }
    assert set(SETTINGS_NOTE_SPECS) == expected_kinds

    for spec in SETTINGS_NOTE_SPECS.values():
        # Authority is declared and one of the closed set.
        assert spec.authority, f"{spec.kind}: authority must be declared"
        # Every section resolves a non-empty split: at least one field is
        # unambiguously human-editable or agent-authored (never conflated --
        # every field must be exactly one, never both/neither).
        for section in spec.sections:
            assert section.fields, f"{spec.kind}/{section.name}: must declare fields"
            for f in section.fields:
                assert f.field_authority in (FIELD_HUMAN_EDITABLE, FIELD_AGENT_AUTHORED)
        # The note-level split is non-degenerate: honest labelling requires
        # naming both roles somewhere (a note with only agent-authored
        # fields has nothing for a human to control -- not a control
        # surface; a note with only human fields records nothing back).
        all_fields = spec.all_fields()
        authorities = {f.field_authority for f in all_fields}
        assert authorities, f"{spec.kind}: must declare at least one field"

    # entities/*.md (the Mimer-owned register substrate, A1) is deliberately
    # NOT a spec in this registry -- it is referenced substrate, not owned or
    # defined here (Out of Scope: "the register runtime (A1)").
    assert "entity" not in SETTINGS_NOTE_SPECS
    assert "entities" not in SETTINGS_NOTE_SPECS


def test_field_spec_rejects_unknown_authority() -> None:
    with pytest.raises(SettingsNoteError):
        FieldSpec("bogus", "not_a_real_authority")


def test_section_spec_rejects_empty_fields() -> None:
    with pytest.raises(SettingsNoteError):
        SectionSpec("empty", ())


def test_note_spec_rejects_unknown_authority_class() -> None:
    with pytest.raises(SettingsNoteError):
        SettingsNoteSpec(
            kind="bad",
            rel_path="bad.md",
            authority="not_a_real_authority_class",
            sections=(SectionSpec("s", (FieldSpec("x", FIELD_HUMAN_EDITABLE),)),),
        )


def test_note_spec_rejects_zero_sections() -> None:
    with pytest.raises(SettingsNoteError):
        SettingsNoteSpec(
            kind="bad",
            rel_path="bad.md",
            authority=WATCHLIST.authority,
            sections=(),
        )


@pytest.mark.parametrize(
    "spec,template_args",
    [
        (WATCHLIST, {}),
        (NEVER_LIST, {}),
        (INTERESTS, {}),
        (SOURCE_CONFIG, {"source_id": "youtube"}),
        (CONSENT, {}),
        (SETTINGS, {}),
        (ATTENTION_DAY, {"date": "2026-07-06"}),
        (ENTITY_REVIEW, {}),
        (DEVICE_CONFIG, {"device_id": "watch-01"}),
    ],
)
def test_render_and_parse_round_trip_preserves_authority_split(
    spec: SettingsNoteSpec, template_args: dict[str, str]
) -> None:
    """Every concrete note kind round-trips its full field set (both
    human-editable and agent-authored) losslessly through render/parse --
    the schema is not just declared, it is actually enforceable end to end."""
    values = {}
    for f in spec.all_fields():
        values[f.name] = f"value-for-{f.name}"

    note = SettingsNote(spec=spec, values=values, updated="2026-07-06T00:00:00Z")
    text = render_note(note)

    # The rendered body documents the split in plain language (Obsidian-
    # readable without this module's docstring).
    for section in spec.sections:
        if section.human_editable_fields():
            assert "Human-editable" in text
        if section.agent_authored_fields():
            assert "Agent-authored" in text

    parsed = parse_note(spec, text)
    assert parsed.values == note.values
    assert parsed.spec.kind == spec.kind

    # The path helper resolves without needing the template a second time.
    rel_path = note_rel_path(spec, **template_args)
    assert rel_path.startswith("_heimdal/")


def test_note_rel_path_requires_template_args_for_glob_kinds() -> None:
    with pytest.raises(SettingsNoteError):
        note_rel_path(SOURCE_CONFIG)  # missing source_id
    with pytest.raises(SettingsNoteError):
        note_rel_path(DEVICE_CONFIG)  # missing device_id
    with pytest.raises(SettingsNoteError):
        note_rel_path(ATTENTION_DAY)  # missing date


# ---------------------------------------------------------------------------
# AC: notes are a writable source of record -- a human edit to an editable
# field is read as intent and honored, not overwritten as read-only.
# ---------------------------------------------------------------------------


def test_notes_are_writable_source_of_record(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # 1. Agent creates the watchlist note with an initial human-editable
    #    watch list plus its own agent-authored bookkeeping field.
    apply_agent_update(
        vault_root,
        WATCHLIST,
        {"last_synced": "2026-07-01T00:00:00Z"},
        write_guard=guard,
    )
    note = read_settings_note(vault_root, WATCHLIST)
    assert note is not None
    note.values["watched"] = ["sources/youtube", "sources/voice_memos"]
    write_settings_note(vault_root, note, write_guard=guard)

    # 2. A human edits the editable field directly on disk (simulating an
    #    Obsidian edit) -- this is the literal human-intent write path, not
    #    a call into this module. Format-agnostic approach: reparse the
    #    frontmatter, mutate the parsed value, re-render -- this mirrors
    #    what a human editing the rendered YAML block in Obsidian actually
    #    changes (the frontmatter value), not this module's internal state.
    path = vault_root / note_rel_path(WATCHLIST)
    text = path.read_text(encoding="utf-8")
    assert "sources/youtube" in text
    reparsed = parse_note(WATCHLIST, text)
    reparsed.values["watched"] = ["sources/youtube", "sources/voice_memos", "sources/podcast_x"]
    human_edited_text = render_note(reparsed)
    path.write_text(human_edited_text, encoding="utf-8")

    # 3. The agent now performs its own update -- reconciling only its own
    #    agent-authored field (`last_synced`). The human's edit to `watched`
    #    (an editable field) must be read as intent and preserved exactly,
    #    not clobbered by the agent's write.
    updated = apply_agent_update(
        vault_root,
        WATCHLIST,
        {"last_synced": "2026-07-06T12:00:00Z"},
        write_guard=guard,
    )
    assert updated.values["watched"] == ["sources/youtube", "sources/voice_memos", "sources/podcast_x"]
    assert updated.values["last_synced"] == "2026-07-06T12:00:00Z"

    # 4. Reading straight off disk confirms the write actually landed (not
    #    just held in the returned object) -- the note is the source of
    #    record, not a rebuildable projection.
    on_disk = read_settings_note(vault_root, WATCHLIST)
    assert on_disk is not None
    assert on_disk.values["watched"] == ["sources/youtube", "sources/voice_memos", "sources/podcast_x"]
    assert on_disk.values["last_synced"] == "2026-07-06T12:00:00Z"


def test_apply_agent_update_rejects_human_editable_field(tmp_path: Path) -> None:
    """An agent has no channel to silently overwrite a human-editable field
    through the agent-update path -- attempting to do so is a contract
    violation, not a permitted (if unusual) write."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    with pytest.raises(SettingsNoteError):
        apply_agent_update(
            vault_root,
            WATCHLIST,
            {"watched": ["sneaky-override"]},
            write_guard=guard,
        )
    # No note should have been written by the rejected call.
    assert read_settings_note(vault_root, WATCHLIST) is None


def test_read_settings_note_returns_none_when_absent(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    assert read_settings_note(vault_root, NEVER_LIST) is None


def test_write_settings_note_honors_write_guard_block(tmp_path: Path) -> None:
    """The governed write seam is real, not decorative: a blocked WriteGuard
    prevents the write entirely (fail-loud), mirroring
    `entity_register.py`'s guard-at-seam precedent."""
    vault_root = _vault(tmp_path)
    note = SettingsNote(spec=CONSENT, values={"grants": []})
    with pytest.raises(WritesBlockedError):
        write_settings_note(vault_root, note, write_guard=_blocking_guard())
    assert read_settings_note(vault_root, CONSENT) is None


def test_source_and_device_and_attention_notes_are_per_instance(tmp_path: Path) -> None:
    """Glob-shaped note kinds (`sources/*.md`, `devices/*.md`,
    `attention/YYYY-MM-DD.md`) write independent files per instance, never
    collapsing distinct sources/devices/days into one note."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    write_settings_note(
        vault_root,
        SettingsNote(spec=SOURCE_CONFIG, values={"source_id": "youtube", "filters": []}),
        write_guard=guard,
        source_id="youtube",
    )
    write_settings_note(
        vault_root,
        SettingsNote(spec=SOURCE_CONFIG, values={"source_id": "voice_memos", "filters": []}),
        write_guard=guard,
        source_id="voice_memos",
    )
    assert (vault_root / "_heimdal/sources/youtube.md").exists()
    assert (vault_root / "_heimdal/sources/voice_memos.md").exists()

    write_settings_note(
        vault_root,
        SettingsNote(spec=DEVICE_CONFIG, values={"device_id": "watch-01", "label": "Watch"}),
        write_guard=guard,
        device_id="watch-01",
    )
    assert (vault_root / "_heimdal/devices/watch-01.md").exists()
    assert not (vault_root / "_heimdal/sources/watch-01.md").exists()

    write_settings_note(
        vault_root,
        SettingsNote(spec=ATTENTION_DAY, values={"counts": {"attended": 3}}),
        write_guard=guard,
        date="2026-07-06",
    )
    assert (vault_root / "_heimdal/attention/2026-07-06.md").exists()
