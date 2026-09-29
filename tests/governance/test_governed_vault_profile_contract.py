from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from app.knowledge._profile_authority_boundary import (
    _DIRECT_OWNER_CORRECTION_CAPABILITY,
    _DIRECT_OWNER_RECONCILIATION_CAPABILITY,
    _OWNER_CONFIRMATION_CAPABILITY,
    _PROFILE_AGENT_WRITE_CAPABILITY,
    _ProfileAgentWriteCapability,
)
from app.knowledge.profile_authority import (
    CandidateRecord,
    CompletedWriteReceiptRecord,
    OwnerConfirmationRecord,
    OwnerCorrectionRecord,
    ProfileAuthorityConflict,
    ProfileAuthorityContractError,
    ProfileIdentityRecord,
    ProposalRecord,
    WriteAttemptRecord,
    WriteFailedRecord,
    WriteReconciliationRecord,
    decode_profile_records,
    encode_profile_records,
    profile_authority_record_json_schema,
    replay_profile_records,
    validate_profile_transition,
)


_VAULT = "vault-01"
_NOTE = "profile-note-01"
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_D = "d" * 64
_DIGEST_E = "e" * 64
_CHANGE_1 = "1" * 64
_CHANGE_2 = "2" * 64
_CHANGE_3 = "3" * 64
_CHANGE_4 = "4" * 64


def _identity() -> ProfileIdentityRecord:
    return ProfileIdentityRecord(
        event_id="event-profile-identity",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        note_path="System/Profile.md",
        initial_content_digest=_DIGEST_A,
    )


def _append(records, record, *, authority=None):
    state = replay_profile_records(records)
    transition = validate_profile_transition(
        state,
        record,
        expected_revision=state.revision,
        authority=authority,
    )
    return transition.next_state.records


def _candidate(records, *, suffix: str, digest: str = _DIGEST_A):
    sequence = len(records)
    return _append(
        records,
        CandidateRecord(
            sequence=sequence,
            event_id=f"event-candidate-{suffix}",
            vault_id=_VAULT,
            profile_note_id=_NOTE,
            candidate_id=f"candidate-{suffix}",
            provenance_ref=f"source-{suffix}",
            candidate_digest=digest,
        ),
    )


def _proposal(
    records,
    *,
    suffix: str,
    candidate_id: str,
    change_digest: str,
    base_digest: str,
    result_digest: str,
    owner_revision: int = 0,
):
    sequence = len(records)
    current = replay_profile_records(records).latest_version
    return _append(
        records,
        ProposalRecord(
            sequence=sequence,
            event_id=f"event-proposal-{suffix}",
            vault_id=_VAULT,
            profile_note_id=_NOTE,
            proposal_id=f"proposal-{suffix}",
            candidate_id=candidate_id,
            proposed_change_digest=change_digest,
            base_content_digest=base_digest,
            base_version_id=None if current is None else current.version_id,
            proposed_result_digest=result_digest,
            owner_revision=owner_revision,
        ),
    )


def _confirm(
    records,
    *,
    suffix: str,
    candidate_id: str,
    change_digest: str,
    base_digest: str,
    result_digest: str,
    owner_revision: int = 0,
):
    sequence = len(records)
    current = replay_profile_records(records).latest_version
    return _append(
        records,
        OwnerConfirmationRecord(
            sequence=sequence,
            event_id=f"event-confirmation-{suffix}",
            vault_id=_VAULT,
            profile_note_id=_NOTE,
            confirmation_id=f"confirmation-{suffix}",
            proposal_id=f"proposal-{suffix}",
            proposed_change_digest=change_digest,
            source_snapshot_digest=base_digest,
            source_version_id=None if current is None else current.version_id,
            proposed_result_digest=result_digest,
            owner_revision=owner_revision,
            confirmation_evidence_ref=f"owner-receipt-{suffix}",
            confirmation_evidence_digest=("d" if suffix == "1" else "e") * 64,
        ),
        authority=_OWNER_CONFIRMATION_CAPABILITY,
    )


