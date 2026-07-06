"""Heimdal capture-note + receipt (J0) tests (#3035, Epic #3019 slice A15).

Covers the governing Issue's three behavioral Acceptance Criteria plus
success/negative/completeness coverage:

- ``test_status_frontmatter_walks_pipeline`` -- a captured memo produces a
  dated vault note whose ``status:`` walks ``captured`` -> ``processing``
  -> ``in-vault`` as it progresses through the pipeline, updated in place.
- ``test_note_carries_transcript_and_attribution`` -- the note carries the
  A8 on-device transcript and the A9 self-record attribution + entity
  mentions, so it is self-describing without a UI.
- ``test_receipt_is_lens_over_status`` -- the receipt UI's projection
  reflects ``status:`` exactly and adds no capability absent from the note
  itself (removing the "UI" loses nothing).

All tests exercise the real production write call site
(``app.heimdal.capture_note.record_capture`` / ``record_processing`` /
``record_in_vault`` -> ``write_capture_note`` ->
``app.knowledge.write_ops.write_note_relative`` ->
``app.write_guard.DEFAULT_WRITE_GUARD.assert_writes_allowed``) over a
temp-vault fixture -- never a stubbed write path -- mirroring
``tests/heimdal/test_settings_notes.py``'s temp-vault-fixture convention:
no network, no real Postgres, no real vault.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.heimdal.asr_stage import TranscriptResult, TranscriptSegment
from app.heimdal.attribution_stage import (
    Attribution,
    AttributionResult,
    BASIS_CAPTURE_CONTEXT,
    EntityMention,
    RESOLUTION_RESOLVED,
    ROLE_SPEAKER,
)
from app.heimdal.capture_note import (
    ARTIFACT_CLASS,
    CAPTURE_NOTE_WRITE_ACTION,
    STATUS_CAPTURED,
    STATUS_IN_VAULT,
    STATUS_ORDER,
    STATUS_PROCESSING,
    CaptureNoteStatusError,
    build_capture_receipt,
    capture_note_rel_path,
    read_capture_note,
    record_capture,
    record_in_vault,
    record_processing,
    write_capture_note,
    CaptureNote,
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


_MEMO_ID = "memo-abc123"
_CAPTURED_DATE = "2026-07-06"


def _sample_transcript() -> TranscriptResult:
    return TranscriptResult(
        id="transcript-1",
        raw_ref="heimraw:test-ref",
        revision_of=None,
        language="en",
        text="Call Anna about the Northvolt invoice tomorrow.",
        segments=[
            TranscriptSegment(
                start=0.0,
                end=3.2,
                text="Call Anna about the Northvolt invoice tomorrow.",
                confidence=0.91,
                calibration="heuristic",
                method="asr_avg_logprob",
            )
        ],
        stage_versions={"asr": "base@heimdal-asr-stage-v1"},
        multi_speaker_detected=False,
    )


def _sample_attribution() -> AttributionResult:
    return AttributionResult(
        attributions=(
            Attribution(
                mention_id="mention:speaker-1",
                role=ROLE_SPEAKER,
                resolution=RESOLUTION_RESOLVED,
                basis=BASIS_CAPTURE_CONTEXT,
                confidence=1.0,
            ),
        ),
        entity_mentions=(
            EntityMention(
                mention_id="mention:anna-1",
                surface_form="Anna",
                resolution=RESOLUTION_RESOLVED,
                kind_hint="person",
                confidence=0.87,
            ),
            EntityMention(
                mention_id="mention:northvolt-1",
                surface_form="Northvolt",
                resolution="ambiguous",
                kind_hint="organization",
                confidence=0.62,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# AC1: a captured memo produces a dated vault note whose `status:` walks
# captured -> processing -> in-vault, updated in place.
# ---------------------------------------------------------------------------


def test_status_frontmatter_walks_pipeline(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    # Step 1: capture -> status: captured.
    captured = record_capture(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        sensor={"adapter": "voice_memo_folder_watch", "version": "v1", "device": "iphone-test"},
        write_guard=guard,
    )
    assert captured.status == STATUS_CAPTURED

    rel_path = capture_note_rel_path(_MEMO_ID, _CAPTURED_DATE)
    note_path = vault_root / rel_path
    assert note_path.exists(), "the dated vault note must exist after capture, before any UI render"
    first_text = note_path.read_text(encoding="utf-8")
    assert f"status: {STATUS_CAPTURED}" in first_text
    assert ARTIFACT_CLASS in first_text

    # Step 2: ASR/attribution begins -> status: processing (same path, in place).
    processing = record_processing(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        transcript=_sample_transcript(),
        write_guard=guard,
    )
    assert processing.status == STATUS_PROCESSING
    assert (vault_root / rel_path) == note_path
    second_text = note_path.read_text(encoding="utf-8")
    assert f"status: {STATUS_PROCESSING}" in second_text
    assert f"status: {STATUS_CAPTURED}" not in second_text  # in-place update, not appended

    # Step 3: published/projected -> status: in-vault (terminal).
    in_vault = record_in_vault(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        attribution=_sample_attribution(),
        write_guard=guard,
    )
    assert in_vault.status == STATUS_IN_VAULT
    third_text = note_path.read_text(encoding="utf-8")
    assert f"status: {STATUS_IN_VAULT}" in third_text

    # The full walk landed on exactly one file, in the fixed order.
    on_disk = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert on_disk is not None
    assert on_disk.status == STATUS_IN_VAULT
    assert STATUS_ORDER == (STATUS_CAPTURED, STATUS_PROCESSING, STATUS_IN_VAULT)


def test_status_is_monotonic_refuses_backward_write(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)
    record_processing(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        transcript=_sample_transcript(),
        write_guard=guard,
    )

    # Attempting to move status backward (processing -> captured) must
    # refuse loudly, never silently corrupt the durable walk.
    backward = CaptureNote(
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        status=STATUS_CAPTURED,
        updated="2026-07-06T00:00:00Z",
    )
    with pytest.raises(CaptureNoteStatusError):
        write_capture_note(vault_root, backward, write_guard=guard)

    # The on-disk note must be unaffected by the refused write.
    still_processing = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert still_processing is not None
    assert still_processing.status == STATUS_PROCESSING


def test_capture_note_write_goes_through_write_guard(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    blocking = _blocking_guard()

    with pytest.raises(WritesBlockedError):
        record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=blocking)

    # No note was written -- the guard refused before the filesystem write.
    assert read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE) is None


# ---------------------------------------------------------------------------
# AC2: the note carries the on-device transcript and self-record
# attribution + entity mentions, self-describing without a UI.
# ---------------------------------------------------------------------------


def test_note_carries_transcript_and_attribution(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)
    record_processing(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        transcript=_sample_transcript(),
        write_guard=guard,
    )
    record_in_vault(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        attribution=_sample_attribution(),
        write_guard=guard,
    )

    note = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert note is not None

    # Transcript (A8) is present in parsed frontmatter and in the raw body text.
    assert note.transcript_segments
    assert note.transcript_segments[0]["text"] == "Call Anna about the Northvolt invoice tomorrow."

    rel_path = capture_note_rel_path(_MEMO_ID, _CAPTURED_DATE)
    raw_text = (vault_root / rel_path).read_text(encoding="utf-8")
    assert "Call Anna about the Northvolt invoice tomorrow." in raw_text

    # Self-record attribution (A9): exactly the operator as speaker, resolved.
    assert len(note.attributions) == 1
    assert note.attributions[0]["role"] == ROLE_SPEAKER
    assert note.attributions[0]["resolution"] == RESOLUTION_RESOLVED
    assert note.attributions[0]["basis"] == BASIS_CAPTURE_CONTEXT

    # Entity mentions (A9): surface forms + three-state resolution, never
    # collapsed into a free-text canonical name.
    surface_forms = {m["surface_form"] for m in note.entity_mentions}
    assert surface_forms == {"Anna", "Northvolt"}
    resolutions = {m["surface_form"]: m["resolution"] for m in note.entity_mentions}
    assert resolutions["Anna"] == RESOLUTION_RESOLVED
    assert resolutions["Northvolt"] == "ambiguous"

    # Self-describing without a UI: raw markdown alone shows attribution.
    assert "Anna" in raw_text
    assert "Northvolt" in raw_text


def test_note_readable_before_processing_or_attribution_exist(tmp_path: Path) -> None:
    """UUID/UI is not a render gate: the note must exist and be readable
    right after capture, before ASR/attribution have run at all."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)

    note = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert note is not None
    assert note.status == STATUS_CAPTURED
    assert note.transcript_text is None
    assert note.attributions == ()
    assert note.entity_mentions == ()


