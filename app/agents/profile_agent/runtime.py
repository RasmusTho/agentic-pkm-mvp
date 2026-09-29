"""ProfileAgent's proposal-first, confirmation-bound write path.

Candidate strings are treated as data. They are rendered as escaped text in a
Panel proposal and are never supplied as instructions or consumer context.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.agents.panel.parser import is_ai_fence
from app.agents.panel_agent.parser import find_panels, parse_panel
from app.events.panel import PanelRuntimeActionResult
from app.knowledge._profile_authority_boundary import (
    _OWNER_CONFIRMATION_CAPABILITY,
    _PROFILE_AGENT_WRITE_CAPABILITY,
)
from app.knowledge.profile_authority import (
    PROFILE_AGENT_ID,
    CandidateRecord,
    CompletedWriteReceiptRecord,
    OwnerConfirmationRecord,
    ProfileAuthorityConflict,
    ProfileAuthorityContractError,
    ProfileAuthorityState,
    ProfileIdentityRecord,
    ProposalRecord,
    WriteAttemptRecord,
    WriteFailedRecord,
)
from app.knowledge.profile_authority_store import ProfileAuthorityStore
from app.knowledge.write_ops import read_note_text_with_version, write_note_from_absolute
from app.write_guard import DEFAULT_WRITE_GUARD
from scripts.yaml_roundtrip import load_frontmatter

PROFILE_APPLY_ACTION_ID = "profile.apply_proposal"
_PROFILE_PROPOSAL_ACTION_PREFIX = "Review ProfileAgent proposal "
_PROFILE_PROPOSAL_START = "<!--mimer:profile-proposal-start id={proposal_id}-->"
_PROFILE_PROPOSAL_END = "<!--mimer:profile-proposal-end id={proposal_id}-->"
_PROFILE_PROPOSAL_MARKER_RE = re.compile(
    r"<!--mimer:profile-proposal-(start|end) id=([A-Za-z0-9][A-Za-z0-9._:-]*)-->"
)
_MAX_TEXT = 24_000
_LINE_SEPARATOR_TRANSLATION = str.maketrans(
    {char: "\n" for char in "\v\f\x1c\x1d\x1e\u0085\u2028\u2029"}
)


def vault_profile_id(vault_root: Path | str) -> str:
    """Return a stable local identity for one resolved vault root."""

    root = Path(vault_root).expanduser().resolve(strict=True)
    digest = hashlib.sha256(root.as_posix().encode("utf-8")).hexdigest()[:32]
    return f"vault-{digest}"


def _normalize_candidate_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .translate(_LINE_SEPARATOR_TRANSLATION)
        .strip("\n")
    )


class ProfileUpdateCandidate(BaseModel):
    """Inspectable proposal input; its text never carries execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    candidate_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    vault_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    profile_note_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    provenance_ref: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    proposed_change: str = Field(min_length=1, max_length=4_000)
    provenance: str = Field(min_length=1, max_length=4_000)
    uncertainty: str = Field(min_length=1, max_length=4_000)
    proposed_content: str = Field(min_length=1, max_length=_MAX_TEXT)

    @field_validator(
        "provenance_ref",
        "proposed_change",
        "provenance",
        "uncertainty",
        "proposed_content",
        mode="before",
    )
    @classmethod
    def _normalize_text(cls, value: Any) -> Any:
        return _normalize_candidate_text(value)

    @field_validator(
        "provenance_ref", "proposed_change", "provenance", "uncertainty", "proposed_content"
    )
    @classmethod
    def _require_visible_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("profile proposal text must be non-empty visible text")
        return value


@dataclass(frozen=True)
class ProfileProposalResult:
    candidate_id: str
    proposal_id: str
    option_id: str
    note_path: str
    revision: int


@dataclass(frozen=True)
class ProfileWriteResult:
    status: Literal["completed", "already_completed", "blocked", "skipped"]
    reason: str | None = None
    candidate_id: str | None = None
    proposal_id: str | None = None
    confirmation_id: str | None = None
    write_id: str | None = None
    version_id: str | None = None
    receipt_id: str | None = None

    def as_panel_action(self, *, action_id: str, label: str, checked: bool) -> PanelRuntimeActionResult:
        details = {
            key: value
            for key, value in {
                "reason": self.reason,
                "candidate_id": self.candidate_id,
                "proposal_id": self.proposal_id,
                "confirmation_id": self.confirmation_id,
                "write_id": self.write_id,
                "version_id": self.version_id,
                "receipt_id": self.receipt_id,
            }.items()
            if value is not None
        }
        completed = self.status in {"completed", "already_completed"}
        return PanelRuntimeActionResult(
            id=action_id,
            label=label,
            checked=checked,
            status="triggered" if completed else ("skipped" if self.status == "skipped" else "logged"),
            emitted_events=[],
            details=details,
        )


