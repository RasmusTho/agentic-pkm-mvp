"""Executable, dormant schema and replay contract for governed vault profiles.

This module defines dormant durable record shapes and validates their ordered
joins. It does not access a vault, admit candidates, confirm a proposal, write
Profile Note content, or commit records to storage. Direct-owner corrections and
reconciliation of uncertain ProfileAgent writes are separate records. A future
adapter must compare ``ValidatedTransition.expected_revision`` atomically with
the current record revision, persist the encoded next state before acknowledging
it, and use the existing expected-version Knowledge write path for Profile Note
updates.

Replay validates structure only. The canonical store and confirmation/write
adapters remain responsible for proving that evidence references are authentic;
deserialization never grants authority or recreates a capability.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Iterable, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

from app.knowledge._profile_authority_boundary import (
    _require_direct_owner_correction_capability,
    _require_direct_owner_reconciliation_capability,
    _require_owner_confirmation_capability,
    _require_profile_agent_write_capability,
)


PROFILE_AUTHORITY_SCHEMA: Literal["mimer.governed-vault-profile-authority.v1"] = (
    "mimer.governed-vault-profile-authority.v1"
)
PROFILE_NOTE_KEY: Literal["owner-profile"] = "owner-profile"
PROFILE_AGENT_ID: Literal["ProfileAgent"] = "ProfileAgent"

Identifier: TypeAlias = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
Sha256Digest: TypeAlias = Annotated[
    str,
    StringConstraints(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
]


class ProfileAuthorityContractError(ValueError):
    """A profile authority record is malformed or violates the lifecycle contract."""


class ProfileAuthorityConflict(ProfileAuthorityContractError):
    """A transition is stale, branched, duplicated, or out of sequence."""


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    contract_schema: Literal["mimer.governed-vault-profile-authority.v1"] = PROFILE_AUTHORITY_SCHEMA
    schema_version: Literal[1] = 1
    kind: str
    sequence: int = Field(ge=0)
    event_id: Identifier
    vault_id: Identifier
    profile_note_id: Identifier


class ProfileIdentityRecord(_Record):
    kind: Literal["profile_identity"] = "profile_identity"
    sequence: Literal[0] = 0
    profile_key: Literal["owner-profile"] = PROFILE_NOTE_KEY
    note_path: str
    initial_content_digest: Sha256Digest

    @field_validator("note_path")
    @classmethod
    def _validate_note_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or "\\" in value
            or path.suffix.lower() != ".md"
        ):
            raise ValueError("Profile Note path must be a vault-relative Markdown path")
        return value


class CandidateRecord(_Record):
    kind: Literal["candidate"] = "candidate"
    sequence: int = Field(ge=1)
    candidate_id: Identifier
    provenance_ref: Identifier
    candidate_digest: Sha256Digest


class ProposalRecord(_Record):
    kind: Literal["proposal"] = "proposal"
    sequence: int = Field(ge=1)
    proposal_id: Identifier
    candidate_id: Identifier
    proposed_change_digest: Sha256Digest
    base_content_digest: Sha256Digest
    base_version_id: Identifier | None
    proposed_result_digest: Sha256Digest
    owner_revision: int = Field(ge=0)


class OwnerConfirmationRecord(_Record):
    kind: Literal["owner_confirmation"] = "owner_confirmation"
    sequence: int = Field(ge=1)
    confirmation_id: Identifier
    proposal_id: Identifier
    proposed_change_digest: Sha256Digest
    source_snapshot_digest: Sha256Digest
    source_version_id: Identifier | None
    proposed_result_digest: Sha256Digest
    owner_revision: int = Field(ge=0)
    confirmation_evidence_ref: Identifier
    confirmation_evidence_digest: Sha256Digest


class WriteAttemptRecord(_Record):
    kind: Literal["write_attempt"] = "write_attempt"
    sequence: int = Field(ge=1)
    write_id: Identifier
    confirmation_id: Identifier
    proposal_id: Identifier
    candidate_id: Identifier
    version_id: Identifier
    generation: int = Field(ge=1)
    previous_version_id: Identifier | None
    base_content_digest: Sha256Digest
    intended_content_digest: Sha256Digest
    owner_revision: int = Field(ge=0)


class WriteFailedRecord(_Record):
    kind: Literal["write_failed"] = "write_failed"
    sequence: int = Field(ge=1)
    write_id: Identifier
    failure_code: Literal[
        "write_rejected",
        "write_failed",
        "stale_owner_revision",
        "receipt_unavailable",
        "indeterminate",
    ]
    content_effect: Literal["none", "indeterminate"]


class CompletedWriteReceiptRecord(_Record):
    kind: Literal["completed_write_receipt"] = "completed_write_receipt"
    sequence: int = Field(ge=1)
    receipt_id: Identifier
    write_id: Identifier
    confirmation_id: Identifier
    proposal_id: Identifier
    candidate_id: Identifier
    version_id: Identifier
    generation: int = Field(ge=1)
    previous_version_id: Identifier | None
    content_digest: Sha256Digest
    owner_revision: int = Field(ge=0)
    writer: Literal["ProfileAgent"] = PROFILE_AGENT_ID
    outcome: Literal["completed"] = "completed"


class OwnerCorrectionRecord(_Record):
    """Record an evidenced direct-owner content correction and new revision."""

    kind: Literal["direct_owner_correction"] = "direct_owner_correction"
    sequence: int = Field(ge=1)
    correction_id: Identifier
    previous_content_digest: Sha256Digest
    corrected_content_digest: Sha256Digest
    owner_revision: int = Field(ge=1)
    evidence_ref: Identifier
    evidence_digest: Sha256Digest
    authority: Literal["direct_owner"] = "direct_owner"


class WriteReconciliationRecord(_Record):
    """Resolve one uncertain write against a separately evidenced owner snapshot."""

    kind: Literal["write_reconciliation"] = "write_reconciliation"
    sequence: int = Field(ge=1)
    reconciliation_id: Identifier
    write_id: Identifier
    observed_content_digest: Sha256Digest
    owner_revision: int = Field(ge=0)
    evidence_ref: Identifier
    evidence_digest: Sha256Digest
    authority: Literal["direct_owner"] = "direct_owner"


ProfileAuthorityRecord: TypeAlias = Annotated[
    ProfileIdentityRecord
    | CandidateRecord
    | ProposalRecord
    | OwnerConfirmationRecord
    | WriteAttemptRecord
    | WriteFailedRecord
    | CompletedWriteReceiptRecord
    | OwnerCorrectionRecord
    | WriteReconciliationRecord,
    Field(discriminator="kind"),
]

_RECORD_ADAPTER: TypeAdapter[ProfileAuthorityRecord] = TypeAdapter(ProfileAuthorityRecord)


@dataclass(frozen=True)
class ProfileVersion:
    """A version derived only from one structurally complete receipt record."""

    version_id: str
    generation: int
    previous_version_id: str | None
    content_digest: str
    receipt_id: str
    write_id: str
    confirmation_id: str
    proposal_id: str
    candidate_id: str
    owner_revision: int


@dataclass(frozen=True)
class ProfileAuthorityState:
    """Replay result; it contains no mutation capability or authenticated actor."""

    records: tuple[ProfileAuthorityRecord, ...]
    identity: ProfileIdentityRecord
    current_owner_revision: int
    current_content_digest: str
    candidates: tuple[CandidateRecord, ...]
    proposals: tuple[ProposalRecord, ...]
    confirmations: tuple[OwnerConfirmationRecord, ...]
    pending_writes: tuple[WriteAttemptRecord, ...]
    failed_writes: tuple[WriteFailedRecord, ...]
    completed_receipts: tuple[CompletedWriteReceiptRecord, ...]
    reconciled_write_ids: tuple[str, ...]
    versions: tuple[ProfileVersion, ...]

    @property
    def revision(self) -> int:
        """Last ordered record sequence, used as the adapter's CAS revision."""

        return self.records[-1].sequence

    @property
    def latest_version(self) -> ProfileVersion | None:
        return self.versions[-1] if self.versions else None

    @property
    def receipt_bound_version(self) -> ProfileVersion | None:
        """Return structural eligibility evidence, not a consumer authorization."""

        latest = self.latest_version
        if latest is None or self.pending_writes:
            return None
        if latest.owner_revision != self.current_owner_revision:
            return None
        if latest.content_digest != self.current_content_digest:
            return None
        if self.unresolved_indeterminate_write_ids:
            return None
        return latest

    @property
    def unresolved_indeterminate_write_ids(self) -> tuple[str, ...]:
        """Indeterminate writes not yet reconciled by an evidenced owner observation."""

        reconciled = set(self.reconciled_write_ids)
        return tuple(
            failure.write_id
            for failure in self.failed_writes
            if failure.content_effect == "indeterminate" and failure.write_id not in reconciled
        )


