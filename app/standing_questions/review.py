"""Governed human review transitions for standing questions (SQ-05)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.expansion.accept import (
    ACCEPT_EVENT_SOURCE,
    AcceptanceReconciliationError,
    AcceptError,
    CREATE_ACCEPTED_EVENT,
    DraftNotFoundError,
    accept_draft,
    decline_draft,
)
from app.expansion.create import standing_question_acceptance_option_id
from app.knowledge.errors import KnowledgeWriteConflict
from app.panel.checkbox_projection import (
    CheckboxProjectionRequest,
    extract_panel_selectable_options,
)
from app.runtime.runtime_loop import resolve_outbox_path
from app.services.outbox import iter_jsonl_outbox_records
from app.standing_questions.answer_refresh import (
    UnreadableVaultReferenceError,
    _question_refresh_lock,
    _resolve_vault_ref,
)
from app.standing_questions.question_store import (
    InvalidQuestionReviewTransition,
    QuestionStore,
    question_note_path,
)
from app.text.helpers import content_hash
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard, WritesBlockedError
from scripts.yaml_roundtrip import load_frontmatter


class QuestionReviewError(RuntimeError):
    """A fail-closed refusal at the SQ-05 review boundary."""

    def __init__(self, status_code: int, error: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = {"error": error, "message": message, **details}


@dataclass(frozen=True)
class QuestionAcceptancePreflight:
    question_id: str
    question: dict[str, Any]
    question_version: str
    draft_path: Path
    request: CheckboxProjectionRequest
    already_projected: bool = False


def _candidate_path(vault_root: Path, reference: object) -> Path:
    if not isinstance(reference, str) or not reference.strip():
        raise QuestionReviewError(409, "candidate_missing", "This question has no pending candidate answer.")
    try:
        path = _resolve_vault_ref(vault_root, reference)
    except UnreadableVaultReferenceError as exc:
        raise QuestionReviewError(409, "candidate_unreadable", "The candidate answer cannot be inspected safely.") from exc
    if path is None:
        raise QuestionReviewError(409, "candidate_missing", "The pending candidate answer is no longer available.")
    return path


def _relative_path(vault_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(vault_root.resolve()).as_posix()
    except (OSError, RuntimeError, ValueError) as exc:
        raise QuestionReviewError(409, "candidate_outside_vault", "The candidate answer is outside the selected vault.") from exc


def prepare_question_acceptance(
    request: CheckboxProjectionRequest,
    *,
    vault_root: Path,
) -> QuestionAcceptancePreflight:
    """Bind a projected EXP-4 checkbox to the exact Question version observed by the page."""

    question_id = request.review_question_id
    expected_version = request.expected_question_version
    if not question_id or not expected_version:
        raise QuestionReviewError(422, "review_binding_required", "Question review needs its observed Question version.")
    try:
        question_note_path(question_id)
    except ValueError as exc:
        raise QuestionReviewError(404, "question_not_found", "The requested question does not exist.") from exc

    vault_root = vault_root.expanduser().resolve()
    store = QuestionStore(vault_root)
    try:
        question, observed_version = store.read_question_with_version(question_id)
    except (OSError, ValueError) as exc:
        raise QuestionReviewError(404, "question_not_found", "The requested question does not exist.") from exc
    if observed_version != expected_version:
        raise QuestionReviewError(409, "stale_question", "This question changed. Reload it before reviewing the candidate.")
    if question["status"] != "open":
        raise QuestionReviewError(409, "question_not_open", "Only an open question can accept a candidate answer.")

    vault_root = vault_root.expanduser().resolve()
    draft_path = _candidate_path(vault_root, question.get("candidate_answer_ref"))
    relative_path = _relative_path(vault_root, draft_path)
    if relative_path != request.note_path:
        raise QuestionReviewError(409, "stale_candidate", "The pending candidate changed. Reload the question before accepting it.")

    try:
        raw = draft_path.read_text(encoding="utf-8")
        frontmatter, _body = load_frontmatter(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise QuestionReviewError(409, "candidate_unreadable", "The candidate answer cannot be inspected safely.") from exc
    frontmatter = frontmatter or {}
    draft_id = str(frontmatter.get("uuid") or draft_path.stem)
    if frontmatter.get("question_id") != question_id or request.artifact_id != draft_id:
        raise QuestionReviewError(409, "candidate_identity_mismatch", "The candidate no longer belongs to this question.")

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    options = extract_panel_selectable_options(
        normalized,
        artifact_id=request.artifact_id,
        note_path=request.note_path,
    )
    option = next(
        (
            item
            for item in options
            if item.panel_id == request.panel_id and item.option_id == request.option_id
        ),
        None,
    )
    already_projected = False
    control_matches = bool(
        option is not None
        and option.proposal_pending
        and option.label == f"Accept this draft into the vault (draft {draft_id[:12]})"
        and option.option_id == standing_question_acceptance_option_id(draft_id)
    )
    if control_matches and option is not None and option.checked:
        # A prior request may have persisted the human checkbox and then lost
        # its acknowledgement before EXP-4. Prove that the current note is
        # exactly the deterministic checked projection of the observed source.
        lines = normalized.splitlines(keepends=True)
        index = option.source_range.start_line
        if 0 <= index < len(lines):
            source_line = lines[index].rstrip("\n")
            newline = lines[index][len(source_line):]
            checked = re.match(r"^(\s*-\s*\[)x(\]\s*.*)$", source_line)
            if checked is not None:
                unchecked_line = f"{checked.group(1)} {checked.group(2)}"
                unchecked = "".join(
                    lines[:index] + [unchecked_line + newline] + lines[index + 1 :]
                )
                already_projected = (
                    content_hash(unchecked) == request.expected_content_hash
                    and sha256(unchecked_line.encode("utf-8")).hexdigest()
                    == request.expected_source_hash
                )
    elif control_matches and option is not None:
        already_projected = False
        control_matches = bool(
            option.selectable
            and option.content_hash == request.expected_content_hash
            and option.source_hash == request.expected_source_hash
        )
    if not control_matches or (option is not None and option.checked and not already_projected):
        raise QuestionReviewError(409, "stale_acceptance_control", "The acceptance control changed. Reload the question before accepting it.")

    if frontmatter.get("create_kind") != "create.answer_note" or frontmatter.get("authority_state") != "proposal":
        raise QuestionReviewError(409, "candidate_not_acceptance_draft", "This candidate is not a staged EXP-4 answer draft.")

    return QuestionAcceptancePreflight(
        question_id=question_id,
        question=question,
        question_version=observed_version,
        draft_path=draft_path,
        request=request,
        already_projected=already_projected,
    )


def complete_question_acceptance(
    preflight: QuestionAcceptancePreflight,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Run EXP-4 and acknowledge its exact receipt on the Question note.

    EXP-4's canonical-note write and the Question-note CAS are separate vault
    writes. A failed final CAS is therefore returned as an explicit
    acknowledgement-indeterminate state; it is never reported as answered.
    """

    vault_root = vault_root.expanduser().resolve()
    question_id = preflight.question_id
    request = preflight.request
    outbox_path = resolve_outbox_path(None)
    store = QuestionStore(vault_root, write_guard=write_guard)
    with _question_refresh_lock(vault_root, question_id):
        try:
            current, current_version = store.read_question_with_version(question_id)
        except (OSError, ValueError) as exc:
            raise QuestionReviewError(409, "question_unavailable", "The question changed before acceptance could be recorded.") from exc
        if current_version != preflight.question_version or current != preflight.question:
            raise QuestionReviewError(409, "stale_question", "The question changed after its acceptance control was loaded.")
        try:
            result = accept_draft(
                preflight.draft_path,
                vault_root=vault_root,
                outbox_path=outbox_path,
                write_guard=write_guard,
            )
        except DraftNotFoundError as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "The checked draft is no longer available. Its acceptance outcome needs reconciliation.",
                state="acknowledgement_indeterminate",
                draft_id=request.artifact_id,
            ) from exc
        except AcceptanceReconciliationError as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "EXP-4 materialized an answer, but its acceptance receipt could not be reconciled safely.",
                state="acknowledgement_indeterminate",
                draft_id=request.artifact_id,
            ) from exc
        except AcceptError as exc:
            raise QuestionReviewError(409, "acceptance_blocked", str(exc), state="blocked") from exc
        except WritesBlockedError as exc:
            raise QuestionReviewError(409, "writeguard_blocked", str(exc), state=exc.state) from exc
        except Exception as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "EXP-4 may have materialized the answer, but its outcome needs reconciliation.",
                state="acknowledgement_indeterminate",
                draft_id=request.artifact_id,
            ) from exc

        if result.status == "already_accepted" or result.final_note_path is None:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "EXP-4 reports an accepted draft without a recoverable final-note path.",
                state="acknowledgement_indeterminate",
                draft_id=result.draft_id,
                authority_receipt_id=result.receipt_id,
            )

        try:
            final_path = (vault_root / result.final_note_path).resolve()
            final_path.relative_to(vault_root)
            materialized_bytes = final_path.read_bytes()
        except (OSError, RuntimeError, ValueError) as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "EXP-4 acceptance materialization is no longer readable for acknowledgement.",
                state="acknowledgement_indeterminate",
                draft_id=result.draft_id,
                final_note_path=result.final_note_path,
                authority_receipt_id=result.receipt_id,
            ) from exc
        if (
            not result.materialized_content_sha256
            or sha256(materialized_bytes).hexdigest() != result.materialized_content_sha256
        ):
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "The accepted answer changed before its Question acknowledgement completed.",
                state="acknowledgement_indeterminate",
                draft_id=result.draft_id,
                final_note_path=result.final_note_path,
                authority_receipt_id=result.receipt_id,
            )

        answer_ref = f"vault://{result.final_note_path}"
        try:
            updated, _receipt = store.update_review_fields_if_unchanged(
                question_id,
                current,
                {
                    "status": "answered",
                    "standing_answer_ref": answer_ref,
                    "candidate_answer_ref": None,
                },
                expected_version=current_version,
            )
        except Exception as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "EXP-4 materialized the answer, but the Question acknowledgement did not complete. The question remains unresolved.",
                state="acknowledgement_indeterminate",
                draft_id=result.draft_id,
                final_note_path=result.final_note_path,
                authority_receipt_id=result.receipt_id,
            ) from exc

    return {
        "status": "answered",
        "question_id": question_id,
        "standing_answer_ref": updated["standing_answer_ref"],
        "authority_receipt_id": result.receipt_id,
        "draft_id": result.draft_id,
    }