class ProfileAgent:
    """Admit one candidate as an unchecked Panel proposal, then apply it later."""

    def __init__(self, vault_root: Path | str, profile_note_path: str | Path) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve(strict=True)
        if not self.vault_root.is_dir():
            raise ProfileAuthorityContractError("profile vault root is not a directory")
        self.note_relative_path = _validate_note_path(
            profile_note_path.as_posix() if isinstance(profile_note_path, Path) else profile_note_path
        )
        self.note_path = _resolve_note_path(self.vault_root, self.note_relative_path)
        self.vault_id = vault_profile_id(self.vault_root)
        self.profile_note_id = _profile_note_id(self.note_path)
        self.store = ProfileAuthorityStore(self.vault_root, self.profile_note_id)

    def propose_candidate(self, candidate: ProfileUpdateCandidate) -> ProfileProposalResult:
        """Persist candidate/proposal records and a visible unchecked proposal."""

        if candidate.vault_id != self.vault_id:
            raise ProfileAuthorityConflict("candidate belongs to a different vault")
        if candidate.profile_note_id != self.profile_note_id:
            raise ProfileAuthorityConflict("candidate targets a different Profile Note")
        if find_panels(candidate.proposed_content) or any(
            is_ai_fence(line) for line in candidate.proposed_content.splitlines()
        ):
            raise ProfileAuthorityConflict(
                "approved profile content cannot contain executable Panel markup"
            )

        DEFAULT_WRITE_GUARD.assert_writes_allowed("profile.proposal")
        note_text, expected_version = read_note_text_with_version(self.note_path)
        if _profile_note_id(self.note_path, note_text=note_text) != self.profile_note_id:
            raise ProfileAuthorityConflict("Profile Note identity changed")
        header, panel, approved_content = _profile_note_parts(note_text)
        current_digest = _digest(approved_content)
        identity = ProfileIdentityRecord(
            event_id=_stable_id("event-profile-identity", self.profile_note_id),
            vault_id=self.vault_id,
            profile_note_id=self.profile_note_id,
            note_path=self.note_relative_path,
            initial_content_digest=current_digest,
        )
        state = self.store.initialize(identity)
        if current_digest != state.current_content_digest:
            raise ProfileAuthorityConflict("Profile Note content changed since its governed snapshot")
        if state.pending_writes or state.unresolved_indeterminate_write_ids:
            raise ProfileAuthorityConflict("profile write outcome requires reconciliation")

        candidate_digest = _candidate_digest(candidate)
        result_digest = _digest(candidate.proposed_content)
        change_digest = _digest(candidate.proposed_change)
        candidate_record = next(
            (item for item in state.candidates if item.candidate_id == candidate.candidate_id),
            None,
        )
        if candidate_record is not None and (
            candidate_record.candidate_digest != candidate_digest
            or candidate_record.provenance_ref != candidate.provenance_ref
        ):
            raise ProfileAuthorityConflict("candidate identity was reused with different data")

        proposal = next(
            (item for item in state.proposals if item.candidate_id == candidate.candidate_id),
            None,
        )
        if proposal is not None and (
            proposal.proposed_change_digest != change_digest
            or proposal.proposed_result_digest != result_digest
        ):
            raise ProfileAuthorityConflict("candidate retry does not match its stored proposal")

        completed_receipt = next(
            (
                item
                for item in state.completed_receipts
                if proposal is not None and item.proposal_id == proposal.proposal_id
            ),
            None,
        )
        if completed_receipt is not None:
            return ProfileProposalResult(
                candidate_id=candidate.candidate_id,
                proposal_id=proposal.proposal_id,
                option_id=_option_id(proposal.proposal_id),
                note_path=self.note_relative_path,
                revision=state.revision,
            )

        completed_proposal_ids = {item.proposal_id for item in state.completed_receipts}
        if proposal is None and any(
            item.proposal_id not in completed_proposal_ids for item in state.proposals
        ):
            raise ProfileAuthorityConflict("another profile proposal is still pending")
        if proposal is None and result_digest == state.current_content_digest:
            raise ProfileAuthorityConflict("proposal does not change the approved profile content")
        if proposal is not None and proposal.base_content_digest != state.current_content_digest:
            raise ProfileAuthorityConflict("candidate retry does not match its stored proposal")

        if candidate_record is None:
            candidate_record = CandidateRecord(
                sequence=state.revision + 1,
                event_id=_stable_id("event-candidate", candidate.candidate_id + candidate_digest),
                vault_id=self.vault_id,
                profile_note_id=self.profile_note_id,
                candidate_id=candidate.candidate_id,
                provenance_ref=candidate.provenance_ref,
                candidate_digest=candidate_digest,
                candidate_payload=candidate.model_dump(mode="json"),
            )
            state = self.store.append(candidate_record, expected_revision=state.revision)

        if proposal is None:
            proposal_id = _stable_id(
                "proposal",
                f"{candidate.candidate_id}:{candidate_digest}:{state.revision}:{current_digest}",
            )
            proposal = ProposalRecord(
                sequence=state.revision + 1,
                event_id=_stable_id("event-proposal", proposal_id),
                vault_id=self.vault_id,
                profile_note_id=self.profile_note_id,
                proposal_id=proposal_id,
                candidate_id=candidate.candidate_id,
                proposed_change_digest=change_digest,
                base_content_digest=state.current_content_digest,
                base_version_id=(
                    None if state.latest_version is None else state.latest_version.version_id
                ),
                proposed_result_digest=result_digest,
                owner_revision=state.current_owner_revision,
            )
            state = self.store.append(proposal, expected_revision=state.revision)

        option_id = _option_id(proposal.proposal_id)
        panel_block = _render_proposal_panel(candidate, proposal.proposal_id, option_id)
        if panel:
            visible = _read_proposal_panel(panel, proposal.proposal_id)
            if visible != candidate:
                raise ProfileAuthorityConflict("visible proposal differs from its durable record")
        else:
            updated = _compose_profile_note(header, panel_block, approved_content)
            write_note_from_absolute(
                self.note_path,
                updated,
                vault_root=self.vault_root,
                expected_version=expected_version,
                writer_identity=PROFILE_AGENT_ID,
                action="profile.proposal",
            )
        return ProfileProposalResult(
            candidate_id=candidate.candidate_id,
            proposal_id=proposal.proposal_id,
            option_id=option_id,
            note_path=self.note_relative_path,
            revision=state.revision,
        )