def _start_write(
    records,
    *,
    suffix: str,
    candidate_id: str,
    intended_digest: str,
    generation: int,
    previous_version_id: str | None,
    base_digest: str,
    owner_revision: int = 0,
):
    sequence = len(records)
    return _append(
        records,
        WriteAttemptRecord(
            sequence=sequence,
            event_id=f"event-write-attempt-{suffix}",
            vault_id=_VAULT,
            profile_note_id=_NOTE,
            write_id=f"write-{suffix}",
            confirmation_id=f"confirmation-{suffix}",
            proposal_id=f"proposal-{suffix}",
            candidate_id=candidate_id,
            version_id=f"version-{suffix}",
            generation=generation,
            previous_version_id=previous_version_id,
            base_content_digest=base_digest,
            intended_content_digest=intended_digest,
            owner_revision=owner_revision,
        ),
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )


def _complete_write(
    records,
    *,
    suffix: str,
    candidate_id: str,
    content_digest: str,
    generation: int,
    previous_version_id: str | None,
    owner_revision: int = 0,
):
    sequence = len(records)
    return _append(
        records,
        CompletedWriteReceiptRecord(
            sequence=sequence,
            event_id=f"event-receipt-{suffix}",
            vault_id=_VAULT,
            profile_note_id=_NOTE,
            receipt_id=f"receipt-{suffix}",
            write_id=f"write-{suffix}",
            confirmation_id=f"confirmation-{suffix}",
            proposal_id=f"proposal-{suffix}",
            candidate_id=candidate_id,
            version_id=f"version-{suffix}",
            generation=generation,
            previous_version_id=previous_version_id,
            content_digest=content_digest,
            owner_revision=owner_revision,
        ),
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )


def _one_completed_version(records, *, suffix: str = "1", digest: str = _DIGEST_B):
    if not records:
        records = (_identity(),)
    records = _candidate(records, suffix=suffix, digest=_DIGEST_A)
    records = _proposal(
        records,
        suffix=suffix,
        candidate_id=f"candidate-{suffix}",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=digest,
    )
    records = _confirm(
        records,
        suffix=suffix,
        candidate_id=f"candidate-{suffix}",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=digest,
    )
    records = _start_write(
        records,
        suffix=suffix,
        candidate_id=f"candidate-{suffix}",
        intended_digest=digest,
        generation=1,
        previous_version_id=None,
        base_digest=_DIGEST_A,
    )
    records = _complete_write(
        records,
        suffix=suffix,
        candidate_id=f"candidate-{suffix}",
        content_digest=digest,
        generation=1,
        previous_version_id=None,
    )
    return records


