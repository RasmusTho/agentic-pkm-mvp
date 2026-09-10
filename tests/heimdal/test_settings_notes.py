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

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.heimdal.settings_notes as settings_notes_module
from app.heimdal.interest_steering import InterestDerivedUpdate, apply_interest_derived_updates
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
    STEERING_LOG,
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
from app.knowledge.errors import KnowledgeWriteConflict
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


def _force_losing_create(
    monkeypatch: pytest.MonkeyPatch,
    vault_root: Path,
    winner: SettingsNote,
) -> None:
    """Make the next settings-note write lose an actual create-once race."""
    original_write = settings_notes_module.write_note_relative
    injected = False

    def create_winner_then_retry(note_rel_path_value: str, content: str, **kwargs: object):
        nonlocal injected
        if not injected:
            injected = True
            winner_receipt = original_write(
                note_rel_path_value,
                render_note(winner),
                vault_root=vault_root,
                action=kwargs["action"],
                write_guard=kwargs["write_guard"],
                expected_version=None,
                writer_identity="concurrent-writer",
                create_once=True,
            )
            assert winner_receipt.outcome == "written"
        return original_write(note_rel_path_value, content, **kwargs)

    monkeypatch.setattr(settings_notes_module, "write_note_relative", create_winner_then_retry)


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
        "steering_log",  # steering.log.md
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
        (STEERING_LOG, {}),
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


def test_apply_agent_update_refuses_concurrent_human_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The agent merge must preserve bytes changed after its read snapshot."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()
    apply_agent_update(vault_root, WATCHLIST, {"last_synced": "before"}, write_guard=guard)
    note_path = vault_root / note_rel_path(WATCHLIST)
    original_write = settings_notes_module.write_note_relative

    def write_after_human_edit(note_rel_path_value: str, content: str, **kwargs: object):
        assert kwargs["expected_version"] is not None
        note_path.write_bytes(b"human edit wins\n")
        return original_write(note_rel_path_value, content, **kwargs)

    monkeypatch.setattr(settings_notes_module, "write_note_relative", write_after_human_edit)

    with pytest.raises(KnowledgeWriteConflict, match="conflict"):
        apply_agent_update(vault_root, WATCHLIST, {"last_synced": "after"}, write_guard=guard)

    assert note_path.read_bytes() == b"human edit wins\n"