def execute_profile_panel_actions(
    actions: Sequence[Any],
    *,
    note_path: str | None,
    vault_root: Path | None,
) -> list[PanelRuntimeActionResult]:
    """Handle profile-owned Panel actions before generic Panel graph/writeback."""

    selected = [action for action in actions if getattr(action, "id", None) == PROFILE_APPLY_ACTION_ID]
    if not selected:
        return []
    if len(selected) != 1 or len(actions) != 1:
        return [
            ProfileWriteResult(status="blocked", reason="profile_action_must_be_the_only_panel_action")
            .as_panel_action(action_id=action.id, label=action.label, checked=action.checked)
            for action in selected
        ]
    if vault_root is None:
        return [
            ProfileWriteResult(status="blocked", reason="no_bound_vault").as_panel_action(
                action_id=action.id,
                label=action.label,
                checked=action.checked,
            )
            for action in selected
        ]
    results: list[PanelRuntimeActionResult] = []
    for action in selected:
        if not action.checked:
            results.append(
                ProfileWriteResult(status="skipped", reason="proposal_not_confirmed").as_panel_action(
                    action_id=action.id,
                    label=action.label,
                    checked=False,
                )
            )
            continue
        try:
            result = _execute_checked_profile_action(
                action,
                note_path=note_path,
                vault_root=vault_root,
            )
        except Exception as exc:
            # Panel checkbox projection may roll back the checked source line
            # when execution raises. Keep profile failures as explicit action
            # outcomes so a post-write receipt failure cannot roll back approved
            # content that already reached the vault.
            result = ProfileWriteResult(
                status="blocked",
                reason=f"profile_runtime_error:{type(exc).__name__}",
            )
        results.append(result.as_panel_action(
            action_id=action.id,
            label=action.label,
            checked=True,
        ))
    return results