# ---------------------------------------------------------------------------
# AC3: the receipt UI reflects `status:` and adds no capability absent
# from the note.
# ---------------------------------------------------------------------------


def test_receipt_is_lens_over_status(tmp_path: Path) -> None:
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)
    note_after_capture = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert note_after_capture is not None
    receipt_after_capture = build_capture_receipt(note_after_capture)

    assert receipt_after_capture.memo_id == note_after_capture.memo_id
    assert receipt_after_capture.status == note_after_capture.status == STATUS_CAPTURED
    assert receipt_after_capture.has_transcript is False
    assert receipt_after_capture.has_attribution is False

    record_processing(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        transcript=_sample_transcript(),
        write_guard=guard,
    )
    record_in_vault(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        attribution=_sample_attribution(),
        write_guard=guard,
    )
    note_final = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert note_final is not None
    receipt_final = build_capture_receipt(note_final)

    # The receipt tracks the note's own status exactly -- no independent state.
    assert receipt_final.status == note_final.status == STATUS_IN_VAULT
    assert receipt_final.has_transcript is True
    assert receipt_final.has_attribution is True


def test_receipt_adds_no_capability_absent_from_note(tmp_path: Path) -> None:
    """Removing the "receipt UI" must leave the note fully functional: the
    receipt is built purely from fields the note itself already exposes,
    never from a side channel, a write, or additional resolved state."""
    vault_root = _vault(tmp_path)
    guard = _allowing_guard()

    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)
    record_processing(
        vault_root,
        memo_id=_MEMO_ID,
        captured_date=_CAPTURED_DATE,
        transcript=_sample_transcript(),
        write_guard=guard,
    )
    note = read_capture_note(vault_root, _MEMO_ID, _CAPTURED_DATE)
    assert note is not None

    rel_path = capture_note_rel_path(_MEMO_ID, _CAPTURED_DATE)
    note_path = vault_root / rel_path
    mtime_before = note_path.stat().st_mtime_ns
    file_count_before = sum(1 for _ in vault_root.rglob("*") if _.is_file())

    receipt = build_capture_receipt(note)

    # Building the receipt performed no write of any kind: no new file, no
    # mutation of the existing note. It is a pure projection.
    assert note_path.stat().st_mtime_ns == mtime_before
    file_count_after = sum(1 for _ in vault_root.rglob("*") if _.is_file())
    assert file_count_after == file_count_before

    # Every field on the receipt is derivable directly from the note that
    # was already read off disk -- nothing the receipt exposes is missing
    # from `note` itself.
    assert receipt.status == note.status
    assert receipt.has_transcript == bool(note.transcript_text)
    assert receipt.has_attribution == bool(note.attributions or note.entity_mentions)
    assert receipt.updated == note.updated


def test_write_action_uses_capture_note_action_string(tmp_path: Path) -> None:
    """The write goes through the named `CAPTURE_NOTE_WRITE_ACTION`, so a
    health-blocked runtime's write guard sees a distinguishable action
    (mirrors the assertion style of test_settings_notes.py)."""
    seen_actions: list[str] = []

    class _RecordingGuard(WriteGuard):
        def assert_writes_allowed(self, action: str) -> None:  # type: ignore[override]
            seen_actions.append(action)
            super().assert_writes_allowed(action)

    guard = _RecordingGuard(lambda: {"state": "healthy"})
    vault_root = _vault(tmp_path)
    record_capture(vault_root, memo_id=_MEMO_ID, captured_date=_CAPTURED_DATE, write_guard=guard)

    assert CAPTURE_NOTE_WRITE_ACTION in seen_actions