def dismiss_question_candidate(
    question_id: str,
    *,
    vault_root: Path,
    expected_question_version: str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Record an EXP-4 decline before clearing the exact pending candidate pointer."""

    vault_root = vault_root.expanduser().resolve()
    store = QuestionStore(vault_root, write_guard=write_guard)
    outbox_path = resolve_outbox_path(None)
    with _question_refresh_lock(vault_root, question_id):
        try:
            question, version = store.read_question_with_version(question_id)
        except (OSError, ValueError) as exc:
            raise QuestionReviewError(404, "question_not_found", "The requested question does not exist.") from exc
        if version != expected_question_version:
            raise QuestionReviewError(409, "stale_question", "This question changed. Reload it before dismissing the candidate.")
        if question["status"] != "open":
            raise QuestionReviewError(409, "question_not_open", "Only an open question can dismiss a candidate answer.")
        draft_path = _candidate_path(vault_root, question.get("candidate_answer_ref"))
        try:
            frontmatter, _body = load_frontmatter(draft_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise QuestionReviewError(409, "candidate_unreadable", "The pending candidate answer cannot be inspected safely.") from exc
        frontmatter = frontmatter or {}
        draft_id = str(frontmatter.get("uuid") or draft_path.stem)
        if (
            frontmatter.get("question_id") != question_id
            or draft_id != draft_path.stem
            or frontmatter.get("create_kind") != "create.answer_note"
            or frontmatter.get("authority_state") != "proposal"
        ):
            raise QuestionReviewError(409, "candidate_identity_mismatch", "The pending candidate is not an answer draft for this question.")
        try:
            result = decline_draft(
                draft_path,
                vault_root=vault_root,
                outbox_path=outbox_path,
                reason="standing_question_candidate_dismissed",
                write_guard=write_guard,
            )
            receipt_id = result.receipt_id
        except DraftNotFoundError as exc:
            raise QuestionReviewError(409, "candidate_missing", "The pending candidate answer is no longer available.") from exc
        except (AcceptError, WritesBlockedError) as exc:
            raise QuestionReviewError(409, "dismissal_blocked", str(exc), state="blocked") from exc

        try:
            updated, _receipt = store.update_review_fields_if_unchanged(
                question_id,
                question,
                {"candidate_answer_ref": None},
                expected_version=version,
            )
        except (KnowledgeWriteConflict, InvalidQuestionReviewTransition, WritesBlockedError) as exc:
            raise QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                "The decline was recorded, but the Question pointer could not be cleared.",
                state="acknowledgement_indeterminate",
                draft_id=draft_id,
                decline_receipt_id=receipt_id,
            ) from exc

    return {
        "status": "open",
        "question_id": question_id,
        "candidate_answer_ref": updated.get("candidate_answer_ref"),
        "decline_receipt_id": receipt_id,
        "draft_id": draft_id,
    }


def transition_question_status(
    question_id: str,
    *,
    vault_root: Path,
    expected_question_version: str,
    status: str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any]:
    """Apply the explicit close or reopen action under the shared refresh lock."""

    vault_root = vault_root.expanduser().resolve()
    store = QuestionStore(vault_root, write_guard=write_guard)
    with _question_refresh_lock(vault_root, question_id):
        try:
            question, version = store.read_question_with_version(question_id)
        except (OSError, ValueError) as exc:
            raise QuestionReviewError(404, "question_not_found", "The requested question does not exist.") from exc
        if version != expected_question_version:
            raise QuestionReviewError(409, "stale_question", "This question changed. Reload it before changing its status.")
        try:
            updated, _receipt = store.update_review_fields_if_unchanged(
                question_id,
                question,
                {"status": status},
                expected_version=version,
            )
        except InvalidQuestionReviewTransition as exc:
            raise QuestionReviewError(409, "invalid_transition", str(exc)) from exc
        except KnowledgeWriteConflict as exc:
            raise QuestionReviewError(409, "stale_question", "The question changed before the status update.") from exc
        except WritesBlockedError as exc:
            raise QuestionReviewError(409, "writeguard_blocked", str(exc), state=exc.state) from exc
    return {"status": updated["status"], "question_id": question_id}


def accepted_question_receipt(
    request: CheckboxProjectionRequest,
    *,
    vault_root: Path,
) -> dict[str, Any] | None:
    """Recognize a retry after both EXP-4 and its Question acknowledgement committed."""

    question_id = request.review_question_id
    if not question_id or request.option_id != standing_question_acceptance_option_id(request.artifact_id):
        return None
    vault_root = vault_root.expanduser().resolve()
    try:
        question_note_path(question_id)
        question = QuestionStore(vault_root).read_question(question_id)
    except (OSError, ValueError):
        return None
    if question.get("status") != "answered" or question.get("candidate_answer_ref") is not None:
        return None
    answer_path = _candidate_path(vault_root, question.get("standing_answer_ref"))
    try:
        frontmatter, _body = load_frontmatter(answer_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    frontmatter = frontmatter or {}
    if (
        str(frontmatter.get("uuid") or "") != request.artifact_id
        or frontmatter.get("question_id") != question_id
        or frontmatter.get("authority_state") != "accepted"
        or frontmatter.get("accepted_by") != "human"
        or not frontmatter.get("acceptance_receipt_id")
    ):
        return None
    return {
        "status": "answered",
        "question_id": question_id,
        "standing_answer_ref": question.get("standing_answer_ref"),
        "authority_receipt_id": frontmatter["acceptance_receipt_id"],
        "draft_id": request.artifact_id,
        "idempotent_replay": True,
    }


def reconcile_missing_question_acceptance(
    request: CheckboxProjectionRequest,
    *,
    vault_root: Path,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> dict[str, Any] | None:
    """Reconcile EXP-4's receipt when its consumed draft outlives no staging file.

    A missing draft is recoverable only when the still-open Question points at
    this exact candidate, the accepted event identifies the same draft, and the
    canonical answer note agrees with every receipt-bound identity. Otherwise
    the route returns an explicit indeterminate acknowledgement state.
    """

    question_id = request.review_question_id
    if (
        not question_id
        or not request.expected_question_version
        or request.option_id != standing_question_acceptance_option_id(request.artifact_id)
    ):
        return None
    try:
        question_note_path(question_id)
    except ValueError:
        return None

    vault_root = vault_root.expanduser().resolve()
    store = QuestionStore(vault_root, write_guard=write_guard)
    with _question_refresh_lock(vault_root, question_id):
        try:
            question, version = store.read_question_with_version(question_id)
        except (OSError, ValueError):
            return None
        if version != request.expected_question_version:
            raise QuestionReviewError(409, "stale_question", "This question changed. Reload it before accepting the candidate.")
        if question.get("status") != "open":
            return None
        expected_candidate_ref = f"vault://{request.note_path}"
        if question.get("candidate_answer_ref") != expected_candidate_ref:
            return None
        try:
            candidate_path = _candidate_path(vault_root, question.get("candidate_answer_ref"))
        except QuestionReviewError as exc:
            if exc.detail.get("error") != "candidate_missing":
                raise
            candidate_path = None
        if candidate_path is not None:
            return None

        def indeterminate(message: str, **details: Any) -> QuestionReviewError:
            return QuestionReviewError(
                409,
                "acknowledgement_indeterminate",
                message,
                state="acknowledgement_indeterminate",
                draft_id=request.artifact_id,
                **details,
            )

        try:
            events = [
                record
                for record in iter_jsonl_outbox_records(resolve_outbox_path(None))
                if record.get("event") == CREATE_ACCEPTED_EVENT
                and isinstance(record.get("payload"), dict)
                and record["payload"].get("draft_id") == request.artifact_id
            ]
        except Exception as exc:
            raise indeterminate("The accepted answer receipt could not be inspected safely.") from exc
        if len(events) != 1:
            raise indeterminate("The checked draft is gone and no unique acceptance receipt can reconcile it.")
        event = events[0]
        payload = event.get("payload")
        if (
            event.get("source") != ACCEPT_EVENT_SOURCE
            or event.get("trace_id") != request.artifact_id
            or not isinstance(event.get("event_id"), str)
            or not event.get("event_id")
            or not isinstance(payload, dict)
            or payload.get("accepted_by") != "human"
            or payload.get("authority_state") != "accepted"
        ):
            raise indeterminate("The acceptance receipt does not prove a complete human-approved answer.")

        final_rel = payload.get("final_note_path")
        if not isinstance(final_rel, str) or not final_rel.strip():
            raise indeterminate("The acceptance receipt has no canonical answer path.")
        final_candidate = Path(final_rel)
        if final_candidate.is_absolute() or ".." in final_candidate.parts:
            raise indeterminate("The acceptance receipt points outside the selected vault.")
        answer_path = (vault_root / final_candidate).resolve()
        try:
            canonical_final_rel = answer_path.relative_to(vault_root).as_posix()
            if canonical_final_rel != final_rel:
                raise ValueError("acceptance receipt path is not canonical")
            accepted_bytes = answer_path.read_bytes()
            accepted_text = accepted_bytes.decode("utf-8")
            frontmatter, _body = load_frontmatter(accepted_text)
        except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
            raise indeterminate("The accepted canonical answer cannot be inspected safely.") from exc
        frontmatter = frontmatter or {}
        receipt_id = payload.get("authority_receipt_id")
        token_ref = payload.get("decision_token_ref")
        if (
            str(frontmatter.get("uuid") or "") != request.artifact_id
            or frontmatter.get("question_id") != question_id
            or frontmatter.get("authority_state") != "accepted"
            or frontmatter.get("accepted_by") != "human"
            or not isinstance(receipt_id, str)
            or not receipt_id
            or frontmatter.get("acceptance_receipt_id") != receipt_id
            or not isinstance(token_ref, str)
            or not token_ref
            or frontmatter.get("decision_token_ref") != token_ref
            or payload.get("sources") != frontmatter.get("sources")
            or not isinstance(payload.get("materialized_content_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", payload["materialized_content_sha256"])
            or sha256(accepted_bytes).hexdigest() != payload["materialized_content_sha256"]
        ):
            raise indeterminate("The canonical answer content and acceptance receipt do not match.")

        try:
            updated, _receipt = store.update_review_fields_if_unchanged(
                question_id,
                question,
                {
                    "status": "answered",
                    "standing_answer_ref": f"vault://{final_rel}",
                    "candidate_answer_ref": None,
                },
                expected_version=version,
            )
        except Exception as exc:
            raise indeterminate(
                "The accepted answer is durable, but its Question acknowledgement remains unresolved.",
                final_note_path=final_rel,
                authority_receipt_id=receipt_id,
            ) from exc

    return {
        "status": "answered",
        "question_id": question_id,
        "standing_answer_ref": updated["standing_answer_ref"],
        "authority_receipt_id": receipt_id,
        "draft_id": request.artifact_id,
        "idempotent_replay": True,
    }


__all__ = [
    "QuestionAcceptancePreflight",
    "QuestionReviewError",
    "accepted_question_receipt",
    "complete_question_acceptance",
    "dismiss_question_candidate",
    "prepare_question_acceptance",
    "transition_question_status",
]