def _execute_checked_profile_action(
    action: Any,
    *,
    note_path: str | None,
    vault_root: Path,
) -> ProfileWriteResult:
    # The Panel event UUID may be an ObjectStore UUID; authority follows the
    # vault-local source path and frontmatter UUID in the durable identity.
    store = ProfileAuthorityStore(vault_root, profile_note_id=None)
    state = store.load_state()
    if state is None:
        return ProfileWriteResult(status="blocked", reason="profile_not_initialized")
    identity = state.identity
    note_file = _resolve_note_path(Path(vault_root).resolve(strict=True), identity.note_path)
    if not _source_path_matches(note_path, note_file, identity.note_path):
        return ProfileWriteResult(status="blocked", reason="panel_source_path_mismatch")

    note_text, expected_version = read_note_text_with_version(note_file)
    if _profile_note_id(note_file, note_text=note_text) != identity.profile_note_id:
        return ProfileWriteResult(status="blocked", reason="profile_note_identity_changed")
    proposal = _proposal_from_action(action, note_text, identity.profile_note_id)
    if proposal is None:
        return ProfileWriteResult(status="blocked", reason="confirmation_not_source_backed")
    proposal_record = next(
        (item for item in state.proposals if item.proposal_id == proposal.proposal_id),
        None,
    )
    if proposal_record is None or proposal.candidate.profile_note_id != identity.profile_note_id:
        return ProfileWriteResult(status="blocked", reason="proposal_not_admitted")
    candidate_record = next(
        (item for item in state.candidates if item.candidate_id == proposal.candidate.candidate_id),
        None,
    )
    durable_candidate: ProfileUpdateCandidate | None = None
    if candidate_record is not None and candidate_record.candidate_payload is not None:
        try:
            durable_candidate = ProfileUpdateCandidate.model_validate(
                candidate_record.candidate_payload
            )
        except Exception:
            durable_candidate = None
    if (
        candidate_record is None
        or durable_candidate is None
        or durable_candidate != proposal.candidate
        or candidate_record.candidate_digest != _candidate_digest(proposal.candidate)
        or candidate_record.provenance_ref != proposal.candidate.provenance_ref
        or proposal_record.candidate_id != proposal.candidate.candidate_id
        or proposal_record.proposed_change_digest != _digest(proposal.candidate.proposed_change)
        or proposal_record.proposed_result_digest != _digest(proposal.candidate.proposed_content)
    ):
        return ProfileWriteResult(status="blocked", reason="proposal_record_mismatch")

    header, panel, approved_content = _profile_note_parts(note_text)
    current_digest = _digest(approved_content)
    completed = next(
        (item for item in state.completed_receipts if item.proposal_id == proposal.proposal_id),
        None,
    )
    if completed is not None:
        if current_digest != completed.content_digest:
            return ProfileWriteResult(
                status="blocked",
                reason="profile_content_changed_after_receipt",
                candidate_id=proposal.candidate.candidate_id,
                proposal_id=proposal.proposal_id,
                confirmation_id=completed.confirmation_id,
                write_id=completed.write_id,
                version_id=completed.version_id,
                receipt_id=completed.receipt_id,
            )
        _best_effort_remove_completed_panel(
            note_file,
            note_text,
            expected_version,
            vault_root=Path(vault_root),
            proposal_id=proposal.proposal_id,
        )
        return ProfileWriteResult(
            status="already_completed",
            candidate_id=completed.candidate_id,
            proposal_id=completed.proposal_id,
            confirmation_id=completed.confirmation_id,
            write_id=completed.write_id,
            version_id=completed.version_id,
            receipt_id=completed.receipt_id,
        )

    if current_digest != proposal_record.base_content_digest:
        return ProfileWriteResult(status="blocked", reason="profile_content_changed_since_proposal")
    latest_version_id = None if state.latest_version is None else state.latest_version.version_id
    if (
        proposal_record.owner_revision != state.current_owner_revision
        or proposal_record.base_version_id != latest_version_id
    ):
        return ProfileWriteResult(status="blocked", reason="proposal_snapshot_is_stale")
    if state.pending_writes:
        return ProfileWriteResult(status="blocked", reason="profile_write_outcome_requires_reconciliation")
    if state.unresolved_indeterminate_write_ids:
        return ProfileWriteResult(status="blocked", reason="profile_write_outcome_is_indeterminate")

    confirmation = next(
        (item for item in state.confirmations if item.proposal_id == proposal.proposal_id),
        None,
    )
    if confirmation is None:
        confirmation = OwnerConfirmationRecord(
            sequence=state.revision + 1,
            event_id=_stable_id(
                "event-confirmation",
                proposal.proposal_id + expected_version + str(action.option_id),
            ),
            vault_id=identity.vault_id,
            profile_note_id=identity.profile_note_id,
            confirmation_id=_stable_id(
                "confirmation",
                proposal.proposal_id + expected_version + str(action.option_id),
            ),
            proposal_id=proposal.proposal_id,
            proposed_change_digest=proposal_record.proposed_change_digest,
            source_snapshot_digest=proposal_record.base_content_digest,
            source_version_id=proposal_record.base_version_id,
            proposed_result_digest=proposal_record.proposed_result_digest,
            owner_revision=proposal_record.owner_revision,
            confirmation_evidence_ref=f"panel-checkbox:{action.option_id}",
            confirmation_evidence_digest=_digest(note_text),
        )
        state = store.append(
            confirmation,
            expected_revision=state.revision,
            authority=_OWNER_CONFIRMATION_CAPABILITY,
        )

    if confirmation.source_snapshot_digest != current_digest:
        return ProfileWriteResult(status="blocked", reason="confirmation_snapshot_is_stale")
    try:
        DEFAULT_WRITE_GUARD.assert_writes_allowed("profile.write")
    except Exception as exc:
        return ProfileWriteResult(
            status="blocked",
            reason=f"write_guard_blocked:{type(exc).__name__}",
            candidate_id=proposal.candidate.candidate_id,
            proposal_id=proposal.proposal_id,
            confirmation_id=confirmation.confirmation_id,
        )

    prior_attempts = [
        item
        for item in state.records
        if isinstance(item, WriteAttemptRecord)
        and item.confirmation_id == confirmation.confirmation_id
    ]
    attempt_number = len(prior_attempts) + 1
    write_id = _stable_id("write", f"{proposal.proposal_id}:{confirmation.confirmation_id}:{attempt_number}")
    version_id = _stable_id("version", write_id)
    latest = state.latest_version
    generation = 1 if latest is None else latest.generation + 1
    attempt = WriteAttemptRecord(
        sequence=state.revision + 1,
        event_id=_stable_id("event-write-attempt", write_id),
        vault_id=identity.vault_id,
        profile_note_id=identity.profile_note_id,
        write_id=write_id,
        confirmation_id=confirmation.confirmation_id,
        proposal_id=proposal.proposal_id,
        candidate_id=proposal.candidate.candidate_id,
        version_id=version_id,
        generation=generation,
        previous_version_id=None if latest is None else latest.version_id,
        base_content_digest=current_digest,
        intended_content_digest=proposal_record.proposed_result_digest,
        owner_revision=state.current_owner_revision,
    )
    state = store.append(
        attempt,
        expected_revision=state.revision,
        authority=_PROFILE_AGENT_WRITE_CAPABILITY,
    )

    updated = _compose_profile_note(header, panel, proposal.candidate.proposed_content)
    try:
        write_note_from_absolute(
            note_file,
            updated,
            vault_root=vault_root,
            expected_version=expected_version,
            writer_identity=PROFILE_AGENT_ID,
            action="profile.write",
        )
    except Exception as exc:
        failure = _write_failure_record(
            state,
            identity=identity,
            attempt=attempt,
            exc=exc,
            note_file=note_file,
            intended_digest=proposal_record.proposed_result_digest,
            base_digest=current_digest,
        )
        if failure is not None:
            try:
                store.append(
                    failure,
                    expected_revision=state.revision,
                    authority=_PROFILE_AGENT_WRITE_CAPABILITY,
                )
            except Exception:
                pass
        return ProfileWriteResult(
            status="blocked",
            reason=f"profile_write_failed:{type(exc).__name__}",
            candidate_id=proposal.candidate.candidate_id,
            proposal_id=proposal.proposal_id,
            confirmation_id=confirmation.confirmation_id,
            write_id=write_id,
            version_id=version_id,
        )

    expected_written_version = hashlib.sha256(updated.encode("utf-8")).hexdigest()
    try:
        latest_text, latest_note_version = read_note_text_with_version(note_file)
        _, _, latest_content = _profile_note_parts(latest_text)
        latest_profile_note_id = _profile_note_id(note_file, note_text=latest_text)
        if (
            latest_note_version != expected_written_version
            or latest_profile_note_id != identity.profile_note_id
            or _digest(latest_content) != proposal_record.proposed_result_digest
        ):
            raise ProfileAuthorityConflict(
                "Profile Note changed after the governed write and before its terminal receipt"
            )
    except Exception as exc:
        failure = _write_failure_record(
            state,
            identity=identity,
            attempt=attempt,
            exc=exc,
            note_file=note_file,
            intended_digest=proposal_record.proposed_result_digest,
            base_digest=current_digest,
            force_indeterminate=True,
        )
        if failure is not None:
            try:
                store.append(
                    failure,
                    expected_revision=state.revision,
                    authority=_PROFILE_AGENT_WRITE_CAPABILITY,
                )
            except Exception:
                pass
        return ProfileWriteResult(
            status="blocked",
            reason=f"profile_snapshot_changed_before_receipt:{type(exc).__name__}",
            candidate_id=proposal.candidate.candidate_id,
            proposal_id=proposal.proposal_id,
            confirmation_id=confirmation.confirmation_id,
            write_id=write_id,
            version_id=version_id,
        )

    receipt_id = _stable_id("receipt", write_id)
    receipt = CompletedWriteReceiptRecord(
        sequence=state.revision + 1,
        event_id=_stable_id("event-receipt", receipt_id),
        vault_id=identity.vault_id,
        profile_note_id=identity.profile_note_id,
        receipt_id=receipt_id,
        write_id=write_id,
        confirmation_id=confirmation.confirmation_id,
        proposal_id=proposal.proposal_id,
        candidate_id=proposal.candidate.candidate_id,
        version_id=version_id,
        generation=generation,
        previous_version_id=None if latest is None else latest.version_id,
        content_digest=proposal_record.proposed_result_digest,
        owner_revision=state.current_owner_revision,
        writer=PROFILE_AGENT_ID,
        outcome="completed",
    )
    try:
        store.append(
            receipt,
            expected_revision=state.revision,
            authority=_PROFILE_AGENT_WRITE_CAPABILITY,
        )
    except Exception as exc:
        # The durable attempt remains pending; keep the checked proposal in
        # the note so the missing terminal receipt remains visible and do not
        # allow a later invocation to repeat the profile write.
        return ProfileWriteResult(
            status="blocked",
            reason=f"terminal_receipt_not_persisted:{type(exc).__name__}",
            candidate_id=proposal.candidate.candidate_id,
            proposal_id=proposal.proposal_id,
            confirmation_id=confirmation.confirmation_id,
            write_id=write_id,
            version_id=version_id,
        )

    _best_effort_remove_completed_panel(
        note_file,
        latest_text,
        latest_note_version,
        vault_root=Path(vault_root),
        proposal_id=proposal.proposal_id,
    )
    return ProfileWriteResult(
        status="completed",
        candidate_id=proposal.candidate.candidate_id,
        proposal_id=proposal.proposal_id,
        confirmation_id=confirmation.confirmation_id,
        write_id=write_id,
        version_id=version_id,
        receipt_id=receipt_id,
    )


