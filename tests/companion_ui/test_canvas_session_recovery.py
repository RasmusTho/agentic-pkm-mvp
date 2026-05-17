"""Tests for Canvas Core paused-session recovery payload (#1030).

These tests verify that interrupted/paused Canvas sessions produce a recovery
payload with the minimum data needed for safe re-entry, block new edits until
recovery is complete, detect external body changes, and preserve existing
provenance rather than creating a second canonical log.

ACs from #1030:
- test_interrupted_session_recovery_payload_contains_identity
- test_recovery_payload_contains_body_version_marker
- test_interrupted_session_blocks_new_edits_until_recovered
- test_reentry_state_visible_for_interrupted_session
- test_changed_artifact_requires_recovery_review
- test_recovery_uses_existing_session_log_provenance
"""

from pathlib import Path

import pytest

from companion_ui.canvas_core.session_recovery import (
    CanvasSessionRecovery,
    RecoveryPayload,
    RecoveryStatus,
)

SESSION_ID = "session-recovery-001"
ARTIFACT_ID = "note-recovery-test"
BODY_TEXT = "# Test Note\n\nOriginal body content."


# ---------------------------------------------------------------------------
# AC: interrupted session stores recovery payload with session id, artifact id, log path
# ---------------------------------------------------------------------------


def test_interrupted_session_recovery_payload_contains_identity() -> None:
    recovery = CanvasSessionRecovery()
    log_path = Path(".chats/test-note/2026-05-17T10-00-session.md")

    payload = recovery.capture(
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        body=BODY_TEXT,
        session_log_path=log_path,
    )

    assert isinstance(payload, RecoveryPayload)
    assert payload.session_id == SESSION_ID
    assert payload.artifact_id == ARTIFACT_ID
    assert payload.session_log_path == log_path


def test_recovery_payload_accessible_via_property() -> None:
    recovery = CanvasSessionRecovery()
    payload = recovery.capture(
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        body=BODY_TEXT,
    )
    assert recovery.payload is payload


# ---------------------------------------------------------------------------
# AC: recovery payload includes last known body version hash or conflict marker
# ---------------------------------------------------------------------------


def test_recovery_payload_contains_body_version_marker() -> None:
    recovery = CanvasSessionRecovery()
    payload = recovery.capture(
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        body=BODY_TEXT,
    )

    assert payload.body_version_hash, "body_version_hash must be non-empty"
    assert isinstance(payload.body_version_hash, str)


def test_body_version_hash_differs_for_different_bodies() -> None:
    recovery1 = CanvasSessionRecovery()
    recovery2 = CanvasSessionRecovery()

    payload1 = recovery1.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body="body A")
    payload2 = recovery2.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body="body B")

    assert payload1.body_version_hash != payload2.body_version_hash


def test_body_version_hash_stable_for_same_body() -> None:
    recovery1 = CanvasSessionRecovery()
    recovery2 = CanvasSessionRecovery()

    payload1 = recovery1.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)
    payload2 = recovery2.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)

    assert payload1.body_version_hash == payload2.body_version_hash


# ---------------------------------------------------------------------------
# AC: paused/interrupted session blocks new assistant body edits until recovery
# ---------------------------------------------------------------------------


def test_interrupted_session_blocks_new_edits_until_recovered() -> None:
    recovery = CanvasSessionRecovery()
    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)

    assert recovery.blocks_new_edits is True, (
        "New edits must be blocked until recovery is complete"
    )

    recovery.mark_recovered()
    assert recovery.blocks_new_edits is False, (
        "New edits must be allowed after recovery is marked complete"
    )


def test_no_payload_means_no_block() -> None:
    recovery = CanvasSessionRecovery()
    assert recovery.blocks_new_edits is False


# ---------------------------------------------------------------------------
# AC: UI/runtime exposes a re-entry state for interrupted session
# ---------------------------------------------------------------------------


def test_reentry_state_visible_for_interrupted_session() -> None:
    recovery = CanvasSessionRecovery()
    assert recovery.reentry_state == "not_captured"

    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)
    assert recovery.reentry_state == "needs_review"

    recovery.mark_recovered()
    assert recovery.reentry_state == "recovered"


def test_reentry_state_conflict_detected() -> None:
    recovery = CanvasSessionRecovery()
    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)

    recovery.check_for_conflict("# Externally Modified\n\nDifferent content.")
    assert recovery.reentry_state == "conflict_detected"
    assert recovery.blocks_new_edits is True


# ---------------------------------------------------------------------------
# AC: recovery detects changed artifact body and surfaces conflict rather than
#     silently applying stale edits
# ---------------------------------------------------------------------------


def test_changed_artifact_requires_recovery_review() -> None:
    recovery = CanvasSessionRecovery()
    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)

    status = recovery.check_for_conflict("# Externally changed body")

    assert status == RecoveryStatus.CONFLICT_DETECTED
    assert recovery.recovery_status == RecoveryStatus.CONFLICT_DETECTED


def test_unchanged_artifact_stays_needs_review() -> None:
    recovery = CanvasSessionRecovery()
    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)

    status = recovery.check_for_conflict(BODY_TEXT)

    assert status == RecoveryStatus.NEEDS_REVIEW


def test_conflict_detected_still_blocks_edits() -> None:
    recovery = CanvasSessionRecovery()
    recovery.capture(session_id=SESSION_ID, artifact_id=ARTIFACT_ID, body=BODY_TEXT)
    recovery.check_for_conflict("changed body")

    assert recovery.blocks_new_edits is True


def test_mark_recovered_without_capture_raises() -> None:
    recovery = CanvasSessionRecovery()
    with pytest.raises(RuntimeError, match="capture"):
        recovery.mark_recovered()


def test_check_for_conflict_without_capture_raises() -> None:
    recovery = CanvasSessionRecovery()
    with pytest.raises(RuntimeError, match="capture"):
        recovery.check_for_conflict("body")


# ---------------------------------------------------------------------------
# AC: recovery preserves append-during-session provenance and does not create
#     a second canonical transcript
# ---------------------------------------------------------------------------


def test_recovery_uses_existing_session_log_provenance() -> None:
    """Recovery must use the session log path already opened by the provenance writer.

    It must not open a second log.  The session_log_path in the payload is the
    same path as the one the provenance writer opened at session start.
    """
    existing_log_path = Path(".chats/test-note/2026-05-17T10-00-session.md")

    recovery = CanvasSessionRecovery()
    payload = recovery.capture(
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        body=BODY_TEXT,
        session_log_path=existing_log_path,
    )

    assert payload.session_log_path == existing_log_path, (
        "Recovery payload must carry the existing provenance log path, not open a new one"
    )


def test_recovery_payload_carries_pending_edit_count() -> None:
    recovery = CanvasSessionRecovery()
    payload = recovery.capture(
        session_id=SESSION_ID,
        artifact_id=ARTIFACT_ID,
        body=BODY_TEXT,
        applied_edit_count=3,
    )

    assert payload.pending_edit_count == 3