@dataclass(frozen=True)
class ValidatedTransition:
    """A proposed next state, not evidence that any durable commit occurred."""

    expected_revision: int
    next_state: ProfileAuthorityState


def profile_authority_record_json_schema() -> dict[str, object]:
    """Return the versioned JSON Schema for the durable record union."""

    return _RECORD_ADAPTER.json_schema()


def initial_profile_authority_state(
    identity: ProfileIdentityRecord,
) -> ProfileAuthorityState:
    """Create the schema state for the single vault-local owner Profile Note."""

    return replay_profile_records((identity,))


def validate_profile_transition(
    state: ProfileAuthorityState,
    record: ProfileAuthorityRecord,
    *,
    expected_revision: int,
    authority: object | None = None,
) -> ValidatedTransition:
    """Validate one append before a future adapter performs compare-and-commit.

    Confirmation observations, ProfileAgent write outcomes, direct-owner
    corrections, and reconciliation have separate identity capabilities. No
    ``actor`` or writer-name string is accepted as authority.
    """

    if expected_revision != state.revision:
        raise ProfileAuthorityConflict("profile authority revision changed")
    if record.sequence != expected_revision + 1:
        raise ProfileAuthorityConflict("profile authority sequence is not contiguous")
    if isinstance(record, OwnerConfirmationRecord):
        _require_owner_confirmation_capability(authority)
    elif isinstance(record, OwnerCorrectionRecord):
        _require_direct_owner_correction_capability(authority)
    elif isinstance(record, WriteReconciliationRecord):
        _require_direct_owner_reconciliation_capability(authority)
    elif isinstance(
        record,
        (WriteAttemptRecord, WriteFailedRecord, CompletedWriteReceiptRecord),
    ):
        _require_profile_agent_write_capability(authority)

    next_state = replay_profile_records((*state.records, record))
    return ValidatedTransition(expected_revision=expected_revision, next_state=next_state)