@dataclass(frozen=True)
class _VisibleProposal:
    proposal_id: str
    candidate: ProfileUpdateCandidate
    panel_block: str


def _proposal_from_action(action: Any, note_text: str, profile_note_id: str) -> _VisibleProposal | None:
    if (
        getattr(action, "id", None) != PROFILE_APPLY_ACTION_ID
        or not getattr(action, "checked", False)
        or not getattr(action, "proposal_pending", False)
    ):
        return None
    label = str(getattr(action, "label", ""))
    if not label.startswith(_PROFILE_PROPOSAL_ACTION_PREFIX):
        return None
    proposal_id = label[len(_PROFILE_PROPOSAL_ACTION_PREFIX):]
    if not proposal_id:
        return None
    expected_start = _PROFILE_PROPOSAL_START.format(proposal_id=proposal_id)
    expected_end = _PROFILE_PROPOSAL_END.format(proposal_id=proposal_id)
    panels = find_panels(note_text)
    matching_panels = [
        block for block in panels
        if expected_start in block.raw_block and expected_end in block.raw_block
    ]
    if len(matching_panels) != 1 or len(panels) != 1:
        return None
    panel_block = matching_panels[0].raw_block
    parsed = parse_panel(panel_block, panel_id=matching_panels[0].panel_id)
    canonical_actions = [
        item for item in parsed.actions
        if item.action_id == PROFILE_APPLY_ACTION_ID
        and item.option_id == _option_id(proposal_id)
    ]
    if len(canonical_actions) != 1:
        return None
    canonical = canonical_actions[0]
    if (
        not canonical.checked
        or not canonical.proposal_pending
        or canonical.label != label
        or getattr(action, "option_id", None) != canonical.option_id
        or not getattr(action, "checked", False)
    ):
        return None
    candidate = _read_proposal_panel(panel_block, proposal_id)
    if candidate.profile_note_id != profile_note_id:
        return None
    return _VisibleProposal(proposal_id, candidate, panel_block)