def test_write_settings_note_returns_concurrent_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A losing create reports the durable winner, never an unapplied note."""
    vault_root = _vault(tmp_path)
    note = SettingsNote(spec=WATCHLIST, values={"last_synced": "requested"})
    winner = SettingsNote(spec=WATCHLIST, values={"last_synced": "winner"})
    original_write = settings_notes_module.write_note_relative
    injected = False

    def create_winner_then_retry(note_rel_path_value: str, content: str, **kwargs: object):
        nonlocal injected
        if not injected:
            injected = True
            original_write(
                note_rel_path_value,
                render_note(winner),
                vault_root=vault_root,
                action=kwargs["action"],
                write_guard=kwargs["write_guard"],
                expected_version=None,
                writer_identity="concurrent-writer",
                create_once=True,
            )
        return original_write(note_rel_path_value, content, **kwargs)

    monkeypatch.setattr(settings_notes_module, "write_note_relative", create_winner_then_retry)

    persisted = write_settings_note(vault_root, note, write_guard=_allowing_guard())

    assert persisted.values == winner.values
    on_disk = read_settings_note(vault_root, WATCHLIST)
    assert on_disk is not None
    assert on_disk.values == winner.values


def test_non_idempotent_create_reports_losing_creator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    requested = SettingsNote(spec=WATCHLIST, values={"last_synced": "requested"})
    winner = SettingsNote(spec=WATCHLIST, values={"last_synced": "winner"})
    _force_losing_create(monkeypatch, vault_root, winner)

    with pytest.raises(KnowledgeWriteConflict, match="create-once") as exc_info:
        write_settings_note(
            vault_root,
            requested,
            write_guard=_allowing_guard(),
            create_once_loss="raise",
        )

    assert exc_info.value.receipt is not None
    assert exc_info.value.receipt.outcome == "already_exists"
    persisted = read_settings_note(vault_root, WATCHLIST)
    assert persisted is not None
    assert persisted.values == winner.values


def test_non_idempotent_settings_callers_preserve_requested_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every bounded non-idempotent settings caller fails after a lost create."""
    from app.heimdal import consent_ledger, retention as retention_module
    from app.heimdal.attention_log import AttentionEvent, record_attention_events
    from app.heimdal.interest_steering import set_interest_weight, update_source_filters
    from app.heimdal.retention import enforce_hard_retention_bound

    guard = _allowing_guard()

    interest_root = _vault(tmp_path / "interest")
    interest_winner = SettingsNote(spec=INTERESTS, values={"weights": {"winner": 0.1}})
    with monkeypatch.context() as case:
        _force_losing_create(case, interest_root, interest_winner)
        with pytest.raises(KnowledgeWriteConflict, match="create-once"):
            set_interest_weight(interest_root, "requested", 0.9, write_guard=guard)
    persisted_interest = read_settings_note(interest_root, INTERESTS)
    assert persisted_interest is not None
    assert persisted_interest.values == interest_winner.values

    source_root = _vault(tmp_path / "source")
    source_winner = SettingsNote(
        spec=SOURCE_CONFIG,
        values={"source_id": "requested", "filters": ["winner"]},
    )
    with monkeypatch.context() as case:
        _force_losing_create(case, source_root, source_winner)
        with pytest.raises(KnowledgeWriteConflict, match="create-once"):
            update_source_filters(source_root, "requested", ["requested"], write_guard=guard)
    persisted_source = read_settings_note(source_root, SOURCE_CONFIG, source_id="requested")
    assert persisted_source is not None
    assert persisted_source.values == source_winner.values

    attention_root = _vault(tmp_path / "attention")
    attention_winner = SettingsNote(
        spec=ATTENTION_DAY,
        values={"counts": {"attended:other": 1}, "reasons": ["other"], "overrides": []},
    )
    with monkeypatch.context() as case:
        _force_losing_create(case, attention_root, attention_winner)
        with pytest.raises(KnowledgeWriteConflict, match="create-once"):
            record_attention_events(
                attention_root,
                "2026-07-06",
                [AttentionEvent("requested", "skipped", "requested")],
                write_guard=guard,
            )
    persisted_attention = read_settings_note(attention_root, ATTENTION_DAY, date="2026-07-06")
    assert persisted_attention is not None
    assert persisted_attention.values == attention_winner.values

    retention_root = _vault(tmp_path / "retention")
    retention_winner = SettingsNote(
        spec=SETTINGS,
        values={"retention_window_days": 30, "last_enforced_at": "winner"},
    )
    with monkeypatch.context() as case:
        _force_losing_create(case, retention_root, retention_winner)
        case.setattr(retention_module, "_resolve_retention_window_days", lambda *_args, **_kwargs: 30)
        case.setattr(retention_module.raw_store, "expired_raw_record_metadata", lambda **_kwargs: ())
        case.setattr(retention_module, "_reconcile_pending_cold_cleanup", lambda **_kwargs: None)
        case.setattr(consent_ledger, "reconcile_revoked_consent_erasure", lambda: None)
        with pytest.raises(KnowledgeWriteConflict, match="create-once"):
            enforce_hard_retention_bound(
                vault_root=retention_root,
                now=datetime(2026, 7, 6, tzinfo=timezone.utc),
            )
    persisted_retention = read_settings_note(retention_root, SETTINGS)
    assert persisted_retention is not None
    assert persisted_retention.values == retention_winner.values


def test_idempotent_create_once_returns_durable_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = _vault(tmp_path)
    winner = SettingsNote(spec=INTERESTS, values={"confidence": {"winner": 0.2}})
    _force_losing_create(monkeypatch, vault_root, winner)

    persisted = apply_interest_derived_updates(
        vault_root,
        [InterestDerivedUpdate(interest="requested", confidence=0.9)],
        write_guard=_allowing_guard(),
    )

    assert persisted.values == winner.values
    on_disk = read_settings_note(vault_root, INTERESTS)
    assert on_disk is not None
    assert on_disk.values == winner.values


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