def replay_profile_records(
    records: Iterable[ProfileAuthorityRecord | dict[str, object]],
) -> ProfileAuthorityState:
    """Validate ordered record joins and rebuild restart state without authority."""

    typed_records: list[ProfileAuthorityRecord] = []
    for item in records:
        try:
            payload = item.model_dump(mode="python") if isinstance(item, _Record) else item
            record = _RECORD_ADAPTER.validate_python(payload)
        except Exception as exc:
            raise ProfileAuthorityContractError("invalid profile authority record") from exc
        if not isinstance(record, _Record):
            raise ProfileAuthorityContractError("invalid profile authority record type")
        typed_records.append(cast(ProfileAuthorityRecord, record))

    if not typed_records or not isinstance(typed_records[0], ProfileIdentityRecord):
        raise ProfileAuthorityContractError("profile identity must be the first record")
    identity = typed_records[0]
    if identity.sequence != 0:
        raise ProfileAuthorityContractError("profile identity sequence must be zero")

    candidates: dict[str, CandidateRecord] = {}
    proposals: dict[str, ProposalRecord] = {}
    confirmations: dict[str, OwnerConfirmationRecord] = {}
    writes: dict[str, WriteAttemptRecord] = {}
    failed: dict[str, WriteFailedRecord] = {}
    receipts: dict[str, CompletedWriteReceiptRecord] = {}
    reconciled_write_ids: set[str] = set()
    entity_ids: set[str] = {identity.profile_note_id}
    version_ids: dict[str, str] = {}
    event_ids: set[str] = set()
    versions: list[ProfileVersion] = []
    owner_revision = 0
    content_digest = identity.initial_content_digest

    for expected_sequence, record in enumerate(typed_records):
        if record.sequence != expected_sequence:
            raise ProfileAuthorityConflict("profile authority records are not contiguous")
        if record.event_id in event_ids:
            raise ProfileAuthorityConflict("profile authority event ID is duplicated")
        event_ids.add(record.event_id)
        if record.vault_id != identity.vault_id:
            raise ProfileAuthorityConflict("record belongs to a different vault")
        if record.profile_note_id != identity.profile_note_id:
            raise ProfileAuthorityConflict("record belongs to a different Profile Note")
        if isinstance(record, ProfileIdentityRecord):
            if expected_sequence != 0:
                raise ProfileAuthorityConflict("a vault may have only one Profile Note identity")
            continue

        if isinstance(record, CandidateRecord):
            if record.candidate_id in entity_ids:
                raise ProfileAuthorityConflict("candidate identity is duplicated")
            entity_ids.add(record.candidate_id)
            candidates[record.candidate_id] = record
        elif isinstance(record, ProposalRecord):
            candidate = candidates.get(record.candidate_id)
            if candidate is None:
                raise ProfileAuthorityConflict("proposal references a missing candidate")
            if record.proposal_id in entity_ids:
                raise ProfileAuthorityConflict("proposal identity is duplicated")
            entity_ids.add(record.proposal_id)
            latest = versions[-1] if versions else None
            current_version_id = None if latest is None else latest.version_id
            if (
                record.owner_revision != owner_revision
                or record.base_content_digest != content_digest
                or record.base_version_id != current_version_id
            ):
                raise ProfileAuthorityConflict("proposal is bound to a stale owner snapshot")
            if record.proposed_result_digest == record.base_content_digest:
                raise ProfileAuthorityConflict("proposal result must change the confirmed snapshot")
            proposals[record.proposal_id] = record
        elif isinstance(record, OwnerConfirmationRecord):
            proposal = proposals.get(record.proposal_id)
            if proposal is None:
                raise ProfileAuthorityConflict("confirmation references a missing proposal")
            if record.proposal_id in {item.proposal_id for item in confirmations.values()}:
                raise ProfileAuthorityConflict("proposal has more than one confirmation record")
            if record.confirmation_id in entity_ids:
                raise ProfileAuthorityConflict("confirmation identity is duplicated")
            entity_ids.add(record.confirmation_id)
            latest = versions[-1] if versions else None
            current_version_id = None if latest is None else latest.version_id
            if (
                record.proposed_change_digest != proposal.proposed_change_digest
                or record.source_snapshot_digest != proposal.base_content_digest
                or record.source_version_id != proposal.base_version_id
                or record.proposed_result_digest != proposal.proposed_result_digest
                or record.owner_revision != proposal.owner_revision
                or record.owner_revision != owner_revision
                or record.source_snapshot_digest != content_digest
                or record.source_version_id != current_version_id
            ):
                raise ProfileAuthorityConflict(
                    "confirmation does not bind the exact current proposal"
                )
            confirmations[record.confirmation_id] = record
        elif isinstance(record, WriteAttemptRecord):
            confirmation = confirmations.get(record.confirmation_id)
            if confirmation is None:
                raise ProfileAuthorityConflict("write attempt lacks durable owner confirmation")
            if any(
                receipt.confirmation_id == record.confirmation_id for receipt in receipts.values()
            ):
                raise ProfileAuthorityConflict("owner confirmation already has a completed write")
            proposal = proposals[confirmation.proposal_id]
            candidate = candidates[proposal.candidate_id]
            latest = versions[-1] if versions else None
            expected_generation = 1 if latest is None else latest.generation + 1
            expected_previous = None if latest is None else latest.version_id
            if record.base_content_digest != confirmation.source_snapshot_digest:
                raise ProfileAuthorityConflict(
                    "write attempt does not match the owner-confirmed source snapshot"
                )
            if record.intended_content_digest != confirmation.proposed_result_digest:
                raise ProfileAuthorityConflict(
                    "write attempt does not match the owner-confirmed result"
                )
            if record.previous_version_id != confirmation.source_version_id:
                raise ProfileAuthorityConflict(
                    "write attempt does not match the owner-confirmed source version"
                )
            if (
                record.proposal_id != proposal.proposal_id
                or record.candidate_id != candidate.candidate_id
                or record.owner_revision != owner_revision
                or record.owner_revision != confirmation.owner_revision
                or record.base_content_digest != content_digest
                or record.generation != expected_generation
                or record.previous_version_id != expected_previous
            ):
                raise ProfileAuthorityConflict(
                    "write attempt is stale or has a broken identity join"
                )
            if record.write_id in entity_ids or record.version_id in entity_ids:
                raise ProfileAuthorityConflict("write or version identity is duplicated")
            entity_ids.update((record.write_id, record.version_id))
            version_ids[record.version_id] = record.write_id
            if any(
                item.generation == record.generation
                and item.write_id not in failed
                and item.write_id not in {receipt.write_id for receipt in receipts.values()}
                for item in writes.values()
            ):
                raise ProfileAuthorityConflict(
                    "two active writes branch from the same profile version"
                )
            if any(
                failure.content_effect == "indeterminate"
                and failure.write_id not in reconciled_write_ids
                for failure in failed.values()
            ):
                raise ProfileAuthorityConflict(
                    "indeterminate write requires reconciliation before retry"
                )
            writes[record.write_id] = record
        elif isinstance(record, WriteFailedRecord):
            if record.write_id not in writes:
                raise ProfileAuthorityConflict("failed write references a missing attempt")
            if record.write_id in failed or record.write_id in {
                item.write_id for item in receipts.values()
            }:
                raise ProfileAuthorityConflict("write attempt already has a terminal outcome")
            failed[record.write_id] = record
        elif isinstance(record, OwnerCorrectionRecord):
            if (
                record.previous_content_digest != content_digest
                or record.owner_revision != owner_revision + 1
            ):
                raise ProfileAuthorityConflict(
                    "owner correction does not advance the current owner revision"
                )
            if record.corrected_content_digest == content_digest:
                raise ProfileAuthorityConflict("owner correction must change the content digest")
            if record.correction_id in entity_ids:
                raise ProfileAuthorityConflict("owner correction identity is duplicated")
            entity_ids.add(record.correction_id)
            owner_revision = record.owner_revision
            content_digest = record.corrected_content_digest
        elif isinstance(record, WriteReconciliationRecord):
            failure = failed.get(record.write_id)
            if failure is None or failure.content_effect != "indeterminate":
                raise ProfileAuthorityConflict(
                    "reconciliation must reference an indeterminate failed write"
                )
            if record.write_id in reconciled_write_ids:
                raise ProfileAuthorityConflict("indeterminate write is already reconciled")
            if any(
                write_id not in failed
                and write_id not in {receipt.write_id for receipt in receipts.values()}
                for write_id in writes
            ):
                raise ProfileAuthorityConflict(
                    "write reconciliation requires all ProfileAgent writes to reach a terminal outcome"
                )
            if (
                record.owner_revision != owner_revision
                or record.observed_content_digest != content_digest
            ):
                raise ProfileAuthorityConflict(
                    "write reconciliation does not bind the current owner-observed snapshot"
                )
            if record.reconciliation_id in entity_ids:
                raise ProfileAuthorityConflict("write reconciliation identity is duplicated")
            entity_ids.add(record.reconciliation_id)
            reconciled_write_ids.add(record.write_id)
        elif isinstance(record, CompletedWriteReceiptRecord):
            write = writes.get(record.write_id)
            if write is None:
                raise ProfileAuthorityConflict("completion receipt references a missing write")
            if record.write_id in failed or record.write_id in {
                item.write_id for item in receipts.values()
            }:
                raise ProfileAuthorityConflict("write attempt already has a terminal outcome")
            if record.receipt_id in entity_ids:
                raise ProfileAuthorityConflict("receipt identity is duplicated")
            if version_ids.get(record.version_id) != record.write_id:
                raise ProfileAuthorityConflict("receipt references an unknown version identity")
            entity_ids.add(record.receipt_id)
            latest = versions[-1] if versions else None
            expected_generation = 1 if latest is None else latest.generation + 1
            expected_previous = None if latest is None else latest.version_id
            if (
                record.confirmation_id != write.confirmation_id
                or record.proposal_id != write.proposal_id
                or record.candidate_id != write.candidate_id
                or record.version_id != write.version_id
                or record.generation != write.generation
                or record.previous_version_id != write.previous_version_id
                or record.owner_revision != write.owner_revision
                or record.content_digest != write.intended_content_digest
                or record.owner_revision != owner_revision
                or write.base_content_digest != content_digest
                or record.generation != expected_generation
                or record.previous_version_id != expected_previous
            ):
                raise ProfileAuthorityConflict(
                    "completion receipt is stale or does not bind the exact write"
                )
            receipts[record.receipt_id] = record
            versions.append(
                ProfileVersion(
                    version_id=record.version_id,
                    generation=record.generation,
                    previous_version_id=record.previous_version_id,
                    content_digest=record.content_digest,
                    receipt_id=record.receipt_id,
                    write_id=record.write_id,
                    confirmation_id=record.confirmation_id,
                    proposal_id=record.proposal_id,
                    candidate_id=record.candidate_id,
                    owner_revision=record.owner_revision,
                )
            )
            content_digest = record.content_digest

    return ProfileAuthorityState(
        records=tuple(typed_records),
        identity=identity,
        current_owner_revision=owner_revision,
        current_content_digest=content_digest,
        candidates=tuple(candidates.values()),
        proposals=tuple(proposals.values()),
        confirmations=tuple(confirmations.values()),
        pending_writes=tuple(
            write
            for write_id, write in writes.items()
            if write_id not in failed
            and write_id not in {receipt.write_id for receipt in receipts.values()}
        ),
        failed_writes=tuple(failed.values()),
        completed_receipts=tuple(receipts.values()),
        reconciled_write_ids=tuple(sorted(reconciled_write_ids)),
        versions=tuple(versions),
    )