def test_only_profile_agent_can_write_approved_profile_content() -> None:
    records = (_identity(),)
    records = _candidate(records, suffix="1")
    records = _proposal(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _confirm(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    confirmation_attempt = OwnerConfirmationRecord(
        sequence=len(records),
        event_id="event-forged-confirmation",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        confirmation_id="confirmation-forged",
        proposal_id="proposal-1",
        proposed_change_digest=_CHANGE_1,
        source_snapshot_digest=_DIGEST_A,
        source_version_id=None,
        proposed_result_digest=_DIGEST_B,
        owner_revision=0,
        confirmation_evidence_ref="invented-owner-receipt",
        confirmation_evidence_digest="d" * 64,
    )
    with pytest.raises(PermissionError, match="authenticated owner confirmation"):
        validate_profile_transition(
            replay_profile_records(records),
            confirmation_attempt,
            expected_revision=len(records) - 1,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )
    attempt = WriteAttemptRecord(
        sequence=len(records),
        event_id="event-write-attempt-1",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-1",
        confirmation_id="confirmation-1",
        proposal_id="proposal-1",
        candidate_id="candidate-1",
        version_id="version-1",
        generation=1,
        previous_version_id=None,
        base_content_digest=_DIGEST_A,
        intended_content_digest=_DIGEST_B,
        owner_revision=0,
    )
    state = replay_profile_records(records)

    with pytest.raises(PermissionError, match="ProfileAgent write capability"):
        validate_profile_transition(
            state, attempt, expected_revision=state.revision, authority=None
        )
    with pytest.raises(PermissionError, match="ProfileAgent write capability"):
        validate_profile_transition(
            state,
            attempt,
            expected_revision=state.revision,
            authority=_OWNER_CONFIRMATION_CAPABILITY,
        )
    with pytest.raises(TypeError, match="not caller-constructible"):
        _ProfileAgentWriteCapability()
    with pytest.raises(PermissionError, match="ProfileAgent write capability"):
        validate_profile_transition(
            state,
            attempt,
            expected_revision=state.revision,
            authority=object.__new__(_ProfileAgentWriteCapability),
        )

    accepted = validate_profile_transition(
        state,
        attempt,
        expected_revision=state.revision,
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )
    assert accepted.next_state.pending_writes == (attempt,)
    with pytest.raises(ProfileAuthorityConflict, match="owner-confirmed result"):
        validate_profile_transition(
            state,
            attempt.model_copy(update={"intended_content_digest": _DIGEST_C}),
            expected_revision=state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )
    assert "actor" not in inspect.signature(validate_profile_transition).parameters
    assert "writer_identity" not in inspect.signature(validate_profile_transition).parameters

    with pytest.raises(ValidationError):
        CompletedWriteReceiptRecord.model_validate(
            {
                "sequence": len(accepted.next_state.records),
                "event_id": "event-receipt-invalid-actor",
                "vault_id": _VAULT,
                "profile_note_id": _NOTE,
                "receipt_id": "receipt-invalid-actor",
                "write_id": "write-1",
                "confirmation_id": "confirmation-1",
                "proposal_id": "proposal-1",
                "candidate_id": "candidate-1",
                "version_id": "version-1",
                "generation": 1,
                "previous_version_id": None,
                "content_digest": _DIGEST_B,
                "owner_revision": 0,
                "writer": "OtherAgent",
            }
        )


def test_profile_version_requires_completed_receipt_binding() -> None:
    first = _one_completed_version((), suffix="1", digest=_DIGEST_B)
    first_state = replay_profile_records(first)
    assert first_state.receipt_bound_version is not None
    assert first_state.receipt_bound_version.version_id == "version-1"

    reused_confirmation = WriteAttemptRecord(
        sequence=first_state.revision + 1,
        event_id="event-reused-confirmation",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-reused-confirmation",
        confirmation_id="confirmation-1",
        proposal_id="proposal-1",
        candidate_id="candidate-1",
        version_id="version-reused-confirmation",
        generation=2,
        previous_version_id="version-1",
        base_content_digest=_DIGEST_B,
        intended_content_digest=_DIGEST_B,
        owner_revision=0,
    )
    with pytest.raises(ProfileAuthorityConflict, match="already has a completed write"):
        validate_profile_transition(
            first_state,
            reused_confirmation,
            expected_revision=first_state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )

    second = _candidate(first, suffix="2", digest=_DIGEST_B)
    second = _proposal(
        second,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_C,
    )
    second = _confirm(
        second,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_C,
    )
    second = _start_write(
        second,
        suffix="2",
        candidate_id="candidate-2",
        intended_digest=_DIGEST_C,
        generation=2,
        previous_version_id="version-1",
        base_digest=_DIGEST_B,
    )
    second = _complete_write(
        second,
        suffix="2",
        candidate_id="candidate-2",
        content_digest=_DIGEST_C,
        generation=2,
        previous_version_id="version-1",
    )

    encoded = encode_profile_records(second)
    decoded = decode_profile_records(encoded)
    replayed = replay_profile_records(decoded)
    assert [version.version_id for version in replayed.versions] == [
        "version-1",
        "version-2",
    ]
    assert replayed.latest_version is not None
    assert replayed.latest_version.previous_version_id == "version-1"
    assert replayed.receipt_bound_version == replayed.latest_version
    schema = profile_authority_record_json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert (
        schema["$defs"]["CompletedWriteReceiptRecord"]["properties"]["writer"]["const"]
        == "ProfileAgent"
    )

    pending = second[:-1]
    pending_state = replay_profile_records(decode_profile_records(encode_profile_records(pending)))
    assert [version.version_id for version in pending_state.versions] == ["version-1"]
    assert pending_state.pending_writes
    assert pending_state.receipt_bound_version is None

    wrong_join = CompletedWriteReceiptRecord.model_validate(
        {
            **second[-1].model_dump(mode="python"),
            "proposal_id": "proposal-other",
        }
    )
    with pytest.raises(ProfileAuthorityConflict, match="exact write"):
        replay_profile_records((*second[:-1], wrong_join))

    duplicate_version = WriteAttemptRecord.model_validate(
        {
            **second[-2].model_dump(mode="python"),
            "event_id": "event-write-duplicate-version",
            "write_id": "write-duplicate-version",
            "version_id": "version-1",
        }
    )
    with pytest.raises(ProfileAuthorityConflict, match="duplicate"):
        replay_profile_records((*second[:-2], duplicate_version))

    with pytest.raises(ValidationError):
        CompletedWriteReceiptRecord.model_validate(
            {
                **second[-1].model_dump(mode="python"),
                "writer": "OtherAgent",
            }
        )


def test_proven_no_effect_failure_allows_retry_with_unspent_confirmation() -> None:
    records = (_identity(),)
    records = _candidate(records, suffix="1")
    records = _proposal(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _confirm(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _start_write(
        records,
        suffix="1",
        candidate_id="candidate-1",
        intended_digest=_DIGEST_B,
        generation=1,
        previous_version_id=None,
        base_digest=_DIGEST_A,
    )
    failure = WriteFailedRecord(
        sequence=len(records),
        event_id="event-write-no-effect-failure",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-1",
        failure_code="write_failed",
        content_effect="none",
    )
    records = _append(
        records,
        failure,
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )

    retry = WriteAttemptRecord(
        sequence=len(records),
        event_id="event-write-retry-after-no-effect",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-retry-1",
        confirmation_id="confirmation-1",
        proposal_id="proposal-1",
        candidate_id="candidate-1",
        version_id="version-retry-1",
        generation=1,
        previous_version_id=None,
        base_content_digest=_DIGEST_A,
        intended_content_digest=_DIGEST_B,
        owner_revision=0,
    )
    retried = _append(
        records,
        retry,
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )
    assert replay_profile_records(retried).pending_writes == (retry,)


def test_unspent_confirmation_cannot_revive_when_content_returns_to_old_digest() -> None:
    records = (_identity(),)
    records = _candidate(records, suffix="1")
    records = _proposal(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _confirm(
        records,
        suffix="1",
        candidate_id="candidate-1",
        change_digest=_CHANGE_1,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )

    # An independent, newer approval moves A -> B -> A while confirmation-1
    # remains unused. Matching bytes alone must not revive its old version base.
    records = _candidate(records, suffix="2")
    records = _proposal(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _confirm(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_A,
        result_digest=_DIGEST_B,
    )
    records = _start_write(
        records,
        suffix="2",
        candidate_id="candidate-2",
        intended_digest=_DIGEST_B,
        generation=1,
        previous_version_id=None,
        base_digest=_DIGEST_A,
    )
    records = _complete_write(
        records,
        suffix="2",
        candidate_id="candidate-2",
        content_digest=_DIGEST_B,
        generation=1,
        previous_version_id=None,
    )
    records = _candidate(records, suffix="3", digest=_DIGEST_B)
    records = _proposal(
        records,
        suffix="3",
        candidate_id="candidate-3",
        change_digest=_CHANGE_3,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_A,
    )
    records = _confirm(
        records,
        suffix="3",
        candidate_id="candidate-3",
        change_digest=_CHANGE_3,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_A,
    )
    records = _start_write(
        records,
        suffix="3",
        candidate_id="candidate-3",
        intended_digest=_DIGEST_A,
        generation=2,
        previous_version_id="version-2",
        base_digest=_DIGEST_B,
    )
    records = _complete_write(
        records,
        suffix="3",
        candidate_id="candidate-3",
        content_digest=_DIGEST_A,
        generation=2,
        previous_version_id="version-2",
    )

    state = replay_profile_records(records)
    stale_attempt = WriteAttemptRecord(
        sequence=state.revision + 1,
        event_id="event-stale-unspent-confirmation",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-stale-unspent-confirmation",
        confirmation_id="confirmation-1",
        proposal_id="proposal-1",
        candidate_id="candidate-1",
        version_id="version-stale-unspent-confirmation",
        generation=3,
        previous_version_id="version-3",
        base_content_digest=_DIGEST_A,
        intended_content_digest=_DIGEST_B,
        owner_revision=0,
    )
    with pytest.raises(ProfileAuthorityConflict, match="owner-confirmed source version"):
        validate_profile_transition(
            state,
            stale_attempt,
            expected_revision=state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )


def test_completed_confirmation_stays_consumed_after_content_returns() -> None:
    first = _one_completed_version((), suffix="1", digest=_DIGEST_B)
    records = _candidate(first, suffix="2", digest=_DIGEST_B)
    records = _proposal(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_A,
    )
    records = _confirm(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_A,
    )
    records = _start_write(
        records,
        suffix="2",
        candidate_id="candidate-2",
        intended_digest=_DIGEST_A,
        generation=2,
        previous_version_id="version-1",
        base_digest=_DIGEST_B,
    )
    records = _complete_write(
        records,
        suffix="2",
        candidate_id="candidate-2",
        content_digest=_DIGEST_A,
        generation=2,
        previous_version_id="version-1",
    )

    state = replay_profile_records(records)
    reused = WriteAttemptRecord(
        sequence=state.revision + 1,
        event_id="event-reused-completed-confirmation",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-reused-completed-confirmation",
        confirmation_id="confirmation-1",
        proposal_id="proposal-1",
        candidate_id="candidate-1",
        version_id="version-reused-completed-confirmation",
        generation=3,
        previous_version_id="version-2",
        base_content_digest=_DIGEST_A,
        intended_content_digest=_DIGEST_B,
        owner_revision=0,
    )
    with pytest.raises(ProfileAuthorityConflict, match="already has a completed write"):
        validate_profile_transition(
            state,
            reused,
            expected_revision=state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )


def test_restart_and_partial_write_preserve_owner_precedence_without_false_approval() -> None:
    records = _one_completed_version((), suffix="1", digest=_DIGEST_B)
    records = _candidate(records, suffix="2", digest=_DIGEST_B)
    records = _proposal(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_C,
    )
    records = _confirm(
        records,
        suffix="2",
        candidate_id="candidate-2",
        change_digest=_CHANGE_2,
        base_digest=_DIGEST_B,
        result_digest=_DIGEST_C,
    )
    records = _start_write(
        records,
        suffix="2",
        candidate_id="candidate-2",
        intended_digest=_DIGEST_C,
        generation=2,
        previous_version_id="version-1",
        base_digest=_DIGEST_B,
    )

    restarted = replay_profile_records(decode_profile_records(encode_profile_records(records)))
    assert restarted.confirmations
    assert [item.write_id for item in restarted.pending_writes] == ["write-2"]
    assert [item.version_id for item in restarted.versions] == ["version-1"]
    assert restarted.receipt_bound_version is None

    correction_while_pending = OwnerCorrectionRecord(
        sequence=restarted.revision + 1,
        event_id="event-owner-correction-while-pending",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        correction_id="correction-while-pending",
        previous_content_digest=_DIGEST_B,
        corrected_content_digest=_DIGEST_D,
        owner_revision=1,
        evidence_ref="owner-correction-pending-evidence",
        evidence_digest="8" * 64,
    )
    pending_correction_state = validate_profile_transition(
        restarted,
        correction_while_pending,
        expected_revision=restarted.revision,
        authority=_DIRECT_OWNER_CORRECTION_CAPABILITY,
    ).next_state
    assert pending_correction_state.current_content_digest == _DIGEST_D
    assert [item.write_id for item in pending_correction_state.pending_writes] == ["write-2"]
    assert pending_correction_state.receipt_bound_version is None
    stale_receipt_after_correction = CompletedWriteReceiptRecord(
        sequence=pending_correction_state.revision + 1,
        event_id="event-stale-completion-after-owner-correction",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        receipt_id="receipt-stale-after-owner-correction",
        write_id="write-2",
        confirmation_id="confirmation-2",
        proposal_id="proposal-2",
        candidate_id="candidate-2",
        version_id="version-2",
        generation=2,
        previous_version_id="version-1",
        content_digest=_DIGEST_C,
        owner_revision=0,
    )
    with pytest.raises(ProfileAuthorityConflict, match="stale"):
        validate_profile_transition(
            pending_correction_state,
            stale_receipt_after_correction,
            expected_revision=pending_correction_state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )

    interrupted = WriteFailedRecord(
        sequence=restarted.revision + 1,
        event_id="event-interrupted-write",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-2",
        failure_code="indeterminate",
        content_effect="indeterminate",
    )
    after_interruption = validate_profile_transition(
        restarted,
        interrupted,
        expected_revision=restarted.revision,
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    ).next_state
    after_interruption_restart = replay_profile_records(
        decode_profile_records(encode_profile_records(after_interruption.records))
    )
    assert after_interruption_restart.unresolved_indeterminate_write_ids == ("write-2",)
    assert [version.version_id for version in after_interruption_restart.versions] == ["version-1"]
    assert after_interruption_restart.receipt_bound_version is None

    correction = OwnerCorrectionRecord(
        sequence=after_interruption_restart.revision + 1,
        event_id="event-owner-correction-1",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        correction_id="correction-1",
        previous_content_digest=_DIGEST_B,
        corrected_content_digest=_DIGEST_C,
        owner_revision=1,
        evidence_ref="owner-correction-evidence-1",
        evidence_digest="f" * 64,
    )
    corrected = validate_profile_transition(
        after_interruption_restart,
        correction,
        expected_revision=after_interruption_restart.revision,
        authority=_DIRECT_OWNER_CORRECTION_CAPABILITY,
    ).next_state
    corrected_after_restart = replay_profile_records(
        decode_profile_records(encode_profile_records(corrected.records))
    )
    assert corrected_after_restart.current_owner_revision == 1
    assert corrected_after_restart.current_content_digest == _DIGEST_C
    assert corrected_after_restart.pending_writes == ()
    assert corrected_after_restart.reconciled_write_ids == ()
    assert corrected_after_restart.unresolved_indeterminate_write_ids == ("write-2",)
    assert corrected_after_restart.receipt_bound_version is None

    blocked_retry = _candidate(corrected_after_restart.records, suffix="4", digest=_DIGEST_C)
    blocked_retry = _proposal(
        blocked_retry,
        suffix="4",
        candidate_id="candidate-4",
        change_digest=_CHANGE_4,
        base_digest=_DIGEST_C,
        result_digest=_DIGEST_D,
        owner_revision=1,
    )
    blocked_retry = _confirm(
        blocked_retry,
        suffix="4",
        candidate_id="candidate-4",
        change_digest=_CHANGE_4,
        base_digest=_DIGEST_C,
        result_digest=_DIGEST_D,
        owner_revision=1,
    )
    blocked_attempt = WriteAttemptRecord(
        sequence=len(blocked_retry),
        event_id="event-write-blocked-by-indeterminate",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        write_id="write-blocked-by-indeterminate",
        confirmation_id="confirmation-4",
        proposal_id="proposal-4",
        candidate_id="candidate-4",
        version_id="version-blocked-by-indeterminate",
        generation=2,
        previous_version_id="version-1",
        base_content_digest=_DIGEST_C,
        intended_content_digest=_DIGEST_D,
        owner_revision=1,
    )
    with pytest.raises(ProfileAuthorityConflict, match="requires reconciliation"):
        validate_profile_transition(
            replay_profile_records(blocked_retry),
            blocked_attempt,
            expected_revision=len(blocked_retry) - 1,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )

    reconciliation = WriteReconciliationRecord(
        sequence=corrected_after_restart.revision + 1,
        event_id="event-write-reconciliation-1",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        reconciliation_id="reconciliation-1",
        write_id="write-2",
        observed_content_digest=_DIGEST_C,
        owner_revision=1,
        evidence_ref="owner-reconciliation-evidence-1",
        evidence_digest="9" * 64,
    )
    with pytest.raises(PermissionError, match="direct-owner write reconciliation"):
        validate_profile_transition(
            corrected_after_restart,
            reconciliation,
            expected_revision=corrected_after_restart.revision,
            authority=_DIRECT_OWNER_CORRECTION_CAPABILITY,
        )
    reconciled = validate_profile_transition(
        corrected_after_restart,
        reconciliation,
        expected_revision=corrected_after_restart.revision,
        authority=_DIRECT_OWNER_RECONCILIATION_CAPABILITY,
    ).next_state
    reconciled_after_restart = replay_profile_records(
        decode_profile_records(encode_profile_records(reconciled.records))
    )
    assert reconciled_after_restart.reconciled_write_ids == ("write-2",)
    assert reconciled_after_restart.unresolved_indeterminate_write_ids == ()
    assert reconciled_after_restart.receipt_bound_version is None

    stale_receipt = CompletedWriteReceiptRecord(
        sequence=reconciled_after_restart.revision + 1,
        event_id="event-stale-completion",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        receipt_id="receipt-stale",
        write_id="write-2",
        confirmation_id="confirmation-2",
        proposal_id="proposal-2",
        candidate_id="candidate-2",
        version_id="version-2",
        generation=2,
        previous_version_id="version-1",
        content_digest=_DIGEST_C,
        owner_revision=0,
    )
    with pytest.raises(ProfileAuthorityConflict, match="terminal outcome"):
        validate_profile_transition(
            reconciled_after_restart,
            stale_receipt,
            expected_revision=reconciled_after_restart.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )

    next_generation = _candidate(reconciled_after_restart.records, suffix="3", digest=_DIGEST_C)
    next_generation = _proposal(
        next_generation,
        suffix="3",
        candidate_id="candidate-3",
        change_digest=_CHANGE_3,
        base_digest=_DIGEST_C,
        result_digest=_DIGEST_D,
        owner_revision=1,
    )
    next_generation = _confirm(
        next_generation,
        suffix="3",
        candidate_id="candidate-3",
        change_digest=_CHANGE_3,
        base_digest=_DIGEST_C,
        result_digest=_DIGEST_D,
        owner_revision=1,
    )
    next_generation = _start_write(
        next_generation,
        suffix="3",
        candidate_id="candidate-3",
        intended_digest=_DIGEST_D,
        generation=2,
        previous_version_id="version-1",
        base_digest=_DIGEST_C,
        owner_revision=1,
    )
    next_generation = _complete_write(
        next_generation,
        suffix="3",
        candidate_id="candidate-3",
        content_digest=_DIGEST_D,
        generation=2,
        previous_version_id="version-1",
        owner_revision=1,
    )
    recovered = replay_profile_records(next_generation)
    assert recovered.latest_version is not None
    assert recovered.latest_version.version_id == "version-3"
    assert recovered.receipt_bound_version == recovered.latest_version

    with pytest.raises(ProfileAuthorityContractError, match="incomplete"):
        decode_profile_records(encode_profile_records(after_interruption.records)[:-1])


def test_profile_authority_replay_fails_closed_on_unknown_or_branched_records() -> None:
    records = _one_completed_version((), suffix="1", digest=_DIGEST_B)
    duplicate = records[1].model_copy(update={"sequence": len(records) + 1})
    with pytest.raises(ProfileAuthorityConflict, match="contiguous"):
        replay_profile_records((*records, duplicate))

    unknown = encode_profile_records(records).replace(
        b'"schema_version":1', b'"schema_version":2', 1
    )
    with pytest.raises(ProfileAuthorityContractError, match="malformed"):
        decode_profile_records(unknown)

    branch_state = replay_profile_records(records)
    stale = CandidateRecord(
        sequence=branch_state.revision + 1,
        event_id="event-candidate-stale-branch",
        vault_id=_VAULT,
        profile_note_id=_NOTE,
        candidate_id="candidate-stale-branch",
        provenance_ref="source-stale-branch",
        candidate_digest=_DIGEST_B,
    )
    with pytest.raises(ProfileAuthorityConflict, match="revision changed"):
        validate_profile_transition(
            branch_state,
            stale,
            expected_revision=branch_state.revision - 1,
        )