def _read_proposal_panel(panel_block: str, proposal_id: str) -> ProfileUpdateCandidate:
    start_marker = _PROFILE_PROPOSAL_START.format(proposal_id=proposal_id)
    end_marker = _PROFILE_PROPOSAL_END.format(proposal_id=proposal_id)
    if panel_block.count(start_marker) != 1 or panel_block.count(end_marker) != 1:
        raise ProfileAuthorityContractError("profile proposal markers are malformed")
    marker_ids = _PROFILE_PROPOSAL_MARKER_RE.findall(panel_block)
    if marker_ids != [("start", proposal_id), ("end", proposal_id)]:
        raise ProfileAuthorityContractError("profile proposal markers are ambiguous")
    start = panel_block.index(start_marker) + len(start_marker)
    end = panel_block.index(end_marker, start)
    block = panel_block[start:end]
    fields: dict[str, list[str]] = {
        "provenance_ref": [],
        "proposed_change": [],
        "provenance": [],
        "uncertainty": [],
        "proposed_content": [],
    }
    headings = {
        "> Provenance reference:": "provenance_ref",
        "> Proposed change:": "proposed_change",
        "> Provenance:": "provenance",
        "> Uncertainty:": "uncertainty",
        "> Proposed approved profile content:": "proposed_content",
    }
    current: str | None = None
    for line in block.splitlines():
        if line in headings:
            current = headings[line]
            continue
        if current is not None and line.startswith("> <code>") and line.endswith("</code>"):
            raw_value = line[len("> <code>"):-len("</code>")]
            fields[current].append(html.unescape(raw_value))
        elif line.startswith("<!--") or line.startswith("- ["):
            current = None
    parsed_fields = {key: "\n".join(value) for key, value in fields.items()}
    action_line = next(
        (
            line
            for line in panel_block.splitlines()
            if line.startswith("- [") and PROFILE_APPLY_ACTION_ID in line
        ),
        None,
    )
    if action_line is None:
        raise ProfileAuthorityContractError("profile proposal action is missing")
    from app.agents.panel.writeback import parse_action_line

    parsed_action = parse_action_line(action_line)
    if parsed_action is None or parsed_action.label != _action_label(proposal_id):
        raise ProfileAuthorityContractError("profile proposal action label is malformed")
    try:
        metadata = json.loads(_metadata_line(panel_block, proposal_id))
        candidate = ProfileUpdateCandidate.model_validate(
            {
                **metadata,
                **parsed_fields,
                "candidate_id": metadata["candidate_id"],
                "profile_note_id": metadata["profile_note_id"],
                "vault_id": metadata["vault_id"],
            }
        )
        if candidate.provenance_ref != metadata["provenance_ref"]:
            raise ValueError("visible provenance reference does not match proposal metadata")
        return candidate
    except Exception as exc:
        raise ProfileAuthorityContractError("visible profile proposal is malformed") from exc


def _metadata_line(panel_block: str, proposal_id: str) -> str:
    marker = f"<!--mimer:profile-proposal-data id={proposal_id} payload="
    for line in panel_block.splitlines():
        if line.startswith(marker) and line.endswith("-->"):
            encoded = line[len(marker):-3]
            try:
                import base64

                return base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
            except Exception as exc:
                raise ProfileAuthorityContractError("profile proposal data is malformed") from exc
    raise ProfileAuthorityContractError("profile proposal data is missing")