def encode_profile_records(records: Iterable[ProfileAuthorityRecord]) -> bytes:
    """Serialize a structurally valid record stream as canonical UTF-8 JSONL."""

    typed_records = tuple(records)
    replay_profile_records(typed_records)
    lines = [
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        for record in typed_records
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def decode_profile_records(raw: bytes) -> tuple[ProfileAuthorityRecord, ...]:
    """Decode a complete JSONL stream and fail closed on torn or unknown records."""

    if not raw or not raw.endswith(b"\n"):
        raise ProfileAuthorityContractError("profile authority record stream is incomplete")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProfileAuthorityContractError("profile authority record stream is not UTF-8") from exc
    try:
        lines = text.splitlines()
        if any(not line for line in lines):
            raise ValueError("blank record line")
        records = tuple(_RECORD_ADAPTER.validate_json(line) for line in lines)
    except Exception as exc:
        raise ProfileAuthorityContractError("profile authority record stream is malformed") from exc
    replay_profile_records(records)
    return records


__all__ = [
    "PROFILE_AGENT_ID",
    "PROFILE_AUTHORITY_SCHEMA",
    "PROFILE_NOTE_KEY",
    "CandidateRecord",
    "CompletedWriteReceiptRecord",
    "OwnerConfirmationRecord",
    "OwnerCorrectionRecord",
    "ProfileAuthorityConflict",
    "ProfileAuthorityContractError",
    "ProfileAuthorityRecord",
    "ProfileAuthorityState",
    "ProfileIdentityRecord",
    "ProfileVersion",
    "ProposalRecord",
    "ValidatedTransition",
    "WriteAttemptRecord",
    "WriteFailedRecord",
    "WriteReconciliationRecord",
    "decode_profile_records",
    "encode_profile_records",
    "initial_profile_authority_state",
    "profile_authority_record_json_schema",
    "replay_profile_records",
    "validate_profile_transition",
]