def _render_proposal_panel(
    candidate: ProfileUpdateCandidate,
    proposal_id: str,
    option_id: str,
) -> str:
    import base64

    payload = json.dumps(
        {
            "candidate_id": candidate.candidate_id,
            "profile_note_id": candidate.profile_note_id,
            "provenance_ref": candidate.provenance_ref,
            "vault_id": candidate.vault_id,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    lines = [
        "%% AI:Start %%",
        "## AI-instruktion",
        "ProfileAgent proposal review. This panel is not approved profile content.",
        "",
        "## AI-åtgärder",
        _PROFILE_PROPOSAL_START.format(proposal_id=proposal_id),
        f"<!--mimer:profile-proposal-data id={proposal_id} payload={encoded}-->",
        (
            f"- [ ] {_action_label(proposal_id)} "
            f"<!--ai:option_id={option_id}--> "
            f"<!--ai:id={PROFILE_APPLY_ACTION_ID}--> "
            "<!--ai:proposed=govprof-->"
        ),
    ]
    for field_name, label in (
        ("provenance_ref", "> Provenance reference:"),
        ("proposed_change", "> Proposed change:"),
        ("provenance", "> Provenance:"),
        ("uncertainty", "> Uncertainty:"),
        ("proposed_content", "> Proposed approved profile content:"),
    ):
        lines.append(label)
        value = getattr(candidate, field_name)
        for value_line in value.split("\n"):
            lines.append(f"> <code>{html.escape(value_line, quote=False)}</code>")
    lines.extend(
        [
            _PROFILE_PROPOSAL_END.format(proposal_id=proposal_id),
            "%% AI:End %%",
        ]
    )
    return "\n".join(lines)


def _compose_profile_note(header: str, panel: str, approved_content: str) -> str:
    normalized = approved_content.strip("\n")
    return f"{header}{panel}\n\n{normalized}\n"


def _profile_note_parts(note_text: str) -> tuple[str, str, str]:
    header = _split_profile_header(note_text)
    remainder = note_text[len(header):]
    panels = find_panels(note_text)
    managed = [block for block in panels if "<!--mimer:profile-proposal-start id=" in block.raw_block]
    if len(managed) > 1 or len(panels) != len(managed):
        raise ProfileAuthorityConflict("Profile Note contains an unrelated or ambiguous Panel")
    panel = ""
    body = remainder
    if managed:
        proposal_ids = _PROFILE_PROPOSAL_MARKER_RE.findall(managed[0].raw_block)
        starts = [proposal_id for kind, proposal_id in proposal_ids if kind == "start"]
        ends = [proposal_id for kind, proposal_id in proposal_ids if kind == "end"]
        if len(starts) != 1 or len(ends) != 1 or starts[0] != ends[0]:
            raise ProfileAuthorityContractError("Profile Note proposal panel is incomplete")
        panel_id = starts[0]
        panel, body = _extract_panel_span(remainder, panel_id)
        if not panel or panel.count(_PROFILE_PROPOSAL_START.format(proposal_id=panel_id)) != 1:
            raise ProfileAuthorityContractError("Profile Note proposal panel is malformed")
    return header, panel, body.strip("\n")


def _split_profile_header(note_text: str) -> str:
    lines = note_text.splitlines(keepends=True)
    index = 0
    if lines and lines[0].rstrip("\r\n") == "---":
        index = 1
        while index < len(lines) and lines[index].rstrip("\r\n") != "---":
            index += 1
        if index >= len(lines):
            raise ProfileAuthorityContractError("Profile Note frontmatter is incomplete")
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    if index >= len(lines) or not lines[index].lstrip().startswith("# "):
        raise ProfileAuthorityContractError("Profile Note must have a top-level title")
    index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1
    return "".join(lines[:index])


def _extract_panel_span(remainder: str, proposal_id: str) -> tuple[str, str]:
    lines = remainder.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    marker_line = next(
        (
            index
            for index, line in enumerate(lines)
            if _PROFILE_PROPOSAL_START.format(proposal_id=proposal_id) in line
        ),
        None,
    )
    if marker_line is None:
        return "", remainder
    start_line = next(
        (index for index in range(marker_line - 1, -1, -1) if _is_panel_fence(lines[index])),
        None,
    )
    end_line = next(
        (index for index in range(marker_line + 1, len(lines)) if _is_panel_fence(lines[index])),
        None,
    )
    if start_line is None or end_line is None:
        return "", remainder
    start_offset = offsets[start_line]
    end_offset = offsets[end_line] + len(lines[end_line])
    return remainder[start_offset:end_offset], remainder[:start_offset] + remainder[end_offset:]


def _is_panel_fence(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("%%") and "ai" in stripped.strip("%").lower()


def _remove_completed_panel(note_text: str, proposal_id: str) -> str | None:
    marker = _PROFILE_PROPOSAL_START.format(proposal_id=proposal_id)
    lines = note_text.splitlines(keepends=True)
    offsets: list[int] = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    marker_line = next((i for i, line in enumerate(lines) if marker in line), None)
    if marker_line is None:
        return None
    start_line = next(
        (i for i in range(marker_line - 1, -1, -1) if _is_panel_fence(lines[i])),
        None,
    )
    end_line = next(
        (i for i in range(marker_line + 1, len(lines)) if _is_panel_fence(lines[i])),
        None,
    )
    if start_line is None or end_line is None:
        return None
    start = offsets[start_line]
    end = offsets[end_line] + len(lines[end_line])
    return note_text[:start] + note_text[end:]


def _best_effort_remove_completed_panel(
    note_file: Path,
    current_text: str,
    expected_version: str,
    *,
    vault_root: Path,
    proposal_id: str,
) -> None:
    updated = _remove_completed_panel(current_text, proposal_id)
    if updated is None:
        return
    try:
        write_note_from_absolute(
            note_file,
            updated,
            vault_root=vault_root,
            expected_version=expected_version,
            writer_identity=PROFILE_AGENT_ID,
            action="profile.receipt_cleanup",
        )
    except Exception:
        # The completed version remains bound to its durable record. A later
        # Panel pass can retry this presentation-only cleanup under CAS.
        return


def _write_failure_record(
    state: ProfileAuthorityState,
    *,
    identity: ProfileIdentityRecord,
    attempt: WriteAttemptRecord,
    exc: Exception,
    note_file: Path,
    intended_digest: str,
    base_digest: str,
    force_indeterminate: bool = False,
) -> WriteFailedRecord | None:
    try:
        current_note, _ = read_note_text_with_version(note_file)
        _, _, current_content = _profile_note_parts(current_note)
        observed_digest = _digest(current_content)
    except Exception:
        observed_digest = ""
    failure_code: Literal[
        "write_rejected", "write_failed", "stale_owner_revision", "receipt_unavailable", "indeterminate"
    ]
    if force_indeterminate:
        # The CAS write succeeded, but its exact source snapshot was not
        # confirmed before the terminal receipt boundary. Even if a later
        # read happens to match the base or intended bytes, the write outcome
        # must remain unresolved until explicit reconciliation.
        failure_code = "indeterminate"
        content_effect: Literal["none", "indeterminate"] = "indeterminate"
    elif observed_digest == intended_digest:
        # A writer may report a conflict after its atomic replacement took
        # effect. Without the terminal receipt, the intended bytes remain
        # uncommitted authority and must stay blocked pending reconciliation.
        failure_code = "receipt_unavailable"
        content_effect: Literal["none", "indeterminate"] = "indeterminate"
    elif type(exc).__name__ == "WritesBlockedError":
        failure_code = "write_rejected"
        content_effect = "none"
    elif type(exc).__name__ == "KnowledgeWriteConflict":
        if observed_digest == base_digest:
            failure_code = "stale_owner_revision"
            content_effect = "none"
        else:
            failure_code = "indeterminate"
            content_effect = "indeterminate"
    elif observed_digest == base_digest:
        failure_code = "write_failed"
        content_effect = "none"
    else:
        failure_code = "indeterminate"
        content_effect = "indeterminate"
    return WriteFailedRecord(
        sequence=state.revision + 1,
        event_id=_stable_id("event-write-failed", attempt.write_id),
        vault_id=identity.vault_id,
        profile_note_id=identity.profile_note_id,
        write_id=attempt.write_id,
        failure_code=failure_code,
        content_effect=content_effect,
    )


def _profile_note_id(note_path: Path, *, note_text: str | None = None) -> str:
    text = note_text if note_text is not None else note_path.read_text(encoding="utf-8")
    try:
        frontmatter, _ = load_frontmatter(text)
    except Exception as exc:
        raise ProfileAuthorityContractError("Profile Note frontmatter is invalid") from exc
    if not isinstance(frontmatter, dict) or not isinstance(frontmatter.get("uuid"), str):
        raise ProfileAuthorityContractError("Profile Note must have a stable uuid")
    return frontmatter["uuid"]


def _validate_note_path(value: str) -> str:
    if not isinstance(value, str):
        raise ProfileAuthorityContractError("Profile Note path must be vault-relative")
    raw_parts = value.split("/")
    path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        not value
        or value != path.as_posix()
        or path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in raw_parts)
        or "\\" in value
        or path.suffix.lower() != ".md"
    ):
        raise ProfileAuthorityContractError("Profile Note path must be a canonical Markdown path")
    return value


def _resolve_note_path(vault_root: Path, note_relative_path: str) -> Path:
    root = Path(vault_root).expanduser().resolve(strict=True)
    lexical = root.joinpath(*PurePosixPath(note_relative_path).parts)
    resolved = lexical.resolve(strict=True)
    if resolved != lexical.absolute() or not resolved.is_relative_to(root) or not resolved.is_file():
        raise ProfileAuthorityContractError("Profile Note path is aliased or outside its vault")
    return lexical


def _source_path_matches(note_path: str | None, expected: Path, relative: str) -> bool:
    if note_path is None or not str(note_path).strip():
        return True
    supplied = Path(note_path).expanduser()
    if supplied.is_absolute():
        try:
            return supplied.resolve(strict=True) == expected.resolve(strict=True)
        except OSError:
            return False
    try:
        return _validate_note_path(supplied.as_posix()) == relative
    except ProfileAuthorityContractError:
        return False


def _action_label(proposal_id: str) -> str:
    return f"{_PROFILE_PROPOSAL_ACTION_PREFIX}{proposal_id}"


def _option_id(proposal_id: str) -> str:
    return f"opt_{hashlib.sha256(proposal_id.encode('utf-8')).hexdigest()[:32]}"


def _candidate_digest(candidate: ProfileUpdateCandidate) -> str:
    payload = json.dumps(
        candidate.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(payload)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


__all__ = [
    "PROFILE_APPLY_ACTION_ID",
    "ProfileAgent",
    "ProfileProposalResult",
    "ProfileUpdateCandidate",
    "ProfileWriteResult",
    "execute_profile_panel_actions",
    "vault_profile_id",
]
